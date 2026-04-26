# Product Decision Records

This directory contains Product Decision Records (PDRs) — lightweight, structured logs of significant product and technical decisions made for BOMexplorer.

## Format

Each record uses the following fields:

- **Context** — What situation or problem prompted this decision?
- **Decision** — What was decided? State it directly and unambiguously.
- **Rationale** — Why this option over alternatives?
- **Trade-offs** — What are the known downsides, risks, or unresolved tensions?
- **Status** — One of: `proposed` | `accepted` | `superseded`
- **Implications** — What does this decision require or constrain going forward?

## Numbering convention

Files are named with a four-digit zero-padded prefix followed by a short kebab-case title:

```
0001-short-title.md
0002-another-decision.md
```

## Immutability rule

Records are **immutable once accepted**. Do not edit an accepted record to change the decision. Instead:

1. Create a new record with the updated decision.
2. Set the old record's status to `superseded`.
3. Add a `Superseded by` line at the top of the old record referencing the new one.
4. Add a `Supersedes` line in the new record referencing the old one.
