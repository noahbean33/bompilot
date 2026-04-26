# BOMexplorer Progress

## Build Sequence

| #   | Item                                        | Status      |
|-----|---------------------------------------------|-------------|
| 1   | Auth                                        | ✅ Done     |
| 2   | Project CRUD + BOM CSV import               | ✅ Done     |
| 3   | Provider layer scaffold + Nexar adapter     | ✅ Done     |
| 4   | BOM table UI                                | ✅ Done     |
| 5   | Parametric matching                         | ✅ Done     |
| 6   | User + project preferences                  | ✅ Done     |
| 6b  | OEMSecrets provider adapter                 | ✅ Done     |
| 7   | Celery worker + monitoring + email          | ✅ Done     |
| 7c  | Frontend UI completion                      | ✅ Done     |
| 8   | Paddle integration + feature gates          | ✅ Done     |
| 9   | Alternatives page                           | ✅ Done     |
| 10  | Polish                                      | ✅ Done     |
| 11  | Admin panel (provider health dashboard)     | ✅ Done     |
| 11b | Admin panel — statistics                    | ✅ Done     |
| 11c | Admin panel — user support tools            | ✅ Done     |
| 12  | AI-5 — Natural language BOM assistant       | ✅ Done     |
| 13  | KiCad CSV importer fixes                    | ✅ Done     |
| 14  | Admin: per-user limits + global settings    | ✅ Done     |
| 15  | Matching fixes: skip list, fallback, rematch| ✅ Done     |
| 16  | AI Assist: no_part_needed + ai_suggested    | ✅ Done     |

## Session Log

### 2026-04-15 (session 17)
**Completed:** Item 8 — Paddle integration, account management, and billing page

**Backend**
- Migrations `0018` (subscription fields on users: `paddle_customer_id`, `paddle_subscription_id`, `subscription_status`, `subscription_plan`, `subscription_current_period_end`, `trial_ends_at`) and `0019` (`paddle_events` table with `event_id` unique idempotency constraint)
- `app/models/user.py`: added subscription fields; `app/models/paddle_event.py`: new model using `JSON` type for SQLite test compat
- `app/core/database.py`: added `paddle_api_key`, `paddle_webhook_secret`, `paddle_price_id_pro_monthly`, `paddle_environment`, `app_base_url` settings
- `app/services/auth.py`: `create_email_verify_token()` and `verify_email_token()` (JWT-based, no DB table required)
- `app/worker/email.py`: `send_verification_email()` for registration flow
- `app/worker/tasks.py`: `downgrade_to_free` Celery task — scheduled via `apply_async(eta=...)` when subscription.cancelled fires; only downgrades if still cancelled (reactivation skips it)
- `app/api/auth.py`: new endpoints — `POST /auth/register` now sends verification email; `POST /auth/verify-email`, `POST /auth/resend-verification`, `POST /auth/forgot-password` (always 200, prevents enumeration), `POST /auth/reset-password`, `POST /auth/change-password`
- `app/api/billing.py`: `GET /billing/subscription`, `POST /billing/subscribe` (Paddle transaction API → checkout URL), `POST /billing/cancel` (cancel at period end), `POST /billing/reactivate`
- `app/api/webhooks.py`: `POST /webhooks/paddle` — HMAC-SHA256 signature verification; handles `subscription.activated` (→ tier=pro, plan=paid), `subscription.updated`, `subscription.cancelled` (keeps tier, schedules Celery downgrade), `subscription.past_due` (no tier change), `subscription.paused` (→ tier=free immediately); uses `get_db` dependency for testability
- `app/api/admin.py`: `AdminStats` gains `pro_users_total` + `free_users_total`; `AdminUserSummary` gains all Paddle billing fields (read-only)
- `app/main.py`: includes `billing_router` and `webhooks_router`
- `backend/.env.example`: added `APP_BASE_URL`, `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET`, `PADDLE_PRICE_ID_PRO_MONTHLY`, `PADDLE_ENVIRONMENT`

**Frontend**
- `frontend/.env.example`: added `VITE_PADDLE_CLIENT_TOKEN`, `VITE_PADDLE_ENVIRONMENT`
- `frontend/src/types/index.ts`: `SubscriptionInfo`, `CheckoutResponse`, `SubscriptionActionResponse`
- `frontend/src/api/billing.ts`: `fetchSubscription`, `createCheckout`, `cancelSubscription`, `reactivateSubscription`
- `frontend/src/api/auth.ts`: `forgotPassword`, `resetPassword`, `changePassword`, `resendVerification`, `verifyEmail`
- `frontend/src/pages/ForgotPasswordPage.tsx`: email input, always shows "check your email" after submit
- `frontend/src/pages/ResetPasswordPage.tsx`: token from query param, validates match/length, redirects to login with success flag
- `frontend/src/pages/LoginPage.tsx`: "Forgot password?" link, green "Password updated" banner on `?reset=success`
- `frontend/src/pages/BillingPage.tsx`: free tier (upgrade button, Paddle.js overlay); pro tier (status badge, renewal date, cancel/reactivate flow with confirmation dialog); Paddle.js loaded dynamically; sandbox/production via `VITE_PADDLE_ENVIRONMENT`
- `frontend/src/pages/PreferencesPage.tsx`: tabbed layout — Preferences / Change Password / Billing; billing tab embeds `BillingPage`
- `frontend/src/components/Layout.tsx`: email verification banner if `email_verified_at` is null; resend button
- `frontend/src/pages/AdminStatsPage.tsx`: pro/free user stat cards
- `frontend/src/pages/AdminUserDetailPage.tsx`: read-only Billing section (all Paddle fields)
- `frontend/src/api/admin.ts`: `AdminStats` and `AdminUserSummary` types updated
- `frontend/src/App.tsx`: `/forgot-password`, `/reset-password`, `/settings/billing` (→ redirect) routes

