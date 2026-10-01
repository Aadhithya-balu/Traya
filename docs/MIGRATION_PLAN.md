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

**Phase 3 status: infrastructure verified on real Postgres, host blocked.** The
schema, the connection, the no-drift check and the fail-loud guarantee are all
proven against a live Postgres 16 with `pgvector` — including the full 207-test
suite. What remains needs a Supabase account: the project itself, Storage
buckets, and the hosted data migration. See the outcome section at the end of
this phase for the exact commands.

## Phase 1 - Unblock the emergency flow

**Problem.** The public emergency identification flow returns 403 on every step
after the first. The backend issues a session token the frontend never sends.
The Match Result tab can never render. Logout is reachable inside the emergency
UI.

### Changes

| File | Change |
| --- | --- |
| `api/types.ts` | Add `session_token` to `EmergencyStartOut`; add `Role`, `ConsentStatus`, `BiometricEnrollmentStatus`, `QualityScores` |
| `api/client.ts` | Store the session token; send `X-TRAYA-Session-Token` on every session-scoped call; add request timeout + `AbortController`; clear the rejected refresh promise in a `finally`; add `ApiError.isNetwork` |
| `pages/Emergency.tsx` | Pass the result through `EmergencyContext`, not router `state`; distinguish network failure from rejection |
| `pages/EmergencyHub.tsx` | Read from context; stop sending `source:"manual"` unconditionally; render the engine disclosure |
| `components/Layout.tsx` | Do not render `logout`/`admin` on emergency routes |
| `context/AuthContext.tsx` | Distinguish `loading` from signed-out; do not null the user on a transient failure |
| `pages/Profile.tsx` | Fix `ENROLLED` -> `enrolled`, `"granted"` -> `"active"` |
| `pages/Admin.tsx` | `registered` -> `registered_user`; add `hospital` |
| `context/EmergencyContext.tsx` | Store the session token; clear it when the session ends |
| `services/identification/engine.py` | Add `algo_version`, so a score is traceable to the engine build |
| `services/identification/pipeline.py` | Emit `algo_version` on every result |
| `schemas/__init__.py` | Add `algo_version` to `IdentifyOut`; **restore class indentation** |

### Gate

- A public, unauthenticated user completes capture -> identify -> result end to
  end.
- The Match Result tab renders, and `Confirm identity` is reachable.
- `Logout` is not reachable from any emergency route.
- A logged-in user who runs a full emergency cycle is still authenticated after
  (this is the regression test from Phase 8, written here).
- `npm run typecheck` and `npm run build` pass; `npm run docs:check` passes.

### Outcome

**Gate met, with one honest caveat.** `147 passed`, `npm run build` exit 0,
`npm run docs:check` exit 0.

The new `tests/test_frontend_contract.py` (17 tests) is the mechanism that
actually closes these bugs. With no frontend test runner, the backend suite is
the only place that can catch a client/server literal mismatch, so role names,
consent states, enrolment states and the emergency header are all asserted there
- against `ROLE_PERMISSIONS` and against live responses, not against a copy.

Three things this phase found that were not in the original list, and all three
are the same failure shape: **a bare `string` and one wrong comparison.**

1. `IdentifyOut` had lost its class indentation in `app/schemas/__init__.py`, so
   `quality`, `face_count`, `engine_mode` and `demo_mode` were module-level
   annotations. **The API had stopped returning them.** The client had already
   stopped reading `engine_mode`, so no test failed.
2. `"ENROLLED"` vs the API's `"enrolled"` - a citizen who had enrolled was shown
   NOT ENROLLED, and the only revoke control never rendered.
3. A result carried no way to identify which engine produced it. `algo_version`
   added end to end; without it, Phase 5's engine swap is indistinguishable from
   a regression.

Also completed here, since it was the same mechanism: the palette migration
(`ink-*` / `slate-*` -> ramp) and the `<alpha-value>` fix. These were nominally
Phase 2, but the contract test that catches an off-ramp colour belongs with the
Phase 1 suite, and the two phases touch the same files.

**Caveat: no browser, no camera, no E2E.** The tests prove the client sends
`X-TRAYA-Session-Token`, publishes the result through context, and keeps Logout
off `/emergency/*`. They do not prove a person can complete an identification on
a phone. Phase 13 is still the only thing that will.

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

### Outcome - passed, with two deviations and one gate item unverified

