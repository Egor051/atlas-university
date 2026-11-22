"""Semester totals, activity breakdown and movement from the student's point ledger."""
from collections import defaultdict

from sqlalchemy import select

from .db import CAMPUS_TZ, campus_today
from .learning_db import Course
from .schedule_calendar import LESSON_KINDS, MAX_DATE, MIN_DATE, Calendar, matches
from .schedule_occurrences import audience
from .session_security import as_utc
from .university_db import Discipline
from .workspace_db import AcademicGroup, GroupMember, ScheduledClass, TeachingLoad


UNASSIGNED = 'unassigned'


def campus_day(value):
    return as_utc(value).astimezone(CAMPUS_TZ).date() if value else None


def semester_key(term):
    return f'{term.academic_year}-{term.number}'


def discipline_key(discipline_id, grade_id):
    return f'discipline-{discipline_id}' if discipline_id is not None else f'grade-{grade_id}'


class PointCalendar:
    def __init__(self, db, group):
        self.db = db
        self.calendar = Calendar(db, MIN_DATE, MAX_DATE)
        self.group = group
        self.groups = {group.id: group} if group else {}
        self.today = campus_today()
        self.terms = {}
        self.periods = {}
        for term in self.terms_for(group):
            self.add_term(term)
        self.current = self.period_for(self.today)

    def terms_for(self, group):
        group_id = group.id if group else None
        if group_id not in self.terms:
            effective = {}
            for term in self.calendar.terms:
                if matches(term, group):
                    effective.setdefault(semester_key(term), term)
            self.terms[group_id] = list(effective.values())
        return self.terms[group_id]

    def add_term(self, term):
        key = semester_key(term)
        self.periods.setdefault(key, dict(id=key, academic_year=term.academic_year, semester=term.number,
                                          label=f'{term.number}-й семестр', starts_on=term.starts_on, ends_on=term.ends_on))
        return key

    def period_for(self, day, group_id=None):
        if day is None:
            return UNASSIGNED
        group = self.group
        if group_id is not None:
            if group_id not in self.groups:
                self.groups[group_id] = self.db.get(AcademicGroup, group_id)
            group = self.groups[group_id]
        for term in self.terms_for(group):
            if term.starts_on <= day <= term.ends_on:
                return self.add_term(term)
        for rule in self.calendar.rules:
            if rule.kind == 'legacy' and rule.starts_on <= day <= rule.ends_on and matches(rule, group):
                key = f'legacy-{rule.starts_on}-{rule.ends_on}'
                self.periods.setdefault(key, dict(id=key, academic_year=None, semester=None,
                                                  label='Опубликованный период', starts_on=rule.starts_on, ends_on=rule.ends_on))
                return key
        return UNASSIGNED


def discipline_totals(subject, grade_id, entries, maxima):
    by_kind = defaultdict(int)
    by_day = defaultdict(int)
    for row in entries:
        by_kind[row['kind_label']] += row['points']
        by_day[row['day']] += row['points']
    total = 0
    timeline = []
    for day, change in sorted(by_day.items(), key=lambda pair: pair[0] or ''):
        total += change
        timeline.append(dict(day=day, change=change, total=total))
    maximum = next(iter(maxima)) if len(maxima) == 1 else None
    return dict(subject=subject, grade_id=grade_id, earned_points=total, max_points=maximum,
                percent=round(total * 100 / maximum, 1) if maximum else None, timeline=timeline,
                breakdown=[dict(label=label, points=points) for label, points in sorted(by_kind.items())])


