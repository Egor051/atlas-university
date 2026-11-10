"""Rebuild the factual ATLAS Campus process PDF from verified local evidence.

pip install -r docs/requirements-report.txt
python docs/make_report.py

Uses an installed embeddable Segoe UI on Windows or DejaVu Sans on Linux.
No font files, external images, or invented interview/chat screenshots are shipped.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import struct
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    PageBreak, KeepTogether, HRFlowable,
)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/ATLAS_Process_Report.pdf'
TMP=ROOT/'tmp/pdfs'
TMP.mkdir(parents=True,exist_ok=True)
W,H=595.276,841.89
CONTENT=511
INK=colors.HexColor('#28283e')
TEXT=colors.HexColor('#5b586e')
PURPLE=colors.HexColor('#68558a')
PALE=colors.HexColor('#ece5f5')
LINE=colors.HexColor('#e2dbea')
MUTED=colors.HexColor('#73657f')


def font_embedding_flag(path):
    data=Path(path).read_bytes()
    count=struct.unpack_from('>H',data,4)[0]
    for i in range(count):
        tag,_,offset,_=struct.unpack_from('>4sIII',data,12+i*16)
        if tag==b'OS/2':
            return struct.unpack_from('>H',data,offset+8)[0]
    raise ValueError('Font embedding flags unavailable')


font_pairs=[
    (Path('C:/Windows/Fonts/segoeui.ttf'),Path('C:/Windows/Fonts/segoeuib.ttf')),
    (Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')),
]
for regular,bold in font_pairs:
    if regular.exists() and bold.exists():
        # Reject restricted embedding, print-only embedding and no-subsetting fonts.
        for path in (regular,bold):
            flags=font_embedding_flag(path)
            if flags & 0x302 or (flags & 4 and not flags & 8):
                raise ValueError(f'Font does not permit this editable/subset PDF: {path.name}')
        pdfmetrics.registerFont(TTFont('Atlas',str(regular)))
        pdfmetrics.registerFont(TTFont('AtlasBold',str(bold)))
        break
else:
    raise SystemExit('Install DejaVu Sans or use Windows with Segoe UI; fonts are not redistributed.')

styles={
    'title':ParagraphStyle('title',fontName='AtlasBold',fontSize=36,leading=42,textColor=INK,spaceAfter=14),
    'subtitle':ParagraphStyle('subtitle',fontName='Atlas',fontSize=17,leading=23,textColor=PURPLE,spaceAfter=14),
    'h1':ParagraphStyle('h1',fontName='AtlasBold',fontSize=25,leading=31,textColor=INK,spaceAfter=15),
    'h2':ParagraphStyle('h2',fontName='AtlasBold',fontSize=13,leading=18,textColor=PURPLE,spaceBefore=12,spaceAfter=7),
    'body':ParagraphStyle('body',fontName='Atlas',fontSize=10.2,leading=15.5,textColor=TEXT,spaceAfter=10),
    'small':ParagraphStyle('small',fontName='Atlas',fontSize=8.2,leading=12,textColor=MUTED,spaceAfter=8),
    'label':ParagraphStyle('label',fontName='AtlasBold',fontSize=8,leading=12,textColor=PURPLE,spaceAfter=12),
    'cell':ParagraphStyle('cell',fontName='Atlas',fontSize=8.7,leading=12.5,textColor=TEXT),
    'cellhead':ParagraphStyle('cellhead',fontName='AtlasBold',fontSize=8.5,leading=12,textColor=PURPLE),
    'number':ParagraphStyle('number',fontName='AtlasBold',fontSize=25,leading=30,textColor=PURPLE),
}


def p(text,style='body'):
    text=str(text).replace('\u2011','-').replace('–','-').replace('—','-')
    return Paragraph(escape(text).replace('\n','<br/>'),styles[style])


def table(headers,rows,widths):
    data=[[p(x,'cellhead') for x in headers]]+[[p(x,'cell') for x in row] for row in rows]
    t=Table(data,colWidths=widths,hAlign='LEFT',repeatRows=1)
    t.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,0),PALE),
        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
        ('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),
        ('LINEBELOW',(0,1),(-1,-1),.5,LINE),
    ]))
    return t


def shot(name,width,maxheight=None,crop=None):
    source=ROOT/'screenshots'/name
    with PILImage.open(source) as img:
        if crop:
            img=img.crop((0,0,img.width,min(crop,img.height)))
        target=TMP/(source.stem+'-'+str(crop or 'full')+'.png')
        img.save(target)
        height=width*img.height/img.width
    if maxheight and height>maxheight:
        width*=maxheight/height;height=maxheight
    image=Image(str(target),width=width,height=height)
    image.hAlign='CENTER'
    return image


def page(title,kicker):
    return [p(kicker.upper(),'label'),p(title,'h1')]


def header(canvas,doc):
    canvas.saveState()
    canvas.setFillColor(PURPLE)
    canvas.setFont('AtlasBold',9)
    canvas.drawString(42,H-31,'АТЛАС / CAMPUS')
    canvas.setFont('Atlas',8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(W-42,H-31,'ПРОЦЕСС СОЗДАНИЯ · 06.11.2026')
    canvas.setStrokeColor(LINE)
    canvas.line(42,43,W-42,43)
    canvas.setFont('Atlas',7)
    canvas.drawString(42,29,'КОНКУРСНЫЙ КОНЦЕПТ · ВСЕ ДАННЫЕ ВЫМЫШЛЕНЫ')
    canvas.drawRightString(W-42,29,str(doc.page))
    canvas.restoreState()


def evidence():
    docs=ROOT/'docs/verification'
    browser=json.loads((docs/'browser-report.json').read_text(encoding='utf-8'))
    a11y=json.loads((docs/'accessibility-report.json').read_text(encoding='utf-8'))
    tests=json.loads((docs/'test-report.json').read_text(encoding='utf-8'))
    deploy=json.loads((docs/'deployment-report.json').read_text(encoding='utf-8'))
    if any(x['status']!='PASS' for x in (browser,a11y,tests)) or a11y['violating_nodes']:
        raise ValueError('Current evidence does not support a passing report')
    if deploy['result']!='PASS_LOCAL_CONTEST_DEPLOYMENT':
        raise ValueError('Deployment evidence not passing')
    return browser,a11y,tests,deploy


def build():
    browser,a11y,tests,deploy=evidence()
    restart=deploy['checks']['restart_persistence']
    backup=deploy['checks']['backup_and_isolated_restore']
    story=[]
    story.extend([Spacer(1,17),p('ЛОКАЛЬНЫЙ РАБОЧИЙ ПРОТОТИП / ВЕРСИЯ 2.0','label'),
                  p('Твой кампус.\nВ твоём ритме.','title'),
                  p('АТЛАС Campus - цифровой деканат будущего','subtitle'),
                  p('Учёба, документы и связь с учебным офисом. От первой пары до готовой справки - с понятным действием и сохранённым результатом.'),
                  shot('desktop-dashboard.png',CONTENT,crop=940),Spacer(1,12),
                  p('Работа выполнена с помощью Codex: основной ассистент и три дочерних агента. Отчёт описывает фактическую итерацию 6 ноября 2026 года и прилагается к исходному коду.','small'),
                  p('Неофициальный конкурсный концепт. Пользователи и данные вымышлены; подключений к настоящему вузу нет. Публичная публикация в этой итерации не выполнялась.','small'),PageBreak()])

    story+=page('От набора экранов к завершённым задачам','01 / Идея и рост проекта')
    story.append(p('Проблема из ТЗ: расписание, оценки, справки и объявления находятся в разных местах. Кабинет объединяет короткие ежедневные вопросы: куда идти, что сдавать, как идут дела и где готовый документ.'))
    story.append(table(['Было в предоставленной версии','Стало в версии 2.0'],[
        ('Просмотр дедлайнов','Отметить выполнение, вернуть задание и увидеть сохранённый план.'),
        ('Заявка и текущий статус','Номер, срок, история, ответ офиса, уведомление и скачиваемый образец.'),
        ('Список сотрудника','Поиск, серверные фильтры, страницы и защита одновременных решений.'),
        ('API-тесты и UI с подменой ответов','Настоящий браузер/HTTP, отрицательные и конкурентные сценарии, PostgreSQL/TLS.'),
        ('Пример Docker-конфигурации','Проверенный перенос, миграции без сброса, два процесса, backup/restore.'),
    ],[CONTENT/2,CONTENT/2]))
    story.append(Spacer(1,17))
    pair=Table([[shot('before-2026-11-06/desktop-dashboard.png',247,crop=900),shot('desktop-dashboard.png',247,crop=900)]],colWidths=[255.5,255.5])
    pair.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),8)]))
    story+=[pair,p('До / после: фрагменты реального локального браузера. Для «до» сохранены исходные JS/CSS и использован исходный действующий API; успешные API-ответы не подменялись.','small'),p('Интервью не проводились. Пять проблем оформлены как гипотезы из ТЗ; участники, статистика и цитаты студентов не выдумывались. План исследования - docs/research.md.','small'),PageBreak()]

    story+=page('Повседневная учёба - в одном ритме','02 / Сценарии студента')
    side=[p('Мой день','h2'),p('Ближайшее занятие учитывает время МСК. Прошедшая первая пара не выдаётся за предстоящую.'),p('Расписание','h2'),p('День и неделя, преподаватель и место, заметные переносы. Настоящий файл ICS добавляется в календарь; изменённая пара сохраняет длительность.'),p('Успеваемость и план','h2'),p('Баллы, зачёты, сессия и зона внимания связаны с конкретным следующим шагом. Выполнение задания сохраняется на сервере и может быть отменено.'),p('Личный план не меняет оценку и не отправляет работу преподавателю. Порог 65 баллов - условие демонстрации, а не правило вуза.','small')]
    layout=Table([[shot('mobile-dashboard-viewport.png',205),side]],colWidths=[225,286])
    layout.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),15)]))
    story+=[layout,Spacer(1,18),p('На телефоне - постоянная нижняя навигация. Уведомления и профиль доступны в верхней части. Быстрый поиск работает также по Ctrl+K; сторонние шрифты и сервисы для открытия кабинета не нужны.','small'),PageBreak()]

    story+=page('Заявка заканчивается результатом','03 / Документы и учебный офис')
    story.append(p('Студент выбирает услугу, видит срок и отправляет вопрос или запрос справки. Черновик остаётся в его вкладке. Повтор после сбоя связи возвращает ту же заявку.'))
    story.append(table(['Отправлена','На рассмотрении','В работе','Готово'],[('Номер и подтверждение','Офис принял обращение','Подготовка результата','Ответ и скачивание')],[127.75]*4))
    story.append(Spacer(1,18))
    result_side=[p('Что видит студент','h2'),p('Историю событий с датами, текущий этап, ориентир готовности и ответ. Уведомление открывает именно эту заявку.'),p('Что делает сотрудник','h2'),p('Находит обращение по номеру, студенту или группе; сохраняет разрешённый переход и понятное решение. Для готовности/отклонения ответ обязателен.'),p('Готовый документ','h2'),p('Только владелец скачивает HTML-образец; браузер позволяет сохранить его как PDF через печать. В образце есть предупреждение о вымышленных данных и отсутствии юридической силы.')]
    t=Table([[shot('mobile-document-ready.png',205,crop=800),result_side]],colWidths=[225,286])
    t.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),15)]))
    story+=[t,Spacer(1,12),p('Подтверждённый сквозной путь: Алина отправила, Кира обработала, Алина скачала. Марк не видит обращение Алины и получает 404 по прямому чужому ID. Все участники вымышлены.','small'),PageBreak()]

    story+=page('Защита выполняется на сервере','04 / Данные и безопасность')
    story.append(table(['Слой','Как работает'],[
        ('Браузер','Строгая CSP, безопасное экранирование, same-origin запросы. HttpOnly cookie не читается клиентским кодом.'),
        ('FastAPI','Владелец и роль берутся из сессии. Студент не назначает student_id, сотрудник не читает оценки и расписание студента.'),
        ('SQLAlchemy / БД','Пароли Argon2id, хеш токена, общая квота входа. Личные SQL-выборки фильтруются владельцем.'),
        ('Заявка','Изменение статуса, история и уведомление фиксируются вместе. Версия не даёт затереть чужое решение; ключ отправки не даёт создать дубль.'),
        ('Документ и календарь','Выдаются только в допустимой роли и только владельцу. Неготовая справка не скачивается, чужой ID не раскрывается.'),
        ('Production','HTTPS и Secure cookie обязательны, host/origin заданы явно, короткий пароль или неизвестная среда блокируют запуск.'),
    ],[110,401]))
    story+=[p('Два особенно важных исправления','h2'),p('Ответ прежнего аккаунта игнорируется после смены сеанса. Запоздалый 401 не разлогинивает нового пользователя. Это проверено в настоящем Chromium с задержкой реальных ответов.'),p('Ограничение входа хранится в SQL, переживает новый процесс и защищено от одновременных попыток. Размер тела проверяется по фактическому потоку, а не только заголовку.'),p('Границы: демонстрационные пароли публичны по требованию конкурса. Это отдельное ИИ-review, а не независимая аттестация для реальных персональных данных. Полные воспроизведения - docs/security-review.md.','small'),PageBreak()]

    story+=page('ИИ - от постановки до проверки','05 / Фактический процесс')
    story.append(p('Работа началась с чтения полного ТЗ и AGENTS.md. Четыре критерия разбиты на 40 проверяемых признаков. Основной агент отвечает за UX/интеграцию; три дочерних агента получили отдельные области файлов.'))
    story.append(table(['Поручение','Фактический вклад'],[
        ('Backend','Контракты до UI, история/документы, идемпотентность, версии, план, ICS, миграции и тесты.'),
        ('Security / QA','Негативные проверки, review нового клиента без его редактирования, задержанные ответы и потеря сети.'),
        ('QA / Release','Настоящий Docker/PostgreSQL/TLS, два процесса, restart, backup/restore, запуск и CI.'),
        ('Основной ассистент','Продуктовые сценарии, интерфейс, согласование контрактов, browser/axe, исправления и отчёт.'),
    ],[112,399]))
    story+=[p('Ключевые фактические постановки','h2'),p('Backend: «Сразу пришли точный согласованный контракт будущих API главному агенту; фронтенд делаю я.»','small'),p('Security: «Проведи воспроизводимый аудит текущего app/main.py и app/db.py, не изменяй их (Backend агент их обновляет).»','small'),p('Release: «Цель существенная готовность облака, подтвержденные проверки, документация.»','small'),p('Как исправлялись ошибки','h2'),p('Светлый текст и неточные подписи исправлены по axe. Потеря черновика при запрете storage закрыта безопасным fallback. Скрытые старые заявки возвращены серверными фильтрами и страницами. Ошибка очистки временной БД Windows исправлена закрытием соединения и остановкой собственного процесса.'),p('Использованы Codex, Python/PowerShell/Node, pytest/HTTPX, Playwright/Chromium, axe, Docker/PostgreSQL/Caddy, ReportLab/Pillow/Poppler. Генеративные изображения, реальные интервью и внешний ИИ в кабинете не использовались. Подробные инструменты и выдержки - docs/process.md и docs/ai-log.md.','small'),PageBreak()]

    story+=page('Работает - проверено действием','06 / Приёмка и доказательства')
    metrics=Table([[p(str(tests['passed']),'number'),p(str(len(browser['checks'])),'number'),p(str(len(a11y['screens'])),'number')],[p('тестов pytest','small'),p('групп browser-сценариев','small'),p('состояния axe-core','small')]],colWidths=[170.3]*3)
    metrics.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE),('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),9),('LEFTPADDING',(0,0),(-1,-1),16)]))
    story+=[metrics,Spacer(1,16),p(f"Настоящий локальный HTTP и Chromium: {len(browser['layout_checks'])} измерений геометрии и {len(browser['screenshots'])} актуальных снимков на 360/390/768/1440 px. Подмены успешных API-ответов нет; JavaScript/CSP-ошибок не обнаружено."),p('Проверены: вход/выход, второй студент, день/неделя и ICS, план после перезагрузки, заявка/офис/документ, уведомление, фокус, восстановление после отказа запроса и настоящие пустые состояния.'),p('Axe-core 4.14.0: 0 обнаруженных нарушений выбранных правил в 32 состояниях на 1440 и 360 px. Дополнительно проверены Tab/Escape и возврат фокуса. Автоматические правила не заменяют полный WCAG-аудит, скринридер или физический телефон.'),p('Отдельные отрицательные и конкурентные тесты','h2'),p('Чужие URL и student_id, роли, CSRF, XSS документа, session replay/expiry, SQL-квота после restart, одновременная обработка, идемпотентность и старая активная заявка после 210 завершённых.'),p('Где проверить результаты','h2'),p('docs/verification/test-report.json\ndocs/verification/browser-report.json\ndocs/verification/accessibility-report.json\ndocs/verification/deployment-report.json','small'),p('Публичный домен, российское подключение и uptime этими локальными результатами не подтверждаются. Два предупреждения pytest относятся к тестовым зависимостям TestClient/httpx и Starlette/AnyIO, а не к падению проверки.','small'),PageBreak()]

    story+=page('Перенос подготовлен и испытан','07 / Облако и сохранность')
    story.append(p('Стенд переносится на Linux VPS с доменом через Docker Compose. В production используются PostgreSQL, Caddy с HTTPS и два серверных процесса. Внешние порты приложения и базы закрыты; публичен только прокси.'))
    story.append(table(['Слой','Проверенная версия / результат'],[
        ('Сервер','Python 3.13.18, FastAPI; два worker-процесса, non-root/read-only контейнер.'),
        ('База','PostgreSQL 17.11; роль atlas_app без superuser/createdb/createrole.'),
        ('HTTPS','Caddy 2.11.9; локальный сертификат проверен отдельным CA, без отключения TLS verification.'),
        ('Миграции','Два независимых seed-процесса: оба exit 0, ровно три вымышленных пользователя.'),
        ('Перезапуск',f"После restart web и db заявка №{restart['request_id']} осталась {restart['status_after_restart']}."),
        ('Резервная копия',f"pg_dump и pg_restore в новую БД. Совпали записи: заявки - {backup['source_requests']}, события - {backup['source_request_events']}. Исходная база не очищалась."),
    ],[110,401]))
    story.append(p('Зависимости: исходные advisory Starlette исправлены обновлением FastAPI/Starlette. PyPI и OSV проверили полный инвентарь контейнера: 0 известных находок, без пропусков и исключений. Детали и первичные источники - docs/dependency-review.md.','small'))
    story+=[p('Воспроизводимый запуск','h2'),p('Исходники + .env с доменом и двумя разными случайными паролями. Затем docker compose up -d --build --wait. Проверка после размещения - scripts/check-deployment.py. Backup/restore, health/readiness, откат и наблюдение описаны в deployment.md и operations.md.'),p('Образы закреплены digest; receipt содержит хеши проверенного backend. Чистый исходный ZIP исключает .env, atlas.db, дампы, .venv, кеши и node_modules. Удалённый CI подготовлен, но не выдаётся за уже выполненный.'),p('До реальной публикации остаются домен, внешний ACME-сертификат, проверка из России и обязательство работы до 28 ноября 2026. Локальный CA этого не доказывает.','small'),PageBreak()]

    story+=page('Открыть и показать жюри','08 / Передача проекта')
    story+=[p('На Windows откройте Start-ATLAS.cmd. После установки зависимостей браузер откроется на http://127.0.0.1:8000. Ctrl+C останавливает сервер; заявки сохраняются. Альтернативные команды - в README.'),table(['Роль / логин','Пароль'],[
        ('Алина / alina.demo','AtlasDemo!2026-A'),('Марк / mark.demo','AtlasDemo!2026-M'),('Кира / dean.demo','AtlasStaff!2026-D'),
    ],[280,231]),p('Пять минут демонстрации','h2'),p('1. Алина: ближайшая пара, расписание, баллы и выполненное задание.\n2. Справка: подача, номер и сохранение после перезагрузки.\n3. Марк: другой профиль и отсутствие заявки Алины.\n4. Кира: найти номер и последовательно обработать обращение.\n5. Алина: уведомление, история и скачивание конкурсного образца.'),p('Что сделано человеком','h2'),p('Подтверждены постановка цели, предоставление ТЗ и AGENTS.md. Код, проверки, снимки и этот отчёт выполнены ассистентом через инструменты. Неподтверждённые интервью, ручной дизайн, публикация и видео капитану не приписываются.'),p('Материалы для отправки','h2'),p('Рабочий код и чистый ZIP; этот PDF и подробный process.md; AI-log; снимки до/после; рубрика; руководство жюри; проверяемые отчёты и инструкция VPS. Реальные скриншоты чата капитан может приложить отдельно - они не генерировались искусственно.'),p('Итоговый статус','h2'),p('Полноценный локальный конкурсный стенд с проверенным переносом. Оценку выставляет жюри. Реальная вузовская интеграция и обработка настоящих персональных данных не входят в демонстрационное ТЗ.','small')]
    doc=SimpleDocTemplate(str(OUT),pagesize=(W,H),rightMargin=42,leftMargin=42,topMargin=61,bottomMargin=58,
                          title='АТЛАС Campus - процесс создания версии 2.0',author='ATLAS Campus / Codex',
                          subject='Фактический процесс и приёмка локального конкурсного прототипа')
    doc.build(story,onFirstPage=header,onLaterPages=header)
    duplicate=ROOT/'output/pdf/ATLAS_Process_Report.pdf'
    duplicate.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(OUT,duplicate)
    print(OUT)


if __name__=='__main__':
    build()
