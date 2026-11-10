"""Recovery decisions must stay inside the owned deployment."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def load_monitor():
    spec = importlib.util.spec_from_file_location('atlas_production_monitor',
        Path(__file__).resolve().parents[1] / 'scripts' / 'production_monitor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recovery_never_restarts_healthy_or_unknown_services():
    monitor = load_monitor()
    containers = [
        {'Service': 'web', 'State': 'running', 'Health': 'healthy'},
        {'Service': 'db', 'State': 'running', 'Health': 'starting'},
        {'Service': 'other-project', 'State': 'exited', 'Health': 'unhealthy'},
    ]
    assert monitor.recovery_plan(containers) == []


def test_recovery_selects_only_failed_owned_services():
    monitor = load_monitor()
    containers = [
        {'Service': 'web', 'State': 'running', 'Health': 'unhealthy'},
        {'Service': 'db', 'State': 'exited', 'Health': ''},
        {'Service': 'caddy', 'State': 'running', 'Health': 'healthy'},
    ]
    assert monitor.recovery_plan(containers) == ['web', 'db']


def test_readiness_failure_reports_exception_type_without_sensitive_details(monkeypatch):
    monitor = load_monitor()
    def unavailable(*args, **kwargs):
        raise OSError('SENSITIVE_SENTINEL')
    monkeypatch.setattr(monitor, 'urlopen', unavailable)
    result = monitor.sample('https://campus.example.test')
    assert result['ok'] is False and result['error_type'] == 'OSError'
    assert 'SENSITIVE_SENTINEL' not in str(result)
