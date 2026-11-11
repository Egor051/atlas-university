"""Seed data for the fictional union and the administrative VUC demonstration."""
from datetime import timedelta

from sqlalchemy import select

from .db import campus_today, utc_now
from .units_db import CenterGroup, CenterProgram, CenterSession, UnitPublication
from .workspace_seed import seed_account


def seed_units(db):
    from datetime import datetime, time, timezone
    from .db import CAMPUS_TZ

    union = seed_account(db,'union.demo','AtlasUnion!2026-U','Полина Савельева','ПС','Представитель профсоюза','union')
    vuc = seed_account(db,'vuc.demo','AtlasCenter!2026-V','Артём Неверов','АН','Сотрудник ВУЦ','vuc')
    day = campus_today()
    if db.scalar(select(CenterProgram.id).limit(1)) is None:
        program = CenterProgram(title='Организация учебного процесса',description='Учебная программа макета. Группа разбирает календарь, порядок обращений и ведение учебных записей.',
                                requirements='Войдите как вымышленный студент. Проверьте образцы заявления и подтверждения статуса в чек-листе.',
                                opens=day-timedelta(days=2),closes=day+timedelta(days=60))
        second = CenterProgram(title='Работа с учебной информацией',description='Практикум по проверке учебных документов, расписания и доступности материалов.',
                               requirements='Учебный аккаунт студента и два демонстрационных подтверждения в заявлении.',
                               opens=day-timedelta(days=1),closes=day+timedelta(days=90))
        db.add_all([program,second]);db.flush()
        a=CenterGroup(program_id=program.id,code='АТ-ВУЦ-01',capacity=16)
        b=CenterGroup(program_id=second.id,code='АТ-ВУЦ-02',capacity=12)
        db.add_all([a,b]);db.flush()
        starts=datetime.combine(day+timedelta(days=12),time(17,30),CAMPUS_TZ).astimezone(timezone.utc)
        db.add(CenterSession(group_id=a.id,title='Вводная встреча и учебный календарь',room='Учебный корпус А, 204',
                             starts_at=starts,ends_at=starts+timedelta(minutes=60)))
        db.add(CenterSession(group_id=b.id,title='Проверка комплектности учебной записи',room='Онлайн в рамках концепта',
                             starts_at=starts+timedelta(days=1),ends_at=starts+timedelta(days=1,minutes=45)))
    for unit,actor,entries in (
        ('union',union,[
            ('structure','Представители студенческого профсоюза','Полина Савельева ведёт обращения и членство. Бюро поддержки разбирает заявки, а команда мероприятий принимает записи.',None,None),
            ('benefit','Поддержка учебных инициатив','Вымышленная программа консультаций и помощи с учебными расходами. Выберите категорию обращения и опишите учебный пример.',None,None),
            ('news','Открыты часы консультаций','Заявку на консультацию можно оформить из кабинета. Представитель укажет время в ответе.',None,None),
            ('event','Встреча студенческих инициатив','Участники предложат идеи для учебных и культурных встреч. Вымышленное место: корпус А, зал 2.',day+timedelta(days=15),18),
            ('document','Учебный образец заявления о вступлении','Заявление формируется в разделе профсоюза после входа. Участник подтверждает своё решение и видит ответ представителя в истории.',None,None),
        ]),
        ('vuc',vuc,[
            ('structure','Учебный офис ВУЦ','Артём Неверов сопровождает демонстрационный отбор, группы и учебные записи. Вопрос можно отправить из кабинета.',None,None),
            ('news','Демонстрационный набор открыт','Даты подачи показаны в карточках программ. После решения сотрудника в кабинете появится учебная группа.',None,None),
            ('document','Чек-лист демонстрационных образцов','Перед подачей отметьте вымышленное заявление и вымышленное подтверждение статуса студента. Список проверяется в учебной форме.',None,None),
            ('material','Как пользоваться учебным календарём','Откройте группу и найдите дату встречи по МСК. Сверьте тему, время и аудиторию. После занятия проверьте запись результата. Вопрос по записи отправьте через раздел обращений.',None,None),
        ]),
    ):
        if db.scalar(select(UnitPublication.id).where(UnitPublication.unit==unit).limit(1)) is not None or actor.role!=unit:
            continue
        db.add_all(UnitPublication(unit=unit,kind=kind,title=title,body=body,author_id=actor.id,
                                   event_day=event_day,capacity=capacity,updated_at=utc_now())
                   for kind,title,body,event_day,capacity in entries)