Everything in the gate is met except the eight-viewport check, which needs a
browser and is therefore Phase 13. Measured instead: zero fixed pixel widths
anywhere in `src/`, no `w-[Npx]` or `min-w-[Npx]`, every grid is single-column
below `sm`, the only `whitespace-nowrap` values sit inside a horizontal
scroller, and `body { overflow-x: hidden }` is still in place.

**The plan was wrong twice and the code was right twice.**

1. *Extend the spacing table with `5.5` and `13`.* Did not. `-translate-x-5.5`
   compiled to nothing because the theme knob is a `w-6` knob in a `w-12` track,
   so its travel is 1.5rem — `translate-x-6`. Adding `5.5` would have
   re-legalised the trap and left the knob still unmoved. The caller was wrong,
   not the scale. `13` is still unused.
2. *Darken `--c-faint`.* Cannot be done in dark mode — darkening a token
   separates it from a near-black canvas by making it invisible, and dark
   `--c-faint` was 3.91:1 partly for that reason. In dark mode `--c-faint` is
   *lightened* to `#86868c`. The second option the plan offered, restrict it to
   large text, was rejected: it is used for `.eyebrow`, placeholders and inactive
   tab labels, so restricting it would leave real text unreadable.

**Four further tokens failed the measurement, none of them on the list.** The
audit's own rule — a tinted pairing is the worst case — turned out to be the
whole story. Dark `--c-danger` was 4.35:1 on `raised` and 3.71:1 on its own
`bg-danger/15` badge; light `--c-warn` passed every plain-surface check at
5.20:1 and still failed at 4.26:1 on its tint; dark `--c-ok` failed at 4.40:1.
The camera-error bar was worse still — `bg-danger/90 text-text` is 3.18:1, and
the fix was `text-accent-fg`, a token the ramp already had for exactly this
question. All of it is now asserted by `backend/tests/test_contrast.py` (41
tests), which enumerates `bg-{tone}/{10,15,90}` over every background in both
themes.

Also landed, because they were the same class of silent failure:
`test_spacing_uses_only_values_in_the_theme_table` now scans `translate-[xy]`
and `scroll-m*` (it previously omitted `translate`, so it could not have caught
the bug it was written for); the dead duplicate `.dark` block in `index.css` is
gone; `Admin` and `EmergencyHub` were hand-rolling `flex overflow-x-auto` instead
of the composed `.scroll-x`; and `prefers-reduced-motion` was already global,
contrary to the plan's claim that it covered only the sheet entry — it now has a
test.

**One more silent failure, found while verifying the above.** Tailwind's content
scanner does not strip comments, so a class named in a comment is a class the
scanner sees and the rule is emitted. The comment explaining why the app bar's
blur was removed named it, and the build shipped a `.backdrop-blur` rule for a
utility nothing used — the same "unused class" trap `.tap` fell into, one level
down. The comments now avoid class syntax, and
`test_no_utility_name_appears_only_in_a_comment` fails the build if one returns.

189 backend tests pass, frontend typecheck and build pass, `docs:check` passes.
(207 after Phase 3, which adds 18 more.)

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

### Outcome - infrastructure verified on real Postgres, host still blocked

Supabase is Postgres with `pgvector` and a Storage API. A local
`pgvector/pgvector:pg16` container is close enough to prove the parts that were
previously unprovable: SQLite has no `vector` extension, no row-level security,
and different behaviour on some type comparisons, so **every "Postgres works"
claim made before this point was untested**.

**Done and verified against real Postgres 16.15:**

| Item | Result |
|---|---|
| `DATABASE_ALLOW_FALLBACK` defaults off, refused in production | Complete. |
| All 4 Alembic migrations apply to Postgres | `EXITCODE=0`, 22 tables created. |
| `alembic check` reports no drift on Postgres | `EXITCODE=0`, "No new upgrade operations detected." |
| `psycopg` connects, `/api/health` resolves | `backend=postgres`, `dialect=postgresql`, `connect=True`, 22 tables. |
| **Full test suite on Postgres** | **207 passed** — same 207 as SQLite, over **three consecutive runs**. |
| Full test suite on SQLite, unchanged | **207 passed.** |
| Dead primary fails to start | `EXITCODE=1`, `ConnectionTimeout`. Did not fall back. |
| `/api/health` survives a database killed mid-flight | `HTTP 200`, `state=disconnected`, `connect=False`, URL masked. |
| `pgvector` + `pgcrypto` install and are visible to `psycopg` | Both created, `pg_extension` lists them. |
| Seeded permission matrix on Postgres | 7 roles, 18 permissions — matches the counts in `AGENTS.md` §2. |
| **Emergency identification, end to end, on Postgres** | Session started unauthenticated, identify returned `200` / `HIGH_CONFIDENCE` / 0.995, candidate `accepted`, `engine_mode=simulation`. Seeding, Fernet encryption, matching, tiering and quality scoring all work. |
| Row counts match the dev database | 9 users, 12 embeddings, 8 consents — 12 embeddings identical to `traya.db`. |

