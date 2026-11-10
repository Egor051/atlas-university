#!/bin/sh
# PostgreSQL custom-format backup. Run from the project root on the server.
set -eu
umask 077
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
backup_dir=${ATLAS_BACKUP_DIR:-./backups}
mkdir -p -- "$backup_dir"
# Keep the lock inode: removing a flock file would allow a second lock inode.
command -v flock > /dev/null || { printf 'flock is required for safe backups.\n' >&2; exit 2; }
exec 9> "$backup_dir/.atlas-backup.lock"
flock -n 9 || { printf 'Another ATLAS backup is running.\n' >&2; exit 75; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
partial=$(mktemp "$backup_dir/.atlas-$stamp.XXXXXX")
checksum_partial="$partial.sha256"
suffix=${partial##*.}
destination="$backup_dir/atlas-$stamp-$suffix.dump"
published_checksum=0
published_backup=0
complete=0
cleanup() {
    result=$?
    trap - EXIT
    rm -f -- "$partial" "$checksum_partial"
    if [ "$complete" -ne 1 ]; then
        if [ "$published_checksum" -eq 1 ]; then rm -f -- "$destination.sha256"; fi
        if [ "$published_backup" -eq 1 ]; then rm -f -- "$destination"; fi
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
docker compose exec -T db pg_dump --username=atlas_admin --dbname=atlas --format=custom --no-owner --no-privileges > "$partial"
# Verify the archive can at least be decoded before retaining it.
docker compose exec -T db pg_restore --list < "$partial" > /dev/null
test -s "$partial"
digest=$(sha256sum "$partial")
digest=${digest%% *}
printf '%s  %s\n' "$digest" "$destination" > "$checksum_partial"
# Hard-link publication is atomic and refuses replacement. Publish the checksum
# first, so a visible .dump always has its complete checksum alongside it.
ln -- "$checksum_partial" "$destination.sha256"
published_checksum=1
ln -- "$partial" "$destination"
published_backup=1
complete=1
printf 'Backup verified: %s\n' "$destination"
