# Changelog

All notable changes to BOMexplorer are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Adheres to: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

## [Unreleased]

### Added
- Signup page with client-side validation
- Email verification redirect flow improvements (pending)

## [1.0.0] — 2026-04-20

Initial public release of BOMexplorer — a BOM (Bill of Materials) management platform for electronics designers and engineers.

### Added

#### Authentication & Account
- Email/password registration and login
- Email verification with JWT-based tokens and SMTP delivery
- Password reset flow (SHA-256 hashed tokens, 24h expiry, single-use)
- Change password from preferences page
- Account disabled check at login and on token validation

#### Projects & BOM Management
- Project CRUD with ownership tracking
- CSV BOM import with automatic column detection (KiCad Symbol Fields Table compatible)
- BOM auto-matching against component providers on import
- Re-match parts action per project
- Admin rematch endpoint (`POST /admin/projects/{id}/rematch`) resets non-locked no-match lines

#### BOM Table UI
- Full interactive table with column visibility toggle
- Sort by any column (reference, MPN, manufacturer, value, description, quantity, confidence, source)
- Pagination with configurable page size
- Inline editing of reference, quantity, description, value fields
- Part thumbnail column (40×40px image or fallback chip icon)
- Matched provider Source badge (shows which provider supplied the match)
- DNP (Do Not Populate) row styling (50% opacity + strikethrough pill)
- Confidence indicator pills (high match, medium match, low match, no match)
- Natural language query bar with debounced auto-query (600ms), amber row highlighting

#### Component Providers
- **Nexar** — GraphQL parametric search + MPN search (default provider)
- **OEMSecrets** — MPN search adapter
- **NextPCB** — Component search with MD5-signed API requests
- **Mouser** — MPN search + keyword search
- **DigiKey** — MPN search + keyword search with OAuth2 token caching (Redis, 3500s TTL)

#### Provider Fallback Chain
- Configurable `PROVIDER_FALLBACK_ORDER` via `.env`
- Automatic fallback on provider errors or empty results
- `matched_provider` tracking per BOM line
- Explicit MPN overrides unmatchable-value skip list

#### Parametric Matching
- Filters BOM lines against Nexar parametric search
- Supports capacitors, resistors, crystals
- Hyphen-stripped MPN fallback → keyword fallback hierarchy

#### Part Locking
- Lock/unlock individual BOM lines via row action
- Bulk Lock All / Unlock All toolbar actions
- Automated matching skips locked rows
- Monitoring service skips locked rows

#### Alternatives & Substitutions
- Variants page (Alternatives) showing rank 2+ provider results as alternative parts
- Swap-with-confirmation flow for alternative parts
- Substitution history tracking (`from_mpn` → `to_mpn` → `swapped_by`)
- Part alternatives stored automatically after every successful match

#### Preferences
- Per-user preferences: preferred suppliers, currency, component provider
- Per-project preferences: preferred suppliers (overwrite global when set)

#### AI Features
- **Natural Language BOM Assistant** — Anthropic Claude Haiku NL query bar: free-text filters parsed into JSON filter expressions (10 operators: eq, neq, lt, lte, gt, gte, contains, not_contains, is_null, is_not_null), highlight-only and filter modes, 16-field BOM schema with few-shot examples
- **AI Assist** — Claude Haiku batch classification (≤15 lines/call): detects copper-only components (no_part_needed), detects real MPNs and queries provider fallback chain (ai_suggested), budget tracking via Redis monthly counters (free=50/mo, paid=500/mo, configurable, 0=unlimited), row styling for AI-flagged lines, token usage tracking

#### Admin Panel
- Admin role via `is_admin` flag on users, `make_admin.py` CLI script
- Provider health dashboard — Redis-tracked calls/errors today, ping endpoint with real latency measurement, 60s auto-refresh
- Statistics page — total users, active users (30d proxy), total projects, avg projects/user, total BOM lines, matched lines, match rate %, provider breakdown
- User management — paginated table, case-insensitive email search, per-user detail view with project/BOM line counts
- User actions — disable/enable account, admin-initiated password reset via email
- Per-user plan/limit overrides (plan, max projects, max parts per project, AI Assist monthly lines)
- Global platform settings — free-plan max projects/parts, provider fallback order

