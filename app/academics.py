"""Read models for the student's combined results and intermediate assessments."""
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import select

from .academic_points import PointAward, award_data
from .db import CAMPUS_TZ, Grade, Lesson, campus_today
from .learning_db import Attendance
from .session_security import as_utc
from .workspace import load_query
from .workspace_db import GroupMember, ScheduledClass, TeachingLoad


ATTENDANCE_LABELS = {'present': 'Присутствие', 'late': 'Опоздание', 'absent': 'Пропуск',
                     'excused': 'Пропуск по уважительной причине'}


def semester_for(day):
    if day is None:
        return ''
    year = day.year if day.month >= 9 else day.year - 1
    term = 1 if day.month >= 9 or day.month == 1 else 2
    return f'{year}/{year + 1} · {term}-й семестр'


def assessment_status(grade, today):
    if not grade or not grade.exam_kind:
        return dict(code='unknown', label='Форма контроля не указана', tone='', admission='', result='', explanation='', action='')
    assessment = grade.assessment.strip()
    normalized = assessment.casefold().replace('ё', 'е')
    final = {'зачтено': 'Зачтено', 'экзамен сдан': 'Экзамен сдан', 'сдано': 'Экзамен сдан',
             'не зачтено': 'Не зачтено', 'не сдано': 'Не сдано', 'экзамен не сдан': 'Экзамен не сдан'}
    failed = normalized.startswith('не ') or normalized == 'экзамен не сдан'
    admission = ('Допущен' if normalized in {'допуск', 'допущен'} else
                 'Не допущен' if normalized in {'не допущен', 'нет допуска', 'не выполнены условия допуска'} else '')
    if normalized in final:
        return dict(code='failed' if failed else 'passed', label=final[normalized],
                    tone='warning' if failed else 'success', result=assessment, admission='',
                    explanation='Результат аттестации опубликован.', action='consultations' if failed else '')
    if normalized == 'пересдача назначена':
        return dict(code='retake', label='Назначена пересдача', tone='warning', result='', admission='',
                    explanation='Проверьте дату и уточните условия у преподавателя.', action='consultations')
    if admission == 'Не допущен':
        return dict(code='blocked', label='Требуется допуск', tone='warning', result='', admission=admission,
                    explanation='Условия допуска уточните у преподавателя.', action='consultations')
    day = grade.exam_date
    if day is None:
        code, label, tone = 'undated', 'Дата не назначена', ''
        explanation = 'Дата появится после публикации расписания аттестации.'
    elif day < today:
        code, label, tone = 'waiting_result', 'Ожидается результат', ''
        explanation = 'Дата аттестации прошла. Результат появится после публикации.'
    elif (day - today).days <= 7:
        code, label, tone = 'soon', 'Аттестация в ближайшие 7 дней', 'warning'
        explanation = 'Проверьте дату и подготовьтесь по материалам дисциплины.'
    else:
        code, label, tone = 'scheduled', 'Назначена дата аттестации', ''
        explanation = ''
    return dict(code=code, label=label, tone=tone, result='', admission=admission or 'Допуск не указан',
                explanation=explanation, action='courses' if code == 'soon' else '')


def attendance_summary(statuses):
    counts = Counter(statuses)
    present = counts['present'] + counts['late']
    denominator = present + counts['absent']
    return dict(class_count=sum(counts.values()), visited=present, missed=counts['absent'] + counts['excused'],
                attendance_percent=round(100 * present / denominator) if denominator else None)


