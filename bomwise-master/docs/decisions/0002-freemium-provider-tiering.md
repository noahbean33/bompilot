# 0002 — Freemium Provider Tiering

**Status:** accepted

## Context

The provider layer supports multiple data sources. Some have commercial API costs (Nexar); others are free to access (OEMSecrets, DigiKey, Mouser). Tiering providers is a natural fit for freemium monetisation.

## Decision

Free plans are restricted to free-access providers (OEMSecrets, DigiKey, Mouser). Paid plans unlock premium providers (Nexar).

## Rationale

- Creates a visible, recurring upgrade prompt at the point of a core workflow (parts lookup)
- Premium providers offer demonstrably richer data: lifecycle status, consolidated pricing, supply chain intelligence
- Effectiveness depends on Nexar delivering clear value over the free tier — linked to the ongoing Nexar pricing negotiation

## Trade-offs

- If free providers are sufficient for most users, upgrade motivation from this feature alone is weak
- Must be combined with other paid features (e.g. project limits from 0001) to create sufficient conversion pressure
- Provider quality differences must be visible to free-tier users; silently absent results would undermine trust

## Implications

- Provider registry needs a `tier` flag (`free` | `premium`) on each provider entry
- A plan check is required before any provider is included in a query
- Free-tier users must see that premium results are available but gated — not silently absent
