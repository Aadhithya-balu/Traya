# Architecture Decision Records

Short records of decisions that shaped the codebase and would otherwise be
re-litigated. Each ADR states the context, the decision, and what it costs us.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-simulation-biometric-engine.md) | The biometric engine is a simulation, not a production recogniser | Accepted |
| [0002](0002-session-token-authorization.md) | Emergency sessions are authorized by a token, not by session id | Accepted |
| [0003](0003-supabase-primary-sqlite-fallback.md) | Supabase/PostgreSQL is primary, SQLite is an explicit fallback | Accepted |
| [0004](0004-monochrome-mobile-design-system.md) | Monochrome, mobile-first, token-driven design system | Accepted |
| [0005](0005-biometric-encryption-at-rest.md) | Biometric embeddings are Fernet-encrypted and never returned to clients | Accepted |
| [0006](0006-audit-on-every-sensitive-action.md) | Every sensitive action writes an append-only audit row | Accepted |
| [0007](0007-rls-claims-and-live-role-resolution.md) | RLS policies read `request.jwt.claims`, and roles are resolved live | Accepted |
| [0008](0008-real-biometric-engine.md) | YuNet plus SFace 128D on the OpenCV runtime, behind the same provider interface as the simulation | Accepted |

## Adding an ADR

1. Copy the shape of an existing file: number, title, Status, then
   **Context / Decision / Consequences**.
2. Use the next free number. Numbers are never reused, even if an ADR is
   superseded - add a new one that references the old number.
3. Superseded ADRs get a `Status: Superseded by ADR-XXXX` line and keep their
   original text. Do not delete them; the record of what was believed and when
   is the point.
4. Add a row to the table above.
