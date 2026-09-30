# TRAYA Security Model

[docs/README.md](README.md) · What protects what, and what is not protected
yet. Implementation-level detail lives in
[backend/security.md](backend/security.md); the target state is in
[TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md).

## Current state, honestly

| Control | State |
| --- | --- |
| Password hashing | **Real.** Argon-style via `app/security/password.py` |
| JWT signing | **Real.** HS256, per-purpose `type` claim |
| Refresh rotation | **Real** |
| Rate limiting | **Real.** `RateLimitMiddleware` |
| Image upload validation | **Real.** Magic bytes, size cap, decode limits |
| Biometric encryption at rest | **Real.** Fernet |
| Permission matrix | **Real.** 7 roles, 18 permissions, seeded and auditable |
| Audit trail | **Real.** Append-only, written with domain writes |
| Embeddings never leave the backend | **Real.** No endpoint returns a vector |
| **Row Level Security** | **Absent.** Python-only authorization |
| **Session storage** | **`localStorage`.** Vulnerable to XSS and extensions |
| **Content Security Policy** | **Absent** |
| **Silent database fallback** | **Closed in Phase 3.** Opt-in, off by default, refused in production mode |
| **Secret rotation** | **Manual.** No dual-key acceptance window |

The gap is not the cryptography. It is **who decides access**: the application
does, and the database will happily serve anyone who reaches it.

## Trust boundaries

| Boundary | Trust level | Assumption |
| --- | --- | --- |
| Browser to API | **Untrusted** | Assume any client-side check was bypassed |
| API to Supabase | Trusted | Service-role connection; scoped by application permission |
| API to ML model | Trusted, validated input | Never runs on undecoded bytes |
| Responder to victim data | **Role-dependent** | Clinical data requires an explicit permission |
| Audit log | Append-only | Tampering must be detectable |

The first row is the one that matters. React deciding a user is an admin is a
UI convenience. The database deciding it is the security boundary.

## Authentication

### Current

Custom JWT. Access token carries `sub`, `type`, `iat`, `exp`; refresh carries
the same with a longer expiry. No `jti`, so **no revocation list** - a leaked
token stays valid until it expires.

Refresh tokens are delivered as an httpOnly cookie, but the **access token is
kept in `localStorage`**, where any XSS or a browser extension can read it.

### Target

| Concern | Decision | Reason |
| --- | --- | --- |
| Session store | httpOnly cookie | Not readable from JavaScript |
| Access token | Memory only | Cleared when the tab closes |
| Revocation | `jti` + denylist, or Supabase sign-out | Currently impossible |
| Email verification | Required before enrolment | Stops throwaway enrolment |
| MFA | Optional; required for `admin` and responders | Privilege escalation is the target |

### The distinction that must not be lost

```
loading          the answer is not known yet
unauthenticated  the server said no
error            the server could not be asked
```

The current `AuthContext` collapses `error` into `unauthenticated`, so a network
blip renders the logged-out screen while the tokens are still present. That is
the second half of the reported logout complaint, and it is a state-machine bug,
not a network bug.

## Authorization

### Two layers, both required

```
Request ─▶ application permission check   (defence in depth, clear errors)
              │
              ▼
          Supabase query ─▶ RLS policy    (the actual boundary)
```

The application layer produces good error messages and fails fast. RLS decides
truth. **A bug in the application layer must not grant access** - that is only
true if RLS is correct, which is why Phase 4 is its own phase in the plan.

### The role matrix

Seven roles, 18 permissions. Full detail in
[backend/security.md](backend/security.md); the design rationale:

| Role | Sees | Deliberately cannot see |
| --- | --- | --- |
| `public` | That identification was attempted | Everything |
| `registered_user` | Own profile, medical, contacts, biometric status | Any other record |
| `police_responder` | Identity, contacts, incidents | **Blood group, allergies, medications** |
| `medical_responder` | Identity, clinical data, contacts | - |
| `hospital` | Clinical data, contacts | **Identity confirmation** |
| `auditor` | Audit trail | Everything operational |
| `admin` | All | - |

The police/medical split is the one most worth defending: **identity** and
**clinical data** are separate powers, and a responder should hold the one their
role actually needs. It is already modelled in `ROLE_PERMISSIONS`; Phase 4 makes
it enforced at the data layer.

## Biometric data

