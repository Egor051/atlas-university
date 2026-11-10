"""Host-side, certificate-verified readiness monitor with bounded recovery.

Run by the VPS systemd timer. Three consecutive failed samples permit recovery
of this Compose project only, at most once per ten minutes. No DB is deleted,
and application data and secrets are never written to the status/log files.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen


def sample(url):
    started = time.monotonic()
    result = {'at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        with urlopen(Request(url.rstrip('/') + '/api/ready', headers={
                'User-Agent': 'ATLAS-Host-Monitor/1.0'}), timeout=10) as response:
            body = json.loads(response.read(8192))
            result.update(status=response.status, ok=response.status == 200 and body.get('ok') is True)
    except Exception as exc:
        result.update(ok=False, error_type=type(exc).__name__)
    result['latency_ms'] = round((time.monotonic() - started) * 1000, 2)
    return result


def recovery_plan(containers):
    """Return only stopped or unhealthy service names; never act on another stack."""
    allowed = {'db', 'web', 'caddy'}
    return [row['Service'] for row in containers if row.get('Service') in allowed
            and (row.get('State') != 'running' or row.get('Health') == 'unhealthy')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--state', type=Path, default=Path('/var/lib/atlas-ops/status.json'))
    parser.add_argument('--log', type=Path, default=Path('/var/log/atlas-ops/monitor.jsonl'))
    args = parser.parse_args()
    if not args.url.startswith('https://'):
        parser.error('A certificate-verified HTTPS URL is required')
    previous = json.loads(args.state.read_text()) if args.state.exists() else {}
    result = sample(args.url)
    result['consecutive_failures'] = 0 if result['ok'] else previous.get('consecutive_failures', 0) + 1
    result['last_recovery_unix'] = previous.get('last_recovery_unix', 0)
    if result['consecutive_failures'] >= 3 and time.time() - result['last_recovery_unix'] >= 600:
        status = subprocess.run(['docker', 'compose', 'ps', '--all', '--format', 'json'],
                                capture_output=True, text=True, timeout=20)
        if status.returncode == 0:
            raw = status.stdout.strip()
            containers = json.loads(raw) if raw.startswith('[') else [json.loads(line) for line in raw.splitlines() if line]
            plan = recovery_plan(containers)
            # A missing service is recreated without building/pulling images.
            missing = {'db', 'web', 'caddy'} - {row.get('Service') for row in containers}
            outcomes = {}
            for service in sorted(missing | set(plan), key=lambda item: ('db', 'web', 'caddy').index(item)):
                action = ['up', '-d', '--no-build', '--no-deps'] if service in missing else ['restart', '--no-deps']
                recovered = subprocess.run(['docker', 'compose', *action, service],
                                           capture_output=True, timeout=40)
                outcomes[service] = recovered.returncode == 0
            if outcomes:
                result.update(recovery=outcomes, last_recovery_unix=time.time())
    args.state.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, ensure_ascii=False) + '\n'
    temporary = args.state.with_suffix('.tmp')
    temporary.write_text(encoded, encoding='utf-8')
    os.replace(temporary, args.state)
    with args.log.open('a', encoding='utf-8') as handle:
        handle.write(encoded)
    print(encoded, end='')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
