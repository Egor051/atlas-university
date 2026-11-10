"""Pull a verified database backup over SSH to a protected owner-side folder.

No private key, cookie, row or environment variable is printed. Run from a
Windows scheduled task only while this computer is available. The destination
must have owner-only permissions prepared by the operator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile


def validate_bundle(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        members = archive.getmembers()
        if len(members) != 2 or any(not member.isfile() or Path(member.name).name != member.name for member in members):
            raise ValueError('Unexpected backup bundle contents')
        dumps = [member for member in members if member.name.endswith('.dump')]
        if len(dumps) != 1:
            raise ValueError('Exactly one database dump is required')
        dump = dumps[0]
        checksum = next((member for member in members if member.name == dump.name + '.sha256'), None)
        if checksum is None:
            raise ValueError('Checksum is missing')
        digest = hashlib.sha256(archive.extractfile(dump).read()).hexdigest()
        recorded = archive.extractfile(checksum).read().decode('ascii').split()[0]
        if digest != recorded:
            raise ValueError('Database backup checksum mismatch')
        return {'dump_name': dump.name, 'dump_sha256': digest, 'dump_bytes': dump.size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    if args.host.startswith('-') or not args.key.is_file():
        parser.error('Use an existing SSH identity and a user@host destination')
    args.destination.mkdir(parents=True, exist_ok=True)
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
               '-i', str(args.key), args.host, 'sudo -n /usr/local/sbin/atlas-backup-export']
    response = subprocess.run(command, capture_output=True, timeout=180,
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if response.returncode:
        raise RuntimeError('SSH database backup export failed; no partial backup was retained')
    receipt = validate_bundle(response.stdout)
    name = receipt['dump_name'].removesuffix('.dump') + '.tar.gz'
    output = args.destination / name
    with output.open('xb') as handle:
        handle.write(response.stdout)
    receipt.update(at_utc=datetime.now(timezone.utc).isoformat(), archive=name,
                   archive_sha256=hashlib.sha256(response.stdout).hexdigest(), status='PASS')
    (args.destination / 'latest.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
