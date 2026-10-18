# AWS + GitHub setup, step by step

Goal: every merge to `main` deploys AQTA (paper mode) to one EC2 server in Mumbai. Allow about an
hour. Do the parts in order. **Never paste secret values into chat, tickets or commits.**

Values to note down as you go (none of them are secrets): **AWS account ID**, **Elastic IP**,
**instance ID**.

---

## Part A: Create the secret (AWS Secrets Manager)

1. Sign in to the AWS Console. Top right, set the region to **Asia Pacific (Mumbai) ap-south-1**.
2. On your PC, generate three random values. Run this three times, in the project folder:
   ```bash
   .venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Use one each for `POSTGRES_PASSWORD`, `API_TOKEN` and `APPROVAL_SECRET`. Don't reuse your local `.env` values.
3. Open **Secrets Manager** -> **Store a new secret** -> **Other type of secret** -> **Plaintext**.
   Replace the content with the following, putting your values in place of the `<...>` parts:
   ```json
   {
     "APP_ENV": "prod",
     "DATABASE_URL": "postgresql+asyncpg://aqta:<POSTGRES_PASSWORD>@postgres:5432/aqta",
     "REDIS_URL": "redis://redis:6379/0",
     "POSTGRES_PASSWORD": "<POSTGRES_PASSWORD>",
     "API_TOKEN": "<API_TOKEN>",
     "APPROVAL_SECRET": "<APPROVAL_SECRET>",
     "TELEGRAM_BOT_TOKEN": "",
     "TELEGRAM_ALLOWED_USER_ID": ""
   }
   ```
   The same `POSTGRES_PASSWORD` value goes in two places. Keep the host `postgres` and the whole
   `REDIS_URL` exactly as shown.
4. Encryption key: leave the default (`aws/secretsmanager`). Click **Next**.
5. Secret name: **`aqta/prod`**. Click **Next** -> rotation off -> **Next** -> **Store**.

## Part B: IAM role for the server

6. Open **IAM** -> **Policies** -> **Create policy** -> **JSON** tab, and paste this (replace
   `ACCOUNT_ID` with your 12-digit account ID, shown top right under your name):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": "secretsmanager:GetSecretValue",
       "Resource": "arn:aws:secretsmanager:ap-south-1:ACCOUNT_ID:secret:aqta/prod-*"
     }]
   }
   ```
   Name it **`aqta-read-prod-secret`** -> **Create policy**.
7. Open **IAM** -> **Roles** -> **Create role**:
   - Trusted entity: **AWS service**, use case **EC2** -> **Next**.
   - Attach **`aqta-read-prod-secret`** -> **Next**.
   - Role name: **`aqta-ec2`** -> **Create role**.

## Part C: Deploy SSH key (on your PC)

8. In a terminal on your PC (outside the repo folder, so the key is never committed):
   ```bash
   ssh-keygen -t ed25519 -f aqta_deploy -N "" -C "github-deploy"
   ```
   This creates `aqta_deploy` (private, for GitHub) and `aqta_deploy.pub` (public, for the server).

## Part D: Launch the EC2 server

9. Open **EC2** -> **Launch instance**:
   - Name: **`aqta-prod`**
   - AMI: **Ubuntu Server 24.04 LTS** (64-bit x86)
   - Instance type: **t3.medium** (2 vCPU, 4 GB RAM)
   - Key pair: create one (e.g. `aqta-admin`) and download the `.pem`. This is for **you** to log in; keep it safe.
   - Network settings -> **Edit** -> create a security group named `aqta-prod-sg` with these rules:
     - SSH (22): source **My IP**. You'll widen it for GitHub in step 20.
     - HTTPS (443): source **My IP** (only needed if you add nginx later).
     - Do **not** open 5432, 6379 or 8000.
   - Storage: **30 GiB gp3**.
   - Advanced details -> **IAM instance profile**: **`aqta-ec2`**.
   - Click **Launch instance**.
10. Open **EC2** -> **Elastic IPs** -> **Allocate Elastic IP address** -> **Allocate**. Then
    **Actions** -> **Associate** -> choose `aqta-prod` -> **Associate**. Note this IP: it's your
    `DEPLOY_HOST`, and the static IP you'll register with the broker (NFR-010).

## Part E: Prepare the server

11. From your PC, log in. Windows PowerShell has `ssh` built in:
    ```bash
    ssh -i aqta-admin.pem ubuntu@<ELASTIC_IP>
    ```
    If Windows complains about the key file's permissions, right-click the `.pem` -> Properties ->
    Security, and leave only your own user with access.
