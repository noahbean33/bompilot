---

# MARKETING SITE CORRECTION — SUPPLY CHAIN MONITORING

## DOCUMENT FOR AI CODING AGENT

### PURPOSE

Update front-facing marketing pages to reflect factual Supply Chain Monitoring capabilities. Current copy over-claims on several features.

---

## CURRENT CLAIMS VS ACTUAL STATE

### CLAIM BLOCK 1: "Overnight re-query"

| Current Copy | Actual Status | Verdict |
|--------------|---------------|---------|
| "Celery background job re-checks all active BOM lines for price and stock changes. Set it and forget it." | ✓ IMPLEMENTED — `monitor_parts` runs every 24h, re-queries all PartResults, skips locked lines, creates flags on changes | ✓ ACCURATE |

**ACTION**: No change needed. This claim is truthful.

---

### CLAIM BLOCK 2: "Flag detection"

| Current Copy | Actual Status | Verdict |
|--------------|---------------|---------|
| "Out-of-stock, low-stock, price spike, end-of-life, and lead-time increase alerts — all detected automatically." | ⚠️ PARTIALLY TRUE — only `out_of_stock` and `price_change` exist. `low_stock`, `end_of_life`, and `lead_time_increase` are NOT implemented | ❌ INACCURATE |

**ACTION**: Replace with:

> "**Out-of-stock and price change alerts** — automatically detected when stock drops to zero or prices shift by more than 10%."

**OR** (if you want to hint at future features):

> "**Out-of-stock and price change alerts** — automatically detected today. Low-stock, end-of-life, and lead-time alerts coming soon."

---

### CLAIM BLOCK 3: "Alert lifecycle"

| Current Copy | Actual Status | Verdict |
|--------------|---------------|---------|
| "Open → Watching → Ignored → Resolved workflow with snooze support. Control which alerts need action." | ❌ NOT IMPLEMENTED — only binary `acknowledged` flag (unacknowledged → acknowledged). No state machine, no snooze | ❌ INACCURATE |

**ACTION**: Replace with:

> "**Simple acknowledge workflow** — review alerts and mark them as acknowledged to clear them from your digest."

---

### CLAIM BLOCK 4: "Morning digest email"

| Current Copy | Actual Status | Verdict |
|--------------|---------------|---------|
| "Start your day informed. Automated email summary of new flags, delivered to your inbox each morning." | ⚠️ PARTIALLY TRUE — digest email exists, runs every 24h from app start, **no fixed morning time**, plain-text only | ❌ MISLEADING |

**ACTION**: Replace with:

> "**Daily digest email** — automated summary of unacknowledged alerts, delivered to your inbox once per day."

---

## CORRECTED MARKETING COPY (FULL BLOCK)

Copy-paste ready replacement for the entire "Supply Chain Monitoring" section:

```
Supply Chain Monitoring

Overnight re-query
Celery background job re-checks all active BOM lines for price and stock changes. Set it and forget it. ✓

Flag detection
Out-of-stock and price change alerts — automatically detected when stock drops to zero or prices shift by more than 10%. ✓

Alert management
Review alerts and mark them as acknowledged. Unacknowledged alerts appear in your daily digest. ✓

Daily digest email
Stay informed. Automated email summary of unacknowledged alerts, delivered to your inbox once per day. ✓
```

---

## FRONTEND PAGES TO UPDATE

Search the marketing site for these sections and replace:

| Section | Old Copy | New Copy |
|---------|----------|----------|
| "Out-of-stock, low-stock, price spike, end-of-life, and lead-time increase alerts" | Full list of 5 alert types | "Out-of-stock and price change alerts" |
| "Open → Watching → Ignored → Resolved workflow with snooze support" | 4-state lifecycle + snooze | "Acknowledge alerts to manage your digest" |
| "Start your day informed...each morning" | Morning-specific timing | "Stay informed...once per day" |

---

## WHAT NOT TO REMOVE

Do NOT remove references to:
- Celery background jobs (exists and works)
- Re-query / overnight refresh (exists and works)
- Digest email (exists, just change "morning" to "daily")
- Flag/alert detection (exists for 2 of 5 claimed types)

---

## FUTURE-STATE PLANNING (OPTIONAL)

If you want to add a "Roadmap" or "Coming Soon" section to the marketing site, these features are real and planned:

| Feature | ETA Effort | Tier |
|---------|------------|------|
| Low-stock alerts | LOW (2-3h) | Pro |
| End-of-life detection | MEDIUM (4-6h) | Pro |
| Lead-time increase alerts | MEDIUM (4-6h) | Pro |
| Full alert lifecycle (Open→Watching→Ignored→Resolved) | MEDIUM (6-8h) | Pro |
| Snooze support | LOW-MED (3-4h) | Pro |
| Fixed-schedule morning digest (e.g. 8am) | LOW (1-2h) | Free + Pro |
| HTML-formatted digest | LOW (2-3h) | Free + Pro |

Consider adding a "Coming in Q2 2026" badge to these to show roadmap without over-claiming.