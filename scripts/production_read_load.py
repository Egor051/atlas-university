"""Small read-only public HTTPS load sample; never a capacity/stress claim."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--requests', type=int, default=160)
    parser.add_argument('--clients', type=int, default=4)
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.path not in {'', '/'} or parts.query or parts.fragment:
        parser.error('Use an HTTPS origin')
    if not 1 <= args.requests <= 200 or not 1 <= args.clients <= 4:
        parser.error('Public safety bounds: at most 200 reads and 4 clients')
    base = args.url.rstrip('/')
    context = ssl.create_default_context()
    request = Request(base + '/api/login', data=json.dumps({
        'login': 'alina.demo', 'password': 'AtlasDemo!2026-A'}).encode(), headers={
        'Origin': base, 'X-Requested-With': 'ATLAS', 'Content-Type': 'application/json'})
    with urlopen(request, context=context, timeout=15) as response:
        cookie = response.headers['Set-Cookie'].split(';', 1)[0]
    routes = ['/api/dashboard', '/api/schedule', '/api/grades',
              '/api/requests?paginated=true&limit=5', '/api/notifications?paginated=true&limit=5',
              '/api/learning/courses', '/api/learning/assignments',
              '/api/services/library?limit=5', '/api/services/events', '/api/campus/portfolio']
    def read(index):
        started = time.perf_counter()
        route = routes[index % len(routes)]
        try:
            req = Request(base + route, headers={'Cookie': cookie, 'User-Agent': 'ATLAS-Bounded-Read-Check/1.0'})
            with urlopen(req, context=context, timeout=10) as response:
                response.read()
                status = response.status
        except HTTPError as exc:
            status = exc.code
        except Exception:
            status = 0
        elapsed = (time.perf_counter() - started) * 1000
        time.sleep(0.15)
        return {'route': route, 'status': status, 'latency_ms': round(elapsed, 2)}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.clients) as workers:
        samples = list(workers.map(read, range(args.requests)))
    duration = time.perf_counter() - started
    latencies = sorted(row['latency_ms'] for row in samples)
    quantile = lambda p: latencies[min(len(latencies)-1, max(0, int((len(latencies)-1)*p)))]
    report = {'at_utc': datetime.now(timezone.utc).isoformat(), 'url': base,
        'scope': 'Bounded real public HTTPS reads; 150 ms pause/client; no domain writes. Not destructive load or a capacity guarantee.',
        'clients': args.clients, 'requests': len(samples), 'duration_seconds': round(duration, 2),
        'requests_per_second': round(len(samples)/duration, 2),
        'p50_ms': quantile(.50), 'p95_ms': quantile(.95), 'p99_ms': quantile(.99),
        'status_counts': {str(status): sum(row['status'] == status for row in samples) for status in sorted({r['status'] for r in samples})},
        'unexpected_responses': [row for row in samples if row['status'] != 200],
        'status': 'PASS' if all(row['status'] == 200 for row in samples) and quantile(.95) <= 1000 else 'FAIL'}
    try:
        logout = Request(base + '/api/logout', data=b'{}', headers={'Cookie': cookie, 'Origin': base,
            'X-Requested-With': 'ATLAS', 'Content-Type': 'application/json'})
        with urlopen(logout, context=context, timeout=10):
            pass
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
