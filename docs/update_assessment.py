"""Publish a conservative, ID-by-ID update of the fixed contest rubric."""
from pathlib import Path
from decimal import Decimal as D, ROUND_HALF_UP
import json,shutil,xml.etree.ElementTree as ET,hashlib,os
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/verification/improvements-2026-11-08'
baseline=ROOT/'outputs/contest-assessment-2026-11-08/score-model.json'
if baseline.exists():shutil.copyfile(baseline,OUT/'score-model-baseline.json')
model=json.loads((OUT/'score-model-baseline.json').read_text(encoding='utf-8'))
done=set('I03.3 I03.4 I03.5 I04.3 I05.5 I06.5 I07.5 I08.5 I09.4 I09.5 A01.5 A02.4 A02.5 A03.5 A04.5 A05.4 A06.3 A07.4 A08.4 A08.5 A09.5 A10.5 E03.5 E04.4 E04.5 E06.5 E07.5 E08.2 E08.3 E08.4 E09.5 Q03.5 Q05.4 Q05.5 Q06.4 Q06.5 Q08.3 Q08.4 Q08.5 Q09.4 Q10.3 Q10.4'.split())
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
for name in ['postgres-https.json','sql-growth.json','load.json','performance.json','adaptation.json','archive-preflight.json']:
    assert read(name)['status']=='PASS',(name,'not verified')