def student_semester_points(db, student_id, grades, works, items):
    member = db.get(GroupMember, student_id)
    calendar = PointCalendar(db, db.get(AcademicGroup, member.group_id) if member else None)
    courses = {row.grade_id: row for row in db.scalars(select(Course).where(Course.student_id == student_id))}
    loads = db.execute(select(Discipline.id, Discipline.title).join(TeachingLoad)
                       .where(TeachingLoad.group_id == member.group_id)).all() if member else []
    meetings = db.execute(audience(
        select(Discipline.id, Discipline.title, ScheduledClass.starts_at, ScheduledClass.group_id)
        .select_from(ScheduledClass).join(TeachingLoad).join(Discipline)
        .where(ScheduledClass.kind.in_(LESSON_KINDS | {'exam', 'credit', 'retake'})), member, student_id)).all()

    candidates = defaultdict(set)
    for discipline_id, name in loads + [(row[0], row[1]) for row in meetings]:
        candidates[name].add(discipline_id)
    for work in works.values():
        candidates[work.subject].add(work.discipline_id)
    for course in courses.values():
        if course.discipline_id is not None:
            candidates[course.subject].add(course.discipline_id)
    for row in items:
        if row['discipline_id'] is not None:
            candidates[row['subject']].add(row['discipline_id'])

    grade_disciplines = {}
    for grade in grades.values():
        course = courses.get(grade.id)
        ids = candidates[grade.subject]
        discipline_id = course.discipline_id if course else None
        if discipline_id is None and len(ids) == 1:
            discipline_id = next(iter(ids))
        grade_disciplines[grade.id] = discipline_id

    subjects = defaultdict(dict)
    semesters = defaultdict(set)
    entries = defaultdict(list)
    maxima = defaultdict(set)

    def include(period, key, subject, grade_id=None):
        if period != UNASSIGNED:
            if key not in subjects[period] or (grade_id is not None and subjects[period][key][1] is None):
                subjects[period][key] = (subject, grade_id)
            semesters[key].add(period)

    for row in items:
        period = calendar.period_for(row.pop('_source_day'), row.pop('_group_id'))
        discipline_id = row['discipline_id'] or grade_disciplines.get(row['grade_id'])
        key = discipline_key(discipline_id, row['grade_id'])
        row.update(period=period, discipline_key=key, discipline_id=discipline_id)
        entries[period, key].append(row)
        include(period, key, row['subject'], row['grade_id'])

    for discipline_id, name, start, group_id in meetings:
        include(calendar.period_for(campus_day(start), group_id), discipline_key(discipline_id, None), name)
    for work in works.values():
        if work.visible:
            include(calendar.period_for(work.day, work.group_id), discipline_key(work.discipline_id, None), work.subject)
    for grade in grades.values():
        include(calendar.period_for(grade.exam_date), discipline_key(grade_disciplines[grade.id], grade.id), grade.subject, grade.id)

    for discipline_id, name in loads:
        include(calendar.current, discipline_key(discipline_id, None), name)
    for grade in grades.values():
        key = discipline_key(grade_disciplines[grade.id], grade.id)
        if not semesters[key] and (grade.id in courses or grade.exam_date is None):
            include(calendar.current, key, grade.subject, grade.id)
        if grade.exam_date:
            period = calendar.period_for(grade.exam_date)
        else:
            period = next(iter(semesters[key])) if len(semesters[key]) == 1 else UNASSIGNED
        if period != UNASSIGNED and grade.max_grade > 0:
            maxima[period, key].add(grade.max_grade)

    periods = sorted(calendar.periods.values(), key=lambda period: (period['starts_on'], period['id']), reverse=True)
    recent = next((period['id'] for period in periods if period['starts_on'] <= calendar.today), UNASSIGNED)
    default = calendar.current if calendar.current != UNASSIGNED else recent
    for period in periods:
        date_key = period['id']
        ordered = sorted(subjects[date_key].items(), key=lambda pair: (pair[1][0].casefold(), pair[0]))
        period['disciplines'] = [dict(key=key, **discipline_totals(name, grade_id, entries[date_key, key], maxima[date_key, key]))
                                 for key, (name, grade_id) in ordered]
    if default == UNASSIGNED or any(row['period'] == UNASSIGNED for row in items):
        periods.append(dict(id=UNASSIGNED, academic_year=None, semester=None, label='Без семестра',
                            starts_on=None, ends_on=None, disciplines=[]))
    return dict(periods=periods, default_period=default)
