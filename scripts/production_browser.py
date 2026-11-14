"""Real browser acceptance over HTTPS or on a disposable local ATLAS server.

The public mode signs in, reads pages and downloads a calendar. Use --isolated
--write-demo for the request, staff answer and document workflow.
Browser engines and viewport emulation do not establish physical-device,
native-Safari or Russian residential/mobile connectivity results.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import traceback
from urllib.parse import urlsplit, urlunsplit
import uuid

from playwright.sync_api import expect, sync_playwright

from improvement_crossbrowser import STAFF, STUDENT
from improvement_runtime import ROOT, browser_login, browser_visit, geometry, isolated_server


WIDTHS = [(360, 800), (390, 844), (768, 1024), (1440, 1000)]
KEY_SCREENS = {"home", "schedule", "requests", "certificates", "announcements", "direct", "staff", "announcement-admin"}
FEATURE_CONTROLS = {
    "home": ".announcement-timeline",
    "certificates": '.page-actions [data-action="new-request"]',
    "announcements": "[data-announcement-filters]",
    "announcement-admin": '[data-announcement-action="new"]',
    "direct": ".messenger",
    "notifications": '[data-action="read-all"]',
}
WEBKIT_CAPTURE_STYLE_MESSAGE = ("Refused to apply a stylesheet because its hash, its nonce, "
                                "or 'unsafe-inline' does not appear in the style-src directive of the Content Security Policy.")
WEBKIT_VIEWPORT_MESSAGE = 'Viewport argument key "interactive-widget" not recognized and ignored.'


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_url(value):
    """Keep only scheme, host and path; reports never contain URL credentials."""
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.port:
        host += ":" + str(parts.port)
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def safe_text(value):
    text = str(value)
    text = re.sub(r"(?i)(atlas_session=)[^\s;]+", r"\1<redacted>", text)
    text = re.sub(r"(?i)((?:password|authorization|cookie|token)[\s:=]+)[^\s,;]+",
                  r"\1<redacted>", text)
    return text[:1200]


class Acceptance:
    def __init__(self, args):
        self.args = args
        self.token = uuid.uuid4().hex[:12]
        self.capturing = set()
        self.report = {
            "started_at_utc": now(), "url": args.url,
            "scope": ("Disposable local server and database" if args.isolated else "Public HTTPS pages")
                     + "; real browser engines, viewport emulation.",
            "physical_devices": False, "native_safari": False,
            "russian_connection_verified": False, "tls_validation_disabled": False,
            "mode": "write-labelled-fictional-requests" if args.write_demo else "read-only-domain-records",
            "run_id": self.token, "widths": [w for w, _ in WIDTHS],
            "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "engines": [], "geometry": [], "checks": [], "screenshots": [],
            "downloads": [], "created_fictional_requests": [], "browser_errors": [],
            "console_errors": [], "unexpected_console_errors": [],
            "http_server_errors": [], "failed_requests": [], "cleanup_errors": [],
            "failures": [], "status": "RUNNING",
        }
        args.screenshots.mkdir(parents=True, exist_ok=True)

    def checkpoint(self, final=False):
        if final:
            self.report["finished_at_utc"] = now()
            bad = any(self.report[key] for key in (
                "failures", "browser_errors", "unexpected_console_errors",
                "http_server_errors", "failed_requests", "cleanup_errors"))
            self.report["status"] = "FAIL" if bad else "PASS"
        self.args.report.parent.mkdir(parents=True, exist_ok=True)
        self.args.report.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def check(self, name, condition, **details):
        self.report["checks"].append({"name": name, "ok": bool(condition), **details})
        if not condition:
            raise AssertionError(name)

    def monitor(self, page, engine, actor):
        def response_seen(response):
            if response.status >= 500:
                self.report["http_server_errors"].append({
                    "engine": engine, "actor": actor,
                    "url": safe_url(response.url), "status": response.status})

        def console_seen(message):
            if message.type != "error":
                return
            location = message.location or {}
            url = safe_url(location.get("url", ""))
            item = {"engine": engine, "actor": actor, "url": url,
                    "message": safe_text(message.text)}
            # A fresh unauthenticated page asks /api/me and correctly gets 401.
            # Browser resource diagnostics for that expected response are kept,
            # but are not application errors. IDOR probes use context.request.
            expected = (urlsplit(url).path == "/api/me" and "401" in message.text)
            # Playwright's WebKit snapshotter appends an empty inline `body {}`
            # style to sync animations, even with caret=initial/animations=allow.
            # Keep this diagnostic and classify it only inside the screenshot call.
            capture_style = (engine == "webkit" and page in self.capturing and url == safe_url(page.url)
                             and message.text == WEBKIT_CAPTURE_STYLE_MESSAGE)
            # WebKit 26 falls back to its default virtual keyboard viewport policy.
            viewport_fallback = (engine == "webkit" and message.text == WEBKIT_VIEWPORT_MESSAGE)
            item["expected_initial_unauthenticated_401"] = expected
            item["playwright_webkit_capture_style"] = capture_style
            item["webkit_viewport_fallback"] = viewport_fallback
            self.report["console_errors"].append(item)
            if not expected and not capture_style and not viewport_fallback:
                self.report["unexpected_console_errors"].append(item)

        page.on("pageerror", lambda error: self.report["browser_errors"].append({
            "engine": engine, "actor": actor, "url": safe_url(page.url),
            "message": safe_text(error)}))
        page.on("console", console_seen)
        page.on("response", response_seen)
        page.on("requestfailed", lambda request: self.report["failed_requests"].append({
            "engine": engine, "actor": actor, "url": safe_url(request.url),
            "failure": safe_text(request.failure)}))

    def capture(self, page, engine, actor, name):
        if self.args.no_screenshots:
            return
        width = page.viewport_size["width"]
        path = self.args.screenshots / f"{self.token}-{engine}-{width}-{actor}-{name}.png"
        self.capturing.add(page)
        try:
            page.screenshot(path=str(path), full_page=not bool(page.locator(".modal").count()),
                            animations="allow", caret="initial")
        finally:
            self.capturing.discard(page)
        relative_path = path.resolve().relative_to(ROOT).as_posix() if path.resolve().is_relative_to(ROOT) else path.name
        self.report["screenshots"].append({
            "engine": engine, "actor": actor, "width": width, "screen": name,
            "path": relative_path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})

    def layout(self, page, engine, actor, route):
        result = geometry(page)
        self.report["geometry"].append({"engine": engine, "actor": actor, "route": route, **result})

    def case(self, name, operation, *, page=None, engine=None, actor=None):
        try:
            operation()
            print("PASS " + name, flush=True)
        except Exception as error:
            self.report["failures"].append({"name": name, "type": type(error).__name__,
                "message": safe_text(error), "trace": safe_text(traceback.format_exc(limit=4))})
            print("FAIL " + name + ": " + type(error).__name__, flush=True)
            if page is not None:
                try:
                    self.capture(page, engine, actor, "failure-" + str(len(self.report["failures"])))
                except Exception:
                    pass
            self.checkpoint()
            return False
        self.checkpoint()
        return True

    def read_page(self, page, engine, actor, route):
        browser_visit(page, self.args.url, route)
        self.check(f"{engine} {actor} {route} stays on its route",
                   urlsplit(page.url).path.rstrip("/") == "/app/" + route)
        self.layout(page, engine, actor, route)
        if route in FEATURE_CONTROLS:
            expect(page.locator(FEATURE_CONTROLS[route])).to_be_visible()
        if route in KEY_SCREENS:
            self.capture(page, engine, actor, route)

    def record_download(self, download, engine, kind, request_id=None):
        path = Path(download.path())
        content = path.read_bytes()
        item = {"engine": engine, "kind": kind, "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest()}
        if request_id is not None:
            item["request_id"] = request_id
        self.report["downloads"].append(item)
        return content

    def calendar(self, page, engine):
        browser_visit(page, self.args.url, "schedule")
        with page.expect_download() as pending:
            page.locator('a[href*="/schedule/export"]').click()
        content = self.record_download(pending.value, engine, "calendar")
        self.check(engine + " actual calendar download", b"BEGIN:VCALENDAR" in content
                   and b"END:VCALENDAR" in content and b"Europe/Moscow" in content)

    def workflow(self, a, b, staff, engine):
        base = self.args.url
        if not self.args.isolated or urlsplit(base).hostname != "127.0.0.1":
            raise RuntimeError("The write workflow requires the runner's disposable server")
        # A leftover draft even on a disposable server would affect the scenario.
        saved = a.request.get(base + "/api/drafts/certificate-order")
        self.check(engine + " draft preflight HTTP", saved.status == 200)
        self.check(engine + " existing request draft is empty", not saved.json().get("values"))
        marker = f"Локальная браузерная приёмка {self.token} {engine}."
        for page in (a, b, staff):
            page.set_viewport_size({"width": 360, "height": 800})
        browser_visit(a, base, "certificates")
        a.locator('[data-request-view="services"]').first.click()
        a.locator('.certificate-service [data-type="study"]').click()
        form = a.locator("#request-form")
        expect(form).to_be_visible()
        # Wait for real server draft restoration before typing, as in regression
        # tests. No JavaScript is injected to alter the application state.
        a.wait_for_function("""() => {
            const form = document.querySelector('#request-form');
            return form && form._atlasDraft && form._atlasDraft.loaded;
        }""")
        self.check(engine + " restored request draft has no comment", not a.locator("#doc-comment").input_value())
        a.locator("#doc-comment").fill(marker)
        a.locator("#service-purpose").fill("Вымышленная заявка для локальной приёмки")
        a.locator("#service-copies").select_option("1")
        self.capture(a, engine, "alina", "request-form")
        with a.expect_response(lambda r: r.url == base + "/api/requests" and r.request.method == "POST") as pending:
            form.locator('button[type="submit"]').click()
        response = pending.value
        self.check(engine + " UI request submitted once", response.status == 201, status=response.status)
        request_id = response.json()["id"]
        self.report["created_fictional_requests"].append({"engine": engine, "request_id": request_id, "marker": marker})
        self.checkpoint()
        expect(a.locator(".detail-summary")).to_be_visible()
        self.layout(a, engine, "alina", "submitted-request")
        self.capture(a, engine, "alina", "submitted-request")
        for path in (f"/api/requests/{request_id}", f"/api/requests/{request_id}/document"):
            denied = b.request.get(base + path)
            self.check(engine + " second student denied " + path, denied.status == 404, status=denied.status)
        browser_visit(staff, base, "staff")
        staff.locator('[data-staff-kind="certificate"]').click()
        staff.locator("#staff-search").fill(str(request_id))
        row = staff.locator(f'.request-row[data-id="{request_id}"]')
        expect(row).to_be_visible()
        row.click()
        answer = "Вымышленный образец справки готов к скачиванию."
        for status in ("review", "processing", "ready"):
            form = staff.locator("#staff-form")
            expect(form).to_be_visible()
            version = int(form.get_attribute("data-version"))
            staff.locator("#staff-status").select_option(status)
            staff.locator("#staff-message").fill(answer)
            with staff.expect_response(lambda r: r.url == base + f"/api/staff/requests/{request_id}/status"
                                       and r.request.method == "POST") as pending:
                form.locator('button[type="submit"]').click()
            self.check(engine + " staff UI transition " + status, pending.value.status == 200,
                       request_id=request_id, status=pending.value.status)
            if status != "ready":
                expect(staff.locator("#staff-form")).to_have_attribute("data-version", str(version + 1))
            else:
                expect(staff.locator("#staff-form")).to_have_count(0)
            self.layout(staff, engine, "staff", "request-" + status)
            self.capture(staff, engine, "staff", "request-" + status)
        if a.locator(".modal").count():
            a.locator(".modal .close-btn").click()
        browser_visit(a, base, "certificates")
        a.locator('[data-request-filter="ready"]').click()
        row = a.locator(f'.request-row[data-id="{request_id}"]')
        expect(row).to_be_visible()
        row.click()
        expect(a.locator(".staff-answer")).to_contain_text(answer)
        self.layout(a, engine, "alina", "ready-result")
        for width, height in WIDTHS:
            a.set_viewport_size({"width": width, "height": height})
            self.layout(a, engine, "alina", "ready-result")
            self.capture(a, engine, "alina", "ready-result")
        with a.expect_download() as pending:
            a.locator(f'a[href="/api/requests/{request_id}/document"]').click()
        content = self.record_download(pending.value, engine, "fictional-document", request_id)
        text = content.decode("utf-8")
        self.check(engine + " actual owner document download", "Не имеет юридической силы" in text and answer in text)
        self.check(engine + " saved new request ready", a.request.get(base + f"/api/requests/{request_id}").json()["status"] == "ready")

    def logout(self, page, engine, actor):
        try:
            browser_visit(page, self.args.url, "profile")
            with page.expect_response(lambda r: r.url == self.args.url + "/api/logout"
                                      and r.request.method == "POST") as pending:
                page.locator('.danger-button[data-action="logout"]').click()
            self.check(engine + " " + actor + " logout", pending.value.status == 200)
            expect(page.locator("#login-form")).to_be_visible()
        except Exception as error:
            self.report["cleanup_errors"].append({"engine": engine, "actor": actor,
                "type": type(error).__name__, "message": safe_text(error)})

    def engine(self, playwright, engine):
        browser = getattr(playwright, engine).launch(headless=True)
        contexts = []
        pages = []
        try:
            self.report["engines"].append({"name": engine, "version": browser.version})
            for index, actor in enumerate(("alina", "mark", "staff")):
                context = browser.new_context(viewport={"width": 360, "height": 800},
                    reduced_motion="reduce", locale="ru-RU", accept_downloads=True,
                    ignore_https_errors=False)
                contexts.append(context)
                page = context.new_page()
                page.set_default_timeout(30000)
                page.set_default_navigation_timeout(45000)
                pages.append(page)
                self.monitor(page, engine, actor)
                browser_login(page, self.args.url, index)
                health_response = page.request.get(self.args.url + "/api/health")
                self.check(engine + " HTTP health", health_response.status == 200)
                health = health_response.json()
                if self.args.expect_version:
                    self.check(engine + " expected application version", health.get("version") == self.args.expect_version)
                if self.args.expect_build:
                    self.check(engine + " expected public build", health.get("build") == self.args.expect_build)
                self.report.setdefault("public_release", {key: health.get(key) for key in ("version", "build")})
                self.check(engine + " release consistency", all(health.get(key) == self.report["public_release"][key]
                           for key in ("version", "build")))
            a, b, staff = pages
            users = [page.request.get(self.args.url + "/api/me").json() for page in pages]
            self.check(engine + " two students and staff are distinct", len({u["id"] for u in users}) == 3
                       and [u["role"] for u in users] == ["student", "student", "staff"])
            self.check(engine + " student groups differ", users[0]["group"] != users[1]["group"])
            for page, actor, path in ((a, "alina", "/api/staff/requests"), (staff, "staff", "/api/grades")):
                denied = page.request.get(self.args.url + path)
                self.check(engine + " " + actor + " role denied " + path, denied.status == 403, status=denied.status)
            for width, height in WIDTHS:
                for page, routes, actor in ((a, [*STUDENT, "direct"], "alina"),
                                            (staff, [*STAFF, "notifications", "direct"], "staff")):
                    page.set_viewport_size({"width": width, "height": height})
                    for route in routes:
                        self.case(f"{engine} {actor} {width}px {route}",
                            lambda page=page, actor=actor, route=route: self.read_page(page, engine, actor, route),
                            page=page, engine=engine, actor=actor)
            for route in ("home", "schedule", "grades", "requests", "certificates", "announcements", "direct", "notifications"):
                self.case(f"{engine} mark 360px {route}", lambda route=route: self.read_page(b, engine, "mark", route),
                          page=b, engine=engine, actor="mark")
            self.case(engine + " calendar export", lambda: self.calendar(a, engine),
                      page=a, engine=engine, actor="alina")
            if self.args.write_demo:
                self.case(engine + " isolated student-staff-document workflow",
                          lambda: self.workflow(a, b, staff, engine), page=a, engine=engine, actor="alina")
        finally:
            for page, actor in zip(pages, ("alina", "mark", "staff")):
                self.logout(page, engine, actor)
            for context in contexts:
                context.close()
            browser.close()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--url", help="Already deployed HTTPS origin for read checks.")
    target.add_argument("--isolated", action="store_true", help="Start a loopback server with a disposable database.")
    parser.add_argument("--report", required=True, type=Path, help="Credential-free JSON evidence path.")
    parser.add_argument("--screenshots", required=True, type=Path, help="Directory for actual public-page PNGs.")
    parser.add_argument("--no-screenshots", action="store_true", help="Run independently of screenshot instrumentation.")
    parser.add_argument("--engines", default="chromium,firefox,webkit", help="Comma-separated installed browser engines.")
    parser.add_argument("--expect-build", help="Expected build identifier from /api/health.")
    parser.add_argument("--expect-version", help="Expected version from /api/health.")
    parser.add_argument("--write-demo", action="store_true", help="Exercise request writes on the disposable server.")
    args = parser.parse_args()
    if args.write_demo and not args.isolated:
        parser.error("--write-demo requires --isolated and cannot use --url")
    if args.url:
        parsed = urlsplit(args.url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            parser.error("--url must be one HTTPS origin without credentials, query or path")
        args.url = args.url.rstrip("/")
    args.engines = args.engines.split(",")
    if not args.engines or len(set(args.engines)) != len(args.engines) or not set(args.engines) <= {"chromium", "firefox", "webkit"}:
        parser.error("--engines must be unique names from chromium,firefox,webkit")
    return args


def run(args):
    acceptance = Acceptance(args)
    try:
        with sync_playwright() as playwright:
            for engine in args.engines:
                acceptance.case(engine + " browser acceptance", lambda engine=engine: acceptance.engine(playwright, engine))
    except Exception as error:
        acceptance.report["failures"].append({"name": "browser runtime", "type": type(error).__name__, "message": safe_text(error)})
    finally:
        acceptance.checkpoint(final=True)
    print(json.dumps({"status": acceptance.report["status"], "engines": acceptance.report["engines"],
        "geometry_checks": len(acceptance.report["geometry"]), "screenshots": len(acceptance.report["screenshots"]),
        "created_fictional_requests": acceptance.report["created_fictional_requests"],
        "failures": len(acceptance.report["failures"]), "report": str(args.report.resolve())}, ensure_ascii=False))
    return 0 if acceptance.report["status"] == "PASS" else 1


def main():
    args = parse_args()
    with isolated_server() if args.isolated else nullcontext() as server:
        if server:
            args.url = server['base']
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