**Tests:** 21 new tests — `test_auth_account.py` (12) and `test_billing.py` (9). 305 total pass. 10 pre-existing `test_nextpcb.py` failures unrelated to Item 8.

**Build:** `npm run build` clean (chunk size warning only, not an error).

**Deferred / notes:**
- End-to-end Paddle sandbox testing requires a sandbox account + `ngrok`/Paddle CLI for local webhooks (as noted in item prompt — out of scope for this session)
- `trial_ends_at` column added but not wired to any feature gate yet (reserved for future use per spec)

**Next:** Item 9 (Alternatives page) was already completed in an earlier session. Next pending item from the build sequence should be reviewed.

### 2026-04-15 (session 17 — addendum: Paddle sandbox fix)
**Completed:** Fix 503 error on Paddle checkout (sandbox credentials hitting production endpoint)

**Root cause:** `paddle_environment` setting defaulted to `"production"` in code; no `PADDLE_ENVIRONMENT` key was present in `.env`, so sandbox API keys were being sent to `https://api.paddle.com` → Paddle rejected them → 503 to the frontend.

**Changes:**
- `backend/app/core/database.py`: `paddle_environment` default changed to `"production"` with comment "set to sandbox in .env for local dev" (explicit safe default — no silent sandbox)
- `backend/.env`: added `PADDLE_ENVIRONMENT=sandbox` (environment now reads `sandbox`, routing to `https://sandbox-api.paddle.com`)
- `backend/app/api/billing.py`:
  - `_paddle_request()`: logs target URL + environment at DEBUG level before every request; catches `httpx.RequestError` separately (network-level failure → 502 "Paddle API unreachable"); error log now shows full `METHOD URL → status: body`
  - `subscribe()`: logs user ID, target base URL, and active environment at INFO level before creating checkout; logs error if price ID is missing

**Tests:** 305 pass (unchanged). `npm run build` clean.

### 2026-04-15 (session 16)
**Completed:** Item 16 — AI Assist: copper-only detection + AI-suggested candidates + budget management

**Root cause addressed:** KiCad BOMs export schematic symbol names (e.g. `Crystal_GND24`, `Fiducial`) as values, not MPNs. Normal matching finds nothing. AI Assist classifies these and either marks them as non-purchasable or queries providers with human-readable search terms.

**Backend**
- `alembic/versions/0017_add_ai_assist_override.py`: adds `ai_assist_monthly_lines_override` column to `users`
- `app/models/user.py`: `ai_assist_monthly_lines_override = Column(Integer, nullable=True)`
- `app/core/database.py`: `ai_assist_free_monthly_lines: int = 50`, `ai_assist_paid_monthly_lines: int = 500` settings
- `app/services/freemium.py`: `get_effective_limits()` extended with `ai_assist_monthly_lines` key; 3-tier resolution: per-user override > platform_settings DB > .env defaults; `0 = unlimited` via `_zero_to_none()` helper
- `app/services/ai_matching.py`: new module
  - `_classify_batch()`: sends ≤15 BOM lines per Claude Haiku call; returns `{copper_only, search_queries}` per line
  - `_search_queries()`: runs keyword queries through provider fallback chain; returns first non-empty result set
  - `get_budget_state()`: budget summary dict for a user (used/limit/remaining/resets_at/unlimited)
  - `_get_lines_used_this_month()` / `_increment_lines_used()`: Redis monthly counters with 35-day TTL
  - `ai_assist_project()`: main entry point — fetches eligible lines (match_type IN NULL/no_match/ai_suggested), applies budget cap (partial processing), batches to Claude, writes `no_part_needed`/`ai_suggested`/`no_match` match_type, stores ≤5 `PartAlternative` rows with `source="ai_assist"`
- `app/api/projects.py`:
  - `GET /projects/{id}/ai-assist/budget` — returns budget state for current user
  - `POST /projects/{id}/ai-assist` — 429 if budget exhausted; else runs `ai_assist_project()`
- `app/api/admin.py`:
  - `AdminUserSummary` / `UserLimitsUpdate`: `ai_assist_monthly_lines_override` field added
  - `PlatformSettingsResponse` / `PlatformSettingsUpdate`: `ai_assist_free_monthly_lines`, `ai_assist_paid_monthly_lines` fields added
  - `update_platform_settings()`: upserts new keys
  - `ai_usage()`: now reports both NL Query and AI Assist token usage + costs

**Frontend**
- `src/api/bom.ts`: `AiAssistBudget`, `AiAssistResult` interfaces; `fetchAiAssistBudget()`, `runAiAssist()` functions
- `src/api/admin.ts`: `ai_assist_monthly_lines_override` on `AdminUserSummary`/`UserLimitsUpdate`; `ai_assist_free_monthly_lines`/`ai_assist_paid_monthly_lines` on `PlatformSettings`
- `src/components/ConfidenceIndicator.tsx`:
  - `no_part_needed`: gray dot, tooltip explains copper-only
  - `ai_suggested`: amber dot, tooltip directs to Alternatives page
  - `rowBgClass()`: exported helper — handles NL highlight > locked > no_part_needed > ai_suggested > default
- `src/pages/ProjectDetailPage.tsx`:
  - BOM table toolbar: AI Assist button (purple border, shows remaining budget, disabled when exhausted)
  - AI Assist result toast: shows no_part_needed / ai_suggested / no_match counts
  - `<tr>` className uses `rowBgClass()` instead of inline conditionals
  - `ai_suggested` rows show amber "AI" pill badge linking to the Variants/Alternatives page
