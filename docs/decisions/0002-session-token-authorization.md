[../README.md](../README.md) | [Decisions](README.md)

# ADR 0002: Emergency sessions are authorized by a token, not by session id

- **Status:** Accepted
- **Date:** 2026-09-28
- **Affects:** `app/api/emergency.py`, `app/utils/helpers.py`, `app/repositories/incident.py`, migration `b32e84ef129d`

## Context

The emergency flow is deliberately open to the public: an unconscious person
cannot consent, so a bystander must be able to photograph them and get a
response without an account. That made session authorization ambiguous.

The original implementation treated knowledge of the session id as sufficient
authorization. Session ids were UUIDs, but they were passed in URLs, logged,
returned in API responses, and stored in `sessionStorage`. Any of those channels
is a disclosure, and a leaked session id exposed medical data and allowed
identity confirmation.

## Decision

A session id identifies a session. It does not authorize access to it.

1. `POST /api/emergency/start` returns a session id **and** an access token. The
   token is returned exactly once and never persisted server-side in plaintext.
2. Only `sha256(token)` is stored, in `emergency_sessions.access_token_hash`.
3. Every subsequent read and write on a session requires either:
   - `X-TRAYA-Session-Token` matching the stored hash by constant-time compare
     (`secrets.compare_digest`), or
   - a signed-in responder JWT whose user holds the `identify_person` permission.
4. A mismatch returns **403** and writes a `session.access_denied` audit row, so
   probing is visible.
5. The migration force-expires every pre-existing `active` session that has no
   token hash. Old sessions are not grandfathered, because grandfathering them
   would preserve exactly the vulnerability being closed.

## Consequences

**Good.** Medical data, contact details and identity confirmation are now gated
on a secret rather than a URL. Denied access is auditable. The public flow still
requires no account.

**Costs.** The client must carry the token. `Emergency.tsx` opens a session
lazily, at the point the photo exists, so an abandoned attempt does not leave a
session in the incident log. Anyone calling the API by hand must thread the
header; the OpenAPI docs and the frontend API client both do. Session token
storage on the client is `sessionStorage`, so a refresh loses it and the user
must start a new flow - which is the correct default for an emergency product.