### What to run in the Supabase SQL editor

Two files, in order. Both idempotent, both executed against real Postgres 16
before being committed — not written blind.

| Order | File | Purpose |
|---|---|---|
| 1 | `migrations/supabase/001_extensions.sql` | `create extension vector, pgcrypto` + an assertion that both exist |
| 2 | `migrations/supabase/002_storage_buckets.sql` | Two private buckets, optional |

**Then `alembic upgrade head`, not a pasted schema.** All 22 tables and the
permission matrix come from Alembic. A hand-written schema in the editor creates
a second source of truth that the next `alembic check` will contradict. This is
why the plan's `003_functions.sql` and `004_seed_roles.sql` were not written:
they would duplicate the Alembic seed in `56a8e0eed1a8`, and the permission
matrix should have exactly one definition.

Both files were run twice against the same database to prove idempotency: second
run reported `INSERT 0 0` and `extension already exists, skipping`, exit 0.
Alembic applied cleanly *after* them, on a database where neither extension had
existed beforehand.

**Why there is no `face_embeddings` table, which the plan does call for.** The
mapping to a pgvector column cannot be done yet, and the reason is not a missing
project. `biometric_embeddings.embedding_blob` is a `bytea` column of
**Fernet-encrypted** numpy bytes (`registry.py:23`, `recognition.py:72`); a
pgvector column holds plaintext float4, and ciphertext does not go in. Adding the
table now would create an empty column that nothing reads while the real data
stayed in a form pgvector cannot index or search — a table that looks like a
completed migration without one having happened.

It also collides with a security decision: `AGENTS.md` §3.27 and
[ADR 0005](decisions/0005-biometric-encryption-at-rest.md) put embeddings behind
encryption at rest with no re-encryption migration. Storing searchable plaintext
vectors changes that posture, which is a Phase 4 decision about access, not a
schema paste. The extension is enabled so the step is one command when it is
ready. **This is a deviation from the plan's entity mapping and it is
deliberate.**

Commands, so none of this is taken on trust. Both migration commands exited 0;
the suite reported 207 passed; the final boot exited 1.

```powershell
docker run -d --name traya-pg -p 54329:5432 `
  -e POSTGRES_PASSWORD=traya_local_dev -e POSTGRES_USER=postgres `
  -e POSTGRES_DB=traya pgvector/pgvector:pg16

cd backend
$env:DATABASE_URL="postgresql+psycopg://postgres:traya_local_dev@127.0.0.1:54329/traya"
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check

$env:TRAYA_TEST_DATABASE_URL="postgresql+psycopg://postgres:traya_local_dev@127.0.0.1:54329/traya_test"
.venv\Scripts\python.exe -m pytest
Remove-Item Env:\TRAYA_TEST_DATABASE_URL

docker stop traya-pg
.venv\Scripts\python.exe -c "import app.main"
```

`TRAYA_TEST_DATABASE_URL` is a `conftest.py` addition. Unset, the suite runs
on a temp SQLite file exactly as it always did.

**Still blocked, and genuinely so:** step 1 (create the project) and the
hosted-project run. `SUPABASE_URL` and the two keys are credentials — they
cannot be derived, guessed or generated. Everything else in this phase is done,
tested, or deliberately declined.

| Step | State |
|---|---|
| 1. Record the four `SUPABASE_*` values | Slots ready in `backend/.env`, empty. Needs the account. |
| 2. Install `supabase` / `pgvector` | `psycopg` 3.3.4 present; `vector` verified working in Postgres. The Supabase SDK is only needed for Phase 11. |
| 3. Write `migrations/supabase/*.sql` | **Done, with a deviation.** `001_extensions.sql` and `002_storage_buckets.sql` exist and are tested. `003`/`004` deliberately not written — they would duplicate the Alembic seed. No `face_embeddings` table; see above. |
| 4. Enable `pgcrypto` + `vector` | **Done and tested.** `001_extensions.sql` creates both and asserts them. |
| 5. Storage buckets | **Done and tested.** Two private buckets. Retention policies are dashboard work and remain outstanding. |
| 6. Explicit opt-in fallback | **Complete.** |
| 7. Data migration + row-count verification | **Partly done.** Row counts verified on a fresh Postgres (9 users, 12 embeddings, 8 consents). Moving the existing dev rows across is a separate step and remains. |

