"""Independent adversarial regressions. Every account and record here is fictional."""
from __future__ import annotations

import hashlib
import itertools
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

# Also safe when this module is run on its own: never open the workspace atlas.db.
_test_directory = tempfile.TemporaryDirectory(prefix="atlas-security-")
if "app.db" not in sys.modules:
    os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_test_directory.name) / "security.db")
os.environ.setdefault("DEMO_MODE", "true")

from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.db import DATABASE_URL, LoginSession, Notification, SessionLocal, User, engine, password_hasher

HEADERS = {"X-Requested-With": "ATLAS"}
STUDENT_A = ("alina.demo", "AtlasDemo!2026-A")
STUDENT_B = ("mark.demo", "AtlasDemo!2026-M")
STAFF = ("dean.demo", "AtlasStaff!2026-D")
_client_numbers = itertools.count(1)


@pytest.fixture(scope="module", autouse=True)
def release_security_database_handles():
    yield
    # Windows cannot remove a temporary SQLite file while a pooled handle is open.
    engine.dispose()


def security_client(ip: str | None = None):
    return TestClient(app, client=(ip or f"192.0.2.{next(_client_numbers)}", 50000))


def login(client, account=STUDENT_A):
    response = client.post("/api/login", json={"login": account[0], "password": account[1]}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response


def create_request(client, *, comment="Security regression; fictional data only.", key=None):
    headers = {**HEADERS, **({"Idempotency-Key": key} if key else {})}
    response = client.post("/api/requests", json={"type": "study", "comment": comment}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def change_status(client, record, status, message="Демонстрационный ответ учебного офиса."):
    response = client.post(f"/api/staff/requests/{record['id']}/status", headers=HEADERS,
                           json={"status": status, "message": message, "expected_version": record["version"]})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("url", [
    "/api/me", "/api/dashboard", "/api/schedule", "/api/schedule/export",
    "/api/grades", "/api/deadlines", "/api/requests", "/api/requests/types",
    "/api/requests/1", "/api/requests/1/document", "/api/notifications",
    "/api/staff/requests", "/api/staff/requests/1",
])
def test_private_resources_require_server_session(url):
    with security_client() as client:
        response = client.get(url)
        assert response.status_code == 401
        assert "no-store" in response.headers.get("cache-control", "")


def test_student_data_cannot_be_selected_by_query_parameter():
    with security_client() as a, security_client() as b:
        login(a, STUDENT_A)
        login(b, STUDENT_B)
        a_profile, b_profile = a.get("/api/me").json(), b.get("/api/me").json()
        assert a_profile["id"] != b_profile["id"]
        assert a.get(f"/api/me?student_id={b_profile['id']}").json()["id"] == a_profile["id"]
        for route in ["grades", "schedule", "deadlines", "requests", "notifications"]:
            own = a.get(f"/api/{route}").json()
            injected = a.get(f"/api/{route}?student_id={b_profile['id']}").json()
            assert injected == own, route
        assert a.get("/api/grades").json()["items"] != b.get("/api/grades").json()["items"]
        assert a.get("/api/schedule").json()["days"] != b.get("/api/schedule").json()["days"]
        calendar = a.get(f"/api/schedule/export?student_id={b_profile['id']}")
        assert calendar.status_code == 200
        assert "BEGIN:VCALENDAR" in calendar.text
        assert "Алгоритмы и структуры данных" in calendar.text.replace("\r\n ", "")
        assert "Инженерия ПО" not in calendar.text


def test_complete_role_boundary_including_new_resources():
    with security_client() as student, security_client() as staff:
        login(student, STUDENT_A)
        login(staff, STAFF)
        for url in ["/api/staff/requests", "/api/staff/requests/1"]:
            assert student.get(url).status_code == 403
        assert student.post("/api/staff/requests/1/status", headers=HEADERS,
                            json={"status": "review", "message": "Недопустимая попытка."}).status_code == 403
        for url in ["/api/schedule", "/api/schedule/export", "/api/grades", "/api/deadlines",
                    "/api/dashboard", "/api/requests", "/api/requests/types", "/api/requests/1",
                    "/api/requests/1/document", "/api/notifications"]:
            assert staff.get(url).status_code == 403, url
        assert staff.post("/api/requests", headers=HEADERS, json={"type": "study"}).status_code == 403
        assert staff.post("/api/deadlines/1/toggle", headers=HEADERS, json={"is_done": True}).status_code == 403
        assert staff.post("/api/notifications/read-all", headers=HEADERS).status_code == 403


def test_request_details_and_document_idor_do_not_reveal_status_or_owner():
    with security_client() as a, security_client() as b, security_client() as staff:
        login(a, STUDENT_A)
        login(b, STUDENT_B)
        login(staff, STAFF)
        record = create_request(a)
        for state in ["submitted", "review", "ready"]:
            if state != "submitted":
                record = change_status(staff, record, state)
            assert b.get(f"/api/requests/{record['id']}").status_code == 404
            foreign = b.get(f"/api/requests/{record['id']}/document")
            absent = b.get("/api/requests/2147483647/document")
            assert foreign.status_code == absent.status_code == 404
            assert foreign.json() == absent.json()
        assert a.get(f"/api/requests/{record['id']}/document").status_code == 200


def test_notification_idor_and_read_all_preserve_other_students_rows():
    with security_client() as a, security_client() as b:
        login(a, STUDENT_A)
        login(b, STUDENT_B)
        foreign_id = b.get("/api/notifications").json()[0]["id"]
        with SessionLocal() as db:
            db.get(Notification, foreign_id).is_read = False
            db.commit()
        assert a.post(f"/api/notifications/{foreign_id}/read", headers=HEADERS).status_code == 404
        assert a.post("/api/notifications/read-all", headers=HEADERS).status_code == 200
        foreign = next(n for n in b.get("/api/notifications").json() if n["id"] == foreign_id)
        assert foreign["is_read"] is False


def test_deadline_idor_and_strict_validation_do_not_mutate_foreign_rows():
    with security_client() as a, security_client() as b:
        login(a, STUDENT_A)
        login(b, STUDENT_B)
        own = a.get("/api/deadlines").json()[0]
        foreign = b.get("/api/deadlines").json()[0]
        assert a.post(f"/api/deadlines/{foreign['id']}/toggle", headers=HEADERS,
                      json={"is_done": not foreign["is_done"]}).status_code == 404
        assert b.get("/api/deadlines").json()[0] == foreign
        for invalid in ["false", "true", 0, 1, None]:
            assert a.post(f"/api/deadlines/{own['id']}/toggle", headers=HEADERS,
                          json={"is_done": invalid}).status_code == 422
        assert a.post(f"/api/deadlines/{own['id']}/toggle", headers=HEADERS,
                      json={"is_done": not own["is_done"]}).status_code == 200
        assert a.get("/api/deadlines").json()[0]["is_done"] is not own["is_done"]
        a.post(f"/api/deadlines/{own['id']}/toggle", headers=HEADERS, json={"is_done": own["is_done"]})


@pytest.mark.parametrize("extra", [{"student_id": 2}, {"status": "ready"}, {"role": "staff"}])
def test_assignment_and_privilege_fields_are_rejected(extra):
    with security_client() as client:
        login(client)
        before = len(client.get("/api/requests").json())
        response = client.post("/api/requests", headers=HEADERS, json={"type": "study", **extra})
        assert response.status_code == 422
        assert len(client.get("/api/requests").json()) == before


@pytest.mark.parametrize("origin", ["https://evil.invalid", "null", "http://testserver.evil.invalid"])
def test_csrf_rejects_untrusted_origins_even_without_public_origin(origin, monkeypatch):
    monkeypatch.delenv("PUBLIC_ORIGIN", raising=False)
    with security_client() as client:
        response = client.post("/api/login", headers={**HEADERS, "Origin": origin},
                               json={"login": STUDENT_A[0], "password": STUDENT_A[1]})
        assert response.status_code == 403
        login(client)
        assert client.post("/api/requests", headers={**HEADERS, "Origin": origin},
                           json={"type": "study"}).status_code == 403


def test_csrf_requires_explicit_header_and_same_origin_browser_context():
    with security_client() as client:
        login(client)
        for headers in [{}, {"X-Requested-With": "XMLHttpRequest"},
                        {**HEADERS, "Sec-Fetch-Site": "cross-site"},
                        {**HEADERS, "Sec-Fetch-Site": "same-site", "Origin": "http://sibling.testserver"}]:
            assert client.post("/api/requests", headers=headers, json={"type": "study"}).status_code == 403
        accepted = client.post("/api/requests", headers={**HEADERS, "Origin": "http://testserver",
                                                       "Sec-Fetch-Site": "same-origin"}, json={"type": "study"})
        assert accepted.status_code == 201


def test_session_tokens_are_random_hashed_and_invalid_after_logout():
    with security_client() as client:
        response = login(client)
        first_token = client.cookies.get("atlas_session")
        assert first_token and len(first_token) >= 50
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        with SessionLocal() as db:
            row = db.scalar(select(LoginSession).where(LoginSession.token_hash == hashlib.sha256(first_token.encode()).hexdigest()))
            assert row is not None
            assert row.token_hash != first_token
            user = db.get(User, row.user_id)
            assert user.password_hash.startswith("$argon2id$")
            assert password_hasher.verify(user.password_hash, STUDENT_A[1])
            assert "password" not in response.text
        assert client.post("/api/logout", headers=HEADERS).status_code == 200
        client.cookies.set("atlas_session", first_token)
        assert client.get("/api/me").status_code == 401
        client.cookies.clear()
        login(client)
        assert client.cookies.get("atlas_session") != first_token


def test_expired_session_is_not_authorized():
    with security_client() as client:
        login(client)
        token_hash = hashlib.sha256(client.cookies.get("atlas_session").encode()).hexdigest()
        with SessionLocal() as db:
            row = db.scalar(select(LoginSession).where(LoginSession.token_hash == token_hash))
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
        assert client.get("/api/me").status_code == 401
        assert client.get("/api/staff/requests").status_code == 401


def test_idempotency_is_payload_sensitive_and_scoped_to_owner():
    key = "security-idempotency-" + os.urandom(8).hex()
    with security_client() as a, security_client() as b:
        login(a, STUDENT_A)
        login(b, STUDENT_B)
        first = create_request(a, key=key)
        retry = a.post("/api/requests", headers={**HEADERS, "Idempotency-Key": key},
                       json={"type": "study", "comment": "Security regression; fictional data only."})
        assert retry.status_code == 200
        assert retry.json()["id"] == first["id"]
        conflict = a.post("/api/requests", headers={**HEADERS, "Idempotency-Key": key},
                          json={"type": "study", "comment": "Changed request; same key is forbidden."})
        assert conflict.status_code == 409
        other = create_request(b, key=key)
        assert other["id"] != first["id"]
        assert a.get(f"/api/requests/{other['id']}").status_code == 404
        assert sum(row["id"] == first["id"] for row in a.get("/api/requests").json()) == 1


def test_staff_concurrency_and_rejection_reason():
    with security_client() as student, security_client() as staff:
        login(student)
        login(staff, STAFF)
        record = create_request(student)
        updated = change_status(staff, record, "review")
        stale = staff.post(f"/api/staff/requests/{record['id']}/status", headers=HEADERS,
                           json={"status": "processing", "message": "Конфликтующая запись.",
                                 "expected_version": record["version"]})
        assert stale.status_code == 409
        missing_reason = staff.post(f"/api/staff/requests/{record['id']}/status", headers=HEADERS,
                                    json={"status": "rejected", "message": "", "expected_version": updated["version"]})
        assert missing_reason.status_code == 422
        assert student.get(f"/api/requests/{record['id']}").json()["status"] == "review"


def test_document_is_owner_only_escaped_and_explicitly_fictional():
    dangerous = "<script>alert(1)</script>"
    with security_client() as student, security_client() as staff:
        login(student)
        login(staff, STAFF)
        record = create_request(student, comment=dangerous)
        assert student.get(f"/api/requests/{record['id']}/document").status_code == 409
        record = change_status(staff, record, "review")
        record = change_status(staff, record, "ready", message=dangerous)
        document = student.get(f"/api/requests/{record['id']}/document")
        assert document.status_code == 200
        assert "text/html" in document.headers["content-type"]
        assert "attachment" in document.headers["content-disposition"].lower()
        assert dangerous not in document.text
        assert "&lt;script&gt;" in document.text
        assert "вымышлен" in document.text.lower()
        assert "конкурс" in document.text.lower()
        policy = document.headers["content-security-policy"]
        assert "script-src 'none'" in policy or "default-src 'none'" in policy
        assert "no-store" in document.headers["cache-control"]


def test_security_headers_and_no_cross_origin_read_permission():
    with security_client() as client:
        response = client.get("/api/me", headers={"Origin": "https://evil.invalid"})
        assert response.status_code == 401
        assert "access-control-allow-origin" not in response.headers
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        policy = client.get("/").headers["content-security-policy"]
        assert "script-src 'self'" in policy
        assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]
        assert "object-src 'none'" in policy and "frame-ancestors 'none'" in policy


def test_streamed_body_limit_does_not_trust_content_length():
    payload = b'{"login":"alina.demo","password":"' + b"A" * 40000 + b'"}'
    with security_client() as client:
        response = client.post("/api/login", headers={**HEADERS, "Content-Type": "application/json"},
                               content=iter([payload[:100], payload[100:]]))
        assert response.status_code == 413
        assert "no-store" in response.headers.get("cache-control", "")
        assert response.headers["x-content-type-options"] == "nosniff"


def test_login_throttle_survives_client_restart_and_rotating_accounts():
    ip = "198.51.100.201"
    with security_client(ip=ip) as client:
        for index in range(40):
            response = client.post("/api/login", headers=HEADERS,
                                   json={"login": f"security-unknown-{index}", "password": "incorrect"})
            assert response.status_code == 401, response.text
    with security_client(ip=ip) as reopened:
        response = reopened.post("/api/login", headers=HEADERS,
                                 json={"login": "security-another-unknown", "password": "incorrect"})
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0
    # A new interpreter has no Python limiter memory from this test process.
    script = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app, client=('198.51.100.201', 50000)) as client:
    result = client.post('/api/login', headers={'X-Requested-With':'ATLAS'}, json={'login':'security-after-process-restart','password':'incorrect'})
    print(result.status_code)
