"""Live HTTP smoke test of the fictional contest workflow; no mocked API data.

Example: python scripts/check-deployment.py --url https://campus.example.ru
For the local compose test, pass --ca /path/to/caddy-root.crt.
"""
from __future__ import annotations

import argparse
import json
import ssl
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Client:
    def __init__(self, base: str, context: ssl.SSLContext):
        self.base = base.rstrip('/')
        self.context = context
        self.cookie = ''
        self.cookie_attributes = ''

    def call(self, path: str, body=None, *, headers=None, expected=200):
        request_headers = {'Origin': self.base, **(headers or {})}
        if self.cookie:
            request_headers['Cookie'] = self.cookie
        if body is not None:
            request_headers.update({'Content-Type': 'application/json', 'X-Requested-With': 'ATLAS'})
        request = Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers=request_headers)
        try:
            response = urlopen(request, context=self.context, timeout=15)
        except HTTPError as exc:
            response = exc
        data = response.read()
        assert response.status == expected, (path, response.status, data[:300])
        if response.headers.get('Set-Cookie', '').startswith('atlas_session='):
            self.cookie_attributes = response.headers['Set-Cookie'].lower()
            self.cookie = response.headers['Set-Cookie'].split(';', 1)[0]
        if 'json' in response.headers.get('Content-Type', ''):
            return json.loads(data)
        return data

    def login(self, login: str, password: str):
        user = self.call('/api/login', {'login': login, 'password': password})
        assert '; httponly' in self.cookie_attributes and '; samesite=lax' in self.cookie_attributes
        if self.base.startswith('https://'):
            assert '; secure' in self.cookie_attributes
        return user


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--ca', help='Trusted local Caddy test CA; default uses the system CA store.')
    parser.add_argument('--request-id', type=int, help='Verify a previous request after a service restart.')
    args = parser.parse_args()
    context = ssl.create_default_context(cafile=args.ca)
    alina, mark, staff = [Client(args.url, context) for _ in range(3)]
    assert alina.call('/api/health')['ok']
    assert alina.call('/api/ready')['ok']
    alina.login('alina.demo', 'AtlasDemo!2026-A')
    mark.login('mark.demo', 'AtlasDemo!2026-M')
    staff.login('dean.demo', 'AtlasStaff!2026-D')
    assert alina.call('/api/me')['group'] != mark.call('/api/me')['group']
    if args.request_id:
        row = alina.call(f'/api/requests/{args.request_id}')
        assert row['status'] == 'ready'
        mark.call(f'/api/requests/{row["id"]}', expected=404)
        document = alina.call(f'/api/requests/{row["id"]}/document')
        assert len(document) > 100
        print(json.dumps({'ok': True, 'persisted_request_id': row['id'], 'status': row['status']}))
        return
    key = str(uuid.uuid4())
    body = {'type': 'study', 'comment': 'Deployment smoke check: fictional data only.'}
    row = alina.call('/api/requests', body, headers={'Idempotency-Key': key}, expected=201)
    duplicate = alina.call('/api/requests', body, headers={'Idempotency-Key': key}, expected=200)
    assert duplicate['id'] == row['id']
    mark.call(f'/api/requests/{row["id"]}', expected=404)
    for next_status in ('review', 'processing', 'ready'):
        details = staff.call(f'/api/staff/requests/{row["id"]}')
        update = {'status': next_status, 'message': 'Готов демонстрационный образец документа.'}
        if 'version' in details:
            update['expected_version'] = details['version']
        elif 'updated_at' in details:
            update['expected_updated_at'] = details['updated_at']
        staff.call(f'/api/staff/requests/{row["id"]}/status', update)
        if next_status == 'review' and 'expected_version' in update:
            staff.call(f'/api/staff/requests/{row["id"]}/status',
                       {**update, 'status': 'processing'}, expected=409)
    details = alina.call(f'/api/requests/{row["id"]}')
    assert details['status'] == 'ready'
    document = alina.call(f'/api/requests/{row["id"]}/document')
    assert len(document) > 100
    assert 'КОНКУРСНЫЙ ОБРАЗЕЦ' in document.decode('utf-8')
    assert 'Марк Северин' not in document.decode('utf-8')
    assert any('Статус заявки' in item['title'] for item in alina.call('/api/notifications'))
    staff_page = staff.call('/api/staff/requests?paginated=true&filter=active&limit=30')
    assert staff_page['total'] >= len(staff_page['items']) and len(staff_page['items']) <= 30
    assert all(item['status'] not in {'ready', 'rejected'} for item in staff_page['items'])
    notification_page = alina.call('/api/notifications?paginated=true&limit=1')
    assert notification_page['total'] >= len(notification_page['items'])
    assert 0 <= notification_page['unread_count'] <= notification_page['total']
    request_page = alina.call('/api/requests?paginated=true&limit=1')
    assert request_page['total'] >= len(request_page['items'])
    alina.call('/api/staff/requests', expected=403)
    staff.call('/api/grades', expected=403)
    ics = alina.call('/api/schedule/export')
    assert b'BEGIN:VCALENDAR' in ics
    deadlines = alina.call('/api/deadlines')
    if deadlines:
        item = deadlines[0]
        mark.call(f'/api/deadlines/{item["id"]}/toggle', {'is_done': True}, expected=404)
        alina.call(f'/api/deadlines/{item["id"]}/toggle', {'is_done': True})
        assert next(x for x in alina.call('/api/deadlines') if x['id'] == item['id'])['is_done']
        alina.call(f'/api/deadlines/{item["id"]}/toggle', {'is_done': item['is_done']})
    print(json.dumps({'ok': True, 'request_id': row['id'], 'status': 'ready', 'checks':
                     ['live', 'ready', 'secure cookies', 'two students', 'IDOR', 'idempotency', 'staff workflow', 'stale version conflict',
                      'document', 'notifications', 'paginated totals and filters', 'role separation', 'calendar', 'deadline persistence']}))


if __name__ == '__main__':
    main()
