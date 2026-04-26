# 0001 — Freemium Project Limits

**Status:** accepted

## Context

Differentiating free and paid tiers requires a usage ceiling that hits real growth without blocking initial value. Project and part count are the most natural axes for BOM tooling.

## Decision

Free accounts are limited to [TBD] parts per project and [TBD] total projects. Exact thresholds are to be confirmed after observing early usage patterns.

## Rationale

Project and part count scale directly with real usage, are easy to enforce server-side, and are difficult to game without genuinely using the product.

## Trade-offs

- Threshold too low → user hits the wall before experiencing value → frustration, churn
- Threshold too high → no conversion pressure → upgrade rate stays flat
- Exact numbers are deliberately deferred until early usage data is available

## Implications

- Project model needs a part-count field or a derived count
- Account model needs a total-project count
- Enforcement must be applied at BOM import and project creation endpoints