def _class_rows(db, student, group_ids, load_by_id, marks):
    from .scheduling import KIND

    meetings = db.scalars(select(ScheduledClass).where(ScheduledClass.group_id.in_(group_ids),
                          ScheduledClass.status == 'active').order_by(ScheduledClass.starts_at.desc())).all()
    session_days = Counter((load_by_id[row.load_id].discipline.title,
                            as_utc(row.starts_at).astimezone(CAMPUS_TZ).date()) for row in meetings if row.load_id in load_by_id)
    by_class = {mark.class_id: mark for mark in marks if mark.class_id}
    by_day = {}
    for mark in marks:
        if not mark.class_id:
            by_day.setdefault((mark.subject, mark.day), mark)
    sessions, used_marks = defaultdict(list), set()
    for row in meetings:
        if row.load_id not in load_by_id:
            continue
        subject = load_by_id[row.load_id].discipline.title
        day = as_utc(row.starts_at).astimezone(CAMPUS_TZ).date()
        legacy = by_day.get((subject, day)) if session_days[(subject, day)] == 1 else None
        mark = by_class.get(row.id) or legacy
        used_marks.update(record.id for record in (mark, legacy) if record)
        sessions[subject].append(dict(class_id=row.id, day=day, kind=KIND.get(row.kind, row.kind), topic=row.note,
                                      status=mark.status if mark else '', note=mark.note if mark else ''))
    lessons = defaultdict(list)
    for lesson in db.scalars(select(Lesson).where(Lesson.student_id == student.id)):
        lessons[(lesson.title, lesson.weekday)].append(lesson)
    for row in marks:
        if row.id in used_marks:
            continue
        legacy_key = (row.subject, row.day)
        if row.class_id is None and row is not by_day[legacy_key]:
            continue
        candidates = lessons[(row.subject, row.day.weekday())]
        sessions[row.subject].append(dict(class_id=row.class_id, day=row.day, kind=candidates[0].kind if len(candidates) == 1 else '',
                                          topic='', status=row.status, note=row.note))
    return sessions


def student_progress(db, student, date_iso):
    from .assignment_workflow import academic_work_results

    now = campus_today()
    grades = db.scalars(select(Grade).where(Grade.student_id == student.id).order_by(Grade.id)).all()
    loads = db.scalars(load_query().join(GroupMember, GroupMember.group_id == TeachingLoad.group_id)
                       .where(GroupMember.student_id == student.id).order_by(TeachingLoad.id)).all()
    load_by_id = {row.id: row for row in loads}
    load_by_subject = {row.discipline.title: row for row in loads}
    marks = db.scalars(select(Attendance).where(Attendance.student_id == student.id)
                       .order_by(Attendance.day.desc(), Attendance.id.desc())).all()
    sessions = _class_rows(db, student, {row.group_id for row in loads}, load_by_id, marks)
    work_by_subject = defaultdict(list)
    for work in academic_work_results(db, student.id):
        work_by_subject[work['subject']].append(work)
    awards = defaultdict(list)
    for row in db.scalars(select(PointAward).where(PointAward.student_id == student.id).order_by(PointAward.id.desc())):
        awards[row.grade_id].append(award_data(row, date_iso))
    by_subject = {}
    for grade in grades:
        by_subject.setdefault(grade.subject, grade)
    items = []
    all_subjects = set(by_subject) | set(load_by_subject) | set(sessions) | set(work_by_subject)
    for subject in sorted(all_subjects, key=str.casefold):
        grade, load = by_subject.get(subject), load_by_subject.get(subject)
        lessons = sorted(sessions[subject], key=lambda row: row['day'], reverse=True)
        work = [{**assignment, 'semester': semester_for(as_utc(datetime.fromisoformat(assignment['due_at']))
                 .astimezone(CAMPUS_TZ).date()) if assignment.get('due_at') else ''} for assignment in work_by_subject[subject]]
        history = awards[grade.id] if grade else []
        linked_awards = defaultdict(list)
        for award in history:
            if award['class_id']:
                linked_awards[award['class_id']].append(award)
        admission = assessment_status(grade, now)
        attendance_by_semester = defaultdict(list)
        for lesson in lessons:
            lesson['semester'] = semester_for(lesson['day'])
            attendance_by_semester[lesson['semester']].append(lesson['status'])
        semesters = set(attendance_by_semester) | {assignment['semester'] for assignment in work if assignment['semester']}
        if grade and grade.exam_date:
            semesters.add(semester_for(grade.exam_date))
        items.append(dict(id=grade.id if grade else None, subject=subject,
                          teacher=grade.teacher if grade else load.assignment.teacher.user.full_name if load else '',
                          semesters=sorted(semesters),
                          **attendance_summary(lesson['status'] for lesson in lessons),
                          attendance_by_semester={semester: attendance_summary(attendance_by_semester[semester]) for semester in semesters},
                          earned_points=grade.current if grade else None, max_points=(grade.max_grade or None) if grade else None,
                          result=admission['result'], assessment=admission,
                          classes=[{**lesson, 'day': date_iso(lesson['day']), 'status_label': ATTENDANCE_LABELS.get(lesson['status'], 'Нет отметки'),
                                    'points': sum(award['points'] for award in linked_awards[lesson['class_id']]),
                                    'work': [assignment for assignment in work if lesson['class_id'] and assignment.get('class_id') == lesson['class_id']]}
                                   for lesson in lessons], work=work, awards=history))
    return {'items': items}