12. On the server, run the setup script:
    ```bash
    curl -fsSL https://raw.githubusercontent.com/kechitrading/trading-app/main/deploy/scripts/server-setup.sh -o server-setup.sh
    bash server-setup.sh
    ```
    At the end it should print `IAM role attached` and `Secret aqta/prod is reachable`. If it
    shows a WARNING instead, recheck Part B (and step 9's IAM instance profile) or Part A.
13. Log out (`exit`) and log back in, so the `docker` group takes effect.
14. Add the GitHub deploy public key. On your PC, print `aqta_deploy.pub` and copy the single line:
    ```bash
    cat aqta_deploy.pub
    ```
    On the server:
    ```bash
    echo "<paste the line from aqta_deploy.pub>" >> ~/.ssh/authorized_keys
    ```
15. Nothing to do for image access: each deploy logs the server in to GitHub's registry with a
    short-lived token and logs out afterwards. (If you ever pull images by hand on the server, use
    `docker login ghcr.io` with a token that has only `read:packages`.)

## Part F: GitHub settings

16. Open the repo -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**, and add three secrets:
    - `DEPLOY_HOST` = the Elastic IP
    - `DEPLOY_USER` = `ubuntu`
    - `DEPLOY_SSH_KEY` = the full content of the **private** file `aqta_deploy` (including the
      `-----BEGIN OPENSSH PRIVATE KEY-----` and `-----END ...-----` lines)
17. Open the repo -> **Settings** -> **Environments** -> **New environment** -> name **`production`**.
    Optional but recommended: tick **Required reviewers** and add yourself, so each deploy waits
    for your click.

## Part G: First deploy and checks

18. Open GitHub -> **Actions** -> **Deploy** -> **Run workflow** (branch `main`, action `deploy`).
    Do this outside 08:30-23:45 IST on weekdays, or any time at the weekend.
19. If the run fails at "Deploy over SSH" with a timeout: GitHub connects from changing IP
    addresses that your "My IP" rule blocks.
20. To fix that, widen the SSH rule in `aqta-prod-sg` to `0.0.0.0/0`. Key-only login is still
    required, since Ubuntu on EC2 disables passwords. If you want port 22 closed entirely, ask for
    the AWS SSM variant of the workflow instead.
21. On the server, check:
    ```bash
    cd /opt/aqta && cat .deployed_tag
    docker compose ps
    curl -s localhost:8000/health
    curl -s localhost:8000/ready
    ```
    Expect `{"status":"ok","mode":"paper"}` and `"status":"ready"`.
22. Make the stack come back after a reboot. Docker already starts at boot and the containers use
    `restart: unless-stopped`, so a quick test is:
    ```bash
    sudo reboot
    ```
    Log in again after a minute and repeat step 21.

From now on, every merge to `main` deploys automatically (weekday merges inside trading hours wait
for 23:50 IST).

## Later / optional

- **Telegram**: put the bot token and your numeric user ID into the `aqta/prod` secret, then
  restart the app on the server so it reloads the secret:
  `cd /opt/aqta && FORCE_REDEPLOY=1 ./deploy.sh "$(cat .deployed_tag)"`
- **Browser access by IP (no domain)**: run `bash setup-nginx-ip.sh <ELASTIC_IP>` on the server
  (from `deploy/scripts/`). It installs nginx with a self-signed HTTPS certificate for the IP. In the
  security group, allow **HTTPS (443) from My IP only**. Then open `https://<ELASTIC_IP>/health` or
  `/docs`. The browser warns once ("not private") because the certificate is self-signed; choose
  Advanced -> Proceed. If your home IP changes, update the security group rule to the new "My IP".
- **Web dashboard** ([kechitrading/trading-react](https://github.com/kechitrading/trading-react)):
  the same nginx site serves it at `https://<ELASTIC_IP>/`, with `/api`, `/health`, `/ready` and
  `/docs` still going to the API. Releases live in `/var/www/aqta-webapp/releases/<sha>`, and
  `/var/www/aqta-webapp/current` points at the live one. If you ran `setup-nginx-ip.sh` before this
  was added, run it again once. The dashboard repo deploys itself; see its README.
- **Remote API access with a domain**: nginx + Let's Encrypt (`deploy/nginx/aqta.conf.example`).
- **Backups**: nightly `pg_dump` to S3; audit rows are kept for 5 years (NFR-011).
- **Broker**: register the Elastic IP with the chosen broker (Q-005, REG-001).

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Deploy run says "DEPLOY_HOST secret not set yet" | Step 16 not done |
| "Deploys are blocked 08:30-23:45 IST" | Manual run inside trading hours; wait, or use force with a reason |
| `ssh: handshake failed` / timeout | Security group (step 20) or wrong `DEPLOY_SSH_KEY` (must be the private key) |
| `denied` / `unauthorized` when pulling the image | Re-run the Deploy workflow (the per-deploy registry login failed), or check the image exists under the repo's Packages |
| `/run/aqta missing or not writable` | Step 12 not run (or run as root) |
| `AccessDeniedException` from Secrets Manager | Role not attached (step 9) or wrong account ID / region in the policy (step 6) |
| `/ready` reports database or redis down | `docker compose -f compose.prod.yml logs postgres redis` on the server |