**Step 3 is still not written, and that is a judgement worth stating.** The
entity mapping renames 19 tables and rewrites the embeddings column to
`vector(320)`. Writing it blind produces a migration set that has never been
applied — the "aspirational doc is worse than no doc" failure. It becomes
writable the moment there is a project to apply it to.

**Gate status:**

| Gate item | State |
|---|---|
| Schema applies cleanly | **Pass on Postgres 16** via Alembic, after `001_extensions.sql`. Not yet on Supabase. |
| `psycopg` connects, queries work | **Pass.** 207 tests, plus a live emergency identification. |
| Data migration verified: counts + spot-checks | **Counts pass** on a freshly seeded database. Migrating existing dev rows is not done. |
| Dead primary fails to start | **Pass, proven by stopping the container.** |
| `alembic check` no drift | **Pass on Postgres** (`EXITCODE=0`). |

**What is left needs the account:** run the two SQL files on the hosted
project, point `DATABASE_URL` at it, run `alembic upgrade head`, and set the
four `SUPABASE_*` values. Step 7's row migration has not been written — with no
real user data in existence (all demo), re-seeding is the honest migration and
the plan says so.

**Three defects found by running it, none on the plan's list:**

- **`/api/health` could not answer the question it exists to answer.**
  Resolution sat outside the never-raise guard. With the fallback off — the safe
  configuration created moments earlier — `initialize()` raised inside
  `health()`, so the endpoint designed to report a failed database returned
  500. Resolution is now inside the guard.
- **A dead primary at *boot* never reaches `/api/health` at all.**
  `session.py:14` calls `db_service.initialize()` at module level, so the
  process dies during import. That is the correct outcome for a dead primary
  (fail fast) but it means health's "unresolved" branch is only reachable for a
  database that dies *after* startup — which is why the test above kills the
  container mid-flight rather than before boot. Worth knowing before anyone
  relies on health to diagnose a boot-time outage: the evidence is the crash,
  not the endpoint.
- **The Postgres test mode I added passed once and then failed.** SQLite starts
  clean because the file is deleted; Postgres does not, so the second run hit
  `409 duplicate email` on four tests. I reported "207 passed on Postgres" from
  the first run before checking that it was repeatable. `conftest.py` now drops
  and recreates the `public` schema in that mode, verified over three
  consecutive runs. The generalisable point: **a single green run of a suite
  that manages its own state is not evidence the state management works.**
- **The plan's step 6 said "defaults off" and nothing about `DEMO_MODE`.** A
  permissive flag is still reachable by env var in production, one `kubectl edit`
  from re-authorising the loss. Two independent conditions, tested as a matrix.

**A measurement worth carrying into Phase 4, not a claim about it.** With zero
RLS policies (`rowsecurity` true on 0 of 22 tables) and a plain
`GRANT SELECT`, a browser-facing role could read **all 9 `users` rows, all 12
`biometric_embeddings` rows and every `audit_logs` row**. Phase 4's "three
policies that matter" are not defence-in-depth polish against a theoretical
reader; without them the anon key is a full data export. The role used for the
measurement was dropped immediately afterwards.

