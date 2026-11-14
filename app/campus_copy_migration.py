"""Update only known bundled copy, leaving user-authored content intact."""
from sqlalchemy import exists, select, update

from .db import DocumentRequest, RequestEvent
from .learning_db import Attendance, CourseModule
from .services_db import CampusEvent, FinanceEntry
from .units_db import CenterProgram, CenterSession, UnitCaseEvent, UnitPublication
from .university_db import Faculty, TeachingMaterial


def upgrade_campus_copy(connection):
    def replace(model, column, old, new, *scope):
        connection.execute(update(model).where(column == old, *scope).values({column.key: new}))

    system_event = exists(select(RequestEvent.id).where(
        RequestEvent.request_id == DocumentRequest.id, RequestEvent.actor_role == 'system'))
    replace(DocumentRequest, DocumentRequest.staff_message, 'Демонстрационный документ подготовлен. Все данные вымышлены.',
            'Документ подготовлен.', DocumentRequest.version == 1, system_event)
    replace(RequestEvent, RequestEvent.message, 'Вымышленная заявка для демонстрации сценария.',
            'Заявка сохранена.', RequestEvent.actor_role == 'system')
    replace(RequestEvent, RequestEvent.message,
            'Заявка сохранена в предыдущей версии прототипа; ранние этапы не восстанавливались.',
            'Заявка перенесена из предыдущей версии. История начинается с сохранённого этапа.',
            RequestEvent.actor_role == 'system')
    replace(FinanceEntry, FinanceEntry.description, 'Демонстрационная академическая стипендия', 'Академическая стипендия')
    replace(FinanceEntry, FinanceEntry.description, 'Демонстрационная плата за проживание', 'Плата за проживание')
    replace(CampusEvent, CampusEvent.description,
            'Соберите команду и предложите решение учебной задачи. Конкурсный демонстрационный сценарий.',
            'Соберите команду, предложите решение учебной задачи и представьте его на разборе.',
            CampusEvent.title == 'Кампус-хакатон: сервисы для студентов')
    replace(CampusEvent, CampusEvent.location, 'Онлайн · ссылка не предоставляется в концепте', 'Онлайн',
            CampusEvent.title == 'Академическая мобильность: первые шаги')
    replace(CourseModule, CourseModule.content,
            'Отличайте нормативный акт, договор и мнение автора. Для учебного разбора фиксируйте дату и юрисдикцию источника. Материал прототипа не является юридической консультацией.',
            'Отличайте нормативный акт, договор и мнение автора. Для учебного разбора фиксируйте дату и юрисдикцию источника.',
            CourseModule.title == 'Источники и контекст')
    replace(CourseModule, CourseModule.content,
            'Для учебного кейса определите, какие данные собираются, зачем, кто имеет доступ и когда данные удаляются. В этом прототипе используются только вымышленные записи.',
            'Для учебного кейса определите, какие данные собираются, зачем, кто имеет доступ и когда данные удаляются.',
            CourseModule.title == 'Данные и доступ')
    replace(Attendance, Attendance.note, 'Вымышленная отметка посещаемости.', '', Attendance.version == 1)
    replace(Attendance, Attendance.note, 'Учебный пример уважительной причины.', 'Уважительная причина.', Attendance.version == 1)
    replace(Faculty, Faculty.description,
            'Институт вымышленного университета АТЛАС. Здесь изучают разработку систем и проектирование цифровых сервисов.',
            'Здесь изучают разработку систем и проектирование цифровых сервисов.', Faculty.slug == 'digital')
    original = ('Вставьте одну книгу с двумя экземплярами. Для каждого добавьте выдачу разным вымышленным читателям. '
                'Попробуйте вставить выдачу для отсутствующего экземпляра: база должна отклонить её. Проверьте выборку '
                'активных выдач по условию returned_on IS NULL.')
    material = TeachingMaterial.__table__
    row_filter = (material.c.title == 'Методические указания. Связи в учебной базе', material.c.version == 1)
    for row in connection.execute(select(material.c.id, material.c.body).where(*row_filter)):
        if original in row.body:
            connection.execute(update(material).where(material.c.id == row.id)
                               .values(body=row.body.replace(original, original.replace('вымышленным ', ''))))
    replace(TeachingMaterial, TeachingMaterial.description,
            'Упражнение на LEFT JOIN и обработку пустых значений на вымышленном формуляре.',
            'Упражнение на LEFT JOIN и обработку пустых значений в журнале выдач.',
            TeachingMaterial.title == 'Практикум. Выборка свободных экземпляров', TeachingMaterial.version == 1)

    replace(CenterProgram, CenterProgram.description,
            'Учебная программа макета. Группа разбирает календарь, порядок обращений и ведение учебных записей.',
            'Группа разбирает календарь, порядок обращений и ведение учебных записей.', CenterProgram.version == 1)
    replace(CenterProgram, CenterProgram.requirements,
            'Войдите как вымышленный студент. Проверьте образцы заявления и подтверждения статуса в чек-листе.',
            'Проверьте заявление и подтверждение статуса студента по чек-листу.', CenterProgram.version == 1)
    replace(CenterProgram, CenterProgram.requirements, 'Учебный аккаунт студента и два демонстрационных подтверждения в заявлении.',
            'Для подачи нужен студенческий аккаунт и два подтверждения в форме.', CenterProgram.version == 1)
    replace(CenterSession, CenterSession.room, 'Онлайн в рамках концепта', 'Онлайн', CenterSession.version == 1)
    replace(UnitCaseEvent, UnitCaseEvent.message, 'Демонстрационная заявка подана.', 'Заявление подано.',
            UnitCaseEvent.action == 'submitted')
    for title, body, new_title, new_body in (
        ('Поддержка учебных инициатив',
         'Вымышленная программа консультаций и помощи с учебными расходами. Выберите категорию обращения и опишите учебный пример.',
         'Поддержка учебных инициатив',
         'Программа консультаций и помощи с учебными расходами. Выберите категорию обращения и опишите ваш вопрос.'),
        ('Встреча студенческих инициатив',
         'Участники предложат идеи для учебных и культурных встреч. Вымышленное место: корпус А, зал 2.',
         'Встреча студенческих инициатив', 'Участники предложат идеи для учебных и культурных встреч. Корпус А, зал 2.'),
        ('Учебный образец заявления о вступлении',
         'Заявление формируется в разделе профсоюза после входа. Участник подтверждает своё решение и видит ответ представителя в истории.',
         'Как подать заявление о вступлении',
         'Заявление формируется в разделе профсоюза после входа. Участник подтверждает своё решение и видит ответ представителя в истории.'),
        ('Учебный офис ВУЦ',
         'Артём Неверов сопровождает демонстрационный отбор, группы и учебные записи. Вопрос можно отправить из кабинета.',
         'Учебный офис ВУЦ',
         'Артём Неверов сопровождает отбор, группы и учебные записи. Вопрос можно отправить из кабинета.'),
        ('Демонстрационный набор открыт',
         'Даты подачи показаны в карточках программ. После решения сотрудника в кабинете появится учебная группа.',
         'Открыт приём заявлений',
         'Даты подачи показаны в карточках программ. После решения сотрудника в кабинете появится учебная группа.'),
        ('Чек-лист демонстрационных образцов',
         'Перед подачей отметьте вымышленное заявление и вымышленное подтверждение статуса студента. Список проверяется в учебной форме.',
         'Документы для подачи заявления',
         'Перед подачей проверьте заявление и подтверждение статуса студента по чек-листу в форме.'),
    ):
        connection.execute(update(UnitPublication).where(UnitPublication.title == title, UnitPublication.body == body,
                           UnitPublication.version == 1).values(title=new_title, body=new_body))