#### Paddle Billing
- Pro monthly subscription via Paddle transaction API
- Paddle.js overlay checkout (sandbox/production support)
- Webhook handler with HMAC-SHA256 signature verification
- Subscription events: activated, updated, cancelled, past_due, paused
- Downgrade-to-free Celery task scheduled at subscription period end (with reactivation skip)
- Billing page embedded in Preferences (free tier upgrade CTA, pro tier status badge, cancel/reactivate flow)

#### Celery Workers
- Background monitoring service — per-project price/status alerts via email
- Email delivery worker — SMTP with TLS, templates for welcome/password reset/alerts
- Scheduled downgrade task via `apply_async(eta=...)`

#### Export
- Raw CSV export (UTF-8 BOM)
- Raw Excel export (openpyxl, bold headers, auto-sized columns)
- Manufacturer BOM format CSV (12-column, UTF-8 BOM)
- Manufacturer BOM format Excel (12-column)

#### Deployment
- Docker Compose configurations (dev + prod)
- Production Docker setup: postgres, redis, backend, celery-worker, celery-beat, frontend
- Production nginx reverse proxy with SPA fallback
- Cloudflare DNS configuration (proxy mode)
- Hetzner CX22 hosting deployment
- `deploy.sh` script (pull → build → migrate → restart)
- Semantic versioning system via `VERSION` file
- `bump-version.sh` script (patch/minor/major)
- Version badge in frontend footer (`v{version} ({git_short_hash})`)
- Version API endpoint (`GET /api/version`)

### Changed

- BOM import: `Refs` column recognized as alias for `reference` (KiCad compatibility)
- BOM import: `Qty` column mapped to `quantity`
- BOM import: `Exclude from BOM` and `DNP` columns set `dnp=True` on rows
- Matching: unmatchable value skip list (~25 entries: DNP, DNF, TestPoint, LED, Fiducial, MountingHole, generic primitives) — auto-classified without provider queries
- Rename: BOMwise → BOMexplorer throughout codebase, documentation, and emails
- CsvImport error handler now distinguishes `plan_limit_exceeded` from generic HTTP errors

### Fixed

- KiCad CSV: grouped references (e.g. `"U702,U703"`) stored verbatim as single reference string
- NextPCB: non-2000 API response now raises `RuntimeError` → triggers fallback chain
- Nginx: `/api/` prefix correctly stripped via `proxy_pass` trailing slash (was broken `rewrite ... break`)
- Paddle sandbox: `paddle_environment` default fixed, sandbox API key now routes to `sandbox-api.paddle.com`
- Provider error handling: HTTP 4xx responses from Mouser/DigiKey return empty result list gracefully
- Celery: `app/worker/__init__.py` re-exports Celery instance (was empty, causing import failures)

### Security

- Email verification tokens: JWT-based with configurable expiry
- Password reset tokens: SHA-256 hashed, 24h expiry, single-use, raw token never returned to client
- Account disabled check blocks login and invalidates existing sessions
- Admin self-disable prevented
- Paddle webhooks: HMAC-SHA256 signature verification prevents replay attacks
- CORS configured for production domain only in production mode

### Internal

- Alembic migrations: 19 migration scripts (users → BOM → preferences → projects → flags → locking → provider tracking → subscription → password reset → DNP → platform settings → AI assist → provider errors)
- Provider registry with auto-discovery and capability reporting
- Redis-based provider health metrics with 25h TTL
- AI token usage tracking in Redis (daily counters with TTL)
- `ComponentProvider.__init_subclass__` auto-wraps search methods for metrics tracking

---

[Unreleased]: https://github.com/futureshocked/bomwise/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/futureshocked/bomwise/releases/tag/v1.0.0