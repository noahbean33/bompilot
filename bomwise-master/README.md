# BOMexplorer

BOM (Bill of Materials) component search and monitoring platform for electronics engineers.

Import a BOM CSV → automatic part matching against 6 component providers → track pricing, stock, and supply chain flags → find alternatives.

**Live:** _(coming soon)_ · **Docs:** [docs/](docs/) · **Progress:** [PROGRESS.md](PROGRESS.md)

---

## Features

- **Import:** Drag-and-drop CSV (Altium, KiCad, generic formats supported)
- **Matching:** Automatic MPN lookup with fallback chain across 6 providers
- **Providers:** Nexar, OEMSecrets, DigiKey, Mouser, FindChips, NextPCB
- **Monitoring:** Overnight price/stock re-query with email flag digests
- **Alternatives:** Swap parts, view substitution history, see AI-suggested candidates
- **AI Assist:** Natural language BOM queries + AI-powered copper-only part classification
- **Billing:** Free tier (single provider, 50 BOM lines/project, 3 projects) and Pro tier via Paddle
- **Admin Panel:** Provider health dashboard, user management, statistics, AI usage tracking

---

## Architecture

```
Browser → React SPA (Vite, TypeScript, Tailwind, shadcn/ui)
  → FastAPI Backend (Python 3.12, uvicorn)
    → PostgreSQL 16 (SQLAlchemy + Alembic)
    → Redis (cache, Celery broker, monthly counters)
    → Celery Worker (background tasks, email)
      → Provider Layer (6 vendor-agnostic adapters)
```

See [docs/bomexplorer-architecture.md](docs/bomexplorer-architecture.md) for full details.

---

## Quick Start

### Prerequisites

- Docker (PostgreSQL + Redis)
- Python 3.12 + [uv](https://astral.sh/uv/)
- Node.js 20 + npm

### Local Development

```bash
# Start infrastructure
docker compose -f docker-compose.dev.yml up -d

# Backend
cd backend
cp .env.example .env   # edit as needed
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Full setup guide: [docs/bomexplorer-getting-started.md](docs/bomexplorer-getting-started.md)

---

## API Modules

| Route | Description |
|---|---|
| `/auth` | Register, login, JWT refresh, password reset, email verification |
| `/users` | Profile, global preferences |
| `/projects` | CRUD, settings, BOM import, matching, export |
| `/flags` | Flag status, acknowledgement, history |
| `/providers` | Active provider capabilities |
| `/billing` | Subscription status, Paddle checkout/webhooks |
| `/admin` | Provider health, user management, statistics, AI usage |

---

## Configuration

```bash
# backend/.env
DATABASE_URL=postgresql://user:pass@localhost:5432/bomexplorer
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=replace-before-production
COMPONENT_PROVIDER=oemsecrets   # switch active provider here
PROVIDER_FALLBACK_ORDER=oemsecrets,digikey,mouser
PADDLE_API_KEY=
PADDLE_WEBHOOK_SECRET=
```

Full list in [backend/.env.example](backend/.env.example).

---

## Testing

```bash
cd backend
uv run pytest              # run all tests
uv run ruff check .         # lint
uv run ruff format .        # format
```

~305 tests passing.

---

## Docs

| File | Content |
|---|---|
| [Architecture](docs/bomexplorer-architecture.md) | Full system architecture |
| [Getting Started](docs/bomexplorer-getting-started.md) | Environment setup guide |
| [UI Feedback](docs/ui-feedback.md) | UX improvement log |
| [Decisions](docs/decisions/) | Architecture Decision Records |
| [Progress](PROGRESS.md) | Build sequence and session log |

---

## License

Proprietary. All rights reserved.