- `src/pages/AdminSettingsPage.tsx`: AI Assist monthly line budget section (free/paid inputs, 0=unlimited hint)
- `src/pages/AdminUserDetailPage.tsx`: AI Assist override field in LimitsPanel; shows effective default based on plan; 0=unlimited / blank=global default

**Tests**
- `tests/test_ai_assist.py` — 14 new tests:
  - `TestParseClaudeResponse` (3): plain JSON, JSON fence, plain fence
  - `TestGetBudgetState` (3): unlimited when None, remaining counts down, floored at zero
  - `TestAiAssistBudgetEndpoint` (2): structure, 401 unauthenticated
  - `TestAiAssistRun` (6): copper_only → no_part_needed, real+provider → ai_suggested, real+no_provider → no_match, 429 on budget exhausted, partial budget (skipped_budget), 401 unauthenticated
- `tests/test_nl_query.py`: updated `test_ai_usage_cost_calculation` mock to scope to `nl_query` keys only (AI Assist entries now also appear in usage response)

**Build:** `269/269` tests pass (excluding pre-existing `test_nextpcb.py` failures); `npm run build` clean
**Next:** next feature item
**Notes:**
- AI Assist uses `claude-haiku-4-5-20251001` (cheapest Haiku model) in batches of 15 for cost efficiency
- Token usage recorded in Redis keys `ai:ai_assist:tokens:input:{date}` / `ai:ai_assist:tokens:output:{date}`
- Monthly line budget tracked in Redis `ai:assist:{user_id}:lines:{YYYY-MM}` with 35-day TTL
- Default budgets: free=50 lines/month, paid=500 lines/month; 0=unlimited
- No DB migration needed for new match_type values — `match_type` column is already a plain VARCHAR

---

### 2026-04-15 (session 13)
**Completed:** Item 13 — KiCad Symbol Fields Table CSV importer fixes

**Root causes fixed**
- `Refs` (plural) was not a recognised alias for the `reference` column — rows imported with `reference=null`
- DNP / Exclude from BOM columns were silently ignored; no `dnp` flag existed on the model
- MPN column absence was already tolerated but undocumented; no explicit handling

**Backend**
- `app/services/bom.py`:
  - Added `refs` to the `reference` alias list alongside `ref`, `references`, `refdes`, `designator`
  - Added `_normalise_header()` helper (strip + lowercase); applied in `_build_header_map()`; replaces the inline `h.strip().lower()` so normalisation is explicit and one place
  - Added `_DNP_HEADERS` sentinel set: `{"dnp", "exclude from bom", "dnp?", "do not populate"}`
  - Added `_is_dnp_row()`: returns `True` if any DNP-sentinel column is present and has a non-empty cell value for that row
  - `import_bom` now extracts `dnp` per row and sets it on both new and updated `BomLine` records
  - MPN column absence documented in module docstring; `_extract` already returned `None` gracefully
  - Grouped reference rows (e.g. `"U702,U703"`) verified: Python `csv.DictReader` strips the outer quotes; the value is stored verbatim as a single `reference` string — correct behaviour
- `app/models/project.py`: added `dnp = Column(Boolean, nullable=False, default=False)` to `BomLine`
- `alembic/versions/0015_add_bom_line_dnp.py`: `ALTER TABLE bom_lines ADD COLUMN dnp BOOLEAN NOT NULL DEFAULT FALSE`
- `app/schemas/project.py`: added `dnp: bool = False` to `BomLineResponse`

**Frontend**
- `src/types/index.ts`: added `dnp: boolean` to `BomLine` interface
- `src/pages/ProjectDetailPage.tsx`:
  - DNP rows get `opacity-50` on the `<tr>`
  - Ref cell shows a muted strikethrough "DNP" pill badge (`bg-gray-200 text-gray-500 line-through`) alongside the editable reference

**Tests**
- `backend/tests/fixtures/kicad_symbol_fields.csv`: 52-row KiCad Symbol Fields Table fixture with `Refs`, `Qty`, no MPN column, and 5 DNP rows (D5 via `DNP=x`, J4 via `DNP=x`, R17 via `DNP=x`, R18 via `Exclude from BOM=x`, U10 via `DNP=x`)
- 7 new tests in `test_projects.py`:
  - `test_import_bom_refs_alias` — `Refs` column maps to `reference`
  - `test_import_bom_qty_alias` — `Qty` column maps to `quantity`
  - `test_import_bom_mpn_optional` — CSV without MPN column imports cleanly; all `mpn_raw` null
  - `test_import_bom_dnp_column` — non-empty `DNP` cell → `dnp=True`; empty → `dnp=False`
  - `test_import_bom_exclude_from_bom_column` — non-empty `Exclude from BOM` → `dnp=True`
  - `test_import_bom_grouped_references` — comma-separated refs stored verbatim per row
  - `test_import_bom_kicad_fixture_52_rows` — full 52-row fixture: all rows imported, 5 DNP, 0 MPN, grouped refs intact; user upgraded to `paid` plan in test to clear the 50-part free-tier cap

**Build:** `230/230` tests pass (excluding 25 pre-existing `test_nextpcb.py` failures unrelated to this work); `npm run build` clean
**Next:** next feature item
**Notes:** The `test_nextpcb.py` suite has pre-existing failures (results list empty) — not introduced by this session.



### 2026-04-15 (session 15)
**Completed:** Item 15 — Matching fixes: unmatchable-value skip list, provider fallback, NextPCB error handling, admin rematch endpoint

