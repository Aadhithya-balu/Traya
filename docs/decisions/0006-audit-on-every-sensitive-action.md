[../README.md](../README.md) | [Decisions](README.md)

# ADR 0006: Every sensitive action writes an append-only audit row

- **Status:** Accepted
- **Date:** 2026-08-15
- **Affects:** `app/repositories/audit.py`, `app/services/audit_service.py`, `app/models/entities.py` (`AuditLog`)

## Context

The product's central claim is that a responder saw specific information about a
specific person at a specific moment, and acted on it. If that claim cannot be
reconstructed afterwards, the system is unusable in exactly the situations it
exists for: a mistaken identification, a disputed disclosure, or a regulatory
inquiry.

## Decision

1. **Append-only.** `AuditRepository` exposes `write`, `list`, `for_resource` and
   `actor_actions`. It exposes no update and no delete. Audit rows are never
   mutated.
2. **Write with the domain change, not after it.** `write_audit(..., commit=False)`
   lets a domain write and its audit row share one transaction. The alternative -
   commit, then log - leaves a window where a successful write has no audit trail.
3. **Record access, not just mutation.** Reads that expose personal data are
   logged: `emergency.session_viewed`, `medical.summary_viewed`,
   `emergency.contact_reached`, and `session.access_denied` for every rejected
   token. A read-only system still produces a complete access history.
4. **Hash, never store, the IP.** `hash_ip` truncates a SHA-256 to 32 characters.
   The audit trail can prove a request came from a given address; it cannot
   reconstruct it.
5. **`SENSITIVE_ACTIONS`** in `audit_service.py` enumerates the 33 action strings
   that must never be silently missing. Adding an action outside that set is a
   review event.
6. Access history is exposed to the citizen: `GET /api/users/access-history`
   returns who looked at their data. Being audited is visible to the person being
   protected, not only to an administrator.

## Consequences

**Good.** Any disclosure can be attributed to an actor and a time. Tampering
would require write access to the audit table. The citizen-facing access history
turns a compliance obligation into a user-facing feature.

**Costs.** The audit table grows without bound and needs a retention job
(`settings.SESSION_RETENTION_DAYS` is 90 days and is currently applied to
sessions, not to audit rows - a real gap, documented in
[the services page](../backend/services.md#audit-service)). `hash_ip` is
truncated to 32 hex characters, which is enough for attribution but means the
audit trail is a privacy liability in its own right and must be protected as
carefully as the data it describes.