Face embeddings are the most sensitive thing TRAYA holds. They are not
passwords: they cannot be changed if leaked, they cannot be individually
revoked, and they are permanent biometric identifiers.

### Controls present

| Control | Where |
| --- | --- |
| Encrypted at rest (Fernet) | `app/security/crypto.py` |
| Never returned by any endpoint | Verified across all 47 routes |
| Never logged | No log statement writes a vector |
| Cascade delete on account removal | `ondelete="CASCADE"` plus ORM `delete-orphan` |
| Users cannot read their own vectors | Target state; requires RLS |

### The design rule

> **The browser submits a captured face. The backend performs embed, search,
> threshold and result. Only the minimum decision returns.**

There is deliberately no endpoint that returns embeddings, and none will be
added. An endpoint that hands one client a vector invites a client that hands
itself the whole table.

### Open problem: encryption versus pgvector

The current design encrypts with Fernet, which is stronger. pgvector's ANN index
needs to read the vectors.

| Option | Trade |
| --- | --- |
| Plaintext `vector(128)` + HNSW | Fast search. **Embeddings readable by anyone with DB access.** |
| Fernet bytes, sequential scan in Python | Strongest at rest. No ANN. Fine at a few thousand enrolments. |
| `pgcrypto` per row + `SECURITY DEFINER` function | Search works. Requires careful key management. |

**Deferred to Phase 10 measurement.** At MVP scale a sequential scan over
encrypted rows is acceptable, and the strongest option is the right default. If
scale forces ANN, the `SECURITY DEFINER` function becomes mandatory so that no
role ever holds the key and the raw vectors together.

## Threat model

### T1 - Biometric enumeration

**Attacker.** Anyone with a phone, submitting photos to discover who is enrolled.

| Mitigation | State |
| --- | --- |
| Rate limit per IP and per session | **Real** |
| Audit every attempt | **Real** |
| Low scores reveal nothing about non-matches | **Real** |
| No bulk export endpoint | **Real** |

Enumeration is mostly a traffic and cost problem, and it is already well
handled. The residual risk is that repeated *high* scores confirm enrolment,
which is why attempt auditing matters.

### T2 - Over-trust in a match

**Attacker.** Not an attacker - a **failure mode**. A responder acts on a false
positive and gives a patient the wrong treatment or contacts the wrong family.

This is the most dangerous risk in the product and it is **not** a security
control in the usual sense.

| Mitigation | State |
| --- | --- |
| Never force a match | **Real.** Below threshold, uncertainty |
| `REVIEW_REQUIRED` forces human confirmation | **Real.** `pipeline.py:238` |
| Never state an unverified match as an identity | **Partial** - UI must not say "this is the person" |
| Margin rule for ambiguous candidates | **Absent** - the pipeline ranks but never inspects the top-2 gap |
| Model versioning so a threshold is traceable | **Partial** - `algo_version` only |

**The margin rule is the missing control.** With real embeddings, two different
people can both score above the high threshold. A top-1 of 0.90 with a top-2 of
0.88 is not a confident match; it is an ambiguous one. The current pipeline has
no way to express this, which is why `MULTIPLE_CANDIDATES` is a new status in
the target architecture.

### T3 - Unauthorized clinical access

**Attacker.** An authenticated responder, or a stolen responder token, reading
medical data they should not see.

| Mitigation | State |
| --- | --- |
| Application permission check | **Real** |
| RLS | **Absent** - Phase 4 |
| Emergency-profile endpoint gated on status and role | **Real** |
| Audit on profile access | **Real** |

### T4 - Silent degradation

**Attacker.** No attacker. A network blip at boot.

`DatabaseService` used to fall back to SQLite when the Postgres probe failed and
`DATABASE_ALLOW_FALLBACK` was true — **which was the default**. The UI did
surface `demo_offline`, which is honest, but the operational risk was real: **a
deployment configured for Supabase could persist real medical and biometric data
into a local file** without anyone intending it. The failure is quiet by
construction: a `logger.warning`, a working app, HTTP 200s, and emergency
records in a file that is not shared with responders and not covered by
row-level security.

**Mitigated in Phase 3.** The fallback is now opt-in and off by default, and
`DEMO_MODE=false` refuses it regardless of the flag, so a production deployment
that cannot reach Postgres **fails to start**. Two conditions rather than one:
a permissive default that production inherits, and a stray env var that
re-authorises data loss, are both ways to get here, and closing only one leaves
the other. The degraded path also logs at `ERROR` and states what is lost.

