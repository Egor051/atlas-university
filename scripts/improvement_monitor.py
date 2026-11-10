"""Read-only HTTPS readiness samples with certificate verification.

For an owned deployed demo: python scripts/improvement_monitor.py
  --url https://YOUR-DOMAIN --checks 60 --interval 60 --report monitor.json
Samples establish only the observed interval; future uptime is not guaranteed.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from pathlib import Path
import json
import ssl
import time
from urllib.parse import urlsplit
from urllib.request import Request,urlopen


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',required=True)
    parser.add_argument('--ca',type=Path)
    parser.add_argument('--checks',type=int,default=1)
    parser.add_argument('--interval',type=float,default=60)
    parser.add_argument('--report',type=Path,default=Path('monitor-readiness.json'))
    args=parser.parse_args();parts=urlsplit(args.url)
    assert parts.scheme=='https' and parts.hostname and not parts.username and not parts.password and not parts.query and not parts.fragment,'Use an HTTPS origin without embedded credentials/query'
    assert parts.path in ['', '/'] and 1<=args.checks<=100000 and 1<=args.interval<=3600
    context=ssl.create_default_context(cafile=str(args.ca) if args.ca else None)
    report={'url':args.url.rstrip('/'),'scope':'Certificate-verified read-only readiness samples; not a proof of uninterrupted or future availability.',
            'certificate_verification':True,'samples':[]}
    for index in range(args.checks):
        sample={'at_utc':datetime.now(timezone.utc).isoformat()};start=time.perf_counter()
        try:
            req=Request(report['url']+'/api/ready',headers={'User-Agent':'ATLAS-Readiness-Monitor/1.0'})
            with urlopen(req,context=context,timeout=10) as response:
                body=json.loads(response.read(8192))
                sample.update(status=response.status,ok=response.status==200 and body.get('ok') is True)
        except Exception as exc:sample.update(ok=False,error_type=type(exc).__name__)
        sample['latency_ms']=round((time.perf_counter()-start)*1000,2)
        report['samples'].append(sample)
        report['successful_samples']=sum(s['ok'] for s in report['samples'])
        report['sample_success_percent']=round(100*report['successful_samples']/len(report['samples']),2)
        report['status']='PASS' if report['successful_samples']==len(report['samples']) else 'FAIL'
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(sample),flush=True)
        if index+1<args.checks:time.sleep(args.interval)
    return 0 if report['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
