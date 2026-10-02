[../README.md](../README.md) | [Backend index](README.md) | [Security](security.md)

# Data Model

Every table, its relationships, and the migration that created it. All models
live in `app/models/entities.py` on a shared `Base` from
`app/database/session.py`.

## Conventions

- Primary keys are `String(36)` UUID4 strings via `uuid_str()`, except
  `SystemSetting`, which is keyed by its `key` string.
- Timestamps are UTC via `utcnow()`.
- JSON columns hold lists or objects (`allergies`, `details`, `payload`).
- Child rows cascade on delete. Optional parents use `SET NULL`, so deleting a
  user never destroys the audit trail that references them.
- `all_models` in `entities.py` is imported by `DatabaseService.create_all()`
  and by `migrations/env.py` for metadata registration. **A new model absent
  from `all_models` is invisible to Alembic.**

## Association tables

| Table | Columns | Introduced by |
|---|---|---|
| `user_roles` | `user_id` -> `users.id`, `role_id` -> `roles.id` (composite PK) | `a8c4ffbe90bd` |
| `role_permissions` | `role_id` -> `roles.id`, `permission_id` -> `permissions.id` (composite PK) | `56a8e0eed1a8` |

## Identity and access

| Model | Table | Introduced by |
|---|---|---|
| `Role` | `roles` | `a8c4ffbe90bd` |
| `Permission` | `permissions` | `56a8e0eed1a8` |

- `Role`: `name` unique + indexed, `description`. Relationships: `users`,
  `permissions`.
- `Permission`: `name` unique + indexed, `description`. Relationship: `roles`.
  Rows are reconciled on every boot by `ensure_permission_matrix`, so this table
  is a cache of the code matrix, not an independent source of truth.

## Users

| Model | Table | Introduced by |
|---|---|---|
| `User` | `users` | `a8c4ffbe90bd` |

`email` unique + indexed (lowercased on write), `hashed_password`, `full_name`,
`phone`, `date_of_birth`, `is_active`, `is_demo`, `created_at`, `updated_at`.

Relationships: `roles` (`lazy="selectin"`), `medical_profile` (1:1),
`contacts`, `biometric_profile` (1:1), `visible_features`, `consents`. All
children use `cascade="all, delete-orphan"`. Exposes a `role_names` property.

## Citizen profile

| Model | Table | Introduced by |
|---|---|---|
| `MedicalProfile` | `medical_profiles` | `a8c4ffbe90bd` |
| `EmergencyContact` | `emergency_contacts` | `a8c4ffbe90bd` |
| `VisibleFeature` | `visible_features` | `a8c4ffbe90bd` |
| `Consent` | `consents` | `a8c4ffbe90bd` |

- `MedicalProfile`: `user_id` unique + CASCADE. `blood_group`; JSON
  `allergies`, `conditions`, `medications`; `emergency_notes`,
  `preferred_hospital`, `home_lat`, `home_lng`, `updated_at`.
- `EmergencyContact`: `user_id` indexed + CASCADE. `name`, `relation`, `phone`,
  `email`, `is_primary` (defaults true), `created_at`. Exactly one primary is
  enforced in the repository, not by a database constraint.
- `VisibleFeature`: `user_id` indexed + CASCADE. `feature_type` constrained to
  `scar`/`tattoo`/`birthmark`/`mark`, `description`, `body_location`,
  `created_at`.
