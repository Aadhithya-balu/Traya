# TRAYA Migration Plan

[docs/README.md](README.md) · Phase 2 deliverable. Follows
[TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md), which it implements. Current
state is in [AUDIT.md](AUDIT.md).

## How to use this plan

Thirteen phases. **Each phase ends at a gate that must pass before the next
starts.** A phase that fails its gate is not partially merged - it is finished
or reverted.

Three things are never done in the middle of the plan, because all three can
lose data or break a working flow:

1. **Never delete the SQLite database.** It is the rollback path until Phase 13
   passes.
2. **Never switch the default database before the migration is verified
   row-for-row.**
3. **Never replace the biometric engine without keeping the simulation
   available.** The simulation is what makes the demo honest and the tests
   fast. It is labelled, not deleted.

## Phase order and why

```
 1  Unblock the emergency flow      fixes the product's core failure first
 2  Fix the frontend design system  unblocks all later UI work
 3  Stand up Supabase               parallel track, no dependency on 1-2
 4  RLS                             requires 3
 5  Replace the biometric engine    requires 1
 6  Guided registration             requires 5
 7  Emergency workflow and fallback requires 5, 6
 8  Auth preservation test          requires 7
 9  Rebuild the UI                  requires 7
10  ML evaluation                   requires 5, and calibrates 7
11  Security pass                   requires 3, 4
12  Documentation                   continuous, formalised at the end
13  End-to-end verification         the definition of done
```

Phases 1 and 2 come first because they are **pure bug fixes against a working
system**. They can be shipped on their own, they need no new infrastructure, and
phase 1 fixes the thing that makes the product not work at all.

Phase 3 runs on its own track because Supabase setup is waiting on a project URL
and keys. It can proceed while phase 1 is in review.

## Phase 1 - Unblock the emergency flow

**Problem.** The public emergency identification flow returns 403 on every step
after the first. The backend issues a session token the frontend never sends.
The Match Result tab can never render. Logout is reachable inside the emergency
UI.

### Changes

| File | Change |
| --- | --- |
| `api/types.ts` | Add `session_token` to `EmergencyStartOut` |
| `api/client.ts` | Store the session token; send `X-TRAYA-Session-Token` on every session-scoped call; add request timeout + `AbortController`; clear the rejected refresh promise in a `finally` |
| `pages/Emergency.tsx` | Pass the result through `EmergencyContext`, not router `state` |
| `pages/EmergencyHub.tsx` | Read from context; stop sending `source:"manual"` unconditionally |
| `components/Layout.tsx` | Do not render `logout`/`admin` on emergency routes |
| `context/AuthContext.tsx` | Distinguish `loading` from signed-out; do not null the user on a transient failure |
| `pages/Profile.tsx` | Fix `ENROLLED` -> `enrolled`, `"granted"` -> `"active"` |
| `pages/Admin.tsx` | `registered` -> `registered_user`; add `hospital` |
| `context/EmergencyContext.tsx` | Store the session token; clear it when the session ends |

### Gate

- A public, unauthenticated user completes capture -> identify -> result end to
  end.
- The Match Result tab renders, and `Confirm identity` is reachable.
- `Logout` is not reachable from any emergency route.
- A logged-in user who runs a full emergency cycle is still authenticated after
  (this is the regression test from Phase 8, written here).
- `npm run typecheck` and `npm run build` pass; `npm run docs:check` passes.

### Risk

Low. No schema, no auth redesign. The behaviour change is that the emergency
flow starts working, which may surface latent UI bugs.

## Phase 2 - Fix the frontend design system

**Problem.** 19 opacity utilities generate no CSS. The fixed app bar and tab bar
have **no background**, so content scrolls visibly under both. Five pages are on
the removed palette. `.tap` - the documented 44px touch target - is purged.

### Changes

| File | Change |
| --- | --- |
| `index.css` | Convert ramp variables to space-separated RGB channels so Tailwind can compose them |
| `tailwind.config.js` | Add `<alpha-value>` to every ramp colour; extend the spacing table with `5.5`, `13` |
| `index.css` | Delete the dead `.dark .card` parallel palette (~20 lines that match nothing) |
| `EmergencyHub`, `Admin`, `Profile`, `Demo`, `Privacy` | Migrate 22 `ink-*` and 112 `slate-*` classes to ramp tokens |
| `index.css` | Darken `--c-faint` to clear 4.5:1, or restrict it to large text |
| `index.css` | Honour `prefers-reduced-motion` for `animate-fade-in` and `animate-pulse`, not just sheet entry |