The `.env` path defect and the embedding-key hazard are in
[AUDIT.md](AUDIT.md#phase-3-opening-the-env-file-had-never-been-read).

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

**Measured, not assumed.** In Phase 3, against real Postgres 16 with the schema
applied, `pg_tables` reported `rowsecurity` true on **0 of 22 tables**. With a
plain `GRANT SELECT` and no policies, a browser-facing role could read all 9
`users` rows, all 12 `biometric_embeddings` rows, and every `audit_logs` row.
The measurement role was dropped immediately afterwards.

So these are not hardening. Without them the anon key is a complete data export,
and Phase 4 is the phase where Python-only authorization stops being the only
thing standing between a public JWT and the medical record. The gate below should
be read as the first real barrier, not the last one.

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

### Outcome

**Done, applied to the hosted project, and measured there rather than only on
local Postgres.** Decision recorded in
[ADR 0007](decisions/0007-rls-claims-and-live-role-resolution.md).

| Gate item | State |
|---|---|
| Each policy has a test asserting the denial path | **Pass.** 18 tests in `test_rls_policies.py`, plus 4 in `test_auth.py` |
| `registered_user` cannot select another user's clinical record | **Pass.** Asserted on the exact set of visible rows, not a count |
| `police_responder` cannot read blood groups | **Pass** |
| A user's own token cannot select from the embeddings | **Pass, and refused** — permission denied, not an empty result |
| A valid token cannot escalate to `admin` by editing the payload | **Pass.** Both halves tested: a forged signature is 401, and a *correctly signed* token claiming `admin` is 403 because roles come from the database |

Verification run after applying, through a throwaway `LOGIN` role granted
`traya_api` against real hosted rows, is recorded in
[SECURITY_MODEL.md](SECURITY_MODEL.md#rls-is-enabled-on-all-22-tables-and-it-filters).
The application was re-checked afterwards and still serves its own traffic:
health connected on all 22 tables, admin login, user list, emergency start and
identification all 200, anon key still 401 on four tables.

Four things this phase changed beyond adding policies, each of which was a
defect found by the tests rather than by review:

1. **`caller_has` was blind to `users.is_active`.** A deactivated account kept
   every permission-gated policy passing. The check now lives in the helper
   rather than being assumed from a sibling.
2. **Responder access was unscoped.** "Permission AND any active incident" gave
   any responder with an open incident every blood group in the system. It is now
   scoped to the incident's `identified_user_id`.
3. **`traya_api` had no grants at all**, so the hosted policies were decorative —
   a role with no `USAGE` on the schema reads nothing, and "no leakage" would
   have been true for the wrong reason. The grants are in `007`, applied through
   `current_schema()` so the same file works on hosted `public` and on the test
   schema.
4. **The helpers had to become `SECURITY DEFINER`.** With RLS on every table, an
   invoker helper reads zero rows and returns `false` forever.

Also recorded because it will bite the next person editing these scripts: they
contain **no percent signs anywhere**, comments included, and use `quote_ident`
rather than `format`. psycopg validates percent sequences even with no parameters
and rejects any specifier that is not its own.

**Deliberately not done.** `FORCE ROW LEVEL SECURITY` is not enabled, so the
application — which owns the tables — still bypasses these policies and remains
authorized in Python alone. `traya_api` is `NOLOGIN` and nothing uses it yet. A
client path needs a login role granted `traya_api` plus per-transaction
`set_config('request.jwt.claims', ...)`; that plumbing is not written.

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

### Outcome - Phase 5 complete

**Delivered.** `providers.py` with `YuNet128Provider` (real) and
`SimulationProvider` behind `FaceEmbeddingProvider`; `engine.py` rewritten behind
the unchanged `BiometricEngine` interface; five-landmark 112x112 alignment;
cosine similarity on L2-normalised vectors; `mean_center` and `compare_centered`
deleted. **No new Python dependency** - OpenCV's DNN runtime runs both models.

**Every gate item passes**, asserted in `backend/tests/test_real_engine.py` and
elsewhere. Verification run after this phase: **252 passed on Postgres, 228
passed + 24 skipped on SQLite, `docs:check` passes across 31 pages.**

**Decisions that differ from the plan above, and why.** The plan's step 1 said
install `onnxruntime`. It was evaluated and **not** installed - it publishes a
`cp314` wheel and so was available, but `cv2.FaceDetectorYN` and
`cv2.FaceRecognizerSF` already run both chosen models, and a second inference
runtime is a dependency with no offsetting benefit. Recorded in
[ADR 0008](decisions/0008-real-biometric-engine.md) so it is not re-derived.

**Two plan steps are partially done, stated plainly rather than claimed.**
Step 8 (persist `embedding_model`, `embedding_dimension`,
`preprocessing_version`, `registration_version` as separate columns) is done as
**one** column, `algo_version`, carrying the engine's version string
(`sface-128d-v1` vs `traya-pseudo-embedding-v2`). That is sufficient for
correctness - it is what stops two vector spaces being compared - and the
dimension is available from `BiometricEngine().dimension`. Adding the four
separate columns is a schema migration and belongs with Phase 10's calibration
work, where the version changes for the first time anyway. Step 10 (the margin
rule for `MULTIPLE_CANDIDATES`) is **not** done; that status does not exist yet
and is Phase 6/7 work on the guided-capture path.

**One real bug this phase found and fixed, worth reading.** Enrollment wrote
`settings.BIOMETRIC_ALGO_VERSION` while `load_enrolled` filtered on
`get_engine().algo_version`. Under simulation those are the same string, so the
suite passed; under the real engine they differ, and every template would have
been invisible to the matcher - enrollment would succeed, the profile would read
"enrolled", and no match would ever be returned. All four write sites now use the
live engine's version, and `test_enrolled_templates_carry_the_active_engine_version`
fails if that ever diverges again.

**What is deliberately not claimed.** The thresholds are the simulation's. The
real engine's measured figures - 0.8977 same-identity, 0.2792 worst
cross-identity - come from three photographs of two people and demonstrate the
pipeline, not accuracy. FAR, FRR, EER, the per-condition breakdown and latency
remain unmeasured and the results tables in
[MODEL_EVALUATION.md](MODEL_EVALUATION.md) are still empty by design. Phase 10
fills them.

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

### Outcome - Phase 6 complete

**Delivered.** Enrollment no longer stores the samples; it stores **one
normalised centroid** of them. `complete_enrollment` decrypts the accepted
vectors, measures every unordered pair against each other through the live
engine, refuses the set below `ENROLLMENT_MIN_SELF_SIMILARITY`, writes the mean,
and **deletes the pending sample rows in that same transaction**. On the frontend
the 2-4 file upload is deleted: `EnrollWizard` drives `startEnrollment`,
`submitEnrollmentSample`, `completeEnrollment` and `cancelEnrollment`, one
capture at a time, and every one of the 25 `enroll.*` keys is referenced.

Verification run after this phase: **258 passed on Postgres, 234 passed + 24
skipped on SQLite, `docs:check` passes across 31 pages, frontend typecheck and
build pass, 16 real-engine tests pass under `BIOMETRIC_ENGINE=yunet`.**

**The gate item that changed the design is retention.** Purging is tied to a
*committed template*, not to an attempt, and that distinction is the whole
decision. A successful `complete` deletes every sample row for the enrollment -
accepted and rejected alike, because each was a biometric derived from someone's
face - leaving the enrollment row as an audit record that keeps quality and pose
reports and no vectors. A **refused** set keeps its samples: that is the one
failure where they are the only diagnostic, since the person cannot see their own
pairwise scores, so an unexplained 422 would otherwise be impossible to
investigate. `sample_vectors_purged` is in the audit details so the count is
checkable after the fact.

**Consistency validation is the part that cannot be left implicit.** Per-image
quality gates cannot detect a wrong person: four individually good photos of two
different faces satisfy every gate in the engine, and an enrolment assembled
carefully-but-haphazardly becomes a template that represents nobody and, at the
review threshold, could match a stranger. The threshold itself is **not
calibrated** - 0.62 is copied from `REVIEW_THRESHOLD` because it is a placeholder,
not a measured false-rejection floor - and Phase 10 replaces it. It is also not
seeded into `system_settings`, unlike the five match thresholds, so the env var
is the only place it lives.

**Three defects were retired by deleting the upload path**, not by fixing it. The
"2-4" label promised a minimum the page never enforced, the 4-image cap silently
discarded images already collected when a later file exceeded 3 MB, and the
person was never told which pose was being asked for. The bulk
`POST /biometric/enroll` endpoint still exists on the backend for the demo seed
and its tests; only the client stopped calling it.

**The accessibility risk above did not materialise**, because the backend already
answered it: `MIN_ACCEPTED_SAMPLES` is 3 against 5 offered steps, and pose
mismatch is reported rather than rejected, so two steps are always skippable.
That is a property of the existing service, not of anything added here, and it
holds for pose failure only - a person the **quality** gates refuse (blurred,
dark, occluded) still cannot complete, which is a genuine unresolved case for an
injury or a disability.

**What is not claimed.** No browser has run this. The wizard is verified by
typecheck, build and the server-side contract tests, **not** by a person holding
a phone, and the real engine has still never been run against a live camera.
`ENROLLMENT_MIN_SELF_SIMILARITY` has no measured distribution behind it. Phase 5's
step 10 (the `MULTIPLE_CANDIDATES` margin rule) remains undone.

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