Failing loudly beats storing PHI somewhere unintended. The rollback is
`DATABASE_ALLOW_FALLBACK=true` in the environment — one variable, no code
change — so nothing about this is irreversible.

### T5 - Malicious upload

**Attacker.** A crafted image: a decompression bomb, a malformed JPEG, a
polyglot, an oversized payload.

| Mitigation | State |
| --- | --- |
| Magic-byte check | **Real.** `engine.py:103` |
| Size cap | **Real** |
| Decode limits | **Real** |
| Rendering in a server process | **Residual.** A malformed image is a parser bug in OpenCV or Pillow |

The residual risk is real: decoding happens in the API process. Mitigation is
patching the decoders and running untrusted decoding in a sandboxed worker -
out of scope for the MVP, and recorded rather than hidden.

### T6 - Token theft via XSS

| Mitigation | State |
| --- | --- |
| No `dangerouslySetInnerHTML` anywhere | **Real.** Verified zero occurrences |
| Tokens in `localStorage` | **The weakness** |
| Content Security Policy | **Absent** |

The app has no injection surface today, so the realistic risk is third-party
supply chain rather than app code. The standard fix is an httpOnly refresh
cookie with the access token in memory, plus a CSP. Both are Phase 9 and 11.

### T7 - SQL injection

| Mitigation | State |
| --- | --- |
| SQLAlchemy parameterised queries | **Real** |
| No raw SQL with interpolation | **Real** |
| No `SECURITY DEFINER` functions yet | N/A - added in Phase 4, must be audited |

Phase 4 introduces functions that bypass RLS by design. They become a new
injection surface and need the same scrutiny as a public endpoint.

## Secrets

| Rule | Status |
| --- | --- |
| No Supabase service-role key in frontend code | **Enforced** - must be a CI check |
| No secrets committed | **Enforced** |
| `.env` gitignored | **Real** |
| `SECRET_KEY` is a dev placeholder by default | **Must be replaced.** Documented in the README |
| `ENCRYPTION_KEY` is derived from `SECRET_KEY` if unset | **Sharp edge.** Rotating `SECRET_KEY` without setting `ENCRYPTION_KEY` makes stored embeddings permanently unreadable |
| Key rotation | **Manual**, no dual-key window |

The `ENCRYPTION_KEY` interaction is the sharpest edge in the codebase. It is
already documented; it is repeated here because it destroys biometric data
silently.

## Audit and logging

### What is audited

`USER_REGISTERED`, `FACE_REGISTERED`, `FACE_UPDATED`, `EMERGENCY_STARTED`,
`MATCH_ATTEMPTED`, `MATCH_FOUND`, `MATCH_REJECTED`, `PROFILE_ACCESSED`,
`INCIDENT_CREATED`, `INCIDENT_UPDATED`, `ADMIN_ACTION`.

Every identification decision is persisted as an `IdentificationAttempt` plus
per-candidate rows **in the same transaction as the domain write**
(`_persist_attempt`, `pipeline.py:260`). That discipline is why the audit trail
is trustworthy.

### What must never be logged

- **Raw embeddings or vectors.** Biometric material in a log file is a copy
  outside every access control the database has.
- Unredacted clinical detail.
- Tokens, passwords, or `SECRET_KEY`.
- Full image bytes.

A test asserts the first of these rather than trusting review.

### Who can read the audit trail

`auditor` and `admin` only. Ordinary users see their own
`access-history`, which is a projection of the trail, not the trail.

## What is deliberately not done

Stated so a future agent does not "fix" it:

- **No silent degradation.** Removing the automatic SQLite fallback was a
  behaviour change, not a bug fix, and it is done — so this is now a note
  against putting it back. If you find yourself enabling
  `DATABASE_ALLOW_FALLBACK` to make a deployment boot, you have traded an
  outage you can see for one you cannot.
- **No user read access to their own vectors.** Someone who wants to delete
  their biometrics should delete them, not export them.
- **No standing clinical access for responders.** Access requires an active
  incident. It is more friction, and the friction is the control.
- **No public embeddings, even encrypted ones.** There is no legitimate client
  need for a vector.
- **No unauthenticated emergency identification.** It is tempting to open the
  flow wide because a bystander has no account. It is already open, with a
  scoped session token that grants only identification. **That is the correct
  boundary** - not a gap to close.