### Gate

- `bg-ok/15`, `bg-surface/95` and the other 17 utilities emit CSS.
- Both fixed bars have an opaque-enough background that content does not show
  through.
- `.tap` is present in the built bundle.
- `--c-faint` clears 4.5:1 in both themes.
- Zero `ink-*` or `slate-*` classes remain in `src/`.
- Verified at 320, 375, 390, 414, 768, 1024, 1280 and 1440px with no horizontal
  overflow.

### Risk

Low, but visual. Every page changes appearance. This is the phase most likely to
surface "it looked fine before" complaints, and the answer is that before it was
rendering nothing.

## Phase 3 - Stand up Supabase

**Problem.** SQLite is the default. No Supabase, no pgvector, no RLS, no
Storage, no pgvector extension, no Supabase Auth.

### Steps

1. Create the Supabase project. Record `SUPABASE_URL`,
   `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PROJECT_REF`.
2. Install `supabase` and `pgvector` into `backend/.venv`.
3. Write the migration set as plain SQL under `backend/migrations/supabase/`
   (`001_schema.sql`, `002_rls.sql`, `003_functions.sql`, `004_seed_roles.sql`)
   plus a data migration from the current 19 tables.
4. Enable `pgcrypto` and `vector`.
5. Create the Storage buckets with retention policies.
6. Replace `DatabaseService`'s **silent** fallback with an explicit, logged,
   opt-in fallback that defaults **off**, and fails startup in production mode.
7. Run the data migration, then verify row counts and spot-check records.

### Entity mapping

| Current table | Target |
| --- | --- |
| `users` | `auth.users` (Supabase-managed) + `profiles` |
| `users.role` | `user_roles` |
| `medical_profiles` | `emergency_profiles` |
| `emergency_contacts` | `emergency_contacts` |
| `biometric_profiles` | `biometric_profiles` |
| `biometric_embeddings` | `face_embeddings` (pgvector) |
| `biometric_enrollments` | `biometric_enrollments` |
| `biometric_enrollment_samples` | `enrollment_samples` |
| `consents` | `consent_records` |
| `audit_logs` | `audit_logs` |
| `emergency_sessions` + attempts | `emergency_incidents` + `incident_events` |
| `locations` | `incident_locations` |
| `hospitals`, `notifications`, `system_settings`, `visible_features`, `roles`, `permissions` | unchanged |

### Embedding migration problem

**The existing vectors cannot be migrated.** They are 12 brightness features
zero-padded to 320 dims. There is nothing to carry across. This is correct and
must be stated plainly rather than papered over:

> Migrating to Supabase moves **identities, medical profiles, contacts,
> consents, incidents and audit history**. Biometric embeddings must be
> **re-enrolled** after Phase 5, because the current vectors are not embeddings
> in any transferable sense.

Demo accounts are re-seeded. No real user data is lost, because none exists.

### Gate

- Schema applies cleanly to a fresh Supabase project.
- `psycopg` connects and every current query works.
- Data migration verified: row counts match, spot-checked records match.
- With `DATABASE_URL` pointing at Supabase and the network down, the app **fails
  to start** instead of silently using SQLite.
- `alembic check` reports no drift.

### Risk

**Medium - the highest-risk phase in the plan.** Mitigated by: SQLite is never
deleted; the migration is a separate SQL script, not an Alembic rewrite; and the
row-count verification is a gate, not a suggestion.

## Phase 4 - Row Level Security

**Depends on** Phase 3. **Cannot start before it** - RLS without a real Postgres
is untestable.

### Changes

