"""Record an actual automated local browser journey on a temporary fictional DB."""
from pathlib import Path
import sys,time,json,shutil,subprocess
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from improvement_runtime import isolated_server,browser_login,browser_ready
from playwright.sync_api import sync_playwright,expect

OUT=ROOT/'docs/verification/improvements-2026-11-08/demo'
OUT.mkdir(parents=True,exist_ok=True)
captions=[]
def ts(seconds):
    milliseconds=int(seconds*1000);return f'{milliseconds//3600000:02}:{milliseconds//60000%60:02}:{milliseconds//1000%60:02},{milliseconds%1000:03}'

with isolated_server() as server,sync_playwright() as automation:
    browser=automation.chromium.launch()
    context=browser.new_context(viewport={'width':1280,'height':900},locale='ru-RU',record_video_dir=OUT/'raw',record_video_size={'width':1280,'height':900})
    page=context.new_page();video=page.video;start=time.monotonic()
    def capture(label,name):
        captions.append((time.monotonic()-start,label));page.screenshot(path=str(OUT/(name+'.png')),full_page=True);page.wait_for_timeout(1100)
    page.goto(server['base'],wait_until='networkidle');capture('Локальная автоматизированная демонстрация. Конкурсный концепт, данные вымышлены.','01-login')
    page.locator('[data-demo="0"]').click();browser_ready(page);capture('Алина: ближайшая пара, учебный риск и заявки в одном кабинете.','02-home')
    page.get_by_role('button',name='Открыть расписание',exact=True).click();browser_ready(page);capture('Переход открывает дату ближайшей пары и выделяет занятие.','03-schedule')
    page.goto(server['base']+'/app/grades',wait_until='networkidle');browser_ready(page);capture('Оценки: понятные показатели и следующий шаг по дисциплине.','04-grades')
    page.goto(server['base']+'/app/requests',wait_until='networkidle');browser_ready(page)
    page.locator('[data-request-view="services"]').click();page.locator('.service-card[data-type="study"]').click()
    page.locator('#doc-comment').fill('Вымышленная справка для демонстрации полного пути.');capture('Заявка: подходящие поля, срок, черновик и безопасная отправка.','05-form')
    with page.expect_response(lambda r:r.url.endswith('/api/requests') and r.request.method=='POST') as created:
        page.locator('#request-form button[type=submit]').click()
    rid=created.value.json()['id'];expect(page.locator('.request-track')).to_be_visible();capture('Заявка сохранена на сервере: номер и история доступны после обновления.','06-submitted')
    page.goto(server['base']+'/app/profile',wait_until='networkidle');page.locator('.danger-button[data-action="logout"]').click();expect(page.locator('#login-form')).to_be_visible()
    page.locator('[data-demo="1"]').click();browser_ready(page);page.set_viewport_size({'width':390,'height':844});capture('Марк: другие данные. Здесь показана эмуляция ширины 390 px, не физический телефон.','07-other-student')
    denied=page.request.get(server['base']+f'/api/requests/{rid}');assert denied.status==404
    page.set_viewport_size({'width':1280,'height':900});page.goto(server['base']+'/app/profile',wait_until='networkidle');page.locator('.danger-button[data-action="logout"]').click();expect(page.locator('#login-form')).to_be_visible()
    page.locator('[data-demo="2"]').click();expect(page.locator('#page-title')).to_contain_text('Учебный офис')
    page.locator(f'.request-row[data-id="{rid}"]').click();expect(page.locator('#staff-form')).to_be_visible()
    for status in ['review','processing','ready']:
        page.locator('#staff-status').select_option(status);page.locator('#staff-message').fill('Демонстрационный результат подготовлен. Все данные вымышлены.')
        with page.expect_response(lambda r:f'/requests/{rid}/status' in r.url and r.request.method=='POST'):
            page.locator('#staff-form button[type=submit]').click()
        if status!='ready':expect(page.locator('#staff-form')).to_be_visible()
        else:expect(page.locator('.request-status.ready')).to_be_visible()
    capture('Сотрудник обрабатывает заявку. Только сотрудник меняет её статус.','08-staff-ready')
    page.goto(server['base']+'/app/profile',wait_until='networkidle');page.locator('.danger-button[data-action="logout"]').click();expect(page.locator('#login-form')).to_be_visible()
    page.locator('[data-demo="0"]').click();browser_ready(page);page.goto(server['base']+'/app/requests',wait_until='networkidle');browser_ready(page)
    page.locator(f'.request-row[data-id="{rid}"]').click();expect(page.locator('.document-result')).to_be_visible();capture('Алина получает ответ и скачивает конкурсный образец документа.','09-result')
    with page.expect_download() as download:page.locator('.document-result a').click()
    download.value.save_as(OUT/'fictional-result.html')
    ics=page.request.get(server['base']+'/api/schedule/export');assert ics.status==200
    (OUT/'fictional-schedule.ics').write_bytes(ics.body())
    duration=time.monotonic()-start;context.close();video.save_as(OUT/'atlas-demo-local.webm');browser.close()
lines=[]
for index,(at,text) in enumerate(captions):
    end=captions[index+1][0] if index+1<len(captions) else duration
    lines.extend([str(index+1),ts(at)+' --> '+ts(end),text,''])
(OUT/'atlas-demo-local.srt').write_text('\n'.join(lines),encoding='utf-8')
mp4=None
if shutil.which('ffmpeg'):
    completed=subprocess.run(['ffmpeg','-y','-loglevel','error','-i','atlas-demo-local.webm','-vf',"subtitles=atlas-demo-local.srt:force_style='FontName=Segoe UI,Fontsize=18,MarginV=18'",'-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','atlas-demo-local.mp4'],cwd=OUT,capture_output=True,timeout=90)
    if completed.returncode:raise RuntimeError(completed.stderr.decode('utf-8','replace'))
    mp4='atlas-demo-local.mp4'
result={'scope':'Actual automated local HTTP journey on an isolated fictional DB. Mobile width emulation, no real participant or public hosting claim.','duration_seconds':round(duration,2),'request_id':rid,'other_student_status':denied.status,'steps':captions,'video':mp4 or 'atlas-demo-local.webm','status':'PASS'}
(OUT/'demo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':'PASS','duration_seconds':result['duration_seconds'],'video':result['video']},ensure_ascii=False))
