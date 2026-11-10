#!/bin/sh
# Runs ONCE when a fresh PostgreSQL volume is initialized by the official image.
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=ON_ERROR_STOP=1 --set=app_password="$ATLAS_APP_PASSWORD" <<'SQL'
CREATE ROLE atlas_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER DATABASE atlas OWNER TO atlas_app;
GRANT USAGE, CREATE ON SCHEMA public TO atlas_app;
SQL