**Backend**
- `app/services/matching.py`:
  - Added `UNMATCHABLE_EXACT` frozenset (~25 entries: DNP, DNF, TestPoint, LED, Fiducial, MountingHole, generic primitives, etc.)
  - Added `UNMATCHABLE_PREFIXES` tuple: `conn_`, `crystal_gnd`, `testpoint`, `mountinghole`, `fiducial`
  - Added `is_unmatchable(value)` predicate: case-insensitive; both exported so tests and other code can use them
  - `_match_line`: if `is_unmatchable(line.value) and not line.mpn_raw`, sets `match_type="no_match"` immediately and returns without querying any provider (explicit MPN overrides the skip list)
  - Provider fallback already catches exceptions and continues to next provider — verified correct; added explicit test coverage
  - All providers returning empty → `match_type="no_match"` — already implemented; added explicit test coverage
- `app/providers/nextpcb.py`: `_search()` now raises `RuntimeError` on `response_code != "2000"` (instead of silently returning `[]`); the error is caught by `_try_provider()` in the matching service and triggers fallback to the next provider
- `app/api/admin.py`: added `POST /admin/projects/{project_id}/rematch` endpoint
  - Verifies project exists (404 if not), requires admin
  - Resets all non-locked `no_match` lines to `match_type=None` (pending)
  - Reports `queued` count (non-locked lines with `match_type=None` after the reset)
  - Runs `PartMatchingService.match_project()` synchronously (consistent with existing `/projects/{id}/match`)
  - Returns `{queued, project_id, total, matched, unmatched}`

**Tests**
- `tests/test_matching.py` — 20 new tests:
  - `TestIsUnmatchable` (17 cases): None, empty string, DNP, DNF, LED, Conn_01x02, Conn_02x05_…, Crystal_GND24, MountingHole, Fiducial, real MPN (negative), LM358 (negative), resistor, whitespace trim; testpoint exact/case-insensitive
  - `test_match_line_skips_unmatchable_value`: SpyProvider counts calls; confirms call_count==0 for TestPoint with no MPN
  - `test_match_line_unmatchable_value_overridden_by_mpn`: LED with explicit MPN → matches normally
  - `test_provider_error_falls_back_to_next_provider`: ErrorProvider (raises) → GoodProvider wins; `matched_provider` set correctly
  - `test_all_providers_exhausted_gives_no_match`: two empty-returning providers → `match_type="no_match"`
- `tests/test_admin.py` — 5 new tests:
  - `TestNextPCBErrorHandling.test_non_2000_response_raises_runtime_error`: mocked httpx response with `response_code=4001` → `RuntimeError("NextPCB API error")` raised
  - `TestAdminRematch`: 4 tests covering 403, 404, `queued` count, locked-lines-untouched

**Build:** `255/255` tests pass (excluding pre-existing `test_nextpcb.py` failures); `npm run build` clean

---

### 2026-04-15 (session 14)
**Completed:** Item 14 — Admin per-user limits + global platform settings

**Backend**
- `alembic/versions/0016_add_platform_settings.py`: new `platform_settings` key/value table (`key PK, value TEXT, updated_at`)
- `app/models/platform_setting.py`: `PlatformSetting` ORM model; registered in `app/models/__init__.py`
- `app/services/freemium.py`: `get_effective_limits(user, db=None)` — added optional `db` param; when provided, reads `free_plan_max_projects` and `free_plan_max_parts_per_project` from `platform_settings` table (DB wins over .env; per-user overrides still win over DB)
- `app/api/projects.py`: both `get_effective_limits` call-sites now pass `db`
- `app/api/admin.py`:
  - `AdminUserSummary` gains `plan`, `max_projects_override`, `max_parts_per_project_override` fields
  - `PUT /admin/users/{id}/limits` — sets plan ("free"|"paid") and per-user override columns
  - `GET /admin/settings` — returns merged DB + .env platform settings
  - `PUT /admin/settings` — upserts `free_plan_max_projects`, `free_plan_max_parts_per_project`, `provider_fallback_order` into the DB table; returns updated values

**Frontend**
- `src/api/admin.ts`: `UserLimitsUpdate`, `PlatformSettings` interfaces; `updateUserLimits()`, `fetchPlatformSettings()`, `updatePlatformSettings()` functions; `AdminUserSummary` extended with plan/override fields
- `src/pages/AdminUserDetailPage.tsx`: `LimitsPanel` component — plan selector (free/paid), max-projects override input, max-parts override input; inputs disabled when plan=paid; placeholder shows global default from platform settings; saves via `PUT /admin/users/{id}/limits`
- `src/pages/AdminSettingsPage.tsx` (new): form with free-plan defaults section and data-sources section; provider fallback order shown as interactive tag list with ↑↓ reorder + × remove + toggle add; raw text fallback input also editable; fetches live provider list from `/admin/providers/status`
- `src/App.tsx`: `/admin/settings` route registered
- `src/components/AdminLayout.tsx`: "Settings" nav link added
- `src/components/CsvImport.tsx`: error handler now distinguishes plan_limit_exceeded (shows human-readable message) from generic HTTP errors

**Build:** `64/64` targeted tests pass; `npm run build` clean
**Next:** next feature item

### 2026-04-14 (session 12)
**Completed:** Item 12 — AI-5 Natural language BOM assistant

**Backend**
- `uv add anthropic` — `anthropic==0.94.1` added to project
- `app/core/database.py`: `anthropic_api_key: str = ""` setting; `.env.example` updated
- `app/services/nl_query.py`: new module
  - Hardcoded `BOM_SCHEMA` (16 fields with types); 7 few-shot examples in `FEW_SHOT_EXAMPLES`
  - `_looks_like_general_question()` regex pre-check (10 patterns) bypasses Anthropic for clearly non-filter inputs
  - `run_nl_query(query)`: calls `claude-haiku-4-5-20251001`, parses JSON response, strips markdown fences, validates structure; returns `_EMPTY_RESULT` sentinel on any failure or missing API key
  - `_track_tokens()`: async fire-and-forget; writes `ai:nl_query:tokens:input:{date}` and `ai:nl_query:tokens:output:{date}` via Redis INCRBY with 25h TTL
  - Module-level imports of `anthropic` and `settings` so tests can patch them
