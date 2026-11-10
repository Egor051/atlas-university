"""Audit a container runtime; REVIEW and infrastructure errors exit nonzero.

Importing this module performs no Docker calls, installation, network or writes.
"""
from __future__ import annotations
import argparse
from pathlib import Path
from datetime import datetime, timezone
import sys, subprocess, tempfile, json, re

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT/'docs/verification/improvements-2026-11-08'


def package_identity(name, version):
    # PyPI package names are case-insensitive and normalize . _ - equally.
    return re.sub(r'[-_.]+', '-', name).lower(), version


def run_audit(image, output, *, runner=subprocess.run):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Actual container Python distributions, transitive packages and bundled pip; disposable scanner.',
              'image': image, 'inventory': [], 'services': {}, 'failures': []}
    try:
        data = runner(['docker', 'run', '--rm', '--entrypoint', 'python', image, '-c',
                       "import importlib.metadata,json;print(json.dumps(sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions())))"],
                      capture_output=True, text=True, check=True, timeout=60)
        inventory = json.loads(data.stdout)
        if not inventory:
            raise ValueError('Container returned an empty package inventory')
        expected = {package_identity(name, version) for name, version in inventory}
        if len(expected) != len(inventory):
            raise ValueError('Container returned duplicate distribution identities')
        report['inventory'] = inventory
        requirements = output/'runtime-inventory.txt'
        requirements.write_text(''.join(name+'=='+version+'\n' for name, version in inventory), encoding='utf-8')
        with tempfile.TemporaryDirectory(prefix='atlas-audit-tools-') as temp:
            directory = Path(temp)/'tools'
            runner([sys.executable, '-m', 'venv', str(directory)], check=True, capture_output=True, timeout=45)
            python = directory/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            installed = runner([str(python), '-m', 'pip', 'install', '--disable-pip-version-check', 'pip==26.2.2', 'pip-audit==2.10.1'],
                               capture_output=True, text=True, timeout=240)
            if installed.returncode:
                raise RuntimeError('Scanner installation failed: '+installed.stderr[-2500:])
            for service in ('pypi', 'osv'):
                result = runner([str(python), '-m', 'pip_audit', '-r', str(requirements), '--no-deps', '--disable-pip',
                                 '--format', 'json', '--vulnerability-service', service],
                                capture_output=True, text=True, encoding='utf-8', timeout=180)
                try:
                    response = json.loads(result.stdout)
                    (output/('audit-'+service+'.json')).write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
                    dependencies = response.get('dependencies', [])
                    skipped = [row for row in dependencies if row.get('skip_reason')]
                    count = sum(len(row.get('vulns', [])) for row in dependencies)
                    audited = {package_identity(row.get('name', ''), row.get('version', '')) for row in dependencies}
                    inventory_matches = audited == expected and len(dependencies) == len(inventory)
                    report['services'][service] = {'exit_code': result.returncode, 'advisories': count,
                                                   'packages_returned': len(dependencies), 'skipped': skipped,
                                                   'inventory_matches': inventory_matches}
                    if result.returncode not in (0, 1) or skipped or not inventory_matches:
                        report['failures'].append(service+': incomplete audit')
                    if result.returncode != 0:
                        report['failures'].append(service+': scanner returned '+str(result.returncode))
                except (ValueError, TypeError, AttributeError) as exc:
                    report['failures'].append(service+': invalid scanner result ('+type(exc).__name__+')')
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, RuntimeError) as exc:
        report['failures'].append(type(exc).__name__+': '+str(exc))
    report['status'] = ('PASS' if not report['failures'] and len(report['services']) == 2
                        and all(row['advisories'] == 0 for row in report['services'].values()) else 'REVIEW')
    (output/'runtime-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main(argv=None, *, runner=subprocess.run):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='atlas-campus:improvements-check')
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = run_audit(args.image, args.output, runner=runner)
    print(json.dumps({name: report[name] for name in ('status', 'services', 'failures')}, ensure_ascii=False))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
