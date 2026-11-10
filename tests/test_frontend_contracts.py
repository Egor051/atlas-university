"""Browser regressions for observed client failures, against a real isolated API.

Opt in with ATLAS_RUN_BROWSER_TESTS=1. No API payload is fabricated: fault
injection only delays an actual response or drops it after the server commits.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(os.environ.get("ATLAS_RUN_BROWSER_TESTS") != "1",
                                reason="Opt-in browser suite: set ATLAS_RUN_BROWSER_TESTS=1")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def frontend_server():
    with tempfile.TemporaryDirectory(prefix="atlas-frontend-") as directory:
        with socket.socket() as candidate:
            candidate.bind(("127.0.0.1", 0))
            port = candidate.getsockname()[1]
        address = f"http://127.0.0.1:{port}"
        env = {**os.environ, "DATABASE_URL": "sqlite:///" + str(Path(directory) / "browser.db"),
               "APP_ENV": "development", "DEMO_MODE": "true", "COOKIE_SECURE": "false",
               "PUBLIC_ORIGIN": address, "ALLOWED_HOSTS": "127.0.0.1,localhost,testserver"}
        with (Path(directory) / "server.log").open("w+", encoding="utf-8") as log:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                       "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        log.seek(0)
                        pytest.fail("Isolated browser server exited: " + log.read())
                    try:
                        if httpx.get(address + "/api/ready", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    pytest.fail("Isolated browser server did not become ready within 20 seconds")
                yield address
            finally:
                if server.poll() is None:
                    if os.name == "nt":
                        # Windows venv launchers can own an actual Python child;
                        # terminate this test's complete server tree before cleanup.
                        subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                                       capture_output=True, timeout=10,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    else:
                        server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


@pytest.fixture(scope="module")
def frontend_browser():
    with sync_playwright() as automation:
        browser = automation.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def frontend_page(frontend_browser, frontend_server):
    context = frontend_browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
    page = context.new_page()
    page.set_default_timeout(8000)
    yield page, frontend_server
    context.close()


def enter_demo(page, index, first_name):
    page.locator(f"button[data-demo='{index}']").click()
    page.wait_for_url("**/app/home")
    expect(page.locator("#page-title")).to_contain_text(first_name)


def leave_demo(page):
    page.locator(".sidebar [data-route='profile']").first.click()
    expect(page.locator("#page-title")).to_have_text("Мой профиль")
    page.locator(".danger-button[data-action='logout']").click()
    expect(page.locator("#login-form")).to_be_visible()


def finish_browser_tasks(page):
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def wait_for_held_response(page, held):
    deadline = time.monotonic() + 8
    while not held and time.monotonic() < deadline:
        page.wait_for_timeout(20)
    assert held, "Expected actual API response was not intercepted"


def test_removed_assistant_is_absent_for_both_students_and_endpoint_is_unavailable(frontend_page):
    page, address = frontend_page
    calls = []
    page.on('request', lambda request: calls.append(request.url) if '/api/navigator' in request.url else None)
    page.goto(address)
    for index, first_name in [(0, 'Алина'), (1, 'Марк')]:
        enter_demo(page, index, first_name)
        expect(page.locator('[data-topic],.navigator-card,.navigator-answer')).to_have_count(0)
        expect(page.get_by_text('Подскажет АТЛАС', exact=True)).to_have_count(0)
        # The real authenticated server must also have no assistant operation.
        response = page.request.post(address + '/api/navigator',
                                     headers={'X-Requested-With': 'ATLAS'}, data={'topic': 'grades'})
        assert response.status == 404
        assert 'answer' not in response.json()
        leave_demo(page)
    assert calls == [], 'The client still calls the removed assistant endpoint'


def test_late_unauthorized_old_request_does_not_clear_new_session(frontend_page):
    page, address = frontend_page
    held = []

    def delay_first_notification_read(route):
        if not held:
            held.append((route, route.request.all_headers()))
        else:
            route.continue_()

    page.route(re.compile(r".*/api/notifications(?:\?.*)?$"), delay_first_notification_read)
    page.goto(address)
    enter_demo(page, 0, "Алина")
    wait_for_held_response(page, held)
    leave_demo(page)
    enter_demo(page, 1, "Марк")
    route, old_headers = held[0]
    actual_old_response = route.fetch(headers=old_headers)
    assert actual_old_response.status == 401
    route.fulfill(response=actual_old_response)
    finish_browser_tasks(page)
    expect(page.locator("#page-title")).to_contain_text("Марк")
    expect(page.locator("#login-form")).to_have_count(0)
    assert page.request.get(address + "/api/me").json()["full_name"] == "Марк Северин"


def test_delayed_dashboard_response_never_replaces_new_student_data(frontend_page):
    page, address = frontend_page
    held = []

    def delay_first_dashboard(route):
        if held:
            route.continue_()
            return
        actual = route.fetch()
        assert actual.status == 200
        assert actual.json()['profile']['full_name'] == 'Алина Ветрова'
        held.append((route, actual))

    page.route('**/api/dashboard', delay_first_dashboard)
    page.goto(address)
    page.locator("button[data-demo='0']").click()
    page.wait_for_url('**/app/home')
    wait_for_held_response(page, held)
    # The shell is usable while the first student's dashboard is loading.
    leave_demo(page)
    enter_demo(page, 1, 'Марк')
    route, actual = held[0]
    route.fulfill(response=actual)
    finish_browser_tasks(page)
    expect(page.locator('#page-title')).to_contain_text('Марк')
    expect(page.locator('#page-content')).not_to_contain_text('Алина Ветрова')
    assert page.request.get(address + '/api/me').json()['full_name'] == 'Марк Северин'


def test_ambiguous_submission_reuses_key_when_session_storage_is_blocked(frontend_page):
    page, address = frontend_page
    page.add_init_script("""
        Object.defineProperty(window, 'sessionStorage', {
            configurable: true,
            get() { throw new DOMException('Blocked for this regression', 'SecurityError'); }
        });
    """)
    page.goto(address)
    enter_demo(page, 0, "Алина")
    page.locator(".nav-stack [data-route='requests']").click()
    expect(page.locator("#page-title")).to_have_text("Заявки и справки")
    page.locator(".page-actions [data-action='new-request']").click()
    comment = "Browser lost-response regression " + uuid.uuid4().hex
    page.locator("#doc-comment").fill(comment)
    keys = []

    def drop_only_first_committed_response(route):
        if route.request.method != "POST":
            route.continue_()
            return
        keys.append(route.request.all_headers().get("idempotency-key"))
        if len(keys) == 1:
            actual = route.fetch()
            assert actual.status == 201
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/api/requests", drop_only_first_committed_response)
    page.locator("#request-form button[type='submit']").click()
    expect(page.locator("#request-error")).to_be_visible()
    expect(page.locator("#request-form button[type='submit']")).to_be_enabled()
    # Closing and reopening after an ambiguous save must preserve both the
    # draft and its submission key, even if browser storage is unavailable.
    page.locator(".modal .close-btn").click()
    page.locator(".page-actions [data-action='new-request']").click()
    expect(page.locator("#doc-comment")).to_have_value(comment)
    page.locator("#request-form button[type='submit']").click()
    expect(page.locator(".detail-summary")).to_be_visible()
    assert len(keys) == 2 and keys[0] and keys[0] == keys[1]
    rows = page.request.get(address + "/api/requests").json()
    assert sum(row["comment"] == comment for row in rows) == 1
