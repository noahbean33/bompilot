Read docs/architecture.md before starting any task. Follow the build sequence in that document.

## Current state
Build sequence items 1–5 are complete and committed. Resume at item 6.

## Key constraints
- Always use `uv run` to execute Python tools (pytest, alembic, mypy, ruff)
- Run `uv run alembic upgrade head` after any migration is generated — never skip this
- Tailwind is pinned to v3 — do not upgrade

## Provider layer
- NexarProvider is implemented and tested
- GraphQL field names are not guessable — validate against api.nexar.com/graphql if modifying queries
- Confirmed valid fields: `totalAvail`, `shortDescription`, `bestDatasheet { url }`, `sellers { company { name } offers { inventoryLevel prices { quantity price currency } clickUrl } }`, `specs { attribute { name } value }`

## Testing
- Never call live provider APIs in tests — always mock
- Run `uv run pytest -v` to confirm full suite passes before committing

- Update `PROGRESS.md`: mark the item's status in the build sequence table and append a new session log entry with today's date, what was completed, test results, what's next, and any deferrals or notes.