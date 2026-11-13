"""Bounded acceptance of the public HTTPS demo or a disposable local server.

Use --isolated --write-demo for record writes and --request-id to verify an
existing ready request. Public checks only read application records.
No passwords, session cookies, response bodies or database URLs enter the report.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import re
import ssl
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler


STUDENTS = [
    ("alina.demo", "AtlasDemo!2026-A"),
    ("mark.demo", "AtlasDemo!2026-M"),
]
STAFF = ("dean.demo", "AtlasStaff!2026-D")
PAGES = [
    "home", "schedule", "grades", "plan", "requests", "certificates", "notifications",
    "announcements", "announcement-admin", "direct",
    "profile", "campus", "courses", "assignments", "exams", "attendance",
    "calendar", "tasks", "notes", "flashcards", "quizzes", "focus",
    "consultations", "messages", "library", "events", "finance", "contacts",
    "knowledge", "portfolio", "settings", "staff", "staffdesk", "staffmessages",
]
STUDENT_READS = [
    "/api/dashboard", "/api/schedule", "/api/grades", "/api/deadlines",
    "/api/requests/types", "/api/requests?paginated=true&limit=3",
    "/api/notifications?paginated=true&limit=3", "/api/announcements", "/api/direct/dialogs", "/api/learning/courses",
    "/api/learning/assignments", "/api/learning/exams", "/api/learning/attendance",
    "/api/learning/tasks", "/api/learning/notes", "/api/learning/flashcards",
    "/api/learning/quizzes", "/api/learning/quiz-attempts", "/api/learning/focus-sessions",
    "/api/services/consultations", "/api/services/bookings", "/api/services/tickets",
    "/api/services/library", "/api/services/loans", "/api/services/events",
    "/api/services/registrations", "/api/services/finance", "/api/services/contacts",
    "/api/services/knowledge", "/api/services/preferences", "/api/campus/portfolio",
    "/api/campus/search?q=atlas", "/api/account/sessions", "/api/drafts/export",
]
STAFF_READS = [
    "/api/staff/requests?paginated=true&limit=3", "/api/staff/overview",
    "/api/staff/tickets", "/api/staff/consultations", "/api/staff/events", "/api/staff/announcements",
]


class AcceptanceFailure(RuntimeError):
    """Safe error text that never contains a response body or credentials."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular, a server redirect must never forward a login/cookie to
        # an unintended host. Canonical redirects are tested independently.
        return None


def normalized_document_sha256(content: bytes) -> str:
    """Ignore only the fresh CSP nonce, retaining all document content."""
    normalized = re.sub(rb'nonce="[A-Za-z0-9_-]+"', b'nonce="<CSP-NONCE>"', content)
    return hashlib.sha256(normalized).hexdigest()


class Reporter:
    def __init__(self, base: str, mode: str):
        self.data = {
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "url": base, "mode": mode, "fictional_data_only": True,
            "checks": [], "ok": False,
        }

    def check(self, name: str, condition: bool, **safe_details):
        self.data["checks"].append({"name": name, "ok": bool(condition), **safe_details})
        if not condition:
            raise AcceptanceFailure(name)