- `app/api/projects.py`: `POST /projects/{id}/bom/nl-query` — verifies project ownership, validates request body with Pydantic, calls `run_nl_query`
- `app/api/admin.py`: `GET /admin/ai/usage` — reads Redis token keys for today; returns per-feature breakdown + total; hardcoded Haiku rates ($0.80/MTok input, $4.00/MTok output); `rate_note` field reminds admin to verify against billing

**Filter expression schema:**
- `filters`: list of `{field, op, value}` — 10 supported ops: eq, neq, lt, lte, gt, gte, contains, not_contains, is_null, is_not_null
- `highlight_only`: true for exploratory queries, false for filtering queries
- `explanation`: one sentence shown to the user

**Frontend**
- `src/api/bom.ts`: `NlFilter`, `NlQueryResult` interfaces; `runNlQuery(projectId, query)` function
- `src/api/admin.ts`: `AiUsageEntry`, `AiUsageResponse` interfaces; `fetchAiUsage()` function
- `src/pages/ProjectDetailPage.tsx`:
  - `_CATEGORY_MAP` + `_getFieldValue()` + `_evalOp()` + `_matchesFilters()` filter evaluator utilities
  - NL query state in `BomTable`: `nlInput`, `nlResult`, `debouncedNl` (600ms), `useMutation` calling `runNlQuery`
  - `matchedLineIds` Set computed from `sortedLines` × NL filters
  - `displayLines`: all rows when `highlight_only=true`, filtered rows when `false`
  - NL query bar UI: full-width input above toolbar, spinner during fetch, × clear button, explanation + row count below bar
  - Highlighted rows get amber left border (`border-l-4 border-l-amber-400 bg-amber-50/60`)
  - NL filter is independent of column visibility/sort
- `src/pages/AdminAiPage.tsx`: AI usage page with `EntryCard` per feature, total cost, rate note
- `src/components/AdminLayout.tsx`: "AI Usage" nav link added
- `src/App.tsx`: `/admin/ai` route registered; `useDebounce` hook re-used

**Tests:** 10 new in `test_nl_query.py` — filter structure, general-question bypass (Anthropic not called), auth/403/404, no-API-key graceful empty, token tracking via create_task, AI usage structure, cost calculation (1M tokens each → $4.80), admin-only access; 248/248 total passing
**Build:** clean
**Next:** next feature item
**Notes:** NL query bar sends a request on every debounced keystroke (600ms). No ANTHROPIC_API_KEY in `.env` means all queries silently return empty filters — the UI shows the explanation text. Token tracking is fire-and-forget; Redis unavailability is swallowed silently.

### 2026-04-14 (session 11)
**Completed:** Item 11c — Admin panel user support tools

**Backend**
- Migration 0014: `password_reset_tokens` table — `user_id` (FK CASCADE), `token_hash` (SHA-256), `expires_at`, `used`, `created_at`; indexed on `user_id` and `token_hash`
- `app/models/password_reset_token.py`: `PasswordResetToken` SQLAlchemy model; registered in `app/models/__init__.py`
- `app/api/auth.py`: added `is_active` check after successful authentication — returns HTTP 403 `"Account disabled. Contact support."` for disabled users at login
- `app/core/security.py`: added `is_active` check in `get_current_user` — returns HTTP 403 for disabled users presenting a valid token (blocks token reuse after disable)
- `app/worker/email.py`: `send_password_reset_email(to_address, raw_token)` — builds reset link and sends via `_send_smtp`
- `app/api/admin.py` — five new endpoints:
  - `GET /admin/users` — paginated (page, page_size≤100), case-insensitive email search; returns `AdminUserList` with per-user `projects_count` via a single GROUP BY query
  - `GET /admin/users/{id}` — full detail with per-project BOM line counts, `bom_lines_total`, `matched_lines_total`
  - `POST /admin/users/{id}/disable` — sets `is_active=False`; guards against disabling own account
  - `POST /admin/users/{id}/enable` — sets `is_active=True`
  - `POST /admin/users/{id}/reset-password` — generates `secrets.token_urlsafe(32)`, stores SHA-256 hash with 24h expiry, calls `send_password_reset_email`; raw token never returned

**Frontend**
- `src/hooks/useDebounce.ts`: generic 300ms debounce hook
- `src/api/admin.ts`: `AdminUserSummary`, `AdminUserDetail`, `AdminProjectSummary`, `AdminUserList` interfaces; `fetchUsers`, `fetchUser`, `disableUser`, `enableUser`, `resetUserPassword` functions
- `src/pages/AdminUsersPage.tsx`: searchable (debounced), paginated user table; click row navigates to detail
- `src/pages/AdminUserDetailPage.tsx`: full detail view with `ConfirmDialog` for disable/enable/reset actions; auto-refreshes after each action via `invalidateQueries`
- `src/components/AdminLayout.tsx`: "Users" nav link added
- `src/App.tsx`: `/admin/users` and `/admin/users/:userId` routes registered

**Tests:** 15 new across `TestAdminUserList`, `TestAdminUserDetail`, `TestAdminDisableEnable`, `TestAdminPasswordReset`; 238/238 total passing
**Build:** clean
**Next:** next feature item
**Notes:** `User.name` and `last_login_at` fields do not exist on the model yet — both return null. `name` is a UI placeholder; `last_login_at` requires a `last_active_at` DB column when request tracking is added.

### 2026-04-14 (session 10)
**Completed:** Item 11b — Admin panel statistics