1. Enable RLS on every table.
2. Write `caller_roles()` and `caller_has()` from the JWT.
3. Policies per the table in
   [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md#row-level-security).
4. `SECURITY DEFINER` search function returning `(profile_id, score)` only.
5. Service-role connection for writes, scoped by permission in Python.
6. Tests asserting denial directly against the database, bypassing FastAPI.

### The three policies that matter

1. **No client policy grants direct read of `face_embeddings`.**
2. **Responder clinical access requires an active incident**, not just a role.
3. **Users cannot read their own vectors.**

### Gate

- Each policy has a test that asserts the denial path, not only the allow path.
- A token with `registered_user` cannot select from `emergency_profiles` for
  another user.
- A token with `police_responder` cannot read blood groups.
- A user's own token cannot select from `face_embeddings`.
- A test proves an attacker with a valid token cannot escalate to `admin` by
  changing the JWT payload (signature check rejects it).

### Risk

Medium. Over-tight policies lock responders out mid-emergency, which is worse
than over-permissive ones in this product. Mitigation: `police_responder` and
`medical_responder` get a synthetic end-to-end test each, so a policy that
breaks a real emergency flow fails CI rather than production.

## Phase 5 - Replace the biometric engine

**The core work.** Everything until now is infrastructure.

### Steps

1. Install `onnxruntime` (wheel-only; no compiler on Windows).
2. Download the YuNet ONNX detector. OpenCV 5 already exposes
   `FaceDetectorYN` - verified present on this machine - so detection needs no
   new Python package.
3. Obtain a 128D ONNX embedding model. Record name, version, licence.
4. Implement `FaceEmbeddingProvider`. Two implementations:
   `YuNet128Provider` (real) and `SimulationProvider` (kept, labelled).
5. Rewrite `engine.py` behind the **existing** `BiometricEngine` interface:
   `process`, `embed`, `pose`, `similarity`, `is_simulation`.
6. Real alignment from YuNet's 5-point landmarks via `estimateAffinePartial2D`.
7. Preprocessing: 112x112 RGB, normalised, documented as
   `preprocessing_version`.
8. Persist `embedding_model`, `embedding_version`, `embedding_dimension`,
   `preprocessing_version`, `registration_version`.
9. Switch `compare()` to cosine similarity on L2-normalised vectors.
10. Add the margin rule for `MULTIPLE_CANDIDATES`.
11. Delete `mean_center()`, `compare_centered()`, and the unreachable branch in
    `estimate_pose`.

### The 128D requirement, stated correctly

**128-dimensional**, not 128-bit. A 128D float32 vector is 512 bytes.
Dimensionality is how many numbers; bit size is how many bits each. The schema
stores `embedding_dimension = 128` and both the model name and version, so a
future switch to ArcFace-512D is a data migration and not a rewrite.

### Engine interface: unchanged

```python
class BiometricEngine:
    mode: str
    def process(self, image_bytes) -> DetectionResult: ...
    def embed(self, image_bytes, box=None) -> np.ndarray: ...
    def pose(self, image_bytes, box=None) -> PoseEstimate: ...
    def similarity(self, a, b) -> float: ...
    @property
    def is_simulation(self) -> bool: ...
```

Every existing caller keeps working. `pipeline.py` does not change.

### Gate

- Real detection on a real photograph, with a real bounding box.
- A 128D embedding from the ONNX model, not padded.
- Cosine similarity, L2-normalised.
- Alignment demonstrably corrects roll.
- `BIOMETRIC_ENGINE=simulation` still works and still returns
  `is_simulation=True` - the demo path is not broken by this phase.
- Same-identity similarity clearly exceeds cross-identity similarity on a real
  test set.
- Model versioning persists and round-trips.
- Full backend suite still passes.

### Risk

**High.** This is where accuracy claims are won or lost. Mitigation: the
simulation stays available so every other phase is testable; thresholds are
**not** carried over from the old engine, so phase 10 calibrates them from
measurements rather than inheriting meaningless numbers.

## Phase 6 - Guided registration

**Depends on** Phase 5.

1. Add `face_samples`.
2. Extend the existing `BiometricEnrollment` lifecycle - `current_step`,
   `status`, per-sample rows already exist and are reused.
3. Five guided steps with pose guidance from the real pose estimate.
4. Per-sample quality gate, rejecting with the **specific** reason from the
   existing `reason_codes` so the panel and the wizard cannot disagree.
5. Consistency validation: pairwise similarity between the person's own samples
   must clear a bound, or the template is not created.
6. Build the template as a centroid; record intra-person spread.
7. Encrypt, store, version.
8. Build the guided registration UI. **The 25 `enroll.*` Tamil strings already
   exist** - wire them rather than writing new copy.
9. Delete the 2-4 file upload path from `Profile.tsx`.

### Gate

- A user completes guided capture end to end.
- A rejected sample states a specific, actionable reason in both languages.
- A deliberately inconsistent capture set is refused at `complete`.
- An abandoned enrollment can be resumed or discarded.
- All 25 `enroll.*` keys are referenced.
- Samples are purged once the template exists, per the retention policy.

### Risk

Medium. The most common failure is a user who cannot satisfy the pose steps on
an injury or a disability. The wizard must allow skipping a step, not block on
it.

## Phase 7 - Emergency workflow, fallback and incidents

**Depends on** 5 and 6.

1. Emit `incident_events` for `INCIDENT_CREATED`, `FACE_CAPTURE_STARTED`,
   `FACE_DETECTED`, `MATCH_ATTEMPTED`, `MATCH_FOUND`, `MATCH_REJECTED`,
   `PROFILE_ACCESSED`, `CONTACT_INITIATED`, `INCIDENT_RESOLVED`.
2. Implement the fallback paths: emergency identifier, manual responder entry,
   assisted verification, manual identification.
3. Every fallback writes an `incident_event`.
4. Incident statuses: `CREATED`, `IDENTIFYING`, `IDENTIFIED`,
   `REVIEW_REQUIRED`, `NO_MATCH`, `ASSISTANCE_IN_PROGRESS`, `RESOLVED`,
   `CANCELLED`.
5. Role-filtered result rendering, enforced against the RLS policies from
   Phase 4 rather than only in Python.
6. `MULTIPLE_CANDIDATES` as a distinct state from `REVIEW_REQUIRED`.

### Gate

- Every listed `incident_event` type is reachable and asserted.
- Police can complete a flow without ever seeing clinical data.
- Medical personnel see clinical data.
- A user with only `registered_user` can see nothing about another user.
- No confident match leads to a working fallback, never a dead end.
- Every fallback path is auditable.

### Risk

Medium.

## Phase 8 - Auth preservation test

**Depends on** Phase 7. Small, and the prompt's explicit Phase 8.

One test, and the acceptance criterion it encodes:

```python
def test_authenticated_user_stays_authenticated_through_emergency(client):
    # sign in
    # run a full emergency cycle: start, capture, identify, confirm
    # return to the app
    # assert /auth/me still succeeds and the user object is unchanged
```

Plus the reverse: a user who was never signed in is still not signed in
afterwards. Emergency Mode is a workflow state; it cannot create or destroy an
authentication state.

### Gate

- The test passes.
- `Logout` is unreachable from any emergency route.
- A transient `/auth/me` failure shows a retry, not a logged-out screen.
- `AuthContext` has `loading`, `authenticated`, `unauthenticated`, `error` as
  distinct states.

### Risk

Very low.

## Phase 9 - UI rebuild

**Depends on** Phase 7.

1. Emergency mode removes distraction: what to do now, what is happening, the
   result, the next step. No analytics, no profile chrome, no ML vocabulary.
2. All nine result states, each with a next action.
3. Five still-hardcoded pages fully localized: `EmergencyHub`, `Profile`,
   `Admin`, `Demo`, `Privacy`. Plus the English strings in `useCamera.ts`,
   `useGeolocation.ts` and `Guards.tsx`.
4. Move the catalogue to `locales/en.json` and `locales/ta.json`.
5. Accessibility: focus trap and restore in `Sheet`, roving tabindex in `Tabs`,
   live regions for capture and identification states, every input labelled,
   `prefers-reduced-motion` honoured everywhere.
6. Desktop surfaces: incident monitoring, responder workspace, user management,
   audit logs, analytics, system status.
7. Verify all eight breakpoints with no horizontal overflow.

### Gate

- Zero hardcoded user-visible English outside the catalogues.
- Tamil and English both complete, with no key missing from either.
- Every result state reachable, each with a working next action.
- Keyboard-only completion of the full emergency flow.
- A screen reader announces every capture and identification state.
- Verified at all eight breakpoints.

### Risk

Low. The design system from Phase 2 is the foundation.

## Phase 10 - ML evaluation

**Depends on** Phase 5. Calibrates the thresholds hardcoded from Phase 7.

1. Build a validation dataset across lighting, pose, expression, distance,
   occlusion, resolution, glasses.
2. Measure FAR, FRR, precision, recall, F1, ROC, EER, score-margin
   distribution, p50/p95 latency, quality-gate precision.
3. **Per condition**, not just aggregate.
4. Choose thresholds from the ROC at an explicit FAR target.
5. Store as `threshold_version` in `system_settings`; record the version on
   every decision.
6. For comparison, evaluate ArcFace-512D if a runtime permits, and record the
   result even though it is not selected.

### Gate

- Published numbers in `MODEL_EVALUATION.md`, with dataset, model, metric,
  methodology, and both error rates stated.
- Thresholds are traceable to a ROC point, not chosen by feel.
- The margin rule for `MULTIPLE_CANDIDATES` has a measured basis.
- Latency p95 is recorded and acceptable for an in-emergency flow.
- **No accuracy claim appears anywhere without a measurement behind it.**

### Risk

Low as engineering, high as a **claim-discipline** gate. If the numbers are bad,
the response is to publish them and say so, not to widen the threshold.

## Phase 11 - Security pass

**Depends on** Phases 3 and 4.

1. Secret scan. **No service-role key in frontend code** - enforced in CI.
2. Upload validation: magic bytes, decode limits, pixel-bomb guard, size cap.
3. Rate limiting per-IP and per-user; identification limited hard, since it is
   the enumeration vector.
4. CORS: explicit allowlist.
5. XSS, CSRF, SQL injection review.
6. Session-expiry handling across the whole app.
7. Confirm no endpoint returns embeddings, and add a test that asserts it.
8. Confirm no log line contains a raw vector or unredacted clinical detail.
9. Session storage migrated to httpOnly cookie.

### Gate

- No secrets in frontend code or the repo.
- An enumeration attempt is rate-limited and audited.
- A malicious upload is rejected without a 500.
- A test proves no endpoint returns an embedding.
- A test proves logs contain no vectors.

### Risk

Low.

## Phase 12 - Documentation

Continuous, formalised here. The existing contract stays: one H1, a
breadcrumb, and every endpoint, model, table, migration, repository method,
service function, setting, role, permission, page, component, icon, API method
and exported type named on its owning page.

Required technical documents: `01_Project_Overview` through
`26_Future_Scope`. Plus `NON_TECHNICAL.md` for reviewers, faculty and
non-technical stakeholders, and `MODEL_EVALUATION.md` from Phase 10.

### Gate

- `npm run docs:check` passes.
- Every claim in the docs matches the code. Where code and docs disagree, the
  code is right and the doc is a bug.
- Aspirational documentation is absent. Where a feature is incomplete, the docs
  say so plainly.

### Risk

Low, but this is the gate most often skipped and the one that keeps the next
agent from rediscovering everything from scratch.

## Phase 13 - End-to-end verification

The definition of done. The full workflow, run for real.

### Journeys

1. **Citizen registration** - signup, profile, emergency information, contacts,
   guided face registration, validation, complete.
2. **Emergency responder** - open, emergency, camera, capture, detection,
   matching, result, authorized information, incident.
3. **No match** - emergency, capture, no confident match, fallback, alternative
   identification, manual verification, response continues.
4. **Authenticated user starts an emergency** - logged in, emergency,
   identification, result, incident, **still authenticated**.

Plus: cross-role access, the fallback matrix, degraded-mode behaviour, and the
breakpoint sweep.

### Gate

- All four journeys pass.
- Backend suite green; frontend typecheck and build green.
- `npm run docs:check` green.
- A real photograph through a real 128D model produces a real decision.
- Every documented limitation is still true.
- No unsupported claim anywhere in the README or docs.

### Risk

None. This phase changes nothing.

## Dependency graph

```
1 emergency flow ──────────────┐
2 design system ────────────┐   │
3 Supabase ── 4 RLS ───────┤   │
5 engine ── 6 registration ┤   │
        └── 7 workflow ────┤   │
                └── 8 auth test
                └── 9 UI ───┤   │
10 evaluation ──────────────┤   │
11 security ────────────────┤   │
12 documentation ────────────┤   │
13 E2E ─────────────────────┴───┘
```

## Rollback

| Phase | Rollback |
| --- | --- |
| 1-2 | Revert the commit. No data involved. |
| 3 | **Keep SQLite.** Revert `DATABASE_URL`. The old path still works. |
| 4 | Disable RLS on the affected table. Documented per policy. |
| 5 | `BIOMETRIC_ENGINE=simulation`. The old path is preserved and tested. |
| 6-7 | Abandon in-progress enrollments. Incidents persist. |
| 8-9 | Revert. |
| 10 | Revert to the previous `threshold_version`. |
| 11-13 | Revert. |

Every phase has a rollback that does not lose data. **The one irreversible
action in this plan - deleting the SQLite database - happens only after Phase 13
passes, and it is not part of any phase.**