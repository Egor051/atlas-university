#!/bin/bash
# Install the already reviewed checkout on the prepared Ubuntu VPS.
# Does not delete volumes, replace the private .env, or change SSH configuration.
set -euo pipefail
test "$(id -u)" = 0
root=/opt/atlas-campus
cd "$root"
test -s .env
chmod 600 .env
revision=$(git -c safe.directory="$root" rev-parse HEAD)
install -d -m 700 /etc/atlas-campus /var/lib/atlas-ops /var/log/atlas-ops /var/backups/atlas-campus
cat > /etc/atlas-campus/compose.env <<EOF
COMPOSE_FILE=$root/compose.yaml:$root/compose.production.yaml
COMPOSE_PROJECT_NAME=atlas-campus
ATLAS_RELEASE_SHA=$revision
EOF
chmod 600 /etc/atlas-campus/compose.env
set -a
. /etc/atlas-campus/compose.env
set +a
docker compose config --quiet
docker compose build web
read -r caddy_image caddy_domain < <(docker compose config --format json | python3 -c \
    'import json, sys; caddy = json.load(sys.stdin)["services"]["caddy"]; print(caddy["image"], caddy["environment"]["DOMAIN"])')
# A second Compose Caddy uses the live proxy's fixed IP. Validation only needs
# the effective config and can run in an isolated network namespace.
docker run --rm --network none --env "DOMAIN=$caddy_domain" \
    --mount "type=bind,source=$root/deploy/Caddyfile,target=/etc/caddy/Caddyfile,readonly" \
    "$caddy_image" caddy validate --config /etc/caddy/Caddyfile
docker compose up -d --wait --wait-timeout 120 db
docker compose run --rm --no-deps web python -m app.db migrate
install -m 644 deploy/systemd/atlas-* /etc/systemd/system/
install -m 750 deploy/atlas-backup-export.sh /usr/local/sbin/atlas-backup-export
cat > /etc/logrotate.d/atlas-campus <<'EOF'
/var/log/atlas-ops/*.jsonl {
    daily
    maxsize 10M
    rotate 30
    compress
    missingok
    notifempty
    copytruncate
    create 0600 root root
}
EOF
install -d -m 755 /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/atlas-campus.conf <<'EOF'
[Journal]
SystemMaxUse=200M
RuntimeMaxUse=50M
EOF
systemctl restart systemd-journald
systemctl daemon-reload
systemctl enable atlas-campus.service atlas-backup.timer atlas-monitor.timer
if systemctl is-active --quiet atlas-campus.service; then
    systemctl reload atlas-campus.service
else
    systemctl start atlas-campus.service
fi
systemctl start atlas-backup.service
systemctl start atlas-backup.timer atlas-monitor.timer
docker compose ps
printf 'Installed source revision: %s\n' "$revision"
