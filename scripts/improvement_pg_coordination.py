"""Temporary PostgreSQL/runtime for an internal reviewer. No secrets in output.

Start builds current runtime and starts only a uniquely named DB/web pair, with
no host ports. The reviewer runs Python inside the returned web container and
reads DATABASE_URL from its environment, never through chat or a file.
Stop accepts only the receipt of this helper and preserves the new test volumes.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from pathlib import Path
import json
import os
import re
import secrets
import subprocess

from improvement_runtime import ROOT,DEFAULT_REPORTS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['start','stop'])
    parser.add_argument('--receipt',type=Path,default=DEFAULT_REPORTS/'postgres-review-runtime.json')
    args=parser.parse_args()
    if args.action=='start':
        assert not args.receipt.exists(),'Do not replace an active runtime receipt; stop it first or use another receipt path.'
        project='atlas-pg-review-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')+'-'+secrets.token_hex(2)
    else:
        receipt=json.loads(args.receipt.read_text(encoding='utf-8'));project=receipt['project']
        assert re.fullmatch(r'atlas-pg-review-[0-9]{14}-[a-f0-9]{4}',project),'Unrecognized review project'
    passwords=[secrets.token_hex(24),secrets.token_hex(24)]
    env={**os.environ,'DOMAIN':'localhost','POSTGRES_PASSWORD':passwords[0],'ATLAS_APP_PASSWORD':passwords[1],'DEMO_MODE':'true'}
    command=['docker','compose','-p',project,'-f','compose.yaml','-f','compose.improvements.yaml']
    def run(*arguments,timeout=180):
        process=subprocess.run([*command,*arguments],cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
        if process.returncode:
            detail=process.stderr[-3000:]
            for value in passwords:detail=detail.replace(value,'<redacted>')
            raise RuntimeError(detail)
        return process.stdout.strip()
    if args.action=='start':
        print('Preparing isolated PostgreSQL reviewer runtime '+project,flush=True)
        receipt={'project':project,'scope':'Temporary DB/web pair with no public or host port; credentials only in container environment','created_at_utc':datetime.now(timezone.utc).isoformat(),'status':'STARTING'}
        args.receipt.parent.mkdir(parents=True,exist_ok=True)
        args.receipt.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        try:
            run('up','-d','--build','--wait','--wait-timeout','240','db','web',timeout=720)
            run('exec','-T','db','createdb','-U','atlas_admin','-O','atlas_app','atlas_draft_race')
            receipt.update(status='READY',web_container=run('ps','-q','web'),db_container=run('ps','-q','db'),database='atlas_draft_race')
        except Exception:
            receipt['status']='FAILED'
            raise
        finally:args.receipt.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(receipt))
    else:
        # Down only the uniquely named project; no password values are needed for removal.
        run('down',timeout=90)
        receipt['status']='STOPPED';receipt['stopped_at_utc']=datetime.now(timezone.utc).isoformat()
        receipt['new_test_volumes_preserved']=True
        args.receipt.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'project':project,'status':'STOPPED','new_test_volumes_preserved':True}))
    return 0

if __name__=='__main__':raise SystemExit(main())