assert json.loads((OUT/'demo/demo.json').read_text(encoding='utf-8'))['status']=='PASS'
ui=json.loads((ROOT/'docs/verification/improvements-ui-2026-11-09.json').read_text(encoding='utf-8'))
assert len(ui['geometry'])==128 and not ui['errors'] and not any(x['violations'] for x in ui['accessibility'])
suites=list(ET.parse(OUT/'pytest-results.xml').getroot().iter('testsuite'))
assert sum(int(x.get('failures',0))+int(x.get('errors',0))+int(x.get('skipped',0)) for x in suites)==0
tests=sum(int(x.get('tests',0)) for x in suites)
evidence={
 'I03':'static/app.js; static/campus.js; tests/test_improvements_drafts_ui.py; tests/test_improvements_campus_ui.py',
 'I04':'docs/alternatives-research-2026-11-09.md',
 'I05':'static/campus.js; tests/test_improvements_campus_ui.py',
 'I06':'static/campus.js; tests/test_improvements_campus_ui.py',
 'I07':'app/improvements.py; app/main.py; tests/test_improvements_core.py',
 'I08':'docs/research.md; docs/demo-video-script.md',
 'I09':'docs/adaptation.md; docs/examples/fictional-faculty.json; verification/improvements-2026-11-08/adaptation.json',
 'A01':'docs/ai-evidence-3.2.md', 'A02':'docs/ai-evidence-3.2.md', 'A03':'docs/ai-evidence-3.2.md; tests/',
 'A04':'docs/ai-evidence-3.2.md', 'A05':'docs/ai-evidence-3.2.md; screenshots/',
 'A06':'AGENTS.md', 'A07':'docs/process.md; docs/ai-evidence-3.2.md', 'A08':'docs/process.md; docs/ATLAS_Campus_3_2_Process.pdf',
 'A09':'verification/improvements-2026-11-08/artifact-manifest.json', 'A10':'verification/improvements-2026-11-08/demo/demo.json',
 'E03':'app/improvements.py; tests/test_improvements_security.py', 'E04':'tests/test_improvements_services.py; verification/improvements-2026-11-08/postgres-https.json',
 'E06':'app/services_db.py; tests/test_improvements_services.py', 'E07':'app/version.py; tests/test_improvements_core.py',
 'E08':'verification/improvements-2026-11-08/sql-growth.json; load.json; tests/test_improvements_services.py',
 'E09':'verification/improvements-2026-11-08/archive-preflight.json; dist/atlas-3.2-acceptance.json (final ZIP)',
 'Q03':'screenshots/improvements-2026-11-09/360-home.png', 'Q05':'static/improvements.js; tests/test_frontend_contracts.py',
 'Q06':'tests/test_improvements_drafts_ui.py; tests/test_improvements_security.py', 'Q08':'verification/improvements-2026-11-08/performance.json',
 'Q09':'static/app.js; docs/verification/improvements-2026-11-08/demo/04-grades.png',
 'Q10':'static/improvements.js; static/app.js; tests/test_improvements_drafts_ui.py',
}
reasons={
 'I01':'Подготовлены протокол, согласие и пустые формы. Нужны реальные добровольные участники и наблюдения.',
 'I04':'Сценарий реализован и автоматически проверен. Востребованность и повторная полезность требуют настоящих студентов.',
 'I05':'Разные ситуации подготовлены как гипотезы, а не подтвержденные потребности подгрупп.',
 'I06':'Приоритеты по ТЗ описаны; востребованность дополнительных разделов ещё не исследована.',
 'I07':'Три услуги получили специальные поля и проверку. Выбор приоритета по данным студентов пока не подтвержден.',
 'I10':'Технические решения записаны; решения по результатам настоящего исследования ещё невозможны.',
 'A05':'Реальные варианты и автоматические измерения есть, пользовательские наблюдения ещё не получены.',
 'A07':'Шаблон ручного вклада подготовлен; требуется фактическое подтверждение капитаном.',
 'E05':'Firefox/WebKit и эмуляции проверены; физических Android/iPhone нет в доступных ресурсах.',
 'E06':'Compose, конфигурация, мониторинг и runbook готовы. Нет предоставленного постоянного Python-хостинга/домена, оплаты и российского подключения.',
 'E09':'Чистый архив готов. Общедоступная ссылка для жюри пока не подтверждена.',
 'Q01':'Автоматические переходы проходят; результаты находимости новыми людьми не измерялись.',
 'Q02':'E2E и симуляции не доказывают успешность и улучшение показателей настоящих участников.',
 'Q04':'Клавиатура, axe, 320px и CSS-стресс 200% выполнены. Настоящий скринридер и проверка физического zoom не подтверждены.',
 'Q07':'Автоматическая эмуляция подготовлена; нужна настоящая телефонная клавиатура, поворот и сенсорное управление.',
 'Q09':'Тексты и связи улучшены; понимание людьми проверяется в подготовленном протоколе.',
 'Q10':'Файлы реально скачиваются; импорт ICS в распространённый календарь и ручная проверка печати остаются неподтвержденными.',
}
def num(value):return str(D(str(value)).quantize(D('.01'),rounding=ROUND_HALF_UP)).replace('.',',')
scores={k:D(v) for k,v in model['scores'].items()};updates=[]
for item in model['improvements']:
    code=item['id'];complete=code in done
    if complete:scores[code[0]]+=D(item['points'])
    updates.append({**item,'completed':complete,'status':'Выполнено и проверено' if complete else 'Подготовлено / частично, балл не начислен',
                    'new_evidence':evidence.get(code.split('.')[0]) if complete else reasons.get(code.split('.')[0],'Требуется внешнее подтверждение.')})
assert len(updates)==70 and len(done)==42 and all(next(x for x in updates if x['id']==i)['completed'] for i in done)
total=sum(scores.values());assert total==D('33.95')
result={'rubric_version':'1.0','project_version':'3.2.0','date':'2026-11-09','previous_total_40':model['total_40'],
        'scores':{k:str(v) for k,v in scores.items()},'total_40':str(total),'gain_40':str(total-D(model['total_40'])),
        'normalized_10':str(total/4),'completed_improvements':42,'prepared_without_credit':28,'updates':updates,
        'note':'Final E09.5 delivery is valid with the separate PASS receipt dist/atlas-3.2-acceptance.json for the delivered ZIP; preflight source archive has already passed.'}
