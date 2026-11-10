"""Read-only DNS, certificate, redirect and public-port evidence."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import ssl
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', required=True)
    parser.add_argument('--expected-ip', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if any(char in args.domain for char in '/:@?#'):
        parser.error('Use one DNS hostname')
    context = ssl.create_default_context()
    report = {'at_utc': datetime.now(timezone.utc).isoformat(), 'domain': args.domain,
              'scope': 'Actual public DNS, system-verified TLS and bounded port connections from this runner; no Russian connectivity inference.',
              'certificates': {}, 'redirects': [], 'ports': {}}
    for host in (args.domain, 'www.' + args.domain):
        with socket.create_connection((host, 443), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=host) as connection:
                certificate = connection.getpeercert()
                report['certificates'][host] = {
                    'valid_chain_and_hostname': True, 'protocol': connection.version(),
                    'not_before': certificate['notBefore'], 'not_after': certificate['notAfter'],
                    'issuer': certificate['issuer'], 'subject_alt_names': certificate.get('subjectAltName', [])}
        report.setdefault('dns_ipv4', {})[host] = sorted({row[4][0] for row in socket.getaddrinfo(host, 443, socket.AF_INET)})
    opener = build_opener(HTTPSHandler(context=context), NoRedirect())
    path = '/app/schedule?acceptance=canonical'
    for base in ('http://' + args.domain, 'http://www.' + args.domain, 'https://www.' + args.domain):
        try:
            response = opener.open(Request(base + path), timeout=10)
        except HTTPError as exc:
            response = exc
        with response:
            report['redirects'].append({'url': base + path, 'status': response.status,
                                        'location': response.headers.get('Location')})
    def port_probe(port):
        try:
            with socket.create_connection((args.expected_ip, port), timeout=2):
                return str(port), True
        except OSError:
            return str(port), False
    with ThreadPoolExecutor(max_workers=6) as pool:
        report['ports'] = dict(pool.map(port_probe, [22, 80, 443, 2019, 5432, 8000]))
    apex = 'https://' + args.domain
    with opener.open(apex + '/api/health', timeout=10) as response:
        report['health'] = json.loads(response.read())
        report['security_headers'] = {key: response.headers.get(key) for key in (
            'Strict-Transport-Security', 'X-Content-Type-Options', 'X-Frame-Options',
            'Referrer-Policy', 'Cache-Control', 'Content-Security-Policy')}
    valid_redirects = all(row['status'] in {301, 308} and row['location'] in {
        apex + path, 'https://www.' + args.domain + path} for row in report['redirects'])
    report['status'] = 'PASS' if (all(args.expected_ip in values for values in report['dns_ipv4'].values())
        and valid_redirects and all(report['ports'][str(port)] for port in (22, 80, 443))
        and not any(report['ports'][str(port)] for port in (2019, 5432, 8000))
        and report['health'].get('ok') is True) else 'FAIL'
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
