"""Initial records for the student union and VUC."""
from datetime import timedelta

from sqlalchemy import select

from .db import campus_today, utc_now
from .units_db import UnitPublication
from .workspace_seed import seed_account


def seed_units(db):
    union = seed_account(db,'union.demo','AtlasUnion!2026-U','Полина Савельева','ПС','Представитель профсоюза','union')
    seed_account(db,'vuc.demo','AtlasCenter!2026-V','Артём Неверов','АН','Сотрудник ВУЦ','vuc')
    day = campus_today()
    if db.scalar(select(UnitPublication.id).where(UnitPublication.unit=='union').limit(1)) is not None or union.role!='union':
        return
    entries = (
        ('structure','Представители студенческого профсоюза','Полина Савельева ведёт обращения и членство. Бюро поддержки разбирает заявки, а команда мероприятий принимает записи.',None,None),
        ('benefit','Поддержка учебных инициатив','Программа консультаций и помощи с учебными расходами. Выберите категорию обращения и опишите ваш вопрос.',None,None),
        ('news','Открыты часы консультаций','Заявку на консультацию можно оформить из кабинета. Представитель укажет время в ответе.',None,None),
        ('event','Встреча студенческих инициатив','Участники предложат идеи для учебных и культурных встреч. Корпус А, зал 2.',day+timedelta(days=15),18),
        ('document','Как подать заявление о вступлении','Заявление формируется в разделе профсоюза после входа. Участник подтверждает своё решение и видит ответ представителя в истории.',None,None),
    )
    db.add_all(UnitPublication(unit='union',kind=kind,title=title,body=body,author_id=union.id,
                               event_day=event_day,capacity=capacity,updated_at=utc_now())
               for kind,title,body,event_day,capacity in entries)
