"""Regressions for B13/B14 and P03/P04/P05; no working database is opened."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module_from(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('outcome', ['clean', 'vulnerability', 'incomplete', 'wrong-name', 'wrong-version', 'install-error', 'scanner-error', 'invalid-json', 'docker-error'])
def test_p04_audit_exit_matches_actual_scanner_result(tmp_path, outcome):
    module = module_from(ROOT/'docs/audit_runtime.py', 'audit_runtime_regression')
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        if command[0] == 'docker':
            if outcome == 'docker-error':
                raise subprocess.CalledProcessError(1, command, stderr='unavailable')
            return SimpleNamespace(returncode=0, stdout=json.dumps([['fictional-package', '1.0']]), stderr='')
        if outcome == 'install-error' and 'install' in command:
            return SimpleNamespace(returncode=1, stdout='', stderr='Fictional bootstrap installation error')
        if 'pip_audit' not in command:
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        if outcome == 'invalid-json':
            return SimpleNamespace(returncode=2, stdout='not-json', stderr='scanner failed')
        rows = [] if outcome == 'incomplete' else [{'name': 'fictional-package', 'version': '1.0',
                'vulns': [{'id': 'TEST-ONLY-ADVISORY'}] if outcome == 'vulnerability' else []}]
        if outcome == 'wrong-name':rows[0]['name'] = 'another-package'
        if outcome == 'wrong-version':rows[0]['version'] = '0.9'
        return SimpleNamespace(returncode=2 if outcome == 'scanner-error' else 1 if outcome == 'vulnerability' else 0,
                               stdout=json.dumps({'dependencies': rows}), stderr='')
    code = module.main(['--output', str(tmp_path), '--image', 'fictional:test'], runner=runner)
    report = json.loads((tmp_path/'runtime-audit.json').read_text())
    assert code == (0 if outcome == 'clean' else 1)
    assert report['status'] == ('PASS' if outcome == 'clean' else 'REVIEW')
    assert calls and report['image'] == 'fictional:test'


def test_p04_import_has_no_scan_or_report_side_effects(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Import triggered an external command')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    module_from(ROOT/'docs/audit_runtime.py', 'audit_runtime_import_regression')


def test_p05_historical_document_links_resolve():
    document = ROOT/'docs/history/process-before-3.2.md'
    links = re.findall(r'\]\(([^)]+)\)', document.read_text(encoding='utf-8'))
    local = [urlsplit(link).path for link in links if not urlsplit(link).scheme and not link.startswith('#')]
    assert len(local) == 20
    missing = [target for target in local if not (document.parent/unquote(target)).exists()]
    assert missing == []


def test_p03_current_report_dependencies_are_declared_and_importable():
    from pypdf import PdfReader
    import PIL
    import reportlab
    requirements = (ROOT/'docs/requirements-report.txt').read_text()
    assert re.search(r'^pypdf==\S+', requirements, re.M)
    assert PdfReader and PIL and reportlab


def test_b14_backup_file_protocol_without_a_database():
    if os.name != 'nt' and shutil.which('flock'):
        command = [sys.executable, str(ROOT/'scripts/backup_regression.py')]
    else:
        docker = shutil.which('docker')
        image = 'python:3.13-slim@sha256:09a17cad02668ae61ece136b4fd36ac3849e14f670ebedb637ea3e15580525bc'
        if not docker or subprocess.run([docker, 'image', 'inspect', image], capture_output=True).returncode:
            pytest.skip('POSIX flock or a locally cached isolated Linux test runtime is required')
        command = [docker, 'run', '--rm', '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,exec,size=16m',
                   '-v', str(ROOT)+':/source:ro', image, 'python', '/source/scripts/backup_regression.py']
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout+result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'PASS' and report['database_calls'] == 0 and report['verified_backups'] == 3


def test_b13_source_zip_preserves_postgres_tls_entrypoint(tmp_path):
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell:
        pytest.skip('Source packaging uses PowerShell; verified separately on Windows')
    checkout = tmp_path/'source'
    checkout.mkdir()
    for name in ('app', 'static', 'scripts', 'deploy', '.github', 'migrations'):
        shutil.copytree(ROOT/name, checkout/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix.lower() not in {'.db', '.sqlite', '.sqlite3'} and not path.name.startswith('.env'):
            shutil.copyfile(path, checkout/path.name)
    env_example = checkout/'.env.example'
    shutil.copyfile(ROOT/'.env.example', env_example)
    if os.name == 'nt':
        # Dotfiles are hidden on Linux; reproduce that provider behavior on Windows.
        subprocess.run(['attrib', '+H', str(env_example)], check=True, capture_output=True, text=True)
    (checkout/'.env').write_text('FICTIONAL_PRIVATE_ENV=must-not-be-packaged\n')
    (checkout/'.env.production').write_text('FICTIONAL_PRIVATE_ENV=must-not-be-packaged\n')
    (checkout/'docs').mkdir()
    for name in ('prepared-drive-links.json', 'credentials-fixture.json', 'private-fixture.key', 'private-fixture.dpapi'):
        (checkout/'docs'/name).write_text('FICTIONAL_PRIVATE_FIXTURE=must-not-be-packaged\n')
    result = subprocess.run([shell, '-NoProfile', '-File', str(checkout/'scripts/package.ps1'),
                             '-OutputDirectory', str(tmp_path/'dist')], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout+result.stderr
    bundle = next((tmp_path/'dist').glob('*.zip'))
    extracted = tmp_path/'extracted'
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(extracted)
        assert 'compose.improvements.yaml' in archive.namelist()
        assert 'compose.production.yaml' in archive.namelist()
        assert 'deploy/systemd/atlas-campus.service' in archive.namelist()
        assert 'atlas.db' not in archive.namelist()
        assert not any(name.startswith('docs/') for name in archive.namelist())
        assert archive.read('.env.example') == (ROOT/'.env.example').read_bytes()
        assert not any(Path(name).name.startswith('.env') and Path(name).name != '.env.example'
                       for name in archive.namelist())
    sys.path.insert(0, str(ROOT/'scripts'))
    try:
        archive_checker = module_from(ROOT/'scripts/improvement_archive.py', 'archive_bundle_regression')
        checked = archive_checker.validate_deployment_bundle(extracted)
        assert 'compose.improvements.yaml' in checked
        assert 'compose.production.yaml' in checked
        (extracted/'compose.improvements.yaml').unlink()
        with pytest.raises(ValueError, match='compose.improvements.yaml'):
            archive_checker.validate_deployment_bundle(extracted)
        with zipfile.ZipFile(bundle) as archive:
            (extracted/'compose.improvements.yaml').write_bytes(archive.read('compose.improvements.yaml'))
    finally:
        sys.path.remove(str(ROOT/'scripts'))
    # Parse the exact two-file entrypoint from the extracted bundle. No services
    # start, image is built/pulled, database is accessed or host port is changed.
    docker = shutil.which('docker')
    if docker:
        env = {**os.environ, 'DOMAIN': 'localhost', 'POSTGRES_PASSWORD': 'FictionalAdminPasswordForConfigOnly123456',
               'ATLAS_APP_PASSWORD': 'FictionalAppPasswordForConfigOnly12345678', 'DEMO_MODE': 'true'}
        compose = subprocess.run([docker, 'compose', '-f', 'compose.yaml', '-f', 'compose.improvements.yaml', 'config', '--quiet'],
                                 cwd=extracted, env=env, capture_output=True, text=True, timeout=30)
        assert compose.returncode == 0, compose.stderr
