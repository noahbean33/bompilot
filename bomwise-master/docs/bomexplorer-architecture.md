# BOMexplorer — Application Architecture

Version 1.0 — MVP

---

## Guiding Constraints

Before the stack: the architecture must support a solo developer building an MVP. That means minimising operational complexity, using managed services where the alternative is weeks of work, and keeping the codebase in Python. Nothing exotic.

One additional constraint drives several decisions throughout this document: **the component data layer must be vendor-agnostic**. BOMexplorer must be able to switch between API providers (OEMSecrets, Nexar, FindChips, DigiKey+Mouser direct, or others) by changing a single environment variable, with no changes to application logic. Features that a given provider cannot supply are silently omitted from the UI rather than breaking it. OEMSecrets is the primary free provider, Nexar is integrated for premium tier pending pricing negotiation.

---

## Overall Structure

BOMexplorer is a three-tier web application with a background job layer for BOM monitoring.

```
Browser
  ↓
Frontend (React SPA)
  ↓
Backend API (FastAPI)
  ↓
PostgreSQL database
  ↓
Background worker (Celery + Redis)
  ↓
Provider Layer (vendor-agnostic abstraction)
  ↓
External APIs (Nexar / FindChips / DigiKey / Mouser)
```

No microservices. No message queues beyond what Celery needs. One deployable backend, one deployable frontend, one worker process.

---

## Provider Layer (Vendor-Agnostic Component Data)

This is the most architecturally significant layer in BOMexplorer. Everything above it is insulated from external API changes.

### Design principle

The rest of BOMexplorer never calls an external component API directly. It calls the provider layer, which returns a standardised internal schema regardless of which vendor is configured. Adding a new vendor, or switching vendors, requires only writing one new adapter class and updating an environment variable.

### Internal data schema

Every part result inside BOMexplorer, from any provider, conforms to this structure:

```python
# app/providers/schema.py

from pydantic import BaseModel
from datetime import datetime

class PriceBreak(BaseModel):
    quantity: int
    unit_price: float
    currency: str

class DistributorStock(BaseModel):
    distributor: str          # "digikey", "mouser", "element14", etc.
    stock: int
    url: str | None           # direct product page link

class PartResult(BaseModel):
    mpn: str
    manufacturer: str
    description: str | None
    package: str | None

    # Pricing — always a list of quantity breaks
    pricing: list[PriceBreak]

    # Stock
    stock_total: int
    distributors: list[DistributorStock]

    # Optional fields — None when provider does not supply them
    lifecycle_status: str | None      # "active", "nrnd", "eol", None
    tech_specs: dict | None           # {"voltage": "3.3V", "package": "SOIC-8"}
    datasheet_url: str | None
    similar_parts: list[str] | None   # list of MPNs

    # Metadata
    source_provider: str              # "nexar", "findchips", "digikey_mouser"
    retrieved_at: datetime
    match_type: str                   # "exact_mpn", "distributor_pn",
                                      # "parametric", "keyword"

class ProviderCapabilities(BaseModel):
    has_lifecycle_status: bool
    has_tech_specs: bool
    has_datasheet_urls: bool
    has_similar_parts: bool
    has_parametric_search: bool
    distributor_coverage: list[str]
```

### Provider interface

```python
# app/providers/base.py

from abc import ABC, abstractmethod
from .schema import PartResult, ProviderCapabilities, ParametricQuery
from app.schemas.preferences import MergedPreferences

class ComponentProvider(ABC):

    @abstractmethod
    async def search_by_mpn(
        self,
        mpn: str,
        quantity: int,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        """Exact or near-exact MPN lookup."""
        pass

    @abstractmethod
    async def search_by_distributor_pn(
        self,
        distributor: str,
        pn: str,
        quantity: int,
    ) -> list[PartResult]:
        """Lookup by distributor-specific part number."""
        pass

    @abstractmethod
    async def search_parametric(
        self,
        params: ParametricQuery,
        preferences: MergedPreferences,
    ) -> list[PartResult]:
        """Search by component specifications when no MPN is available."""
        pass

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declare what this provider can and cannot return."""
        pass
```

