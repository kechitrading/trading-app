#!/usr/bin/env bash
# One-time setup of the AQTA production host (Ubuntu 24.04 on EC2, ap-south-1).
# Run as the deploy user (e.g. ubuntu), which needs sudo:
#   curl -fsSL https://raw.githubusercontent.com/kechitrading/trading-app/main/deploy/scripts/server-setup.sh -o server-setup.sh
#   bash server-setup.sh
# Safe to re-run. Installs Docker + compose plugin, AWS CLI v2, chrony (NFR-012), creates
# /opt/aqta, /var/lib/aqta and /run/aqta, and fetches compose.prod.yml + deploy/rollback scripts.
set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/kechitrading/trading-app/main"
DEPLOY_USER="${SUDO_USER:-$USER}"
APP_DIR=/opt/aqta

log() { printf '\n==> %s\n' "$*"; }

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as the deploy user (e.g. ubuntu), not root; the script uses sudo where needed." >&2
  exit 1
fi

log "Base packages and time sync (chrony uses the Amazon Time Sync Service)"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg unzip python3 chrony
sudo systemctl enable --now chrony

log "Docker Engine + compose plugin (official Docker repository)"
if ! command -v docker >/dev/null 2>&1; then
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo systemctl enable --now docker
sudo usermod -aG docker "$DEPLOY_USER"

log "AWS CLI v2"
if ! command -v aws >/dev/null 2>&1; then
  tmp=$(mktemp -d)
  arch=$(uname -m)  # x86_64 or aarch64
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${arch}.zip" -o "$tmp/awscliv2.zip"
  unzip -q "$tmp/awscliv2.zip" -d "$tmp"
  sudo "$tmp/aws/install" --update
  rm -rf "$tmp"
fi

log "Directories: $APP_DIR, /var/lib/aqta (data), /run/aqta (runtime secret, recreated at boot)"
sudo install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0750 "$APP_DIR"
sudo install -d -m 0755 /var/lib/aqta /var/lib/aqta/pgdata /var/lib/aqta/redis
echo "d /run/aqta 0700 $DEPLOY_USER $DEPLOY_USER -" | sudo tee /etc/tmpfiles.d/aqta.conf >/dev/null
sudo systemd-tmpfiles --create /etc/tmpfiles.d/aqta.conf

log "Fetching compose.prod.yml, deploy.sh and rollback.sh into $APP_DIR"
curl -fsSL "$REPO_RAW/deploy/compose.prod.yml" -o "$APP_DIR/compose.prod.yml"
curl -fsSL "$REPO_RAW/deploy/scripts/deploy.sh" -o "$APP_DIR/deploy.sh"
curl -fsSL "$REPO_RAW/deploy/scripts/rollback.sh" -o "$APP_DIR/rollback.sh"
chmod 0750 "$APP_DIR/deploy.sh" "$APP_DIR/rollback.sh"

log "Checks"
docker --version || true
sudo docker compose version
aws --version
if aws sts get-caller-identity --query Arn --output text >/dev/null 2>&1; then
  echo "IAM role attached: $(aws sts get-caller-identity --query Arn --output text)"
else
  echo "WARNING: no IAM role credentials found. Attach the aqta-ec2 role to this instance."
fi
if aws secretsmanager get-secret-value --region ap-south-1 --secret-id aqta/prod \
     --query Name --output text >/dev/null 2>&1; then
  echo "Secret aqta/prod is reachable."
else
  echo "WARNING: cannot read secret aqta/prod yet (create it, or fix the role policy)."
fi

cat <<EOF

Done. Next steps:
  1. Log out and back in (so the docker group applies), then run:
       docker login ghcr.io -u <your-github-username>
     and paste a GitHub token with only the read:packages scope.
  2. Make sure the GitHub deploy public key is in ~/.ssh/authorized_keys.
  3. Merge to main (outside 08:30-23:45 IST on weekdays) or run Actions -> Deploy manually.
EOF
