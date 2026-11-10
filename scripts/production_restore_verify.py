"""Verify a fresh PostgreSQL backup in a new database, without overwriting atlas.

Run as the VPS administrator with /etc/atlas-campus/compose.env exported.
The full table digests before/after backup must match the restored database.
Only digests/counts, never data or credentials, enter the report.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess


def run(arguments, *, input_bytes=None):
    result = subprocess.run(arguments, capture_output=True, input=input_bytes, timeout=180)
    if result.returncode:
        raise RuntimeError('Administrative command failed: ' + arguments[0])
    return result.stdout.decode('utf-8').strip()


def sql(query, database='atlas'):
    return run(['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'atlas_admin',
                '-d', database, '-At', '-v', 'ON_ERROR_STOP=1', '-c', query])


def snapshot(database='atlas'):
    tables = sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename", database).splitlines()
    queries = []
    for table in tables:
        if not re.fullmatch('[a-z_][a-z_0-9]*', table):
            raise ValueError('Unexpected table name')
        queries.append("SELECT json_build_object('table','" + table + "','rows',count(*),'md5',md5(COALESCE(string_agg(row_to_json(t)::text, chr(10) ORDER BY row_to_json(t)::text),''))) FROM " + '"' + table + '" t')
    return {row['table']: {'rows': row['rows'], 'md5': row['md5']}
            for line in sql(' UNION ALL '.join(queries), database).splitlines() if (row := json.loads(line))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if not Path('scripts/backup.sh').is_file() or not Path('compose.yaml').is_file():
        parser.error('Run from the deployed ATLAS checkout')
    before = snapshot()
    backup_dir = Path(os.environ.get('ATLAS_BACKUP_DIR', '/var/backups/atlas-campus'))
    os.environ['ATLAS_BACKUP_DIR'] = str(backup_dir)
    run(['sh', 'scripts/backup.sh'])
    backup = max(backup_dir.glob('atlas-*.dump'), key=lambda item: item.stat().st_mtime_ns)
    run(['sha256sum', '-c', str(backup) + '.sha256'])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    target = 'atlas_restore_' + stamp
    run(['sh', 'scripts/restore.sh', str(backup), target])
    after = snapshot()
    restored = snapshot(target)
    roles = sql("SELECT json_build_object('name',rolname,'superuser',rolsuper,'createdb',rolcreatedb,'createrole',rolcreaterole,'replication',rolreplication) FROM pg_roles WHERE rolname='atlas_app'")
    report = {'at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Fresh custom-format dump restored transactionally into a NEW database; running atlas was not overwritten or deleted.',
        'backup_name': backup.name, 'restore_database': target,
        'source_stable_during_backup': before == after, 'all_tables_match': before == after == restored,
        'table_count': len(restored), 'row_count': sum(row['rows'] for row in restored.values()),
        'source_tables': before, 'restored_tables': restored, 'application_role': json.loads(roles)}
    report['status'] = 'PASS' if report['all_tables_match'] and not any(report['application_role'][key] for key in ('superuser', 'createdb', 'createrole', 'replication')) else 'FAIL'
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in {'source_tables', 'restored_tables'}}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
