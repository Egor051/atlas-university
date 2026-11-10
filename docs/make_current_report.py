"""Rebuild the factual process PDF and inspect a downloaded A4 result.

Install requirements-dev.txt and docs/requirements-report.txt, then install the
Playwright Chromium runtime. Run this script from any working directory using
that Python environment. Input evidence and screenshots must exist alongside it.
"""
from pathlib import Path
from xml.sax.saxutils import escape
import json,sys,subprocess,xml.etree.ElementTree as ET
from PIL import Image as PIL
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from pypdf import PdfReader
import make_report as base  # Reuses the verified embeddable installed font, never copies a font file.

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/verification/improvements-2026-11-08'
OUT=ROOT/'docs/ATLAS_Campus_3_2_Process.pdf'
styles=base.styles
styles['body'].fontSize=10.5;styles['body'].leading=15.5
story=[]
def p(text,style='body'):return Paragraph(text,styles[style])
def add(text,style='body'):story.append(p(text,style))
def page(title):
    if story:story.append(PageBreak())
    add('АТЛАС CAMPUS / 3.2 / 9 НОЯБРЯ 2026','label');add(title,'h1')
def table(head,rows,widths):
    data=[[p(escape(str(x)),'cellhead') for x in head]]+[[p(escape(str(x)),'cell') for x in row] for row in rows]
    t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT');t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),base.PALE),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,-1),.4,base.LINE)]));story.append(t);story.append(Spacer(1,12))
def shot(name,width,maxheight=500):
    path=ROOT/name
    with PIL.open(path) as source:w,h=source.size
    scale=min(width/w,maxheight/h);return Image(str(path),width=w*scale,height=h*scale)
def footer(canvas,doc):
    canvas.saveState();canvas.setStrokeColor(base.LINE);canvas.line(42,36,553,36);canvas.setFont('Atlas',8);canvas.setFillColor(base.MUTED);canvas.drawString(42,23,'Конкурсный концепт. Все данные вымышлены. Локальная проверка.');canvas.drawRightString(553,23,str(doc.page));canvas.restoreState()
scores=json.loads((DATA/'score-update.json').read_text(encoding='utf-8'))
perf=json.loads((DATA/'performance.json').read_text(encoding='utf-8'))
load=json.loads((DATA/'load.json').read_text(encoding='utf-8'))
pg=json.loads((DATA/'postgres-https.json').read_text(encoding='utf-8'))
suites=ET.parse(DATA/'pytest-results.xml').getroot();tests=sum(int(x.get('tests',0)) for x in suites.iter('testsuite'))
def n(value):return str(value).replace('.',',')

page('Цифровой деканат:\nот задачи к результату')
add('Рабочий прототип личного кабинета студента','subtitle')
add('Учёба, документы и связь с офисом в одном месте. Версия 3.2 соединяет сигналы с конкретными действиями и сохраняемым результатом. Все персонажи, правила и документы вымышлены; это неофициальный конкурсный концепт.')
table(['Факт','Подтверждение'],[
 ('Обязательное ядро','Вход/профиль, день/неделя расписания, успеваемость, заявка/статус, уведомления.'),
 ('Локальная приёмка',f'{tests} pytest без пропусков; реальные HTTP/Chromium, отдельные Firefox/WebKit и PostgreSQL/HTTPS.'),
 ('Прозрачная оценка',n(scores['total_40'])+'/40 по авторской фиксированной шкале. 42 улучшения закрыты, 28 подготовлены без неподтверждённых баллов.'),
 ('Граница доказательств','Настоящие интервью, физические телефоны, РФ и публичный хостинг пока не подтверждены.')],[150,361])
story.append(shot('screenshots/improvements-2026-11-09/1440-home.png',480,300))

page('Проблема и продуктовая гипотеза')
add('ТЗ описывает разрозненные расписание, оценки, справки и объявления. Выбраны пять обязательных задач, а дополнительная функциональность сгруппирована вокруг учебного действия и получения ответа. Потребности настоящих студентов ещё не исследованы: частоты, цитаты и предпочтения не выдумывались.')
table(['Задача','Путь в прототипе'],[
 ('Понять свой день','Главная → ближайшая пара → правильная дата, аудитория и преподаватель.'),
 ('Не пропустить перенос','Баннер → изменённая пара → прежние и новые сведения.'),
 ('Понять успеваемость','Оценка → своя дисциплина → материал, работа, консультация или вопрос офису.'),
 ('Получить справку','Услуга → поля и срок → отправка → обработка → история и результат.'),
 ('Вернуться к работе','Личный серверный черновик → повторный вход той же личности → восстановление.')],[150,361])
