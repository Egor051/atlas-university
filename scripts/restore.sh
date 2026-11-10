#!/bin/sh
# Restore to a NEW database first; never overwrite the running atlas database.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ "$#" -ne 2 ]; then
  printf 'Usage: %s /path/to/atlas.dump atlas_restore_YYYYMMDD\n' "$0" >&2
  exit 2
fi
archive=$1
target=$2
test -f "$archive" || { printf 'Backup file not found.\n' >&2; exit 2; }
case "$target" in atlas_restore_[0-9]*) ;; *) printf 'Target must begin atlas_restore_ followed by a date.\n' >&2; exit 2;; esac
case "$target" in *[!a-zA-Z0-9_]*) printf 'Unsafe database name.\n' >&2; exit 2;; esac
docker compose exec -T db pg_restore --list < "$archive" > /dev/null
# createdb fails if the target exists. No --clean / DROP DATABASE is used.
docker compose exec -T db createdb --username=atlas_admin --owner=atlas_app "$target"
docker compose exec -T db pg_restore --username=atlas_admin --role=atlas_app --dbname="$target" --no-owner --no-privileges --exit-on-error --single-transaction < "$archive"
docker compose exec -T db psql --username=atlas_admin --dbname="$target" --command='SELECT count(*) AS requests FROM document_requests;'
printf 'Restored into %s. Running database unchanged. Inspect before a planned switch.\n' "$target"