### Implemented providers

```python
# app/providers/nexar.py
class NexarProvider(ComponentProvider):
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=True,
            has_tech_specs=True,
            has_datasheet_urls=True,
            has_similar_parts=True,
            has_parametric_search=True,
            distributor_coverage=[
                "digikey", "mouser", "element14", "arrow",
                "rs", "avnet", "future"
            ],
        )
    # ... GraphQL client implementation

# app/providers/findchips.py
class FindChipsProvider(ComponentProvider):
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=True,
            has_tech_specs=True,
            has_datasheet_urls=True,
            has_similar_parts=False,
            has_parametric_search=True,
            distributor_coverage=["digikey", "mouser", "arrow", "avnet"],
        )
    # ... REST client implementation

# app/providers/digikey_mouser.py
class DigiKeyMouserProvider(ComponentProvider):
    """Combines DigiKey v4 and Mouser APIs directly. No aggregator."""
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            has_lifecycle_status=False,
            has_tech_specs=False,
            has_datasheet_urls=True,
            has_similar_parts=False,
            has_parametric_search=False,
            distributor_coverage=["digikey", "mouser"],
        )
    # ... parallel async calls to both APIs
```

### Provider registry

```python
# app/providers/registry.py

class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, ComponentProvider] = {}
        self._active: str | None = None

    def register(self, name: str, provider: ComponentProvider):
        self._providers[name] = provider

    def set_active(self, name: str):
        if name not in self._providers:
            raise ValueError(f"Unknown provider: {name}")
        self._active = name

    def get(self) -> ComponentProvider:
        if not self._active:
            raise RuntimeError("No active provider configured")
        return self._providers[self._active]

    def capabilities(self) -> ProviderCapabilities:
        return self.get().capabilities()

# Initialised at app startup in app/main.py
registry = ProviderRegistry()
registry.register("nexar", NexarProvider())
registry.register("findchips", FindChipsProvider())
registry.register("digikey_mouser", DigiKeyMouserProvider())
registry.set_active(settings.COMPONENT_PROVIDER)  # from .env
```

### Environment variable

```bash
# .env
COMPONENT_PROVIDER=nexar   # switch to "findchips" or "digikey_mouser" here
```

Switching providers is this one line change. No code changes required.

### Capabilities endpoint

The backend exposes provider capabilities to the frontend on login:

```
GET /api/capabilities
→ { has_lifecycle_status: true, has_tech_specs: true, ... }
```

The frontend stores this and uses it to conditionally render columns and features. A column that depends on `has_lifecycle_status` simply does not render when that field is `false`. No errors, no empty columns, no broken UI.

### Redis caching

All provider responses are cached in Redis keyed by `provider:mpn:quantity_bucket`. Default TTL: 6 hours for pricing/stock, 24 hours for specs and lifecycle (these change rarely). The cache is provider-namespaced so switching providers does not serve stale data from the previous vendor.

---

## Frontend

**Framework:** React with TypeScript
**UI library:** shadcn/ui + Tailwind CSS
**State management:** React Query for server state, Zustand for local UI state
**Build tool:** Vite

### Key views

| Route | View |
|---|---|
| `/` | Dashboard: all projects, flagged parts summary |
| `/projects/new` | New project form |
| `/projects/:id` | Project view: BOM table |
| `/projects/:id/settings` | Per-project preference overrides |
| `/projects/:id/bom/:lineId/alternatives` | Alternatives page (full page, not modal) |
| `/settings` | Global user preferences |
| `/settings/billing` | Subscription management |

### BOM table behaviour