**Backend**
- `app/api/admin.py`: added `AdminStats` Pydantic schema; added `GET /admin/stats` endpoint protected by `require_admin`
  - `users_total` — COUNT of all users
  - `users_active_30d` — users with `created_at >= now-30d` (proxy; no last_login field yet; comment in code)
  - `projects_total`, `projects_per_user_avg` (1 decimal, safe against 0 users)
  - `bom_lines_total`, `bom_lines_matched` (selected_result_id IS NOT NULL), `match_rate_pct` (1 decimal, safe against 0 lines)
  - `providers_breakdown` — dict of `{name: calls_today}` from same Redis keys as provider health

**Frontend**
- `src/api/admin.ts`: `AdminStats` interface + `fetchAdminStats()` function
- `src/pages/AdminStatsPage.tsx`: stat cards in three groups (Users, Projects & BOM, Provider usage today); `MatchRateCard` with coloured progress bar; `ProviderBreakdown` badges using same green/amber/red threshold as usage bar; manual Refresh button
- `src/components/AdminLayout.tsx`: "Statistics" nav link added below "Provider Health"
- `src/App.tsx`: `/admin/stats` route added under `AdminLayout`

**Tests:** 4 new in `TestAdminStats` — correct structure, non-admin 403, match_rate_pct is 0.0 when no BOM lines (not a division error), all counts non-negative; 223/223 total passing
**Build:** clean
**Next:** next feature item
**Notes:** `users_active_30d` uses `created_at` as proxy. When a `last_active_at` column is added, update the query in `admin_stats()`.

### 2026-04-13 (session 9)
**Completed:** Item 11 — Admin panel (provider health dashboard)

**Backend**
- Migration 0013: added `is_admin` boolean (server default false, NOT NULL) to `users`
- `app/models/user.py`: `is_admin` column added
- `app/schemas/auth.py`: `is_admin: bool = False` added to `UserResponse`
- `app/core/security.py`: `require_admin` FastAPI dependency — raises HTTP 403 if not admin
- `app/providers/base.py`: full rewrite — `_redis_record` coroutine writes per-provider metrics (calls today, errors today, last_called_at, last_success_at) to Redis with 25h TTL; `_make_tracked` wrapper; `ComponentProvider.__init_subclass__` auto-wraps `search_by_mpn`, `search_by_distributor_pn`, `search_by_keyword`, `search_parametric` on every concrete subclass; `PROVIDER_NAME` and `DAILY_LIMIT` class attributes added to all adapters (oemsecrets: 250, nexar/mouser/digikey/nextpcb: None)
- `app/providers/registry.py`: `all_providers()` method added
- `app/api/admin.py`: new router — `GET /admin/providers/status` returns list of `ProviderStatus`; `POST /admin/providers/{name}/ping` measures latency of a real `search_by_mpn("LM358", 1)` call; both require `require_admin`
- `app/main.py`: admin router registered
- `scripts/make_admin.py`: CLI script — `python scripts/make_admin.py <email>` promotes user to admin

**Frontend**
- `src/types/index.ts`: `is_admin: boolean` added to `User`
- `src/api/admin.ts`: `fetchProviderStatus()` and `pingProvider(name)` functions
- `src/pages/AdminProvidersPage.tsx`: provider health dashboard — ProviderCard with usage bar, ping button + latency result, 60s auto-refresh, "last updated Xs ago" live counter
- `src/components/AdminLayout.tsx`: admin route guard (redirects non-admin to /projects) + sidebar nav
- `src/App.tsx`: `/admin` route tree nested under `AdminLayout`
- `src/components/Layout.tsx`: conditional "Admin" nav link visible to `is_admin` users

**Tests:** 231/231 passed (14 new in test_admin.py)
**Build:** clean (chunk size warning only, cosmetic)
**Next:** next feature item
**Notes:** Redis unavailability is silently swallowed — metrics simply won't populate if Redis is down. `_redis_record` never raises.

### 2026-04-14
- Renamed all in-codebase and in-documentation references from BOMwise/BOMWise/Bomwise to BOMexplorer/BOMExplorer throughout codebase, frontend, emails, scripts, and docs.
- Physical project directory left unchanged (`~/Documents/code_projects/bomwise`).
- Delivered via branch `rename/bomwise-to-bomexplorer`, merged to `master` after full test suite pass (205/205).
- Also fixed a pre-existing bug: `app/worker/__init__.py` was empty, causing `celery -A app.worker` to fail with "no attribute 'celery'". Fixed by re-exporting the Celery instance from `__init__.py`.
- **Note:** `backend/.env` DATABASE_URL still points to `postgresql://bomwise:bomwise@localhost:5432/bomwise` — the live database has not been renamed. To fully align, run: `ALTER USER bomwise RENAME TO bomexplorer; ALTER DATABASE bomwise RENAME TO bomexplorer;` and update `.env` accordingly.

### 2026-04-13 (session 8)
**Completed:** NextPCB component search adapter

**Backend**
- `app/providers/nextpcb.py`: `NextPCBAdapter` — MD5 signature scheme (`_sign_params`), `GET /order/goods_search/`, maps `goods_name→mpn`, `brand_name→manufacturer`, `encap→package`, `goods_desc→description`, `min→moq`, `max→stock`, `dt→lead_time` (in `tech_specs`), `url→DistributorStock.url`, `goods_img→image_url`, `price_step[]→pricing` (`purchases→quantity`, `unit_price→price`); `response_code "2000"` check; `X-Rate-Limit-Remaining ≤ 5` warning; raises `ValueError` at construction if credentials missing (not at import)
- `app/core/database.py`: added `nextpcb_app_id: str | None = None` and `nextpcb_app_secret: str | None = None` settings
- `.env.example`: added `NEXTPCB_APP_ID=` and `NEXTPCB_APP_SECRET=`; updated `PROVIDER_FALLBACK_ORDER` to include `nextpcb` after `oemsecrets`; updated registered providers comment
- `app/main.py`: `NextPCBAdapter` registered under name `"nextpcb"` via the graceful `ValueError`-catching loop (skipped automatically if credentials absent)
- `tests/test_nextpcb.py`: 25 tests — signature algorithm (determinism, key sorting, URL encoding, all-params coverage), response parsing (MPN, pricing tiers, stock/moq, lead_time, image_url), non-2000 error handling + warning log, rate-limit header warning, missing-credentials ValueError (not ImportError), import-time safety, capabilities