add('Moodle, Canvas и MyStudyLife по официальным описаниям уже соединяют ряд учебных функций. Поэтому число разделов не считается доказательством новизны. Выбранный акцент ATLAS - законченный понятный путь от личного учебного сигнала к действию и ответу офиса. Это гипотеза ценности, готовая к проверке.')
add('Подготовлены протокол 5–8 добровольцев, согласие, пустой журнал задач и наблюдений, критерии повторной проверки. Автоматизированные сценарии хранятся отдельно. Материалы: research-kit/, alternatives-research-2026-11-09.md, feature-priorities.md.','small')

page('Хранение и защита простыми словами')
table(['Механизм','Что обеспечивает'],[
 ('Вход','Пароль сравнивается с Argon2-хешем. Случайный токен сеанса хранится в HttpOnly/SameSite cookie; на HTTPS - Secure. В БД хранится хеш токена.'),
 ('Владелец','Сервер получает пользователя из сеанса и ограничивает SQL-запрос. Подстановка student_id не назначает владельца.'),
 ('Роли','Студент не имеет API сотрудника, сотрудник не читает студенческие оценки/расписание. Прямые чужие ID отклоняются.'),
 ('Сохранение','SQLite локально, PostgreSQL в Compose. Аддитивные миграции сохраняют историю. Полный backup/restore проверяется отдельно.'),
 ('Повтор и конфликт','Receipt связывает актёра, операцию, ключ и отпечаток. Повтор не создаёт дубль; версия заявки защищает решение сотрудника.'),
 ('Черновики','Личные данные формы доступны владельцу 14 дней; повторный вход другой личности их не открывает. Ключ отправки сохраняется до подтверждения.'),
 ('Ограничения','CSRF/Origin, размер тела, строгие поля, экранирование, CSP и SQL-квоты записи. Демоаккаунты публичны и вымышлены.')],[130,381])
add('Студент может уточнить сведения или попросить отозвать заявку; он не меняет статус. Этап «Нужны уточнения» назначает сотрудник. Все сообщения остаются в истории. Контракты: api-contracts.md, services-api.md.','small')

page('Как использовались ИИ-ассистенты')
add('Код, интерфейс и материалы создавались с Codex в настольном приложении. Главный ассистент согласовал общую задачу и интеграцию; три дочерние роли выполняли ограниченные поручения. Это одна ИИ-среда, а не три внешних независимых эксперта.')
table(['Роль','Фактическая работа'],[
 ('Главный ассистент','ТЗ, рубрика/70 ID, core API, черновики, маршрутизация, интеграция, проверки и отчёт.'),
 ('Backend / Security','SQL-фильтрация/страницы, receipt, фиктивные даты до финала, N+1; затем review гонок черновиков и повторов.'),
 ('UX/Visual','Точные календарные маршруты, предметный контекст, формы, страницы услуг, клавиатура и CSS-стресс.'),
 ('QA/Release','Изолированный PostgreSQL/HTTPS, нагрузка, SQL-профиль, производительность, Firefox/WebKit и чистый запуск архива.')],[135,376])
add('Полные выбранные выдержки постановок, ответов и уточнений: ai-evidence-3.2.md. Например: «Не имитируй результаты испытаний с реальными людьми и не выдумывай доказательства». Это ограничение сохранено в коде проверок и формулировках результатов.')
add('Backend: «поиск до LIMIT… идемпотентность… негативные IDOR… неразрушительная миграция». UX: «точные переходы календаря… контекст… ясная связь личной отметки и сдачи». Release: «текущая версия PostgreSQL+HTTPS+backup restore… не выдавай simulated INP за field INP». Исходные формулировки и интеграционные решения доступны в текстовых выдержках, не в поддельных снимках чата.','small')
add('Инструкции для ИИ','h2')
add('AGENTS.md содержит карту текущих модулей, инварианты владения и ролей, сохранения и 360 px. Контракты API и команды тестов отделены от оформления. Каждое поручение имело границы файлов и проверяемый выход.')

