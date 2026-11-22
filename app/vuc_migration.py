"""Preserve former practice records and seed only verified reference programs."""
from datetime import date

from sqlalchemy import select, update

from .db import User
from .units_db import CenterProgram, UnitPublication
from .vuc_db import VucProgram

MGSU_PAMPHLET = (
    'https://mgsu.ru/education/Voennaya_kafedra/'
    '%D0%9F%D0%90%D0%9C%D0%AF%D0%A2%D0%9A%D0%90%20'
    '%D0%9F%D0%9E%D0%A1%D0%A2%D0%A3%D0%9F%D0%90%D0%AE%D0%A9%D0%95%D0%9C%D0%A3.pdf'
)


def upgrade_vuc_admission(connection):
    connection.execute(update(CenterProgram).where(CenterProgram.published.is_(True))
                       .values(published=False, version=CenterProgram.version + 1))
    legacy_titles = (
        'Учебный офис ВУЦ', 'Открыт приём заявлений', 'Документы для подачи заявления',
        'Как пользоваться учебным календарём',
    )
    connection.execute(
        update(UnitPublication).where(
            UnitPublication.unit == 'vuc',
            UnitPublication.author_id.in_(select(User.id).where(User.login == 'vuc.demo')),
            UnitPublication.title.in_(legacy_titles),
            UnitPublication.published.is_(True),
        ).values(published=False, version=UnitPublication.version + 1)
    )
    reference = (
        ('officer_reserve', 'Подготовка офицеров запаса', 30,
         'НИУ МГСУ: очный специалитет 08.05.01 (3-й курс), 23.05.01 (2-й курс) '
         'и бакалавриат 07.03.01, 07.03.02, 07.03.04 (2-й курс).'),
        ('sergeant_reserve', 'Подготовка сержантов запаса', 24,
         'НИУ МГСУ: очный бакалавриат 08.03.01 «Строительство», 1-й курс.'),
        ('soldier_reserve', 'Подготовка солдат запаса', 18,
         'НИУ МГСУ: 2-й курс отдельных направлений очного четырёхлетнего бакалавриата. '
         'Перечень направлений опубликован в разделе «Военный учебный центр сегодня».'),
    )
    connection.execute(VucProgram.__table__.insert(), [
        dict(category=category, title=title, duration_months=months, academic_link=academic_link,
             outcome='Подготовка к зачислению в запас после успешного завершения военной подготовки '
             'и окончания вуза в порядке, установленном законом.',
             requirements='Курс и направление обучения сверяются с условиями конкретного набора.',
             selection='Предварительный отбор, затем конкурс. По рекомендации комиссии оформляются '
             'договор с Минобороны и допуск к обучению приказом ректора.',
             state='active', source_title='НИУ МГСУ · Памятка для поступающего в ВУЦ',
             source_url=MGSU_PAMPHLET, verified_on=date(2026, 11, 22), version=1)
        for category, title, months, academic_link in reference
    ])
