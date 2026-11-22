"""Published reserve-training rules and the scope of VUC credentials."""
from typing import Literal

from .config import DEMO_LOGINS, settings

ProgramCategory = Literal['officer_reserve', 'sergeant_reserve', 'soldier_reserve']
StageKind = Literal['preliminary', 'medical', 'psychological', 'physical', 'competition', 'results', 'formalities']

CATEGORIES = {
    'officer_reserve': 'Офицеры запаса',
    'sergeant_reserve': 'Сержанты запаса',
    'soldier_reserve': 'Солдаты запаса',
}
STAGES = {
    'preliminary': 'Предварительный отбор',
    'medical': 'Медицинское освидетельствование',
    'psychological': 'Профессиональный психологический отбор',
    'physical': 'Оценка физической подготовки',
    'competition': 'Конкурсный отбор с учётом текущей успеваемости',
    'results': 'Объявление решения конкурсной комиссии',
    'formalities': 'Заключение договора и допуск приказом ректора',
}
FEDERAL_REQUIREMENTS = (
    'Гражданство РФ, возраст до 30 лет и очное обучение в федеральном государственном вузе.',
    'Отсутствие иностранного гражданства, вида на жительство или иного права постоянного проживания за рубежом.',
    'Заключения о годности к военной службе или годности с незначительными ограничениями и о соответствии '
    'профессионально-психологическим требованиям. Их оформляют уполномоченные специалисты.',
    'Для заключения договора требуется отсутствие неснятой или непогашенной судимости '
    'и уголовного преследования.',
    'Действуют основания недопуска из п. 26 Порядка № 400, в том числе академическая задолженность. '
    'Окончательное решение принимает конкурсная комиссия.',
)
LAW_URL = 'https://www.consultant.ru/document/cons_doc_LAW_18260/ee151c8b432bc65eeb27338aa070fd553463515a/'
ORDER_URL = 'https://sudact.ru/law/prikaz-ministra-oborony-rf-ot-26082020-n/prilozhenie/iii/'


def private_account(user):
    return settings.app_env != 'production' or user.login not in DEMO_LOGINS


def can_manage_vuc(user):
    return user.role == 'vuc' and private_account(user)
