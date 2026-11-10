#!/bin/sh
# Root-owned helper invoked over the existing authenticated SSH connection.
# Only a freshly verified database backup is exported; env secrets stay separate.
set -eu
umask 077
cd /opt/atlas-campus
set -a
. /etc/atlas-campus/compose.env
set +a
export ATLAS_BACKUP_DIR=/var/backups/atlas-campus
sh scripts/backup.sh >&2
archive=$(find "$ATLAS_BACKUP_DIR" -maxdepth 1 -type f -name 'atlas-*.dump' -printf '%f\n' | sort | tail -n 1)
test -n "$archive"
cd "$ATLAS_BACKUP_DIR"
sha256sum -c "$archive.sha256" >&2
exec tar --create --gzip --file - "$archive" "$archive.sha256"