"""
    restarted = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                               env={**os.environ, "DATABASE_URL": DATABASE_URL}, timeout=30)
    assert restarted.returncode == 0, restarted.stderr
    assert restarted.stdout.strip() == "429"


def test_login_throttle_limits_repeated_account_attempts():
    with security_client(ip="198.51.100.202") as client:
        for _ in range(12):
            response = client.post("/api/login", headers=HEADERS,
                                   json={"login": "security-pair-limited", "password": "incorrect"})
            assert response.status_code == 401
        assert client.post("/api/login", headers=HEADERS,
                           json={"login": "security-pair-limited", "password": "incorrect"}).status_code == 429


def test_parallel_login_attempts_cannot_race_account_limit():
    ip = "198.51.100.203"
    body = {"login": "security-parallel-limited", "password": "incorrect"}
    with security_client(ip=ip) as client:
        for _ in range(10):
            assert client.post("/api/login", headers=HEADERS, json=body).status_code == 401
    with ExitStack() as stack:
        clients = [stack.enter_context(security_client(ip=ip)) for _ in range(6)]
        with ThreadPoolExecutor(max_workers=6) as workers:
            statuses = list(workers.map(lambda c: c.post("/api/login", headers=HEADERS, json=body).status_code, clients))
    assert statuses.count(401) == 2, statuses
    assert statuses.count(429) == 4, statuses


def test_production_configuration_rejects_insecure_deployment():
    from app.config import Settings
    safe = Settings(app_env="production", demo_mode=True, cookie_secure=True,
                    public_origin="https://campus.example.test", allowed_hosts=("campus.example.test",))
    fictional_database = "postgresql+psycopg://user:PublicFictionalTestPasswordAtLeast32Chars@db/atlas"
    safe.validate(fictional_database)
    for unsafe in [replace(safe, cookie_secure=False), replace(safe, public_origin="http://campus.example.test"),
                   replace(safe, allowed_hosts=("*",)), replace(safe, allowed_hosts=("different.example.test",)),
                   replace(safe, public_origin="https://campus.example.test/a/path")]:
        with pytest.raises(RuntimeError):
            unsafe.validate(fictional_database)
    with pytest.raises(RuntimeError):
        safe.validate("sqlite:///unused.db")
    for insecure_database in ["postgresql+psycopg://user:short@db/atlas",
                              "postgresql+psycopg://user:" + "%41" * 11 + "@db/atlas",
                              "postgresql+psycopg://user:REPLACE_WITH_A_LONG_PASSWORD_123456789@db/atlas"]:
        with pytest.raises(RuntimeError):
            safe.validate(insecure_database)


@pytest.mark.parametrize("account", [STUDENT_A, STUDENT_B, STAFF])
def test_disabled_demo_blocks_preexisting_public_credentials(account, monkeypatch):
    from app import main as main_module
    with security_client() as client:
        # Seeded accounts already exist; turning demo off must not merely hide UI buttons.
        login(client, account)
        monkeypatch.setattr(main_module, "settings", replace(main_module.settings, demo_mode=False))
        assert client.get("/api/config").json()["demo_mode"] is False
        assert client.get("/api/me").status_code == 401
        response = client.post("/api/login", headers=HEADERS,
                               json={"login": account[0], "password": account[1]})
        assert response.status_code == 401


def test_unknown_environment_cannot_silently_select_development_guards(monkeypatch):
    from app.config import load_settings
    monkeypatch.setenv("APP_ENV", "produciton")
    with pytest.raises(RuntimeError):
        load_settings()