page('Ошибки ИИ и проверяемые исправления')
table(['Исходный сбой','Решение и доказательство'],[
 ('Ближайшая пара → пустой текущий день','Дата/неделя/id передаются в маршрут; занятие выделяется. Исходная проба и настоящая Chromium-регрессия сохранены.'),
 ('После 300 записей нет нужной книги/будущего слота','Фильтрация в SQL до LIMIT, страницы и архив. Проверки 310+ записей находят нужный результат.'),
 ('После потери ответа создаётся вторая тема','Реальный сервер сохраняет 201, ответ прерывается, повтор идёт с тем же ключом и возвращает тот же ID.'),
 ('Длинный черновик дублируется в fingerprint','Отпечаток заменён компактным SHA-256. Длинный ответ восстанавливается после перезагрузки.'),
 ('Поздняя очистка может попасть в новый сеанс','После ожидания очереди повторно сверяются uid и epoch. Детерминированный callback-тест защищает смену личности.'),
 ('Контраст метатекста 4,44:1','Изменён цвет, повторно проверены 128 состояний axe. Уменьшение текста ради плотности не использовалось.')],[160,351])
add('Новые проверки находили и обычные интеграционные несоответствия: состав счётчиков после нового статуса, порядок Tab после добавления ссылок, оставшийся disabled у отметки. Они исправлены и перепроверены. Количество тестов не подменяет полезность продукта.')
add('Первичные до-данные: baseline-security-probes.json, baseline-ui-probes.json. После: tests/test_improvements_*.py, JSON текущей приёмки и ai-evidence-3.2.md.','small')

page('Фактический интерфейс 3.2')
add('Настоящие локальные браузерные снимки, 9 ноября 2026. На телефоне показана эмуляция ширины, а не физическое устройство. Горизонтальное переполнение проверяется отдельно.')
t=Table([[shot('screenshots/improvements-2026-11-09/1440-home.png',335,490),shot('screenshots/improvements-2026-11-09/390-home.png',155,490)]],colWidths=[345,166]);t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]));story.append(t)
add('Главная и постоянная навигация. Состояние связи не исчезает вместе с кратким сообщением; переход к паре выбирает конкретную дату.','small')

page('Путь заявки и реальная запись')
for names in [('05-form.png','08-staff-ready.png'),('06-submitted.png','09-result.png')]:
    t=Table([[shot('docs/verification/improvements-2026-11-08/demo/'+name,245,185) for name in names]],colWidths=[255,256]);t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]));story.append(t);story.append(Spacer(1,12))
add('Реальный автоматизированный проход: форма → сохранение → решение сотрудника → ответ владельцу и скачивание HTML-образца. Кадры соответствуют видео atlas-demo-local.mp4 с субтитрами. Чужой студент получил 404. Файлы и JSON шагов включены в исходный комплект.','small')
add('Материалы не выданы за публичную E2E-проверку или исследование реального человека. Подробный живой сценарий до пяти минут: jury-guide.md и demo-video-script.md.')

page('Проверки и практические границы')
mobile=next(x for x in perf['summary'] if x['profile']=='mobile_lab')
table(['Область','Фактический результат'],[
 ('Pytest',f'{tests} пройдено, без ошибок и пропусков. Два предупреждения тестовых библиотек о deprecated API.'),
 ('Геометрия/axe','128 состояний 360/390/768/1440 px, без горизонтального переполнения и выбранных нарушений; отдельно 24 CSS-стресс состояния и 320 px.'),
 ('Другие браузеры','Firefox 142.0.1 / WebKit 26.0: 192 проверки геометрии и сквозной путь заявки через UI.'),
 ('Нагрузка',f'8 искусственных клиентов, 800 чтений, 40 созданий и 40 повторов. p95 чтений {n(load["p95_ms"])} мс; неожиданных ответов нет.'),
 ('SQL','SELECT 4→4 для курсов, заданий и тем при увеличении данных; N+1 в этих сценариях устранён.'),
 ('Мобильная лаборатория',f'LCP p75 {n(mobile["cold_login_lcp_p75_ms"])} мс, CLS {n(mobile["cls_p75"])}. 150 мс сети, 1,6 Мбит/с, CPU×4. Это не полевой INP.'),
 ('PostgreSQL / TLS',f'Два web-процесса, роли, конкурентные места/книги/черновики и уточнения. Restart и восстановление {pg["backup_restore"]["tables"]} таблиц с одинаковыми digest.'),
 ('Передача','Чистый архив стартует в новом venv, проходит API/IDOR, workflow и restart; финальный SHA подтверждён отдельным актом рядом с ZIP.')],[133,378])
