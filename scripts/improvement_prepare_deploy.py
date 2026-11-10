"""Prepare a private Docker env file for an owned hostname; never overwrite it.

Example: python scripts/improvement_prepare_deploy.py --domain campus.example.ru
Generates separate random DB/application passwords, chmod 0600 where supported,
and validates Compose without printing secret values. It does not publish, buy a
domain, configure DNS or establish public availability.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import ipaddress
import os
import re
import secrets
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain',required=True,help='An owned DNS hostname, without scheme, port or path.')
    parser.add_argument('--output',type=Path,default=ROOT/'.env')
    parser.add_argument('--skip-compose-validation',action='store_true')
    args=parser.parse_args()
    domain=args.domain.strip().encode('idna').decode('ascii').lower()
    assert 3<=len(domain)<=253 and '.' in domain and not domain.endswith('.')
    assert all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',label) for label in domain.split('.')),'Invalid DNS hostname'
    try:ipaddress.ip_address(domain)
    except ValueError:pass
    else:raise ValueError('Use the owned DNS hostname, not an IP literal')
    output=args.output.resolve()
    assert output.parent.exists(),'Create the intended parent directory first'
    assert output.name.startswith('.env') and output.name!='.env.example','Use a private .env or .env.* filename'
    content=f'DOMAIN={domain}\nPOSTGRES_PASSWORD={secrets.token_hex(32)}\nATLAS_APP_PASSWORD={secrets.token_hex(32)}\nDEMO_MODE=true\nWEB_WORKERS=2\n'
    descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as handle:handle.write(content)
    if not args.skip_compose_validation:
        result=subprocess.run(['docker','compose','--env-file',str(output),'-f',str(ROOT/'compose.yaml'),'config','--quiet'],cwd=ROOT,capture_output=True,text=True)
        if result.returncode:
            # Do not echo validation output: an external tool might expand the private env.
            print('Private environment created; Compose validation failed. Inspect locally without sharing secret values.')
            return 1
    print('Private environment created. Compose validation '+('skipped.' if args.skip_compose_validation else 'passed.'))
    print('No public deployment, DNS change or domain purchase was performed.')
    return 0

if __name__=='__main__':raise SystemExit(main())
