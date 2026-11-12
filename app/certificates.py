"""Verified-in-scenario enrollment and immutable Appendix 4 preparation."""

from datetime import date, datetime
from html import escape
import json

from fastapi import HTTPException
from sqlalchemy import DateTime, ForeignKey, JSON, select, update
from sqlalchemy.orm import Mapped, mapped_column

from .certificate_catalog import APPENDIX_4, APPENDIX_4_BASIS, CERTIFICATE_CODES, COMMISSIONER_OPTIONS
from .db import Base, User, campus_today


class CertificateEnrollment(Base):
    __tablename__ = 'certificate_enrollments'

    student_id: Mapped[int] = mapped_column(ForeignKey('users.id'), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class CertificateIssue(Base):
    __tablename__ = 'certificate_issues'

    request_id: Mapped[int] = mapped_column(ForeignKey('document_requests.id'), primary_key=True)
    prepared_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON)


ENROLLMENT_LABELS = {
    'full_name': 'Фамилия, имя, отчество',
    'birth_year': 'Год рождения',
    'admission_year': 'Год поступления',
    'previous_education': 'Уровень образования при поступлении',
    'institution': 'Полное наименование организации',
    'education_level': 'Уровень программы',
    'program_group': 'Код и наименование укрупнённой группы',
    'program': 'Код и наименование направления подготовки',
    'accreditation': 'Сведения об аккредитации в учебном реестре',
    'course': 'Курс',
    'study_mode': 'Форма обучения',
    'duration': 'Срок получения образования',
    'graduation_date': 'Окончание обучения',
}
APPENDIX_4_LEVELS = {'СПО', 'Бакалавриат', 'Специалитет', 'Магистратура'}
ENROLLMENT_SEED = {
    'full_name': 'Северин Марк Алексеевич',
    'birth_year': '2005',
    'admission_year': '2023',
    'previous_education': 'Среднее общее образование',
    'institution': 'Учебная организация «АТЛАС»',
    'education_level': 'Бакалавриат',
    'program_group': '09.00.00 Информатика и вычислительная техника',
    'program': '09.03.03 Прикладная информатика',
    'accreditation': 'Учебная запись АТЛАС-АКК-01 от 01.08.2023, бессрочно; учебный реестр АТЛАС',
    'study_mode': 'Очная',
    'duration': '4 года',
    'graduation_date': '2027-06-30',
    'accredited': True,
}


def seed_certificate_enrollment(db):
    student = db.scalar(select(User).where(User.login == 'mark.demo', User.role == 'student'))
    if student and db.get(CertificateEnrollment, student.id) is None:
        db.add(CertificateEnrollment(student_id=student.id, data=ENROLLMENT_SEED.copy()))


def migrate_certificate_drafts(connection):
    from .improvement_db import PersonalDraft

    existing = set(connection.scalars(select(PersonalDraft.user_id).where(PersonalDraft.name == 'certificate-order')))
    drafts = connection.execute(select(PersonalDraft.id, PersonalDraft.user_id, PersonalDraft.values_json)
                                .where(PersonalDraft.name == 'request')).all()
    for draft in drafts:
        if draft.user_id not in existing and json.loads(draft.values_json).get('type') in CERTIFICATE_CODES:
            connection.execute(update(PersonalDraft).where(PersonalDraft.id == draft.id)
                               .values(name='certificate-order'))


def appendix_4_enrollment(db, student):
    row = db.get(CertificateEnrollment, student.id)
    if not row or student.role != 'student' or student.course <= 0:
        return None
    data = row.data
    if (
        data.get('education_level') not in APPENDIX_4_LEVELS
        or data.get('study_mode') != 'Очная'
        or data.get('accredited') is not True
    ):
        return None
    fields = ENROLLMENT_LABELS.keys() - {'course'}
    if any(not isinstance(data.get(key), str) or not data[key].strip() for key in fields):
        return None
    try:
        graduation = date.fromisoformat(data['graduation_date'])
        current_date = campus_today()
        birth_year = int(data['birth_year'])
        admission_year = int(data['admission_year'])
        if not 1900 <= birth_year < admission_year <= current_date.year or current_date > graduation:
            return None
    except ValueError:
        return None
    return {**{key: data[key] for key in ENROLLMENT_LABELS if key != 'course'},
            'course': str(student.course), 'graduation_date': graduation.strftime('%d.%m.%Y')}


def public_service(service, eligible):
    if service['id'] != APPENDIX_4:
        return service
    return {**service, 'available': eligible, 'destinations': COMMISSIONER_OPTIONS,
            'unavailable_reason': 'В учебном реестре вашего аккаунта нет подтверждённых сведений для этой формы.'}


def get_destination(details):
    name = COMMISSIONER_OPTIONS.get(details.get('commissioner'))
    if not name:
        raise HTTPException(422, {'message': 'Выберите военный комиссариат из списка', 'field': 'details.commissioner'})
    return name


def prepare_appendix_4(db, row, staff, confirmed, prepared_at):
    if not confirmed:
        raise HTTPException(422, 'Подтвердите сверку сведений перед подготовкой справки')
    student = db.get(User, row.student_id)
    enrollment = appendix_4_enrollment(db, student)
    if enrollment is None:
        raise HTTPException(409, 'В реестре нет подтверждённых сведений для подготовки справки')
    return CertificateIssue(request_id=row.id, prepared_by=staff.id, prepared_at=prepared_at,
                            data={**enrollment, 'commissioner': get_destination(json.loads(row.details))})


def enrollment_rows(data):
    if not data:
        return []
    return [{'label': label, 'value': data[key]} for key, label in ENROLLMENT_LABELS.items()]


def appendix_4_html(issue):
    if issue is None:
        raise HTTPException(409, 'Подготовленная справка не найдена')
    data = {key: escape(value) for key, value in issue.data.items()}
    return f'''<section aria-label="Форма приложения № 4">
      <p><small>{escape(APPENDIX_4_BASIS)}</small></p>
      <p><small>Место для углового штампа организации. Регистрационные реквизиты не заполнены.</small></p>
      <p>Сведения об обучающемся: <strong>{data['full_name']}</strong>, {data['birth_year']} год рождения.</p>
      <p>Год поступления — {data['admission_year']}. Образование при поступлении — {data['previous_education']}.
      Образовательная организация — {data['institution']}.</p>
      <p>Аккредитованная программа — {data['education_level']}. Укрупнённая группа: {data['program_group']}.
      Направление подготовки или специальность: {data['program']}. Сведения об аккредитации: {data['accreditation']}.</p>
      <p>Текущий курс — {data['course']}. Форма обучения — {data['study_mode']}.
      Срок получения образования — {data['duration']}. Окончание обучения — {data['graduation_date']}.</p>
      <p>Для представления: {data['commissioner']}.</p>
      <p>Руководитель или заместитель руководителя образовательной организации<br>
      <small>Имя и фамилия не заполнены, подпись отсутствует. Место печати пустое.</small></p>
      <h2>Военная подготовка</h2>
      <p>Раздел ВУЦ оставлен пустым. Договор, начало и окончание подготовки, комиссариат,
      оформляющий аттестационные материалы, и подпись должностного лица отсутствуют в подтверждённых сведениях.</p>
    </section>'''