add('Непроверенное: физические Android/iPhone, ручной скринридер, настоящие добровольцы, российское подключение, публичный DNS/CA и будущая доступность до 28 ноября. Эти результаты не засчитаны.','small')

page('Инструменты, капитан и передача')
add('Обычные программы не названы нейросетями: PowerShell/Python/Node; FastAPI/SQLAlchemy/Argon2; Pytest/HTTPX; Playwright/axe; Docker/PostgreSQL/Caddy; FFmpeg; ReportLab/Pillow/Poppler; Google Drive для подготовленных файлов подачи. В актуальном комплекте есть проверка 22 пакетов фактического runtime через PyPI и OSV. Данные о неизвестных инструментах прошлых этапов не выдуманы.')
add('Капитан предоставил ТЗ и задачи. Иные ручные действия не подтверждены. Для их фактического описания подготовлен пустой шаблон captain-contribution.md. Реальные интервью, записи голосов и отзывы не создавались.')
table(['Роль','Демо-логин','Вымышленный пароль'],[
 ('Студентка Алина','alina.demo','AtlasDemo!2026-A'),('Студент Марк','mark.demo','AtlasDemo!2026-M'),('Учебный офис Кира','dean.demo','AtlasStaff!2026-D')],[145,156,210])
add('Что подготовлено владельцу','h2')
add('Чистые исходники и внешний акт приёмки; Compose и безопасное создание конфигурации; мониторинг/backup/restore; текущие отчёт и видео; исследовательский протокол и пустые формы; чек-листы настоящих устройств, РФ и календаря. Нужны постоянный хостинг/домен, проверка из РФ без VPN, настоящие участники и подтверждение ручного вклада.')
add('Полная трассировка по всем 70 ID и фиксированная оценка: improvements-3.2-status.md. Подробные первичные сообщения: ai-evidence-3.2.md. JSON, хеши и исходные сценарии проверок находятся в verification/improvements-2026-11-08/.')
add('Итог авторской модели: '+n(scores['total_40'])+'/40. Это оценка подтверждённых свойств, не обещание решения жюри.','subtitle')

doc=SimpleDocTemplate(str(OUT),pagesize=(595.276,841.89),leftMargin=42,rightMargin=42,topMargin=39,bottomMargin=48,title='ATLAS Campus 3.2 - factual creation process',author='ATLAS Campus / Codex-assisted prototype')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
# Actual downloaded HTML is rendered locally; no synthetic successful API body.
code="""from pathlib import Path
from playwright.sync_api import sync_playwright
import sys
p=Path(sys.argv[1])
with sync_playwright() as a:
 b=a.chromium.launch();page=b.new_page();page.goto(p.as_uri());page.emulate_media(media='print');page.pdf(path=str(p.with_name('fictional-result-a4.pdf')),format='A4',print_background=True);b.close()
"""
subprocess.run([sys.executable,'-c',code,str(DATA/'demo/fictional-result.html')],check=True,timeout=45)
result_pdf=DATA/'demo/fictional-result-a4.pdf'
text='\n'.join(p.extract_text() for p in PdfReader(result_pdf).pages)
assert 'ВЫМЫШЛЕНЫ' in text and 'Справка' in text
assert len(PdfReader(result_pdf).pages)<=2
report={'process_pdf':OUT.name,'pages':len(PdfReader(OUT).pages),'downloaded_result_a4_pages':len(PdfReader(result_pdf).pages),'cyrillic_extraction':'PASS','manual_calendar_import':'NOT_VERIFIED','status':'PASS'}
(DATA/'pdf-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
