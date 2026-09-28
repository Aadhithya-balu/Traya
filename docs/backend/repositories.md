[../README.md](../README.md) | [Backend index](README.md) | [Services](services.md)

# Repositories

The only layer that touches the database. One contract, applied everywhere.

## The contract

From `app/repositories/__init__.py`:

1. A repository takes a SQLAlchemy `Session` in its constructor.
2. It returns ORM instances or dataclasses. Never dicts of raw rows.
3. **It never commits implicitly.** `flush()` yes, `commit()` no. The caller
   owns the transaction.

Rule 3 is the important one. It is what lets a domain write and its audit row
share a single transaction - the caller writes the audit with
`write_audit(..., commit=False)` and commits once, so there is never a window
where a successful write left no trail. A repository that committed on its own
would break that.

`__all__` exports `AuditRepository`, `BaseRepository`, `IncidentRepository`,
`ProfileRepository`, `RecognitionRepository` and `UserRepository`.
`NotificationRepository` is **not** in `__all__`; `users.py` imports it by full
path. That inconsistency is worth fixing.

| Module | Class | Domain |
|---|---|---|
| [`base.py`](#baserepository) | `BaseRepository[T]` | Generic CRUD. |
| [`user.py`](#userrepository) | `UserRepository` | Users and roles. |
| [`profile.py`](#profilerepository) | `ProfileRepository` | Medical, contacts, features, consent, biometrics. |
| [`incident.py`](#incidentrepository) | `IncidentRepository` | Emergency sessions and their children. |
| [`recognition.py`](#recognitionrepository) | `RecognitionRepository` | Enrolled templates and audit reads. |
| [`audit.py`](#auditrepository) | `AuditRepository` | Append-only audit trail. |
| [`notification.py`](#notificationrepository) | `NotificationRepository` | Notification rows. |

---

## BaseRepository

`class BaseRepository(Generic[T])` declares `model: type[T]` and takes a `Session`.

| Method | Behaviour |
|---|---|
| `get` | `db.get(self.model, entity_id)` -> `T | None`. |
| `add` | `add` then `flush`. Returns the instance. |
| `delete` | `delete` then `flush`. |
| `commit` | Explicit, for the caller. |
| `rollback` | Explicit. |
| `count` | `select(func.count()).select_from(self.model)` with filters. |

Subclasses inherit all six; most never call `delete` directly.

---

## UserRepository

`UserRepository(BaseRepository[User])`.

| Method | Behaviour |
|---|---|
| `by_email` | Case-insensitive, whitespace-stripped. |
| `by_id` | Straight lookup. |
| `list_paginated` | Newest first. |
| `roles_by_name` | Resolves several role names to `Role` rows. |
| `role` | One role by name. |
| `all_roles` | All roles, alphabetical. |
| `set_roles` | **Replaces** a user's roles, then flushes. |
| `total` | User count. |
| `active_count` | `is_active` user count. |
| `stored_permissions` | Distinct permission names from the `role_permissions` join. |
| `effective_permissions` | `stored_permissions`, or the static `permissions_for_roles(...)` when the database has nothing. |

That last fallback is a safety net: a fresh or half-migrated database must not
lock every user out. The trade-off is that editing the static matrix alone does
not change behaviour on a running system, because the seeded rows win.

---

## ProfileRepository

`ProfileRepository(BaseRepository[User])` - note `model` is `User`, because
every method is scoped to a user id. All child lookups are **owner-scoped**:
`contact`, `feature` and friends filter on `user_id` as well as the id, so a
guessed id cannot reach another person's data.

| Method | Behaviour |
|---|---|
| `medical` | The medical profile, or `None`. |
| `upsert_medical` | Insert or update by `user_id`. |
| `contacts` | Primary first, then by name. |
| `count_contacts` | Used for the 10-contact cap. |
| `clear_primary_contacts` | Bulk `UPDATE` clearing `is_primary`. |
| `contact` | One contact, scoped to the owner. |
| `primary_contact` | The primary, **falling back to the first contact** when none is flagged. |
| `add_contact` | Insert a contact. |
| `features` | Visible features, newest first. |
| `feature` | One feature, scoped to the owner. |
| `add_feature` | Insert a feature. |
| `consents` | Consents, newest first. |
| `latest_consent` | Most recent by `granted_at`. |
| `add_consent` | Insert a consent. |
| `active_consent` | The active consent of a given type, or `None`. Enrollment's precondition. |
| `set_consent` | Grant or withdraw; stamps `withdrawn_at` on withdrawal. |
| `biometric` | The biometric profile, or `None`. |
| `replace_embeddings` | **Deletes** old embedding rows, inserts new ones, updates `algo_version` and `num_samples`. |

Two behaviours here are load-bearing:

- **`clear_primary_contacts` before setting a primary** is how "exactly one
  primary contact" is maintained. It is an application invariant, not a database
  constraint, so any code path that sets a primary must call it first.
- **`replace_embeddings` replaces.** Re-enrollment cannot leave a previous
  template behind, so a revoked-and-re-enrolled person cannot be matched against
  an old template. See
  [ADR 0005](../decisions/0005-biometric-encryption-at-rest.md).

---

## IncidentRepository

`IncidentRepository(BaseRepository[EmergencySession])`. Not yet wired into any
router - `create_incident` and `update_incident` are in the permission matrix
but nothing calls these - so treat it as modelled-but-unused.

| Method | Behaviour |
|---|---|
| `start` | Creates a session with a `session_code` and `expires_at`. |
| `get_active` | Returns the session unless `expired`/`aborted`; **persists** `status="expired"` on a lapsed session. |
| `recent` | Newest first. |
| `complete` | Sets `identified_user_id`, `confidence_category`, `outcome`, `completed_at`. |
| `abort` | Marks the session aborted. |
| `count_expired` | Expired-session count. |
| `add_location` | Inserts a `Location` with `source` (`gps` or `manual`). |
| `record_attempt` | Inserts an `IdentificationAttempt` with the quality scores. |
| `latest_attempt` | Most recent attempt for a session. |
| `add_candidate` | Inserts a ranked candidate. |
| `candidates` | Candidates ordered by `rank`. |
| `candidate` | One candidate by id. |
| `timeline` | The session's audit rows, chronological. |

`get_active` writing expiry as a side effect of a read is deliberate: a session
that has passed `expires_at` must stop being treated as active everywhere,
including in reports, and one place is more reliable than a check at every call
site.

---

## RecognitionRepository

`RecognitionRepository(BaseRepository[BiometricProfile])`, with the
`EnrolledProfile` dataclass: `user_id`, `full_name`, `embeddings`, `algo_version`,
`is_demo`.

| Method | Behaviour |
|---|---|
| `enrolled_profiles` | Joins `User`, filters `status == "enrolled"` and `User.is_active`; **skips** profiles whose blobs fail to decrypt. |
| `decrypt_templates` | `np.frombuffer(decrypt_bytes(blob), dtype=np.float64)` per blob, each in its own `try`. |
| `enrolled_count` | Enrolled profile count. |
| `audit_entries` | Paged audit rows, optional `action` or `actor_id` filter. |
| `audit_count` | Total audit rows. |
| `access_history` | Rows where `resource_id` is the user **or** where a session produced a candidate for them. |
| `attempts_since` | Queries `BiometricProfile.updated_at`. **Misnamed** - it is not querying identification attempts. |

`access_history` is what powers `GET /api/users/access-history`: the citizen sees
both "someone read my profile" and "my face was matched in session X", which is
the access history a person would actually want to see.

`attempts_since` is only used to find profiles needing re-enrollment after an
algorithm change. Its name is wrong; rename it if you touch it.

---

## AuditRepository

`AuditRepository(BaseRepository[AuditLog])`. **Append-only: no update method and
no delete method exist.** That is a deliberate API shape, not an oversight -
see [ADR 0006](../decisions/0006-audit-on-every-sensitive-action.md).

| Method | Behaviour |
|---|---|
| `write` | The single insert path. `ip` is stored as `hash_ip(ip)`, never raw. Does not commit. |
| `write_user` | `write` with `actor_type="user"`. |
| `write_session` | `write` with `actor_type="public_session"`. |
| `list` | Paged, optional `action` filter. Newest first. |
| `for_resource` | By `resource_id`. |
| `actor_actions` | By `actor_id`, `actor_type="user"` only. |

Module function `hash_ip(ip)` returns a SHA-256 truncated to 32 characters, or
`None` for no IP. A request can be attributed to an address without the trail
storing it.

---

## NotificationRepository

`NotificationRepository(BaseRepository[Notification])`. Not in
`repositories.__all__`.

| Method | Behaviour |
|---|---|
| `recent` | Most recent for a user. |
| `unread_count` | Count where `read` is false. |
| `enqueue` | Inserts a notification with a type and JSON payload. |
| `mark_read` | Marks read, scoped to the owner. Returns `False` when not found or not owned. |

This repository and `services/notification/notification_service.py` overlap and
disagree - `get_unread` in the service does not actually filter on `read`, while
`unread_count` here does. Reconcile them before building UI on either.
