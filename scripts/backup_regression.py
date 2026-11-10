"""Exercise backup file publication with a fake Docker executable and no database.

Uses only a new temporary directory. Requires a POSIX shell, flock and sha256sum.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def check(script):
    with tempfile.TemporaryDirectory(prefix='atlas-backup-regression-') as directory:
        root = Path(directory)
        (root/'scripts').mkdir()
        target = root/'scripts/backup.sh'
        target.write_bytes(Path(script).read_bytes())
        tools = root/'bin'
        tools.mkdir()
        fake = tools/'docker'
        fake.write_text('''#!/bin/sh
set -eu
case "$*" in
  *pg_dump*)
    if [ "${FAKE_DUMP_FAIL:-0}" = 1 ]; then printf partial; exit 9; fi
    if [ -n "${FAKE_MARKER:-}" ]; then : > "$FAKE_MARKER"; fi
    sleep "${FAKE_DELAY:-0}"
    printf 'PGDMP synthetic %s\\n' "${FAKE_ID:-one}"
    ;;
  *pg_restore*)
    cat > "$FAKE_CAPTURE"
    test "${FAKE_RESTORE_FAIL:-0}" != 1
    ;;
  *) exit 99 ;;
esac
''', encoding='utf-8')
        (tools/'date').write_text("#!/bin/sh\nprintf '%s\\n' '20261110T000000Z'\n", encoding='utf-8')
        for file in tools.iterdir():
            file.chmod(0o755)
        backups = root/'backups'
        env = {**os.environ, 'PATH': str(tools)+os.pathsep+os.environ['PATH'],
               'ATLAS_BACKUP_DIR': str(backups), 'FAKE_CAPTURE': str(root/'restored-input')}
        def invoke(**changes):
            return subprocess.run(['sh', str(target)], env={**env, **changes}, capture_output=True, text=True, timeout=10)
        def saved():
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in backups.glob('*.dump*')}
        def verified():
            dumps = sorted(backups.glob('*.dump'))
            for dump in dumps:
                digest, name = Path(str(dump)+'.sha256').read_text().strip().split('  ', 1)
                assert name == str(dump), (name, str(dump))
                assert digest == hashlib.sha256(dump.read_bytes()).hexdigest(), dump.name
            assert not [p for p in backups.glob('.atlas-*') if p.name != '.atlas-backup.lock'], 'Partial artifacts remain'
            return len(dumps)
        first = invoke(FAKE_ID='first')
        second = invoke(FAKE_ID='second')
        assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
        assert verified() == 2, 'Same-second backups replaced a completed archive'
        before = saved()
        for failure in ({'FAKE_DUMP_FAIL': '1'}, {'FAKE_RESTORE_FAIL': '1'}):
            result = invoke(**failure)
            assert result.returncode != 0, 'Backup failure returned success'
            assert saved() == before, 'Failure changed a previously verified backup/checksum'
            verified()
        marker = root/'dump-started'
        running = subprocess.Popen(['sh', str(target)], env={**env, 'FAKE_ID': 'parallel', 'FAKE_DELAY': '1', 'FAKE_MARKER': str(marker)},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic()+5
            while not marker.exists() and running.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            assert marker.exists(), 'First writer did not enter pg_dump'
            loser = invoke(FAKE_ID='should-not-publish')
            assert loser.returncode == 75, ('Concurrent backup was not rejected', loser.returncode, loser.stderr)
            stdout, stderr = running.communicate(timeout=10)
            assert running.returncode == 0, (stdout, stderr)
        finally:
            if running.poll() is None:
                running.kill()
                running.communicate(timeout=5)
        assert verified() == 3
        assert all(saved()[name] == digest for name, digest in before.items())
        return {'status': 'PASS', 'database_calls': 0, 'verified_backups': 3,
                'checks': ['same-second unique publication', 'dump failure preserves prior hashes',
                           'restore validation failure preserves prior hashes',
                           'concurrent writer rejected', 'published checksums match', 'temporary files removed']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, default=Path(__file__).with_name('backup.sh'))
    args = parser.parse_args()
    print(json.dumps(check(args.script)))


if __name__ == '__main__':
    main()
