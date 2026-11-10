"""Shared isolated HTTP harness for the 2026-11-08 release checks.

Only synthetic data are used. The default server never opens the working atlas.db.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS = ROOT / 'docs' / 'verification' / 'improvements-2026-11-08'


def source_hashes(root=ROOT):
    paths = [*sorted((root/'app').glob('*.py')), *sorted((root/'static').glob('*')),
             *sorted(root.glob('compose*.yaml')),root/'Dockerfile',root/'requirements.txt',root/'requirements-runtime.lock',
             *sorted((root/'scripts').glob('improvement_*.py'))]
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


def report_start(scope):
    return {'started_at_utc':datetime.now(timezone.utc).isoformat(), 'scope':scope,
            'source_sha256':source_hashes(), 'checks':[], 'failures':[]}


def save_report(path, report):
    report['finished_at_utc']=datetime.now(timezone.utc).isoformat()
    now=source_hashes()
    report['source_changed_during_run']=[n for n in sorted(set(now)|set(report['source_sha256']))
                                       if now.get(n)!=report['source_sha256'].get(n)]
    report['status']='FAIL' if report['failures'] or report['source_changed_during_run'] else 'PASS'
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


@contextmanager
def isolated_server(*, root=ROOT, workers=1, python_executable=None, database_path=None):
    with tempfile.TemporaryDirectory(prefix='atlas-improvement-http-') as folder:
        folder=Path(folder)
        with socket.socket() as candidate:
            candidate.bind(('127.0.0.1',0)); port=candidate.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        db=Path(database_path) if database_path else folder/'isolated.sqlite3'
        env={**os.environ,'DATABASE_URL':'sqlite:///'+db.as_posix(),
             'APP_ENV':'test','DEMO_MODE':'true','COOKIE_SECURE':'false',
             'PUBLIC_ORIGIN':base,'ALLOWED_HOSTS':'127.0.0.1,localhost,testserver',
             'PYTHONIOENCODING':'utf-8'}
        with (folder/'server.log').open('w+',encoding='utf-8') as log:
            process=subprocess.Popen([str(python_executable or sys.executable),'-m','uvicorn','app.main:app',
                '--host','127.0.0.1','--port',str(port),'--workers',str(workers),
                '--log-level','warning'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                for _ in range(200):
                    if process.poll() is not None:
                        log.seek(0);raise RuntimeError('Isolated API exited: '+log.read()[-4000:])
                    try:
                        with urlopen(base+'/api/ready',timeout=.5) as response:
                            if response.status==200:break
                    except Exception: time.sleep(.1)
                else:raise RuntimeError('Isolated API readiness timed out')
                yield {'base':base,'db':db,'env':env,'folder':folder,'root':root}
            finally:
                if process.poll() is None:
                    if os.name=='nt':
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
                                       timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    else:process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def browser_ready(page):
    from playwright.sync_api import expect
    page.locator('#page-title').wait_for(timeout=25000)
    expect(page.locator('#page-content')).not_to_have_attribute('aria-busy','true',timeout=25000)
    expect(page.locator('.error-state')).to_have_count(0)


def browser_login(page,base,account=0):
    page.goto(base,wait_until='networkidle')
    page.locator(f'[data-demo="{account}"]').click()
    browser_ready(page)


def browser_visit(page,base,route):
    page.goto(base+'/app/'+route,wait_until='networkidle')
    browser_ready(page)


def geometry(page):
    result=page.evaluate('''() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
        title:document.querySelector('#page-title')?.textContent,
        concept:document.querySelector('.concept-bar')?.textContent})''')
    assert result['scrollWidth']<=result['width'],result
    assert 'вымышлен' in result['concept'],result
    return result
