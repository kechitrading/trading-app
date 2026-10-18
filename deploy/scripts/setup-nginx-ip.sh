#!/usr/bin/env bash
# HTTPS access to the API by IP address, without a domain: nginx on 443 with a self-signed
# certificate whose subjectAltName is the server's public IP. The API itself stays bound to
# 127.0.0.1:8000. Restrict who can connect with the EC2 security group (HTTPS from your IP only).
#
# The web dashboard (kechitrading/trading-react) is served from the same origin: its deploy
# workflow puts each build in $WEB_DIR/releases/<sha> and points $WEB_DIR/current at it.
# /api, /health, /ready, /docs and /openapi.json go to the API; every other path is the dashboard.
#
# Usage (on the server, as the deploy user):   bash setup-nginx-ip.sh <PUBLIC_IP>
# Safe to re-run; the certificate is only regenerated if the IP changes or it is near expiry.
set -euo pipefail

IP="${1:?usage: setup-nginx-ip.sh <PUBLIC_IP>}"
CERT_DIR=/etc/nginx/aqta
CERT="$CERT_DIR/aqta-ip.crt"
KEY="$CERT_DIR/aqta-ip.key"
SITE=/etc/nginx/sites-available/aqta
# Outside /opt/aqta on purpose: that directory is 0750 and holds the host .env.
WEB_DIR=/var/www/aqta-webapp
DEPLOY_USER="${DEPLOY_USER:-$(id -un)}"

log() { printf '==> %s\n' "$*"; }

log "Installing nginx"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q nginx openssl >/dev/null

log "Preparing $WEB_DIR for dashboard releases (owned by $DEPLOY_USER)"
sudo install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0755 "$WEB_DIR" "$WEB_DIR/releases"
if [[ ! -e "$WEB_DIR/current" ]]; then
  # Until the first dashboard deploy, / shows a short holding page instead of a 404.
  sudo -u "$DEPLOY_USER" install -d -m 0755 "$WEB_DIR/releases/placeholder"
  echo '<!doctype html><title>AQTA</title><p>Dashboard not deployed yet. API: <a href="/health">/health</a></p>' \
    | sudo -u "$DEPLOY_USER" tee "$WEB_DIR/releases/placeholder/index.html" >/dev/null
  sudo -u "$DEPLOY_USER" ln -sfn "$WEB_DIR/releases/placeholder" "$WEB_DIR/current"
fi

sudo install -d -m 0750 "$CERT_DIR"
regen=1
if sudo test -f "$CERT"; then
  if sudo openssl x509 -in "$CERT" -noout -ext subjectAltName 2>/dev/null | grep -q "IP Address:$IP" \
     && sudo openssl x509 -in "$CERT" -noout -checkend $((30*24*3600)) >/dev/null; then
    regen=0
  fi
fi
if [[ $regen -eq 1 ]]; then
  log "Creating self-signed certificate for $IP (valid 825 days)"
  sudo openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout "$KEY" -out "$CERT" \
    -subj "/CN=$IP/O=AQTA" -addext "subjectAltName=IP:$IP" 2>/dev/null
  sudo chmod 0600 "$KEY"
fi

log "Writing nginx site"
if sudo test -f "$SITE"; then sudo cp -p "$SITE" "$SITE.bak"; fi
sudo tee "$SITE" >/dev/null <<EOF
# Managed by deploy/scripts/setup-nginx-ip.sh. Access is limited by the EC2 security group.
limit_req_zone \$binary_remote_addr zone=aqta_api:10m rate=10r/s;

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    http2 on;
    server_name _;

    ssl_certificate     $CERT;
    ssl_certificate_key $KEY;
    ssl_protocols TLSv1.2 TLSv1.3;

    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;
    server_tokens off;
    client_max_body_size 1m;

    # API, probes and API docs go to FastAPI.
    location ~ ^/(api|health|ready|docs|redoc|openapi\.json)(/|\$) {
        limit_req zone=aqta_api burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Request-ID \$request_id;
        proxy_read_timeout 30s;
    }

    # Dashboard. Hashed build assets are immutable; index.html is never cached so a deploy or
    # rollback takes effect on the next page load. nginx resolves the current symlink per request.
    root $WEB_DIR/current;

    location /assets/ {
        try_files \$uri =404;
        expires 1y;
        add_header Cache-Control "public, immutable" always;
        add_header X-Content-Type-Options nosniff always;
    }

    location / {
        try_files \$uri /index.html;
        add_header Cache-Control "no-cache" always;
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options DENY always;
        add_header Referrer-Policy no-referrer always;
        add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
    }
}
EOF
sudo ln -sf "$SITE" /etc/nginx/sites-enabled/aqta
sudo rm -f /etc/nginx/sites-enabled/default

if ! sudo nginx -t; then
  if sudo test -f "$SITE.bak"; then
    sudo mv "$SITE.bak" "$SITE"
    echo "nginx config test failed; restored the previous site file, nginx not reloaded." >&2
  fi
  exit 1
fi
sudo systemctl enable --now nginx >/dev/null 2>&1
sudo systemctl reload nginx
log "Local check through nginx:"
curl -sk "https://127.0.0.1/health" && echo
log "Local check of the dashboard root:"
curl -sk -o /dev/null -w "HTTP %{http_code}\n" "https://127.0.0.1/"
log "Done. Open https://$IP/ for the dashboard and https://$IP/health for the API (allow HTTPS from your IP in the security group)."
