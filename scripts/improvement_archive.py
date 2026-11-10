"""Extract the final source ZIP, install runtime dependencies into a NEW venv,
and run the fictional API from that extraction against a new persistent test DB.
The workspace venv, source and working database are not used as the application.
"""
from __future__ import annotations
import argparse
from pathlib import Path,PurePosixPath
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import traceback
import venv
import zipfile

import httpx
from improvement_runtime import ROOT,DEFAULT_REPORTS,isolated_server,report_start,save_report


DEPLOYMENT_FILES = (
    'Dockerfile', 'compose.yaml', 'compose.test.yaml', 'compose.improvements.yaml',
    'deploy/init-db.sh', 'deploy/Caddyfile', 'deploy/Caddyfile.test',
    'scripts/improvement_deployment.py', 'scripts/improvement_runtime.py',
)


def validate_deployment_bundle(checkout):
    """Check the delivered checkout, rather than the packaging workspace."""
    missing = [name for name in DEPLOYMENT_FILES if not (Path(checkout)/name).is_file()]
    if missing:
        raise ValueError('Source archive is missing deployment files: ' + ', '.join(missing))
    return list(DEPLOYMENT_FILES)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--report',type=Path,default=DEFAULT_REPORTS/'clean-archive.json')
    args=parser.parse_args();archive=args.archive.resolve()
    report=report_start('Final source archive extracted to an isolated folder, NEW Python venv and runtime installation, own SQLite; actual HTTP workflow and restart. Not an external deployment.')
    report['archive']=str(archive);report['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
    try:
        with tempfile.TemporaryDirectory(prefix='atlas-improvement-archive-') as folder:
            folder=Path(folder);checkout=folder/'source';checkout.mkdir()
            with zipfile.ZipFile(archive) as z:
                assert z.testzip() is None
                for info in z.infolist():
                    relative=PurePosixPath(info.filename.replace('\\','/'))
                    assert not relative.is_absolute() and '..' not in relative.parts
                    target=(checkout/Path(*relative.parts)).resolve()
                    assert target.is_relative_to(checkout.resolve())
                    assert not stat.S_ISLNK(info.external_attr>>16),'Symlinks forbidden in source archive'
                    filename=Path(info.filename).name
                    assert not filename.startswith('.env') or filename=='.env.example'
                    assert not any(p in ['.venv','node_modules'] for p in relative.parts)
                    assert Path(info.filename).suffix.lower() not in ['.db','.db-wal','.db-shm','.sqlite','.sqlite3','.sqlite-wal','.sqlite-shm','.sqlite3-wal','.sqlite3-shm']
                z.extractall(checkout)
            candidates=[checkout,*[p.parent for p in checkout.rglob('requirements.txt')]]
            candidates=[p for p in candidates if (p/'app/main.py').is_file() and (p/'static/index.html').is_file()]
            assert len(set(candidates))==1,candidates
            checkout=candidates[0]
            report['deployment_bundle_files'] = validate_deployment_bundle(checkout)
            venv_dir=folder/'fresh-runtime'
            print('Creating fresh archive runtime and installing requirements',flush=True)
            venv.EnvBuilder(with_pip=True).create(venv_dir)
            python=venv_dir/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            bootstrap=subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','--upgrade','pip==26.2.2'],cwd=checkout,capture_output=True,text=True,timeout=120)
            assert bootstrap.returncode==0,bootstrap.stderr[-3000:]
            report['bootstrap_pip']='26.2.2'
            install=subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(checkout/'requirements.txt'),'-c',str(checkout/'requirements-runtime.lock')],cwd=checkout,capture_output=True,text=True,timeout=360)
            assert install.returncode==0,install.stderr[-3000:]
            check=subprocess.run([str(python),'-m','pip','check'],capture_output=True,text=True,timeout=30)
            assert check.returncode==0,check.stdout+check.stderr
            report['pip_check']=check.stdout.strip()
            report['runtime_constraints_applied']=True
            inventory=subprocess.run([str(python),'-c',"import importlib.metadata,json;print(json.dumps({d.metadata['Name']:d.version for d in importlib.metadata.distributions()}))"],capture_output=True,text=True,check=True,timeout=30)
            report['fresh_runtime_inventory']=json.loads(inventory.stdout)
            database=folder/'persistent-check.sqlite3'
            def login(client,account):
                credentials=[('alina.demo','AtlasDemo!2026-A'),('mark.demo','AtlasDemo!2026-M'),('dean.demo','AtlasStaff!2026-D')][account]
                r=client.post('/api/login',json=dict(zip(['login','password'],credentials)),headers={'X-Requested-With':'ATLAS'})
                assert r.status_code==200,r.text
            with isolated_server(root=checkout,python_executable=python,database_path=database) as server:
                with httpx.Client(base_url=server['base'],timeout=20) as a,httpx.Client(base_url=server['base'],timeout=20) as b,httpx.Client(base_url=server['base'],timeout=20) as staff:
                    login(a,0);login(b,1);login(staff,2)
                    for path in ['/api/dashboard','/api/schedule','/api/grades','/api/learning/courses','/api/services/library','/api/campus/portfolio']:
                        assert a.get(path).status_code==200,path
                    created=a.post('/api/requests',json={'type':'study','comment':'Изолированная заявка из переданного архива.'},headers={'X-Requested-With':'ATLAS'})
                    assert created.status_code==201,created.text
                    request_id=created.json()['id']
                    assert b.get(f'/api/requests/{request_id}').status_code==404
                    for status in ['review','processing','ready']:
                        current=staff.get(f'/api/staff/requests/{request_id}').json()
                        r=staff.post(f'/api/staff/requests/{request_id}/status',json={'status':status,'expected_version':current['version'],'message':'Вымышленный ответ для приёмки архива.'},headers={'X-Requested-With':'ATLAS'})
                        assert r.status_code==200,r.text
                    assert a.get(f'/api/requests/{request_id}/document').status_code==200
                    report['health']=a.get('/api/health').json()
            with isolated_server(root=checkout,python_executable=python,database_path=database) as server:
                with httpx.Client(base_url=server['base'],timeout=20) as a:
                    login(a,0)
                    r=a.get(f'/api/requests/{request_id}')
                    assert r.status_code==200 and r.json()['status']=='ready'
            report['checks']=['ZIP integrity','safe extraction','no runtime DB/secrets/dependency folders','complete PostgreSQL/TLS deployment bundle','new venv','fresh dependency installation','pip check',
                              'actual API from extracted source','two students and staff','IDOR','complete request workflow','document','restart persistence']
    except Exception:report['failures'].append(traceback.format_exc())
    finally:save_report(args.report,report)
    print(json.dumps({'status':report['status'],'archive_sha256':report['archive_sha256'],'checks':len(report['checks']),'failures':report['failures']},ensure_ascii=False))
    return 1 if report['status']=='FAIL' else 0

if __name__=='__main__':raise SystemExit(main())
