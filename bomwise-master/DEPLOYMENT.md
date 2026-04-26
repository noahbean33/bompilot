# BOMExplorer — Deployment Guide

This guide covers provisioning a Hetzner VPS and deploying BOMExplorer to `app.bomexplorer.app`.

---

## Prerequisites

- [Hetzner Cloud account](https://hetzner.cloud)
- Domain `bomexplorer.app` managed by [Cloudflare](https://cloudflare.com)
- Docker installed locally (for building/pushing if needed)
- SSH key registered with Hetzner

---

## 1. Provision Hetzner VPS

### Server specs
- **Location:** Nuremberg / Falkenstein / Helsinki
- **Type:** CX22 (2 vCPU, 4 GB RAM, 40 GB SSD) — €4–5/month
- **OS:** Ubuntu 24.04 LTS
- **SSH Key:** Add your public key during creation

### After creation
Note the server IP address. You will need it for DNS and SSH.

---

## 2. Configure Cloudflare DNS

In your Cloudflare dashboard for `bomexplorer.app`:

| Type | Name | Content | Proxy status |
|------|------|---------|--------------|
| A | `app` | `<VPS_IP>` | Proxied (orange cloud ON) |
| CAA | `bomexplorer.app` | `0 issue "letsencrypt.org"` | DNS only |

Cloudflare SSL mode: **Full (strict)**

With Cloudflare proxying enabled, Cloudflare handles the public SSL certificate. On the VPS you can use a **self-signed** or **Cloudflare Origin CA** certificate — neither is publicly trusted but Cloudflare validates them internally.

---

## 3. Server Setup (SSH into VPS)

```bash
ssh root@<VPS_IP>

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu   # if using ubuntu user
systemctl enable docker
systemctl start docker

# Install Git
apt install -y git

# Switch to non-root user
su - ubuntu
```

---

## 4. Clone Repository

```bash
cd ~
git clone git@github.com:futureshocked/bomwise.git
cd bomwise
```

(Or use HTTPS: `git clone https://github.com/futureshocked/bomwise.git`)

---

## 5. Generate SSL Certificate

### Option A: Self-signed (Cloudflare validates internally)

```bash
sudo mkdir -p /etc/ssl/certs /etc/ssl/private
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/ssl/private/bomexplorer.key \
  -out /etc/ssl/certs/bomexplorer.pem \
  -subj "/CN=bomexplorer.app" \
  -addext "subjectAltName=DNS:app.bomexplorer.app"
```

### Option B: Cloudflare Origin CA (recommended, 15-year validity)

1. Go to Cloudflare → SSL/TLS → Origin Server → Create Certificate
2. Add hostnames: `bomexplorer.app`, `*.bomexplorer.app`
3. Download PEM files and upload to VPS:
   ```bash
   # On VPS:
   sudo mkdir -p /etc/ssl/certs /etc/ssl/private
   # Then paste the cert and key:
   sudo nano /etc/ssl/certs/bomexplorer.pem    # paste Origin cert
   sudo nano /etc/ssl/private/bomexplorer.key   # paste Origin key
   ```

---

## 6. Install Nginx Reverse Proxy

```bash
# Install nginx
sudo apt install -y nginx

# Copy nginx config
sudo cp nginx/prod.conf /etc/nginx/sites-available/bomexplorer
sudo ln -s /etc/nginx/sites-available/bomexplorer /etc/nginx/sites-enabled/bomexplorer
sudo rm -f /etc/nginx/sites-enabled/default

# Test config
sudo nginx -t

# Enable and start
sudo systemctl enable nginx
sudo systemctl restart nginx
```

---

## 7. Configure Environment Variables

```bash
# Copy the example file
cp .env.production.example .env

# Edit with real values
nano .env
```

**Required variables to fill:**

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Long random string (`openssl rand -hex 64`) |
| `POSTGRES_PASSWORD` | Strong database password |
| `OEMSECRETS_API_KEY` | Your OEMSecrets API key |
| `SMTP_PASSWORD` | Resend.com API key |
| `EMAIL_FROM` | Verified sender address (e.g. `noreply@email.yourdomain.com`) |
| `PADDLE_API_KEY` | Paddle API key |
| `PADDLE_WEBHOOK_SECRET` | Paddle webhook secret |
| `ANTHROPIC_API_KEY` | Anthropic API key |

---

## 8. First Deploy

```bash
cd ~/bomwise
./scripts/deploy.sh
```

This will:
1. Pull latest code from GitHub
2. Build Docker images
3. Start all containers (postgres, redis, backend, celery-worker, celery-beat, frontend)
4. Run Alembic database migrations
5. Verify the backend is running

---

## 9. Create Admin User

### Option A: Via API (requires an existing admin)

Once you have one admin user, create more via the admin UI or API:

```bash
# First, get the user ID from the admin UI or:
curl -H "Authorization: Bearer <admin-token>" \
  https://app.bomexplorer.app/api/admin/users?search=email@example.com

# Then grant admin:
curl -X POST -H "Authorization: Bearer <admin-token>" \
  https://app.bomexplorer.app/api/admin/users/<user_id>/make-admin
```

### Option B: Via script (first admin, before anyone has admin)

```bash
# Pull latest code and restart
cd ~/bomwise
git pull
./scripts/deploy.sh

# Run the make_admin script inside the backend container
docker compose -f docker-compose.prod.yml exec backend \
  uv run python scripts/make_admin.py <your-email@example.com>
```

### Option C: Via psql (fallback)

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U bomexplorer \
  -c "UPDATE users SET is_admin = true WHERE email = '<your-email@example.com>';"
```

---

## 10. Verify Deployment

| Check | URL |
|-------|-----|
| Frontend | `https://app.bomexplorer.app` |
| API docs | `https://app.bomexplorer.app/api/docs` |
| Version | `https://app.bomexplorer.app/api/version` |
| Health | `https://app.bomexplorer.app/api/health` |

---

## Updating the Application

Each time you want to deploy new code:

### On your development machine:
```bash
# 1. Bump version (optional but recommended)
./scripts/bump-version.sh patch   # or minor, major

# 2. Push to GitHub
git push origin master --tags
```

### On the VPS (via SSH):
```bash
cd ~/bomwise
./scripts/deploy.sh
```

That's it. The deploy script pulls latest code, rebuilds Docker images, restarts containers, and runs migrations automatically.

---

## Rollback

```bash
cd ~/bomwise

# List available versions
git tag -l

# Checkout previous version
git checkout v1.0.0

# Rebuild and restart
docker compose -f docker-compose.prod.yml up -d --build

# If DB migration was involved, downgrade:
docker compose -f docker-compose.prod.yml exec backend \
  uv run alembic downgrade -1
```

---

## Useful Commands

| Command | Description |
|---------|-------------|
| `docker compose -f docker-compose.prod.yml ps` | List running containers |
| `docker compose -f docker-compose.prod.yml logs -f backend` | Tail backend logs |
| `docker compose -f docker-compose.prod.yml logs -f celery-worker` | Tail worker logs |
| `docker compose -f docker-compose.prod.yml exec backend bash` | Shell into backend |
| `docker compose -f docker-compose.prod.yml exec postgres psql -U bomexplorer` | Database shell |
| `docker compose -f docker-compose.prod.yml exec backend uv run alembic current` | Current Alembic migration |
| `df -h /var/lib/docker` | Check Docker disk usage |
| `docker system prune -f` | Clean up unused images |

---

## Troubleshooting

### Backend won't start
```bash
docker compose -f docker-compose.prod.yml logs backend
```
Common causes: missing `.env` variable, DB not reachable, migration failed.

### Celery worker not processing tasks
```bash
docker compose -f docker-compose.prod.yml logs celery-worker
```
Check that Redis is running and accessible:
```bash
docker compose -f docker-compose.prod.yml exec redis redis-cli ping
```

### Nginx 502 Bad Gateway
- Backend container not running → `docker compose -f docker-compose.prod.yml ps`
- Nginx config wrong → `sudo nginx -t`
- SSL cert issue → check `/etc/ssl/certs/bomexplorer.pem` and key exist

### Database migration fails
```bash
docker compose -f docker-compose.prod.yml exec backend uv run alembic current
docker compose -f docker-compose.prod.yml exec backend uv run alembic upgrade head
```

### Admin script can't find app module
```bash
# Use psql directly instead:
docker compose -f docker-compose.prod.yml exec postgres psql -U bomexplorer \
  -c "UPDATE users SET is_admin = true WHERE email = 'user@example.com';"
```

---

## Architecture

```
Internet
  → Cloudflare (DNS + SSL)
    → Hetzner VPS (app.bomexplorer.app)
      → Nginx (port 443 reverse proxy)
        → Frontend (Docker, static files on port 3000)
        → Backend API (Docker, FastAPI on port 8000)
          → PostgreSQL (Docker volume)
          → Redis (Docker volume)
          → Celery Worker (background tasks)
          → Celery Beat (scheduled tasks)
```

---

## Security Checklist

- [x] Cloudflare proxy enabled (orange cloud)
- [x] SSL certificate installed
- [x] `.env` file has strong `SECRET_KEY` and `POSTGRES_PASSWORD`
- [x] Only port 80/443 open to internet (check Hetzner firewall)
- [x] PostgreSQL and Redis NOT exposed to public IP
- [x] CORS configured for `https://app.bomexplorer.app` only (production mode)
- [ ] Rate limiting on auth endpoints (already in FastAPI config)
- [ ] Paddle webhook signature verification active
- [ ] Regular backups configured (Hetzner snapshots or manual pg_dump)

---

## Backup

### Database backup
```bash
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U bomexplorer -Fc bomexplorer > bomwise_$(date +%Y%m%d).dump
```

### Restore
```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U bomexplorer -d bomexplorer --clean < bomwise_20250101.dump
```

---

*Last updated: April 2026*