class Client:
    def __init__(self, base: str, report: Reporter, context: ssl.SSLContext, label: str):
        self.base, self.report, self.label = base, report, label
        self.cookie = ""
        self.user_id = None
        self.opener = build_opener(HTTPSHandler(context=context), NoRedirects())

    def call(self, path, body=None, *, method=None, headers=None, expected=200,
             csrf=True, name=None, return_headers=False):
        method = method or ("POST" if body is not None else "GET")
        request_headers = {"Origin": self.base}
        if self.cookie:
            request_headers["Cookie"] = self.cookie
        if self.user_id is not None:
            request_headers["X-ATLAS-User"] = str(self.user_id)
        if method != "GET" and csrf:
            request_headers["X-Requested-With"] = "ATLAS"
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = Request(self.base + path, method=method, headers=request_headers,
                          data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
        started = time.monotonic()
        try:
            response = self.opener.open(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            # HTTPMessage preserves case-insensitive lookup even when a proxy
            # chooses lowercase names. Never serialize this object.
            response_headers = response.headers
            status = response.status
        self.report.check(name or f"{self.label} {method} {path}", status == expected,
                          status=status, expected_status=expected,
                          elapsed_ms=round((time.monotonic() - started) * 1000, 1))
        if path.startswith("/api/"):
            self.report.check(f"{self.label} private API response {path}",
                              "no-store" in response_headers.get("Cache-Control", ""))
        cookie = response_headers.get("Set-Cookie", "")
        if cookie.startswith("atlas_session="):
            self.cookie = cookie.split(";", 1)[0]
            lower = cookie.lower()
            self.report.check(f"{self.label} session attributes",
                              all(item in lower for item in ("; httponly", "; samesite=lax"))
                              and (self.base.startswith("http://127.0.0.1:") or "; secure" in lower))
        data = json.loads(raw) if "json" in response_headers.get("Content-Type", "") else raw
        if return_headers:
            # Callers consume headers in memory; they are never included in JSON.
            return data, response_headers
        return data

    def login(self, account):
        data = self.call("/api/login", {"login": account[0], "password": account[1]})
        self.user_id = data["user"]["id"]
        return data["user"]


def verify_ready_request(alina, mark, staff, request_id, report, expected_sha=None):
    path = f"/api/requests/{request_id}"
    row = alina.call(path)
    report.check("previously saved request is ready", row["status"] == "ready")
    mark.call(path, expected=404)
    mark.call(path + "/document", expected=404)
    staff.call(path + "/document", expected=403)
    document, headers = alina.call(path + "/document", return_headers=True)
    text = document.decode("utf-8")
    report.check("document is a fictional downloadable HTML sample",
                 "КОНКУРСНЫЙ ОБРАЗЕЦ" in text and "ВСЕ ДАННЫЕ ВЫМЫШЛЕНЫ" in text
                 and "attachment" in headers.get("Content-Disposition", ""))
    policy = headers.get("Content-Security-Policy", "")
    report.check("downloaded document blocks active content",
                 "script-src 'none'" in policy and "sandbox" in policy)
    doc_sha = normalized_document_sha256(document)
    if expected_sha:
        report.check("document content survived restart or restore", doc_sha == expected_sha)
    projection = {key: row[key] for key in ("id", "status", "version", "comment", "history")}
    report.data["persistence"] = {
        "request_id": request_id, "status": row["status"], "version": row["version"],
        "history_events": row["history_total"], "document_content_sha256": doc_sha,
        "request_sha256": hashlib.sha256(json.dumps(projection, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
    }
    return row


def run(args, report):
    if args.write_demo and (not args.isolated or urlsplit(args.url).hostname != "127.0.0.1"):
        raise AcceptanceFailure("The write workflow requires the runner's disposable server")
    context = ssl.create_default_context(cafile=args.ca)
    public, alina, mark, staff = [Client(args.url, report, context, name)
                                   for name in ("anonymous", "alina", "mark", "staff")]
    health = public.call("/api/health")
    report.check("release version", health["ok"] is True and bool(health["version"])
                 and (not args.expect_version or health["version"] == args.expect_version))
    report.data["release"] = {key: health.get(key) for key in ("version", "build")}
    if args.expect_build:
        report.check("source build identity", health.get("build") == args.expect_build)
    report.check("database readiness", public.call("/api/ready")["ok"] is True)
    config = public.call("/api/config")
    report.check("public fictional contest configuration", config["demo_mode"] and config["concept"])
    shell, headers = public.call("/", return_headers=True)
    report.check("public shell declares the concept", "концепт" in shell.decode("utf-8").lower())
    report.check("security response headers", headers.get("X-Content-Type-Options") == "nosniff"
                 and headers.get("X-Frame-Options") == "DENY"
                 and (args.isolated or "max-age=" in headers.get("Strict-Transport-Security", ""))
                 and "frame-ancestors 'none'" in headers.get("Content-Security-Policy", ""))
    for page in PAGES:
        public.call("/app/" + page)
    for asset in ("app.js", "campus.js", "improvements.js", "style.css", "usability.css", "campus.css",
                  "announcements.js", "announcements.css", "shell.css", "university.js", "university.css", "viewport.js"):
        public.call("/static/" + asset)
    for path in ("/.env", "/.git/HEAD", "/compose.yaml", "/Dockerfile", "/docs", "/redoc", "/openapi.json"):
        public.call(path, expected=404)
    for path in ("/api/me", "/api/grades", "/api/schedule", "/api/requests", "/api/notifications",
                 "/api/staff/requests", "/api/learning/notes", "/api/services/finance", "/api/drafts/export",
                 "/api/announcements", "/api/direct/dialogs"):
        public.call(path, expected=401)
    _, cross_origin_headers = public.call("/api/me", headers={"Origin": "https://untrusted.invalid"},
                                          expected=401, return_headers=True)
    report.check("no cross-origin permission to read private API", not cross_origin_headers.get("Access-Control-Allow-Origin"))
    if args.isolated:
        public.call("/api/login", {"login": "acceptance.invalid", "password": "x" * 40000}, expected=413)

    # Three sequential correct logins; no brute-force or throttle saturation.
    users = [alina.login(STUDENTS[0]), mark.login(STUDENTS[1]), staff.login(STAFF)]
    report.check("three distinct fictional actors", len({u["id"] for u in users}) == 3
                 and [u["role"] for u in users] == ["student", "student", "staff"])
    report.check("student group isolation", users[0]["group"] != users[1]["group"])
    for student in (alina, mark):
        for path in STUDENT_READS:
            student.call(path)
        for path in STAFF_READS:
            student.call(path, expected=403)
    for path in STAFF_READS:
        staff.call(path)
    for path in ("/api/grades", "/api/schedule", "/api/requests",
                 "/api/learning/notes", "/api/services/finance"):
        staff.call(path, expected=403)
    staff.call("/api/notifications")
    alina.call("/api/me", headers={"X-ATLAS-User": str(users[1]["id"])}, expected=409)
    if args.isolated:
        for method_headers in ({"Origin": "https://untrusted.invalid"}, {"Sec-Fetch-Site": "same-site"},
                               {"Sec-Fetch-Site": "cross-site"}):
            alina.call("/api/requests", {"type": "study"}, headers=method_headers, expected=403)
        alina.call("/api/requests", {"type": "study"}, csrf=False, expected=403)
        alina.call("/api/notifications/read-all", {}, csrf=False, expected=403)
        alina.call("/api/requests", {"type": "study", "student_id": users[1]["id"]}, expected=422)
    for owner, other in ((alina, mark), (mark, alina)):
        own = owner.call("/api/requests?paginated=true&limit=1")["items"]
        if own:
            other.call(f'/api/requests/{own[0]["id"]}', expected=404)
            other.call(f'/api/requests/{own[0]["id"]}/document', expected=404)
        notices = owner.call("/api/notifications?paginated=true&limit=1")["items"]
        if notices:
            other.call(f'/api/notifications/{notices[0]["id"]}', expected=404)
        courses = owner.call("/api/learning/courses")["items"]
        if courses:
            other.call(f'/api/learning/courses/{courses[0]["id"]}', expected=404)
    calendar = alina.call("/api/schedule/export")
    report.check("calendar export", b"BEGIN:VCALENDAR" in calendar and b"END:VCALENDAR" in calendar)
    portfolio = alina.call("/api/campus/portfolio/export")
    report.check("portfolio export declares fictional data", "ВСЕ ДАННЫЕ ВЫМЫШЛЕНЫ" in portfolio.decode())

    if args.write_demo:
        marker = "Локальная приёмка API " + uuid.uuid4().hex
        request_key = uuid.uuid4().hex
        body = {"type": "study", "comment": marker + ": fictional data only.",
                "details": {"purpose": "Вымышленная заявка для локальной приёмки", "copies": "1"}}
        key_headers = {"Idempotency-Key": request_key}
        created = alina.call("/api/requests", body, headers=key_headers, expected=201)
        rid = created["id"]
        report.data["created_fictional_request_id"] = rid
        duplicate = alina.call("/api/requests", body, headers=key_headers)
        report.check("request replay creates no duplicate", duplicate["id"] == rid)
        alina.call("/api/requests", {**body, "comment": marker + " different"}, headers=key_headers, expected=409)
        path = f"/api/requests/{rid}"
        mark.call(path, expected=404)
        mark.call(path + "/document", expected=404)
        alina.call(path + "/document", expected=409)
        alina.call(f"/api/staff/requests/{rid}/status", {"status": "ready"}, expected=403)
        staff.call(f"/api/staff/requests/{rid}/status", {"status": "ready", "expected_version": 1,
                   "message": "Вымышленный образец для автоматической приёмки."}, expected=409)
        draft_name = "acceptance:" + uuid.uuid4().hex
        values = {"comment": marker}
        alina.call("/api/drafts/" + draft_name, {"values": values}, method="PUT")
        report.check("private draft roundtrip", alina.call("/api/drafts/" + draft_name)["values"] == values)
        report.check("private draft hidden from second student", mark.call("/api/drafts/" + draft_name)["values"] == {})
        report.data["created_fictional_draft_name"] = draft_name
        followup_body = {"message": marker + " additional fictional details", "expected_version": 1}
        followup_headers = {"Idempotency-Key": uuid.uuid4().hex}
        followup = alina.call(path + "/followup", followup_body, headers=followup_headers)
        replay = alina.call(path + "/followup", followup_body, headers=followup_headers)
        report.check("clarification replay is stable", followup == replay and followup["status"] == "submitted")
        for status in ("review", "processing", "ready"):
            details = staff.call(f"/api/staff/requests/{rid}")
            update = {"status": status, "expected_version": details["version"],
                      "message": "Вымышленный образец для автоматической приёмки."}
            staff.call(f"/api/staff/requests/{rid}/status", update)
            if status == "review":
                staff.call(f"/api/staff/requests/{rid}/status", {**update, "status": "processing"}, expected=409)
        final = verify_ready_request(alina, mark, staff, rid, report)
        report.check("bounded staff workflow history", final["history_total"] == 5)
        notices = alina.call("/api/notifications?paginated=true&limit=200")["items"]
        report.check("request notifications saved for owner", any(n["request_id"] == rid for n in notices))
        other_notices = mark.call("/api/notifications?paginated=true&limit=200")["items"]
        report.check("request notifications hidden from second student", not any(n["request_id"] == rid for n in other_notices))
        report.check("isolated draft retained", alina.call("/api/drafts/" + draft_name)["values"] == values)
    elif args.request_id:
        verify_ready_request(alina, mark, staff, args.request_id, report, args.expected_document_sha)
        if args.draft_name:
            draft = alina.call("/api/drafts/" + args.draft_name)
            report.check("saved isolated draft survived restart or restore", bool(draft["values"]))
            report.check("saved isolated draft remains private", mark.call("/api/drafts/" + args.draft_name)["values"] == {})
    for client in (alina, mark, staff):
        client.call("/api/logout", {})
        client.cookie = ""
        client.call("/api/me", expected=401)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--url")
    target.add_argument("--isolated", action="store_true", help="Start a loopback server with a disposable database.")
    parser.add_argument("--ca", help="Optional explicit trusted CA file; certificate validation is never disabled.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write-demo", action="store_true", help="Exercise request writes on the disposable server.")
    mode.add_argument("--request-id", type=int, help="Verify a previously prepared ready request; no domain writes.")
    parser.add_argument("--draft-name", help="Optional previously created isolated acceptance draft.")
    parser.add_argument("--expected-document-sha", help="Normalized document content SHA-256 from the earlier report.")
    parser.add_argument("--expect-build", help="Expected public /api/health build identifier.")
    parser.add_argument("--expect-version", help="Expected version from /api/health.")
    parser.add_argument("--report", type=Path, help="Write a credential-free JSON report, including failures.")
    args = parser.parse_args()
    if args.write_demo and not args.isolated:
        parser.error("--write-demo requires --isolated and cannot use --url")
    if not args.isolated:
        args.url = (args.url or "https://atlas-university.ru").rstrip("/")
        parsed = urlsplit(args.url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
            parser.error("--url must be one HTTPS origin without credentials or path")
    if args.request_id is not None and args.request_id < 1:
        parser.error("--request-id must be positive")
    if args.expected_document_sha and not re.fullmatch(r"[a-f0-9]{64}", args.expected_document_sha):
        parser.error("--expected-document-sha must be a lowercase SHA-256 digest")
    if args.draft_name and not re.fullmatch(r"acceptance:[a-f0-9]{32}", args.draft_name):
        parser.error("--draft-name must identify a prior isolated acceptance draft")
    if (args.expected_document_sha or args.draft_name) and args.request_id is None:
        parser.error("--expected-document-sha and --draft-name require --request-id")
    return args


def report_run(args):
    mode = "write-labelled-fictional-records" if args.write_demo else "verify-persistence" if args.request_id else "read-only-domain-records"
    report = Reporter(args.url, mode)
    try:
        run(args, report)
        report.data["ok"] = True
    except Exception as error:
        # Generic transport errors may include request metadata; preserve only
        # the type. Assertion text is from this script's safe labels only.
        report.data["failure"] = str(error) if isinstance(error, AcceptanceFailure) else type(error).__name__
    report.data["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report.data["checks_passed"] = sum(check["ok"] for check in report.data["checks"])
    report.data["checks_total"] = len(report.data["checks"])
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report.data, ensure_ascii=False))
    return 0 if report.data["ok"] else 1


def main():
    args = parse_args()
    from improvement_runtime import isolated_server
    with isolated_server() if args.isolated else nullcontext() as server:
        if server:
            args.url = server["base"]
        return report_run(args)


if __name__ == "__main__":
    sys.exit(main())