- Virtualised rows via `@tanstack/react-virtual` — required for large BOMs
- Confidence indicators as coloured dots: green (exact MPN), amber (parametric), red (keyword/unmatched)
- Flag indicators on rows with monitoring alerts
- Padlock icon on locked rows
- Clickable rows navigate to `/alternatives` page
- Columns that depend on provider capabilities are conditionally rendered:

```typescript
// Example: lifecycle column only renders when provider supports it
const { data: capabilities } = useQuery('capabilities', fetchCapabilities)

{capabilities?.has_lifecycle_status && (
  <TableHead>Lifecycle</TableHead>
)}
```

### Alternatives page

Full-page view at `/projects/:id/bom/:lineId/alternatives`. Deep-linkable URL — can be reached directly from notification emails.

Shows:
- Header: BOM line context (reference, value, footprint)
- Currently selected part (highlighted)
- Alternatives table: MPN, manufacturer, package, price at project quantity, stock, distributors, lifecycle (if available), datasheet link (if available), Octopart redirect link
- "Use this part" button per row — writes selection, records substitution, navigates back
- "Keep current" option for acknowledged flags
- Sorting by price, stock, rank
- "In stock only" filter toggle

### File import

CSV drag-and-drop. Papa Parse runs client-side before the upload, validating column headers and providing instant feedback on a malformed file before any network round trip.

---

## Backend

**Framework:** FastAPI (Python 3.12)
**Async:** httpx for all external API calls, allowing concurrent provider queries

### API modules

```
/auth              — register, login, JWT refresh, password reset
/users             — profile, global preferences
/projects          — CRUD, settings, BOM association
/bom               — import, line items, status polling
/parts             — match, alternatives, lock/unlock
/monitoring        — flag status, acknowledgement, history
/billing           — subscription status, Paddle webhook receiver
/capabilities      — active provider capabilities (read-only)
```

### Internal services

**PartMatchingService** — central service called by BOM import, rematch requests, and the monitoring worker. Applies the matching hierarchy (exact MPN → distributor PN → parametric → keyword), calls the provider layer, applies preferences and ranking, writes results to the database. Not a route — a service class used by multiple routes and workers.

**PreferencesMerger** — merges global user preferences with per-project overrides into a flat `MergedPreferences` object. Called by PartMatchingService on every query. Project-level values take precedence; falls back to global; falls back to application defaults.

**RankingEngine** — scores and sorts candidate PartResult objects according to MergedPreferences. Applies: excluded distributor filter, lifecycle filter, grade filter, preferred manufacturer boost, price scoring, stock sufficiency check. Pure function: takes candidates and preferences, returns ordered list.

---

## Database

**PostgreSQL 16** via SQLAlchemy ORM with Alembic migrations.

### Schema

```
users
  id, email, password_hash, created_at, subscription_tier,
  email_verified_at

user_preferences
  user_id, distributor_order (jsonb), excluded_distributors (jsonb),
  preferred_manufacturers (jsonb), accept_generic_passives (bool),
  lifecycle_policy, quantity_multiplier, currency, region, grade

projects
  id, user_id, name, description, variant_tag, created_at, updated_at

project_preferences
  project_id, distributor_restriction (jsonb), quantity,
  grade, lifecycle_policy   -- null values inherit from user_preferences

bom_lines
  id, project_id, reference, value, footprint, description,
  quantity, mpn_raw, raw_fields (jsonb), match_type,
  selected_result_id (fk → part_results), pinned (bool), created_at
  -- raw_fields stores the complete original CSV row as JSON
  -- allows re-running matching against original data without re-import

part_results
  id, bom_line_id, rank, mpn, manufacturer, description, package,
  distributor, unit_price, stock, lifecycle_status (nullable),
  tech_specs (jsonb, nullable), datasheet_url (nullable),
  source_provider, match_type, retrieved_at

user_preferred_parts               -- v2 feature (favourite parts)
  id, user_id, mpn, manufacturer, added_at

part_snapshots
  id, bom_line_id, snapshot_at, stock_json (jsonb), price_json (jsonb)
  -- periodic monitoring snapshots for diff comparison

flags
  id, bom_line_id, flag_type, detail, status, created_at,
  acknowledged_at, snoozed_until
  -- flag_types: out_of_stock, low_stock, price_spike, eol, lead_time_increase
  -- status: open, watching, ignored, resolved

substitution_history
  id, bom_line_id, previous_mpn, new_mpn, reason, triggered_by,
  swapped_at
  -- reason: user_preference, out_of_stock, price, eol, flag_response
  -- triggered_by: user_manual, monitoring_flag

notification_log
  id, user_id, channel, subject, sent_at, payload (jsonb)
```