- `Consent`: `user_id` indexed + CASCADE. `consent_type` (`biometric`,
  `medical`, `data`), `status` (`active`, `withdrawn`), `version` (default
  `v1`), `granted_at`, `withdrawn_at`. **Consent is a required precondition for
  enrollment** - see [guided enrollment](services.md#guided-biometric-enrollment).

## Biometrics

| Model | Table | Introduced by |
|---|---|---|
| `BiometricProfile` | `biometric_profiles` | `a8c4ffbe90bd` |
| `BiometricEmbedding` | `biometric_embeddings` | `a8c4ffbe90bd` |
| `BiometricEnrollment` | `biometric_enrollments` | `c74d0b1e8fa2` |
| `BiometricEnrollmentSample` | `biometric_enrollment_samples` | `c74d0b1e8fa2` |

- `BiometricProfile`: `user_id` unique + CASCADE, `status` (default
  `not_enrolled`), `algo_version`, `num_samples`, `enrolled_at`, `updated_at`.
- `BiometricEmbedding`: `profile_id` indexed + CASCADE, `embedding_blob`
  (`LargeBinary`, **Fernet-encrypted**), `algo_version`, `created_at`. Never
  returned by any endpoint - see
  [ADR 0005](../decisions/0005-biometric-encryption-at-rest.md).
- `BiometricEnrollment`: `user_id` indexed + CASCADE, `status` (`in_progress`,
  `completed`, `abandoned`, `expired`), `current_step`, `total_steps`,
  `accepted_samples`, `rejected_samples`, `algo_version`, `sample_reports`
  (JSON, not null, last 20 verdicts), `baseline_offset_x`, `baseline_offset_y`,
  `created_at`, `completed_at`. Composite index
  `ix_biometric_enrollments_user_status` on `(user_id, status)`.
- `BiometricEnrollmentSample`: `enrollment_id` indexed + CASCADE,
  `step_index`, `step_key` (default `front`), `embedding_blob` (encrypted),
  `quality_score`, `pose_offset_x`, `pose_offset_y`, `accepted`, `created_at`.

The `baseline_offset_*` columns store the vertical asymmetry measured on the
first accepted `front` sample. Up/down guidance is relative to that baseline.
Horizontal guidance needs no baseline. These are **normalised asymmetry values
in (-1, 1), not degrees in yaw/pitch** - the engine never invents an angle it
cannot measure.

## Emergency sessions

| Model | Table | Introduced by |
|---|---|---|
| `EmergencySession` | `emergency_sessions` | `a8c4ffbe90bd` |
| `IdentificationAttempt` | `identification_attempts` | `a8c4ffbe90bd` |
| `IdentificationCandidate` | `identification_candidates` | `a8c4ffbe90bd` |
| `IncidentEvent` | `incident_events` | `eabc34d087df` |
| `Location` | `locations` | `a8c4ffbe90bd` |

- `EmergencySession`: `session_code` unique + indexed (`ER-YYYY-NNNNNN`),
  `access_type` (default `public`), `initiator_id`, `access_token_hash` (added by
  `b32e84ef129d`), `status`, `outcome`, JSON `identification_method`,
  `confidence_category`, `identified_user_id` (indexed, `SET NULL`),
  `device_id`, `ip_hash`, `created_at`, `expires_at`, `completed_at`.
  Relationships: `identified_user` (`lazy="selectin"`), `location` (1:1
  cascade), `attempts`, `events`.

  **The `status` vocabulary changed in Phase 7.** It was `active`, `completed`,
  `expired`, `aborted`; it is now the ten values in
  `app/services/incident_service.py`. `active` became `created`, `identifying`,
  `review_required` or `no_match` depending on how far the attempt got, and
  `completed` became `identified` or `resolved`. The rename is not cosmetic:
  `completed` reads as success, and an unidentified person at a hospital
  entrance is not a success. `expired` and `aborted` were already written by
  `IncidentRepository` and are kept. Existing rows are **not** rewritten by the
  migration - the column is unconstrained text and Phase 7 does not rewrite
  history, so an old `active` row stays `active` and no longer matches the
  frontend union.
- `IdentificationAttempt`: `session_id` indexed + CASCADE. The five quality
  scores, `face_count`, `usable`, JSON `method`, `result`, `confidence`,
  `fallback_used`, `created_at`. One row per identification attempt, including
  rejected ones.
- `IdentificationCandidate`: `attempt_id` indexed + CASCADE, `user_id` indexed +
  CASCADE, `confidence`, `rank`, JSON `method`, `status` (`pending`,
  `confirmed`, `rejected`), `confirmed_by`, `created_at`.
- `IncidentEvent`: `session_id` indexed + CASCADE, `sequence`,
  `event_type`, `actor_id`, `subject_id`, `fallback_used`, JSON `details`,
  `created_at`. **Unique on `(session_id, sequence)`** and that constraint is the
  real ordering guarantee: `next_sequence()` reads `MAX(sequence) + 1` inside the
  caller's transaction, which two concurrent responders can race, and the
  database is what actually stops a duplicate. The endpoint orders by
  `sequence`, not `created_at`, because two events inside the same millisecond
  must still have a defined order or the log cannot answer "what happened
  first".

  Twelve event types: the nine required (`INCIDENT_CREATED`,
  `FACE_CAPTURE_STARTED`, `FACE_DETECTED`, `MATCH_ATTEMPTED`, `MATCH_FOUND`,
  `MATCH_REJECTED`, `PROFILE_ACCESSED`, `CONTACT_INITIATED`,
  `INCIDENT_RESOLVED`) plus `CAPTURE_REJECTED`, `ASSISTANCE_REQUESTED` and
  `ASSISTANCE_COMPLETED`. `record_event` raises `UnknownEventType` outside the
  set, so a typo is a test failure rather than a row nothing reads.

  `fallback_used` is one of the four fallback path names and defaults to null on
  the biometric path. It exists so "how was this person actually identified?"
  is answerable from the incident alone, without reading the audit trail.
  Deliberately carries **no clinical detail** - which is why every responder
  role can hold `view_incident` without that widening what any of them can read
  about the victim.
- `Location`: `session_id` nullable + CASCADE, `user_id` nullable + `SET NULL`,
  `latitude`, `longitude`, `accuracy`, `source` (`gps`, `manual`),
  `captured_at`. `source` must describe where the fix came from, because the
  context boost in the match tier trusts it.

## Support tables

| Model | Table | Introduced by |
|---|---|---|
| `Hospital` | `hospitals` | `a8c4ffbe90bd` |
| `AuditLog` | `audit_logs` | `a8c4ffbe90bd` |
| `Notification` | `notifications` | `a8c4ffbe90bd` |
| `SystemSetting` | `system_settings` | `a8c4ffbe90bd` |

- `Hospital`: `name`, `address`, `phone`, `latitude`, `longitude`,
  `emergency_available`, `availability_verified`, `created_at`. No relationships.
  `availability_verified` reflects the stored value only; availability is never
  inferred or invented.
- `AuditLog`: `actor_type` (`user`, `public_session`, `system`), `actor_id`
  (indexed), `action` (indexed), `resource_type`, `resource_id`, `session_id`
  (indexed, `SET NULL`), JSON `details`, `ip_hash` (hashed, never raw),
  `created_at` (indexed). Append-only - no update, no delete path exists.
- `Notification`: `user_id` indexed + CASCADE, `type`, JSON `payload`, `read`,
  `created_at`.
- `SystemSetting`: `key` is the **string primary key** (no `id` column),
  `value` (Text), `description`, `updated_at`. Holds the live thresholds, which
  is why changing one changes matching behaviour without a deploy.

## Migration chain

Linear, five revisions. `alembic upgrade head` provisions the schema **and** the
access model: `56a8e0eed1a8` calls `ensure_permission_matrix`, so roles and
permissions exist without a separate seed.

| Order | Revision | File | What it does |
|---|---|---|---|
| 1 | `a8c4ffbe90bd` | `a8c4ffbe90bd_initial_schema.py` | 17 of the 21 tables plus all indexes. Base revision (`down_revision = None`). |
| 2 | `56a8e0eed1a8` | `56a8e0eed1a8_permission_matrix_and_hospital_role.py` | Creates `permissions` + `role_permissions`, seeds the matrix via `ensure_permission_matrix`, introduces the `hospital` role. |
| 3 | `b32e84ef129d` | `b32e84ef129d_emergency_session_access_token.py` | Adds `emergency_sessions.access_token_hash`; force-expires pre-existing `active` sessions that have no hash. |
| 4 | `c74d0b1e8fa2` | `c74d0b1e8fa2_guided_biometric_enrollment.py` | Creates `biometric_enrollments` + `biometric_enrollment_samples`, including `baseline_offset_x/y` and the composite index. |
| 5 | `eabc34d087df` | `eabc34d087df_incident_events.py` | Creates `incident_events` with its `session_id` index and the `(session_id, sequence)` unique constraint. |

## Working with the schema

```bash
cd backend
.venv\Scripts\python.exe -m alembic upgrade head                        # apply
.venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."   # after a model change
.venv\Scripts\python.exe -m alembic check                              # prove no drift
```

`migrations/env.py` takes its URL from `settings.DATABASE_URL` and sets
`compare_type=True`, so type drift is reported rather than ignored. After
changing a model, `alembic check` must report "No new upgrade operations
detected" once the migration exists, and the demo seed must remain idempotent on
the migrated schema - re-seed with
`python -m app.services.demo.seed` and confirm it does not duplicate rows.