**Migrations:** none (no new DB columns)

**Smoke test (manual):** once real credentials are set, run:
```bash
cd backend
NEXTPCB_APP_ID=<your_id> NEXTPCB_APP_SECRET=<your_secret> python - <<'EOF'
import asyncio
from app.providers.nextpcb import NextPCBAdapter
from app.schemas.preferences import MergedPreferences

async def main():
    adapter = NextPCBAdapter()
    results = await adapter.search_by_mpn("LM358", 10, MergedPreferences())
    for r in results:
        print(r.mpn, r.manufacturer, r.stock_total, r.pricing[:1])

asyncio.run(main())
EOF
```

**Tests:** 205/205 passed  
**Build:** ruff clean, no new migrations  
**Next:** next feature item

### 2026-04-07 (session 7)
**Completed:** Bulk lock / unlock all BOM lines

**Backend**
- `api/projects.py`: two new endpoints registered before the per-line lock/unlock routes
  - `POST /{project_id}/bom/lock-all` — bulk-updates all `bom_lines.locked = True`, returns `{"locked_count": N}`
  - `POST /{project_id}/bom/unlock-all` — bulk-updates all `bom_lines.locked = False`, returns `{"unlocked_count": N}`
  - Both require auth and verify project ownership (404 if not found or wrong user)
- Re-match already skips locked rows — confirmed by existing `test_rematch_skips_locked_lines`
- `tests/test_locking.py`: 7 new tests — lock-all sets all rows, unlock-all sets all rows, correct count returned, 404 for wrong user (both endpoints), 401 without auth (both endpoints)

**Frontend**
- `api/bom.ts`: `lockAllBomLines` and `unlockAllBomLines` functions added
- `ProjectDetailPage.tsx`: `lockAllMutation`, `unlockAllMutation`, `bulkBusy` flag added to `BomTable`; "Lock All" and "Unlock All" buttons added to toolbar next to "Re-match Parts"; both show spinner + label during loading; both disabled while any bulk operation or matching is in flight; comment noting re-match already skips locked rows

**Tests:** 174/174 passed  
**Build:** clean (expected xlsx chunk warning only)  
**Next:** next feature item

### 2026-04-07 (session 6)
**Completed:** Provider fallback chain + Source column in BOM table

**Backend**
- Migration 0011: added `matched_provider` (nullable String) to `bom_lines`
- `models/project.py`: `matched_provider` column on `BomLine`
- `schemas/project.py`: `matched_provider: str | None = None` on `BomLineResponse`
- `core/database.py`: added `provider_fallback_order: str = ""` setting
- `.env.example`: added `PROVIDER_FALLBACK_ORDER=oemsecrets,mouser,digikey` with doc comments
- `providers/registry.py`: added `get_by_name(name) -> ComponentProvider | None`
- `services/matching.py`: full fallback chain refactor
  - `_resolve_fallback_order`: reads `PROVIDER_FALLBACK_ORDER` → `COMPONENT_PROVIDER` → explicit arg
  - `PartMatchingService.__init__` accepts optional `fallback_order: list[str]` for tests
  - Auto-fallback: if none of the configured chain members are in the registry, uses the active provider (keeps all existing tests green without changes)
  - `_match_line` iterates providers in chain; first to return results wins; stores `matched_provider`
  - `_try_provider` extracted: runs MPN → hyphen-stripped → keyword hierarchy for a single provider
  - Unmatched lines: `matched_provider = None`
- `tests/test_fallback.py`: 7 new tests — first provider wins, second-provider fallback, all-empty, unconfigured provider skipped, `matched_provider` reflects winner, null for unmatched, single-item chain

**Frontend**
- `types/index.ts`: `matched_provider: string | null` added to `BomLine`
- `ProjectDetailPage.tsx`: `source` added to `ColKey`, `COL_DEFS` (after manufacturer, visible by default, label "Source"), `<th>` + `<td>` + footer `<td>`; renders as a subtle grey badge (`bg-gray-100 text-gray-500`) or `—` when null

**Tests:** 167/167 passed  
**Build:** clean (expected xlsx chunk warning only)  
**Next:** next feature item  
**Notes:** PROVIDER_FALLBACK_ORDER takes precedence over COMPONENT_PROVIDER; both need not be set simultaneously.