---

## Authentication

JWT-based. Short-lived access tokens (15 min), long-lived refresh tokens (30 days) in httpOnly cookies. No localStorage.

Libraries: `python-jose` for JWT, `passlib[bcrypt]` for password hashing.

Email verification on signup. Password reset via tokenised email link. Transactional email via Resend.

No OAuth for v1. Google/GitHub login is a v2 addition.

---

## Background Jobs

**Celery** with **Redis** as broker. Redis doubles as provider response cache.

### Scheduled tasks

```
monitor_boms       — nightly. Re-queries all active project BOMs via the
                     provider layer. Diffs against last part_snapshot.
                     Creates flag records for any condition changes.

send_flag_digest   — each morning. Emails users a summary of new flags
                     from the overnight run. Respects snoozed_until on
                     each flag.
```

### Triggered tasks

```
match_bom          — triggered on BOM import. Runs the full matching
                     pipeline asynchronously. Frontend polls
                     GET /bom/:id/status for progress.

rematch_line       — triggered when user requests alternatives for a
                     specific BOM line. Re-queries provider with current
                     preferences applied.
```

---

## Payments

**Paddle Billing** (not Classic). Webhook receiver at `/billing/webhook` validates Paddle signature before any database write.

Subscription tiers stored as enum in database: `free`, `solo`, `team`. Feature gates enforced server-side on every protected route.

**Events handled:** `subscription.created`, `subscription.updated`, `subscription.canceled`, `payment.succeeded`, `payment.failed`

**Export gating:**
- CSV export: all tiers including free
- Excel export: solo and team only
- Distributor order files: solo and team only

---

## File Handling

BOM import: CSV only for v1. Uploaded directly to backend, parsed in memory with Python's `csv` module, never written to disk. Max 2MB (generous for any realistic BOM). The full original CSV row is stored as JSON in `bom_lines.raw_fields` so matching can be re-run without re-import.

No object storage for v1. Add Backblaze B2 in v2 if file retention becomes needed.

---

## Deployment

### Development (local)

FastAPI dev server and Vite dev server run directly on the Linux Mint PC. PostgreSQL and Redis run as two Docker containers via `docker-compose.dev.yml`. No other containers needed for local development.

### Production (Hetzner VPS)

Single VPS, 4 vCPU / 8GB RAM minimum. All services run as Docker containers. Cloudflare in front for SSL termination and DDoS protection. Nginx serves the compiled React frontend as static files. FastAPI served by uvicorn behind Nginx.

Unraid is not involved in BOMexplorer production hosting.

### Environment variables (production additions)

```bash
COMPONENT_PROVIDER=nexar

# Nexar (if active provider)
NEXAR_CLIENT_ID=
NEXAR_CLIENT_SECRET=

# FindChips (if active provider)
FINDCHIPS_API_KEY=

# DigiKey (if active provider)
DIGIKEY_CLIENT_ID=
DIGIKEY_CLIENT_SECRET=

# Mouser (if active provider)
MOUSER_API_KEY=

# Always required
DATABASE_URL=
REDIS_URL=
SECRET_KEY=
PADDLE_WEBHOOK_SECRET=
RESEND_API_KEY=
ENVIRONMENT=production
```

