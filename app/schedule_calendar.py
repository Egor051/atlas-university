"""Term and day rules shared by schedule readers and publication."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select

from .workspace_db import AcademicDayRule, AcademicTerm

MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2099, 12, 31)
DEMO_WINDOW = (date(2026, 11, 9), date(2026, 11, 30))
LESSON_KINDS = frozenset({'lecture', 'practice', 'lab', 'seminar'})
KIND = {
    'lecture': 'Лекция', 'practice': 'Практическое занятие', 'lab': 'Лабораторная работа',
    'seminar': 'Практическое занятие',
    'consultation': 'Консультация', 'credit': 'Зачёт', 'exam': 'Экзамен', 'retake': 'Пересдача',
    'organization': 'Организационное мероприятие', 'other': 'Учебное мероприятие',
    'campus': 'Мероприятие кампуса', 'vuc': 'Занятие ВУЦ', 'deadline': 'Срок сдачи',
}
REASONS = {
    'holiday': 'Государственный праздник', 'weekend': 'Выходной', 'summer': 'Летние каникулы',
    'credit': 'Зачётная неделя', 'exam': 'Экзаменационная сессия', 'break': 'Межсеместровые каникулы',
    'teaching': 'Занятия по расписанию отсутствуют', 'unscheduled': 'Занятия по расписанию отсутствуют',
    'unconfigured': 'Учебный календарь не опубликован',
}

# Article 112 of the Labour Code and annual government decrees listed in docs/schedule.md.
HOLIDAYS = {
    **{(1, day): 'Новогодние каникулы' for day in range(1, 9)},
    (1, 7): 'Рождество Христово', (2, 23): 'День защитника Отечества', (3, 8): 'Международный женский день',
    (5, 1): 'Праздник Весны и Труда', (5, 9): 'День Победы', (6, 12): 'День России',
    (11, 4): 'День народного единства',
}
TRANSFERS = {
    2025: (((1, 4), (5, 2)), ((1, 5), (12, 31)), ((2, 23), (5, 8)), ((3, 8), (6, 13)), ((11, 1), (11, 3))),
    2026: (((1, 3), (1, 9)), ((1, 4), (12, 31))),
    2027: (((1, 2), (11, 5)), ((1, 3), (12, 31)), ((2, 20), (2, 22))),
}


def date_range(first, last):
    return (first + timedelta(days=offset) for offset in range((last - first).days + 1))


def federal_days(year, weekdays):
    transfers = dict(TRANSFERS.get(year, ()))
    days_off = {date(year, *target) for target in transfers.values()}
    working = {date(year, *source) for source in transfers if source not in HOLIDAYS}
    for month_day in HOLIDAYS:
        day = date(year, *month_day)
        if day.month == 1 or month_day in transfers or str(day.weekday()) in weekdays:
            continue
        day += timedelta(days=1)
        while ((day.month, day.day) in HOLIDAYS or day in days_off
               or (str(day.weekday()) not in weekdays and day not in working)):
            day += timedelta(days=1)
        days_off.add(day)
    return days_off, working


def scope_rank(record):
    return 2 if record.group_id is not None else int(bool(record.program))


def matches(record, group):
    if record.group_id is not None:
        return group is not None and record.group_id == group.id
    return not record.program or (group is not None and record.program == group.program)


@dataclass(frozen=True)
class Day:
    code: str
    detail: str = ''
    term: AcademicTerm | None = None
    legacy: bool = False

    def payload(self):
        return {
            'code': self.code, 'label': REASONS[self.code], 'detail': self.detail,
            'academic_year': self.term.academic_year if self.term else None,
            'semester': self.term.number if self.term else None,
        }


class Calendar:
    def __init__(self, db, first, last):
        self.terms = sorted(db.scalars(select(AcademicTerm).where(
            AcademicTerm.starts_on <= last, AcademicTerm.ends_on >= first)), key=scope_rank, reverse=True)
        self.rules = sorted(db.scalars(select(AcademicDayRule).where(
            AcademicDayRule.starts_on <= last, AcademicDayRule.ends_on >= first)), key=scope_rank, reverse=True)
        self._federal = {}

    def term(self, day, group):
        return next((row for row in self.terms if row.starts_on <= day <= row.ends_on and matches(row, group)), None)

    def day(self, day, group):
        term = self.term(day, group)
        weekdays = term.weekdays if term else '01234'
        rules = [row for row in self.rules if row.starts_on <= day <= row.ends_on and matches(row, group)]
        holiday = HOLIDAYS.get((day.month, day.day))
        if holiday:
            return Day('holiday', holiday, term)
        holiday_rule = next((row for row in rules if row.kind == 'holiday'), None)
        if holiday_rule:
            return Day('holiday', holiday_rule.label, term)
        key = (day.year, weekdays)
        if key not in self._federal:
            self._federal[key] = federal_days(*key)
        off, working = self._federal[key]
        phase = next((part['kind'] for part in term.periods
                      if part['start'] <= day.isoformat() <= part['end']), None) if term else None
        recess = next((row for row in rules if row.kind in {'summer', 'break'}), None)
        if recess:
            return Day(recess.kind, recess.label, term)
        if phase in {'credit', 'exam', 'break'}:
            return Day(phase, term=term)
        if day in off:
            return Day('weekend', 'Перенос выходного дня', term)
        rule = next((row for row in rules if row.kind in {'off', 'working'}), None)
        if rule and rule.kind == 'off':
            return Day('weekend', rule.label, term)
        if str(day.weekday()) not in weekdays and day not in working and not (rule and rule.kind == 'working'):
            return Day('weekend', term=term)
        imported = term is None and any(row.kind == 'legacy' for row in rules)
        if phase == 'teaching' or imported:
            return Day('teaching', term=term, legacy=imported or bool(term and term.legacy))
        return Day('unscheduled' if term else 'unconfigured', term=term)


def occurrence_kind(value):
    return {
        'seminar': 'practice', 'Семинар': 'practice', 'Практика': 'practice',
        'Практическое занятие': 'practice', 'Лекция': 'lecture', 'Лабораторная': 'lab',
        'Лабораторная работа': 'lab',
    }.get(value, value if value in KIND else 'practice')
