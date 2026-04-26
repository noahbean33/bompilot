# 0003 — System Admin Role

**Status:** accepted

## Context

The application needs a privileged operator account for internal management tasks — monitoring usage, manually adjusting user plans, triaging support issues, and accessing future admin dashboards. This is distinct from regular user accounts and from the free/paid plan model.

## Decision

A designated system admin account (`bom_admin@futureshock.com.au`) is provisioned as a standard registered user. Admin identity and privileges will be enforced via a dedicated flag or role field on the `User` model in a follow-up migration. Admin-only pages and a management dashboard are planned but not yet built.

## Rationale

- Fastest path to having an operational admin account without blocking other work
- Keeps the auth flow unified (same JWT mechanism) rather than introducing a separate credential system
- The dedicated account email makes admin sessions identifiable in logs

## Trade-offs

- Until the `is_admin` flag and route guards are implemented, the admin account has no more privileges than any other user
- Admin credentials must be stored securely (not committed to source control); the `.http` request file is for local development only and must not be deployed or shared

## Implications

- `User` model needs an `is_admin: bool` column (future migration)
- All admin-only API routes must check `is_admin` before processing
- Admin pages in the frontend will be gated on the same flag
- The `.http` file containing the admin password is a development convenience only; production provisioning should use a secrets manager or a dedicated CLI command