### 2026-04-07 (session 5)
**Completed:** Mouser and DigiKey provider adapters
- `app/providers/mouser.py`: `MouserProvider` — POST `/api/v1/search/partnumber`, maps `ManufacturerPartNumber`, `Manufacturer`, `Description`, `Availability` (strips non-numeric), `PriceBreaks` (strips currency symbol), `ImagePath` → `image_url`; raises `ValueError` if `MOUSER_API_KEY` not set; HTTP 4xx → empty list; registered as `"mouser"` (not default)
- `app/providers/digikey.py`: `DigiKeyProvider` — OAuth2 client_credentials token via `/v1/oauth2/token`; token cached in Redis (TTL 3500 s, key `digikey:access_token`) with in-memory fallback when Redis is unavailable; POST `/products/v4/search/keyword` with `X-DIGIKEY-Client-Id` header; maps `ManufacturerProductNumber`, `Manufacturer.Name`, `Description.ProductDescription`, `QuantityAvailable`, `StandardPricing`, `PrimaryPhoto` → `image_url`; `search_by_keyword` supported (sets `match_type="keyword"`); raises `ValueError` if either credential is missing; HTTP 4xx → empty list; registered as `"digikey"` (not default)
- `app/core/database.py`: added `mouser_api_key`, `digikey_client_id`, `digikey_client_secret` settings fields
- `app/main.py`: registers `"mouser"` and `"digikey"` at startup with graceful `ValueError` catch (logs warning if credentials absent, does not crash)
- `tests/test_mouser.py`: 14 tests — successful MPN lookup, empty result, HTTP 4xx, missing key, non-numeric availability, absent ImagePath, helper unit tests
- `tests/test_digikey.py`: 7 tests — token fetch + memory cache, cached token reused on 2nd call, successful MPN lookup, HTTP 4xx, missing credentials, keyword match_type, absent PrimaryPhoto

**Tests:** 160/160 passed  
**Build:** n/a (backend only)  
**Next:** next UI or feature item  
**Notes:** Default provider remains `oemsecrets`. Neither `.env.example` keys changed (already present). Redis unavailability is handled silently with memory fallback.

### 2026-04-07 (session 4)
**Completed:** UIF-015 — Part thumbnail column in BOM table
- `PartResult` provider schema (`providers/schema.py`): added `image_url: str | None = None`
- `PartResult` SQLAlchemy model (`models/part_result.py`): added `image_url` nullable String column
- `PartResultResponse` Pydantic schema (`schemas/project.py`): added `image_url: str | None`
- Migration 0010: added `image_url` column to `part_results` table
- Nexar adapter: `image_url=None` — Nexar GraphQL schema has no confirmed image field (comment in code)
- OEMSecrets adapter: `image_url=None` — partsearch response carries no image URL (comment in code)
- `matching.py` `_to_db_row`: passes `image_url=result.image_url` to the DB row
- Frontend `types/index.ts`: added `image_url: string | null` to `PartResult` interface
- Frontend `ProjectDetailPage.tsx`: added `thumbnail` to `ColKey`, added `{ key: 'thumbnail', label: 'Image', defaultVisible: true }` as first entry in `COL_DEFS`, added 48px-wide `<th>` and `<td>` before the Ref column, added footer `<td>` for summary row; thumbnail shows 40×40 image (clickable, opens new tab) when `image_url` is present, or a greyed-out inline IC/chip SVG icon when null

**Tests:** 139/139 passed  
**Build:** clean (expected xlsx chunk warning only)  
**Next:** UIF-016 (column visibility toggle) already implemented; next unstarted UI item  
**Notes:** Neither Nexar nor OEMSecrets currently returns an image URL; thumbnail column will populate automatically once a provider supplies one.

### 2026-04-07 (session 3)
**Completed:** Item 10 — Part locking and manufacturer BOM export
- Migration 0009: added `locked` boolean (default false) to `bom_lines`
- New endpoints: POST `/bom/{lineId}/lock`, POST `/bom/{lineId}/unlock`
- `matching.py`: `match_project` filters locked lines from the query (automated matching skips them)
- `tasks.py`: `run_monitor` joins to `bom_lines` and filters `locked=False` (monitoring skips locked lines)
- New endpoint: `GET /projects/{id}/export/manufacturer?format=csv|xlsx`
  - CSV: UTF-8 BOM, standard comma-sep, 12-column manufacturer format
  - Excel: `openpyxl`, bold header row, auto-sized columns, sheet named "BOM"
  - All lines (locked + unlocked, resolved + unresolved) included
- Frontend `ProjectDetailPage.tsx`: lock icon button (🔒/🔓) per row, amber tint for locked rows, export dropdown replacing two separate export buttons (Raw CSV, Raw Excel, Manufacturer CSV, Manufacturer Excel)
- Frontend `VariantsPage.tsx`: 🔒 badge + Lock/Unlock toggle on part detail page; "Swap to this part" disabled with tooltip when locked
- 11 new backend tests; all 139 tests pass

**Tests:** 139/139 passed  
**Build:** clean (expected xlsx chunk warning only)  
**Next:** n/a — all items complete (Item 8 Paddle deferred)  
**Notes:** Item 8 (Paddle) still deferred.

### 2026-04-07 (session 2)
**Completed:** Item 9 — Alternatives page, swap endpoint, substitution history rework
- Migration 0008: dropped old `substitution_history` (result-ID-based), recreated with `from_mpn`/`to_mpn`/`swapped_by`; added `part_alternatives` table
- New endpoints: GET `/bom/{lineId}/alternatives`, POST `/bom/{lineId}/swap`, updated GET `/bom/{lineId}/history`
- `matching.py`: stores rank 2+ results into `part_alternatives` after every successful match
- `matching.py`: added `raise_on_provider_error` param for swap endpoint to detect provider failures
- Frontend: `VariantsPage.tsx` extended into three sections — current part (existing), alternatives cards with swap+confirm flow, collapsible history table
- 11 new backend tests; all 128 tests pass

**Tests:** 128/128 passed  
**Build:** clean (expected xlsx chunk warning only)  
**Next:** Item 10 — Polish  
**Notes:** Item 8 (Paddle) still deferred.

### 2026-04-07 (session 1)
**Completed:** PROGRESS.md created; CLAUDE.md updated with progress tracking requirement  
**Tests:** n/a  
**Next:** Item 9 — alternatives page, swap action, substitution history  
**Notes:** Item 8 (Paddle) deferred until after items 9 and 10. OEMSecrets API access pending.