(OUT/'score-update.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
parts=['# Реализация 70 улучшений ATLAS Campus 3.2','',
       '9 ноября 2026. Фиксированная шкала 1.0 сохранена; веса и условия не подгонялись под результат.',
       '',f'Подтверждённая оценка после выполнения и приёмки: **{num(total)}/40**, среднее **{num(total/4)}/10**. Рост с 26,10 на **+7,85**. Полностью закрыты **42 из 70** улучшений. Для **28** подготовлены техническая часть, протоколы или инструкции; недостающие реальные свидетельства не засчитаны.',
       '', 'Для окончательного передаваемого ZIP приёмка E09.5 подтверждается отдельным `dist/atlas-3.2-acceptance.json` с SHA архива. Встроить акт с хешем ZIP в этот же ZIP невозможно; внешний акт входит в комплект передачи.',
       '', '| Критерий | Было | Стало | Прирост |','|---|---:|---:|---:|']
for code,name in model['categories'].items():parts.append(f'| {name} | {num(model["scores"][code])} | {num(scores[code])} | +{num(scores[code]-D(model["scores"][code]))} |')
parts.extend(['','Оценка авторская. Физические устройства, интервью, ручной скринридер, публичная инфраструктура и РФ не заменяются автоматизацией. Идеальный эталон остаётся 40/40.','',
              '## Полный результат по ID','', '| ID | Результат | Балл к /40 | Свидетельство или оставшийся шаг |','|---|---|---:|---|'])
def evidence_links(text):
    result=[]
    for part in text.split('; '):
        path=part.strip()
        target=next((p for p in (ROOT/path,ROOT/'docs'/path,OUT/path) if p.exists()),None)
        if target:
            relative=os.path.relpath(target,ROOT/'docs').replace('\\','/')
            result.append('['+path+']('+relative+')')
        else:result.append(path)
    return '; '.join(result)
for item in updates:
    proof=evidence_links(item['new_evidence']) if item['completed'] else item['new_evidence']
    parts.append(f'| {item["id"]} | {item["status"]}: {item["improvement"]} | '+('+'+num(item['points']) if item['completed'] else '0,00')+f' | {proof} |')
parts.extend(['','## Что остаётся за владельцем','',
 '1. Провести подготовленное добровольное исследование с 5–8 студентами, получить реальные наблюдения и повторно проверить исправления. Шаблоны и согласие — `research-kit/`.',
 '2. Подтвердить фактический ручной вклад капитана; не приписывать себе действия, которые выполнял ИИ.',
 '3. Пройти основные задачи на физических Android/iPhone, проверить клавиатуру, системный масштаб, касания и скринридер; заполнить подготовленный журнал приёмки.',
 '4. Предоставить постоянный Python/PostgreSQL-хостинг и домен либо выполнить готовые Compose-команды на своём сервере. Затем — реальный тест из РФ без VPN, проверка трёх аккаунтов, оплата до 28 ноября и внешний мониторинг.',
 '5. Проверить импорт ICS в календарь и образец печати. Дать жюри доступ к исходникам, PDF и ролику, затем отправить последнюю версию через кабинет конкурса.',
 '', '## Границы доказательств','',
 'Отчёты автоматизации относятся к локальным временным данным и явно объявленным условиям. 192 проверки Firefox/WebKit не являются тестом Safari на iPhone. CSS-стресс 200% не выдаётся за физическое увеличение текста. Лабораторный EventTiming не называется полевым INP. Нагрузочная пропускная способность не пересчитывается в число настоящих студентов. Будущая доступность до 28 ноября не объявляется уже проверенной.'])
(ROOT/'docs/improvements-3.2-status.md').write_text('\n'.join(parts)+'\n',encoding='utf-8')
print(json.dumps({'total':str(total),'scores':result['scores'],'done':42,'remaining':28,'tests':tests},ensure_ascii=False))
