# BOMExplorer — State of the Union Report
*Prepared for Project Planning Meeting — 2026-04-24*

---

## 1. PRODUCT OVERVIEW

**BOMExplorer** is a BOM (Bill of Materials) component search and monitoring platform for electronics engineers.

**Value proposition:** Import a BOM CSV → automatic part matching against 6 providers → track pricing, stock, and supply chain flags → find alternatives.

**MVP Status:** All 16 build-sequence items complete. ~305 tests passing. Production-ready.

---

## 2. CURRENT SUBSCRIPTION MODEL (Pro-Only)

### Architecture
- **Payment processor:** Paddle Billing (sandbox + production)
- **Single paid tier:** "Pro" at $10/month
- **User model fields:** `plan` ("free"|"paid"), `subscription_tier` ("free"|"pro"), `subscription_status` (active|past_due|cancelled|paused), `paddle_customer_id`, `paddle_subscription_id`, `subscription_current_period_end`, `trial_ends_at`
- **Enforcement:** `get_effective_limits()` in `freemium.py` — 3-tier resolution: per-user override → platform_settings DB → .env defaults

### Current Limit Table

| Feature | Free | Pro |
|---|---|---|
| Projects | 3 | Unlimited |
| Parts per project | 50 | Unlimited |
| AI-assisted lines/month | 50 | 500 |
| AI advisor queries/month | (env default) | (env default, typically higher) |
| Provider access | Free-tier only (OEMSecrets, DigiKey, Mouser) | All providers incl. premium (Nexar) |

### Provider Tiering
- Free users restricted to free-access providers
- Pro users unlock premium providers (Nexar)
- Decision record 0002: free-tier users must see premium results are "gated" — not silently absent

### Trial Support
- `trial_ends_at` field exists on User model
- Active trials treated as paid users for enforcement purposes
- Currently not wired to any feature gate (reserved)

### Admin Controls
- Per-user limit overrides (projects, parts, AI lines, AI advisor queries)
- Global platform settings via DB (admin-editable)
- Admin panel: user management, statistics, AI usage tracking

---

## 3. EXISTING PROVIDER ECOSYSTEM

| Provider | Tier | Capabilities |
|---|---|---|
| OEMSecrets | Free | Basic MPN lookup |
| DigiKey | Free | Direct API, pricing, stock |
| Mouser | Free | Direct API, pricing, stock |
| Nexar | Premium | Lifecycle, tech specs, datasheets, similar parts, parametric search |
| FindChips | Premium | Aggregator, lifecycle, specs |
| NextPCB | Free | PCB assembly search, pricing |

**Fallback chain:** Configurable via env var (default: `oemsecrets,digikey,mouser`)

---

## 4. MAJOR FEATURES SHIPPED

1. Auth (JWT, email verification, password reset)
2. Project CRUD + CSV import (Altium, KiCad, generic)
3. Provider layer (6 adapters, vendor-agnostic)
4. BOM table with capability-driven columns
5. Parametric matching (no MPN available)
6. User + project preferences
7. Celery monitoring + email flag digests
8. Paddle billing integration
9. Alternatives page with swap + substitution history
10. Part locking, manufacturer export
11. Admin panel (provider health, stats, user management)
12. Natural language BOM assistant (Claude Haiku)
13. KiCad CSV importer fixes
14. Admin per-user limits + global settings
15. Matching fixes: unmatchable skip list, fallback chain
16. AI Assist: copper-only detection + budget management

---

## 5. TECHNICAL STACK

- **Frontend:** React + TypeScript, shadcn/ui, Tailwind, Zustand, React Query, Vite
- **Backend:** FastAPI (Python 3.12), SQLAlchemy, Alembic
- **Database:** PostgreSQL 16
- **Cache/Broker:** Redis
- **Background jobs:** Celery
- **Payments:** Paddle
- **Email:** Resend
- **AI:** Anthropic (Claude Haiku)
- **~305 tests** passing

---

## 6. OPPORTUNITY ANALYSIS FOR "PRO+" TIER

### Current Gaps & Opportunities

**A. Tier Structure**
- Currently only Free → Pro ($10/mo). No middle ground, no premium tier above Pro
- **Opportunity:** Three-tier model (Free / Pro / Enterprise) or multi-seat team plans

**B. Feature Gating Opportunities**
| Candidate Feature | Current State | Gating Potential |
|---|---|---|
| Multi-provider simultaneous query | Single active provider only | Team/Enterprise |
| KiCad plugin | Deferred to v2 | Pro+ |
| Export to distributor order files | Already shipped (Pro) | Maintain gate |
| Favourite parts (cross-project) | Deferred to v2 | Pro+ |
| Multi-BOM comparison | Deferred to v2 | Enterprise |
| Google/GitHub OAuth | Deferred to v2 | Any tier |
| S3 file storage | Deferred to v2 | Enterprise |
| Team collaboration | Not scoped | Enterprise |
| API access / tokens | Not scoped | Pro+ / Enterprise |
| Advanced analytics | Admin stats exist | Pro+ |

**C. Technical Readiness for New Tiers**
- `plan` column: currently "free"|"paid" — easily extendable to "free"|"pro"|"enterprise"
- `subscription_tier`: "free"|"pro" — extensible
- `freemium.py` limit resolution already supports per-plan defaults
- Platform settings table supports per-key per-plan configuration
- Paddle integration handles multiple price IDs (add `paddle_price_id_team_monthly`, etc.)

**D. AI Cost Considerations**
- NL queries and AI Assist both use Claude Haiku
- Free: 50 lines/mo, Pro: 500 lines/mo
- AI costs scale directly with usage — important for tier pricing

---

## 7. RECOMMENDATIONS FOR NEXT PLANNING CYCLE

1. **Define tier structure:** Decide between three-tier (Free/Pro/Team) or keep binary + trial
2. **Identify gateable features:** What new features justify each tier upgrade?
3. **Cost modeling:** AI usage, provider API costs per tier
4. **Paddle setup:** New price IDs for each tier, Paddle products catalog update
5. **Migration plan:** `plan` column and `get_effective_limits()` updates
6. **UI updates:** Billing page comparison table, upgrade prompts, tier-aware feature badges

---

## 8. KEY FILES FOR REFERENCE

| Purpose | Path |
|---|---|
| Subscription logic | `backend/app/services/freemium.py` |
| Billing API | `backend/app/api/billing.py` |
| User model | `backend/app/models/user.py` |
| Platform settings | `backend/app/models/platform_setting.py` |
| Billing page UI | `frontend/src/pages/BillingPage.tsx` |
| Decision records | `docs/decisions/` |
| Architecture | `docs/bomexplorer-architecture.md` |

---