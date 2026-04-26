# BOMExplorer — Infrastructure

## Production Server

| Field | Value |
|-------|-------|
| Provider | Hetzner Cloud |
| Location | Nuremberg, Germany |
| Server Type | CX22 |
| CPU | 2 vCPU |
| RAM | 4 GB |
| Storage | 40 GB SSD |
| OS | Ubuntu 23.04 |
| IP Address | 91.98.119.88 |
| SSH User | root (or ubuntu) |

## Domain & DNS

| Field | Value |
|-------|-------|
| Domain | bomexplorer.app |
| App Subdomain | app.bomexplorer.app |
| DNS Provider | Cloudflare |
| SSL Mode | Full (strict) |
| Proxy Status | Proxied (orange cloud) |

## DNS Records

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | app | 91.98.119.88 | Proxied |

## Service Architecture

```
Internet
  → Cloudflare (DNS + SSL proxy)
    → Hetzner VPS (91.98.119.88)
      → Nginx (port 443 reverse proxy)
        → Frontend (Docker, port 3000)
        → Backend API (Docker, port 8000)
          → PostgreSQL (Docker volume)
          → Redis (Docker volume)
          → Celery Worker (background tasks)
          → Celery Beat (scheduled tasks)
```

## Deployment

- **Deploy script:** `scripts/deploy.sh`
- **Docker compose:** `docker-compose.prod.yml`
- **Version tracking:** `VERSION` file + git tags

## Last Updated

- 19/04/2026 — Initial provisioning