---

## Security

- All API routes require JWT validation except `/auth/*` and `/billing/webhook`
- Paddle webhook validated by signature header before any DB write
- All provider API keys in environment variables only, never in code or database
- PostgreSQL and Redis bound to localhost only, not exposed externally
- Rate limiting on auth endpoints: 5 attempts per minute per IP (slowapi)
- CORS restricted to the frontend domain
- All user data queries scoped by `user_id` — cross-user data access is structurally impossible
- Provider response cache namespaced by provider name — switching providers never serves stale foreign data

---

## Development Tooling

```
uv             — Python package management
pytest         — testing, with pytest-asyncio for async routes
ruff           — linting and formatting
alembic        — database migrations
docker compose — local dev environment (postgres + redis only)
```

Frontend: Vite, ESLint, Prettier, TypeScript strict mode.

---

## Build Sequence for MVP
In this order. Items 1–4 give something demonstrable. Items 5–8 make it a real product. Items 9–10 complete the user-facing workflow.

| #   | Item                                      | Notes                                          |
|-----|-------------------------------------------|------------------------------------------------|
| 1   | Auth                                      | Register, login, JWT                           |
| 2   | Project CRUD + BOM CSV import             | Parsing, raw_fields storage                    |
| 3   | Provider layer scaffold + Nexar adapter   | Exact MPN matching only first                  |
| 4   | BOM table UI                              | Confidence indicators, capabilities-driven columns |
| 5   | Parametric matching                       | For BOM lines without MPN                      |
| 6   | User preferences + project preferences    | Global and per-project                         |
| 6b  | OEMSecrets provider adapter               | Default active provider                        |
| 7   | Celery worker + monitoring job + email    | Flags, digest emails                           |
| 7c  | Frontend UI completion                    | Preferences pages, BOM detail, variants/distributor offers page, flag acknowledgement, CSV/Excel export |
| 8   | Paddle integration + feature gates        | Subscription tiers                             |
| 9   | Alternatives page                         | Full-page UI, swap action, substitution history |
| 10  | Polish                                    | Part locking, export to distributor order files |

Note: Item 6b entails the following:
- Implement OEMSecretsProvider following the existing provider interface
- Register it in the provider registry
- Set it as the default active provider (replacing Nexar as default)
- Nexar remains in the registry but is not the default
- Tests with mocked HTTP responses

Note: Item 7c pulls forward UI work originally scoped to items 9 and 10 to
enable usability testing before Paddle integration. The alternatives/variants
page in 7c is a simplified distributor-offers view for a single BOM line.
Item 9 will extend this into the full alternatives workflow (swap action,
substitution history). Item 10 retains distributor order file export, which
is distinct from the generic CSV/Excel export delivered in 7c.

Note: Item 3 scaffolds the full provider layer architecture (base class,
registry, capabilities endpoint) even though only the Nexar adapter is
implemented. This ensures all subsequent code is written against the
abstraction, not against Nexar directly. Adding OEMSecrets, DigiKey, or
Mouser adapters later requires no changes to items 4–10.

Note: Cross-project part preference ("favourite variant") is deferred to
v2. Implementation requires a preferred_parts table (user_id, mpn,
manufacturer, distributor_name) and integration with the matching service
ranking logic so preferred distributors are prioritised in results. The
variants page (item 9) should be designed with this extension in mind —
specifically, the offer selection UI should have a clear hook for a future
"set as preferred" action without requiring a redesign.

---

## V2 Features (Out of Scope for MVP)

- Favourite parts flag on the alternatives page (cross-project part consistency)
- User-supplied API keys for their own provider account
- Google/GitHub OAuth login
- Multi-provider simultaneous query with result merging
- Simultaneous multi-BOM comparison view
- KiCad plugin for direct BOM push to BOMexplorer
- S3-compatible file storage for original BOM files
