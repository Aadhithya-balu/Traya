# TRAYA — Agent Rules

**Read this before you change anything.** Then read the docs it points to. Do
not read the codebase to find out how it works — the answers are written down,
and the codebase will mislead you in at least one important place.

This file is authoritative and live. When a project fact changes, this file and
the owning docs page change with it.

---

## 0. START HERE

| You want to know | Read | Cost |
|---|---|---|
| What actually exists today | [docs/AUDIT.md](docs/AUDIT.md) | 1 page |
| Where this is going | [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md) | 1 page |
| What order to work in | [docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md) | 1 page |
| Anything, explained without jargon | [docs/NON_TECHNICAL.md](docs/NON_TECHNICAL.md) | 1 page |
| A specific subsystem | The 20 reference pages below | targeted |

**The 30-second version:** this is a well-built prototype whose centre is a
placeholder. The documentation, tests, API design, RBAC, audit trail and design
system are real and good — keep all of it. **As of Phase 5 there is a real face
detector and a real 128-dimensional face embedding** (YuNet + SFace, see
[ADR 0008](docs/decisions/0008-real-biometric-engine.md)). **The thresholds are
still the simulation's, and nothing is calibrated yet.** Everything else in this
plan is built around measuring that honestly.

---

## 1. THE ONE THING YOU MUST NOT GET WRONG

> **A real recogniser exists. It is only real if the model weights are on disk,
> and which engine ran is never a guess.**

This is stated here first because it is the trap that makes reasonable agents
wrong, and Phase 5 changed the shape of the trap.

### What was true before Phase 5, and is still true of the simulation

`engine.py` used to decide the engine mode with
`bool(hasattr(cv2, "CascadeClassifier"))`. Measured on this machine:

```
cv2.__version__                    -> 5.0.0     (installed)
hasattr(cv2, 'data')               -> True      (present)
os.listdir(cv2.data.haarcascades)  -> ['__init__.py', '__pycache__']   (EMPTY)
hasattr(cv2, 'CascadeClassifier')  -> False     (REMOVED in OpenCV 5)
```

Two independent reasons the old real path never executed: **`CascadeClassifier`
was removed in OpenCV 5**, and **the cascade directory contains no `.xml` files**
even if the class existed. So the guard was never entered, and
`BIOMETRIC_ENGINE=opencv` fell through to `_simulate_detect` and reported
`source="simulation"` anyway. `opencv` never meant what it said.

That is why the simulation embedding was twelve real numbers zero-padded to 320
(`np.pad(features, (0, EMBEDDING_DIM - features.size))`) — not 128D, not 320D,
twelve numbers and 308 zeros. That code still exists, as
`SimulationProvider`, and is still what `BIOMETRIC_ENGINE=simulation` runs.

### What is true now

**`providers.py` holds two implementations of one interface** —
`YuNet128Provider` (real: `cv2.FaceDetectorYN` + `cv2.FaceRecognizerSF`, five
landmarks, 112x112 alignment via `estimateAffinePartial2D`, 128D L2-normalised
descriptor, cosine similarity) and `SimulationProvider` (the old engine).
`get_provider()` resolves one, caches it per process, and logs the choice.

**The weights are not in the repository.** They live in `backend/.models/`,
fetched by `backend/scripts/fetch_biometric_models.py`, which verifies a pinned
SHA-256 per file and writes a `NOTICE`. So "does TRAYA detect faces?" is
answerable only by asking, not by reading:

```
cd backend; .venv\Scripts\python.exe -c "from app.services.identification import providers; print(providers.models_present())"
```

### The three rules that follow

1. **Never set `BIOMETRIC_ENGINE=opencv` expecting anything.** It is now an
   alias for `yunet` and logs a warning on every resolution. It exists only so an
   old `.env` does not silently keep meaning "give me a simulation".
2. **`yunet` raises if the weights are missing; `auto` falls back to simulation
   *and says so in the log*.** That asymmetry is deliberate: a deployment that
   asked for a recogniser and silently got a brightness comparator is the worst
   failure this project has.
3. **`settings.EMBEDDING_DIM` is 320 and describes only the simulation.** The
   real engine is 128D. Anything that sizes a buffer or stores a vector must
   read `BiometricEngine().dimension`, which reads through to the active
   provider — not the setting.

**And the disclosure still does the work.** Every result carries `engine_mode`
and `demo_mode`; templates are tagged with the engine's version string
(`sface-128d-v1` vs `traya-pseudo-embedding-v2`) so the two vector spaces are
never compared; and `similarity()` raises on a dimension mismatch rather than
returning a meaningless low score. **What is still missing is calibration** —
the seeded thresholds are the simulation's, and
[docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) has the real engine's
measured smoke-test figures and an explicit list of what is not yet measured.

**Also still absent: no face model beyond these two.** No liveness detection, no
deepfake defence, no ensemble. And the *asymmetry* pose reader is still the
simulation's brightness heuristic — the real engine reads pose from landmarks
and returns `unknown` for horizontal without a baseline.

---

## 1b. WHAT THE SIMULATION STILL IS, FOR THE RECORD

**Nothing was ever wrong with the design.** `BiometricEngine` exposes
`process` / `embed` / `pose` / `similarity` / `is_simulation`, and that interface
is correct and must be preserved. Phase 5 kept it and put `YuNet128Provider`
behind it, so every existing caller keeps working and no caller had to change.

**The simulation's own limits still stand, for anyone who selects it:**
`SimulationProvider` still produces twelve brightness statistics padded to 320,
still has no landmarks and no alignment, and its `PoseEstimate` is still
normalised brightness asymmetry. Its measured impostor similarity still reaches
0.817. Selecting it is a deliberate choice, made with `engine_mode` visible.

---

## 2. CURRENT HARD FACTS

Verified by running the code at commit `497e7af`. Full detail and reproduction
commands in [docs/AUDIT.md](docs/AUDIT.md).

| Fact | Value |
|---|---|
| Backend tests | **414 passed, 0 skipped** on real Postgres; **385 passed + 29 skipped** on SQLite |
| Backend tests on real Postgres | **414 passed, 0 skipped**, ~125s. Runs in a throwaway `traya_test` schema, **never `public`** — `TRAYA_TEST_DATABASE_URL` — see [operations/README.md](docs/operations/README.md#testing) |
| Hosted Supabase | **Live and verified.** PostgreSQL 17.11, 23 tables, RLS on 23/23 with 19 policies, 7 roles / 18 permissions, emergency flow HIGH_CONFIDENCE 0.995 |
| Frontend typecheck | **passes**, exit 0, strict TS |
| `npm run docs:check` | **passes**, 31 pages |
| Endpoints | **47** across 7 routers |
| Tables | **23** in `public` (22 ORM tables plus `alembic_version`), 4 Alembic migrations |
| Roles / permissions | **7** / **18** |
| Settings fields | **48**, all documented in `backend/.env.example` (was 20 of 36 — closed in Phase 11) |
| Evaluation harness | **built** — `python -m evaluation.run --manifest ...`; 62 tests. **No accuracy claim**, see [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) |
| Default database | **SQLite** (`sqlite:///./traya.db`) |
| `EMBEDDING_DIM` | **320** — describes the **simulation only**. The real engine is 128D; read `BiometricEngine().dimension` |
| Real engine | **YuNet + SFace 128D**, weights in `backend/.models/`, **not committed** |
| Real engine measured | same-identity **0.8977**, cross-identity **0.2573 / 0.2792**, 128 non-zero coords, norm 1.0. Three photographs, two people — **not an accuracy claim** |
| Thresholds | HIGH 0.82, REVIEW 0.62, FALLBACK_FACE 0.60, BOOST 0.05/0.06 — **still the simulation's, not calibrated** |
| Max impostor similarity (simulation) | **0.817** — 6 of 30 impostor pairs exceed the 0.62 review threshold |
| Rows in `face_embeddings` / pgvector | **none** — the column does not exist |
| RLS | **Enabled on 23 of 23, and it filters.** Policies are written for `traya_api`, a `NOLOGIN` role; `anon` gets 401 on every app table. **The application connects as table owner and bypasses its own policies** — `FORCE` is deliberately off. See [ADR 0007](docs/decisions/0007-rls-claims-and-live-role-resolution.md) and [SECURITY_MODEL.md](docs/SECURITY_MODEL.md#rls-is-enabled-on-all-23-tables-and-it-filters) |
| Storage buckets | **2, private**, created on the hosted project. Retention policies still to set in the dashboard |
| Supabase SDK | **not installed** — the app connects with `psycopg` as `postgres`, so nothing needs it |
| Frontend test runner | **none** |

### ML libraries available in `backend\.venv`

| Available | Missing |
|---|---|
| `cv2` 5.0.0 (`FaceDetectorYN` + `FaceRecognizerSF`, no cascade API) | `dlib`, `face_recognition`, `insightface` |
| `numpy` 2.5.2, `PIL` 12.3.0 | `onnxruntime`, `mediapipe`, `torch` |
| `psycopg` 3.3.4 | `supabase`, `pgvector` |

**NumPy, Pillow and the OpenCV DNN runtime are what Phase 5 uses, and no new
dependency was added.** `cv2.FaceDetectorYN` and `cv2.FaceRecognizerSF` are both
present in the installed OpenCV 5.0.0, so YuNet and SFace need only their weight
files.

`onnxruntime` 1.30.0 *was* evaluated and **deliberately not used**: it publishes a
`cp314` win_amd64 wheel, so it was installable, but OpenCV's DNN runtime already
runs both chosen models, and a second inference runtime is a dependency with no
offsetting benefit. Recorded in [ADR 0008](docs/decisions/0008-real-biometric-engine.md)
so it is not re-derived. `dlib`, `face_recognition`, `insightface` and `torch`
remain unusable on Python 3.14.2 without a compiler. ArcFace-512D would score
higher and is **rejected because the 128D requirement is explicit**; it must
still be measured and recorded, not dismissed.

### The bugs that will bite you — all five were fixed in Phase 1

Ranked in [docs/AUDIT.md](docs/AUDIT.md#bugs-ranked). These were the five that
mattered, kept here because the shape of each one recurs. **All five are fixed;
do not re-report them — the fixed list is in §7.** The present-tense description
below is the original defect, not the current state.

1. **The emergency flow 403s and cannot complete.** The backend issues a
   `session_token` (`emergency.py:180`) and requires it as an
   `X-TRAYA-Session-Token` header (`emergency.py:57-58`). The frontend has **no
   `session_token` field in its types** and never sends the header. Step 1
   returns 200, every step after returns 403. The product did not work.
2. **The Match Result tab can never render.** `Emergency.tsx:82` passes the
   result via router `state`; `EmergencyHub.tsx:26` reads `EmergencyContext` and
   never calls `useLocation()`. `setSession` has zero call sites.
3. **Logout is reachable inside the emergency UI.** `Layout.tsx:169-181` renders
   `moreItems` with no `isAuthed` gate, so `logout` appears on `/emergency/*`.
   One mis-tap during an emergency destroys the session. *This is the reported
   "emergency logs me out" complaint — there is no automatic logout; this is a
   reachable button plus `AuthContext` nulling the user on any `/auth/me` failure.*
4. **19 Tailwind opacity utilities generate no CSS.** Ramp colours are bare
   `var()` strings with no `<alpha-value>` (`tailwind.config.js:9-31`). The fixed
   app bar and tab bar have **no background**, so content scrolls visibly under
   both. Every status badge tint is missing too.
5. **Consent can never be withdrawn.** `Profile.tsx:177` checks `=== "granted"`;
   the backend returns `"active"`.

---

## 3. HARD-WON RULES — VIOLATIONS CAUSE BUGS

### Windows / shell

1. PowerShell 5.1. **Never use `&&`.** Use `cmd1; if ($?) { cmd2 }`.
2. **Never round-trip a UTF-8 file through `Get-Content` / `Set-Content`.**
   PS 5.1 reads a BOM-less UTF-8 file as the system ANSI codepage, so every
   em-dash and middle dot becomes mojibake, then writes it back *with* a BOM.
   This silently rewrote 41 lines of `MIGRATION_PLAN.md` before it was caught.
   Use the `read`/`edit`/`write` tools for file edits. If you must use the shell
   for anything, `Get-Content -Encoding UTF8` and `[System.IO.File]::WriteAllText`
   at minimum, and verify with `git diff` afterwards.
3. **PowerShell 5.1 `Set-Content -Encoding UTF8` writes a BOM.** This leaked
   `EF BB BF` into three `git commit -F` messages. Write message files with
   `[System.IO.File]::WriteAllText($p, $text)` or `[IO.File]::WriteAllLines`,
   or pipe via `-Encoding ascii` where the content is ASCII.
4. Vite binds `localhost` (IPv6 `::1`); uvicorn binds `127.0.0.1` (IPv4). Probe
   with an explicit host.
5. **`uvicorn --reload` spawns orphaned `multiprocessing-fork` workers** that
   inherit the listening socket and survive parent kills, holding port 8000.
   `dev-all.mjs` deliberately runs uvicorn **without** `--reload`. To clear a
   stuck port, kill processes whose commandline matches `uvicorn app.main:app`.
6. Python is 3.14.2. Use `.venv\Scripts\python.exe`, not bare `python`.

### Code style

7. **Do not add comments to code unless the user asks.**
8. **No emojis** in code, docs or replies unless the user asks.
9. **Prefer a composed class** from `@layer components` (`.btn`, `.card`,
   `.input`, `.badge`, `.tap`, `.eyebrow`, `.scroll-x`) over a long `className`.
10. **No `dark:*` variants.** Light and dark share one class name via CSS custom
    properties. `ink-*` / `slate-*` were **removed** — five pages still use them
    and are migrating.
11. **`theme.spacing` is `replace`, not `extend`.** `0.5` is 0.125rem, there is
    no `5.5` and no `13`. Anything outside the table **compiles to nothing** —
    the same silent failure as an opacity modifier on a ramp colour.
12. **44px minimum touch targets** via `.tap`. Phase 2 applied it, so it is no
    longer purged. An `@layer components` class that no component references
    emits **no CSS at all** — the same silent failure as a bare `var()` colour.
    Do not add a class and leave it unused.
13. **Contrast is measured, not eyeballed.** `backend/tests/test_contrast.py`
    asserts 4.5:1. A **tinted** pairing is always the worst case: `bg-{tone}/15`
    pulls the background toward `text-{tone}`, so light `--c-warn` measured
    5.20:1 on every plain surface and 4.26:1 on its own badge. Check the tinted
    pair.
14. **Do not name a Tailwind class inside a comment.** The content scanner does
    not strip comments, so a class mentioned in prose is a class the build emits
    a rule for. `test_no_utility_name_appears_only_in_a_comment` fails the build
    on it. Describe the utility in words instead.

### Frontend architecture

15. **All network calls go through `src/api/client.ts`.** Repo-wide, `fetch(`
    appears exactly twice, both inside the client. Never add a third outside it.
16. **Layout routes render `<Outlet />`, not `{children}`.** `App.tsx` wraps
    pages in `<Route element={<Layout />}>`.
17. **`EmergencyContext` is a guarded `JSON.parse`** against `sessionStorage`.
    Keep the guard.
18. **Every user-visible string is an i18n key, and that is now enforced.**
    Phase 9 closed the last five pages, so no page hardcodes English.
    `test_no_page_or_component_hardcodes_user_visible_english` fails the build
    when a literal appears in a `.tsx` page or component. Its exclusions are
    **named** (`Escape`, arrow-key names, `.querySelector`, the demo password),
    not pattern-matched loosely, because the loose version passed two of the
    three English strings that actually shipped. When you add an exclusion, add
    it with the reason and re-run the mutation check described in §7.
    A hook that produces user-visible text must expose a **code**, not a string:
    `useCamera` and `useGeolocation` both return codes mapped through
    `CAMERA_ERROR_KEYS` / `GEO_ERROR_KEYS`, because a hook returning English is
    English the Tamil UI cannot avoid.
18a. **Never write a user-visible string through a shell pipeline.** The
    i18n catalogues moved to `i18n/locales/*.json` in Phase 9 for exactly this
    reason: `hub.engine.simulationTitle` and `hub.engine.simulationBody` were
    written through PowerShell, whose console encoding could not represent the
    prose, so **every** character it could not encode became a literal `?`. The
    simulation disclosure — the one string in the product that must never be
    unreadable — shipped as two rows of question marks. Typecheck passed. The
    build passed. Both catalogues were "symmetric" by key count. A row of `?`
    is a valid string, so **no existing assertion could see it.**
    `test_no_catalogue_value_is_corrupted_by_an_encoding_round_trip` now asserts
    the signature (a run of 2+ `?`, or `U+FFFD`) directly. Keep it that way:
    edit JSON with the editor or Python `encoding="utf-8"`, never with
    `Set-Content`, a here-string, or a piped `echo`.
    Two related traps in the same place: a PowerShell console **renders valid
    Unicode as `?` too**, so `?` in terminal output proves nothing in either
    direction — check codepoints, not the screen. And an interpolation token
    (`{mode}`, `{total}`) is legitimately Latin inside a Tamil value, so a
    "no Latin in Tamil" rule must exempt `\{[a-z]+\}`.

18b. **A hook that returned `null` for a failed capture was a silent failure.**
    `useCamera.capture` returned `Promise<string | null>` and both call sites
    treated `null` as "nothing to report", so a failed capture showed no message
    at all — the button simply stopped working. It now returns a discriminated
    `CaptureResult`, so `ok: false` cannot be dropped. If you add a hook that can
    fail, return a result object, not `null`.

18c. **A scanner is only as good as its weakest assumption, so mutation-check
    every exclusion.** The Tamil-catalogue guard has three rules beyond the
    encoding signature: no foreign script, no digit adjacent to Tamil, no
    untranslated Latin. Each one was verified by reinstating the exact string
    that broke it and confirming the build fails. Two exclusions are named
    rather than pattern-based for a concrete reason: `e.g.` opens with a dotted
    token that reads as member access, and `e.g. penicillin, peanuts` yields the
    words `e` and `g`, which a "bare lowercase words are an enum" rule eats. That
    placeholder shape is what actually shipped on the profile form, so the rule
    requires `len >= 3` or an underscore, and `e.g`/`i.e` are excluded from the
    member-access check by name.

### Backend architecture

19. **New queries go in `app/repositories/`.** Never in a router or a service.
20. **Repositories flush but never commit.** The caller owns the transaction, so
    a domain write and its audit row land together. A repository that commits
    breaks that invariant.
21. **New tables or columns require an Alembic migration**
    (`alembic revision --autogenerate`) **plus a check that the demo seed is
    still idempotent** on the migrated schema. An Alembic migration is also the
    *only* way a new table arrives, which means it inherits **no RLS**: the
    `005` sweep already ran and only covers tables that existed when it did. So
    every new table needs an explicit `alter table ... enable row level
    security` in `007`, and `007` asserts at the end that no policy-carrying
    table is left unprotected. `incident_events` shipped to hosted without this
    and was world-readable to any granted role.
22. **`migrations/supabase/*.sql` contains no percent signs**, comments
    included. psycopg validates percent sequences even with no parameters and
    rejects any specifier that is not its own, so `format('%I', ...)` raises
    before touching the network. Use `quote_ident` and concatenation. A test
    enforces this across **every** file in the directory, not only the three the
    suite executes — `004` carried a `raise exception` specifier for a long time
    precisely because nothing ever ran it. Two related traps in the same files:
    `RAISE` rejects a leading `||` and needs `USING MESSAGE =`, and Postgres only
    continues an expression when the operator is at the **end** of the line.
23. **Authentication is `Depends(get_current_user)` plus a permission helper**
    from `app/security/permissions.py`. Authorization is a data question, not a
    role-string comparison.

### Testing

24. **`pytest` env vars go at the very top of `tests/conftest.py`, before any
    `app` import** — `TESTING=1`, `DEMO_MODE=1`, `DATABASE_URL`. The suite uses a
    fresh temp SQLite DB, removed per run.
25. **`TestClient.delete()` has no `json=` kwarg.** Use
    `client.request("DELETE", url, headers=..., json=...)`.
26. **`pytest.ini` sets `addopts = -q`.** Passing another `-q` yields `-qq`,
    which suppresses the `N passed` summary. Judge success by `$LASTEXITCODE`,
    not by the missing summary.
27. **The evaluation metrics are tested against literal scores, not faces.**
    `tests/test_evaluation.py` uses hand-computable score/label lists on
    purpose. Never "simplify" those into a real-corpus test: the point is that
    AUC and EER can be verified on paper before a number is quoted. Two real
    bugs (AUC integrated over thresholds, EER returning 1.0 on an
    anti-correlated set) were caught exactly this way.
28. **A harness that measures nothing must fail, not report zero.**
    `TrialRunner` records load failures per sample rather than catching and
    marking them undetected — a swallowed `AttributeError` once reported "0% of
    trials dropped" for a run that embedded nothing.

### Biometric determinism

29. **Synthetic face seeds must be deterministic.** The face feature space is
    small, so arbitrary identity strings collide — observed
    `unknown-person-X9` vs `test-identity` = 0.807. **Never introduce a
    random UUID-based identity into enrollment; it made the suite flaky.** The
    demo no-match identity is `enroll-demo-charlie-99`.
30. `app/api/demo.py` seeds the demo-enroll face from `user.email`, and
    `test_demo_enroll_works_with_consent` uses a fixed account. On purpose.
31. **All demo data is fictional and must stay that way.** No real names,
    addresses, phone numbers or medical histories. Emails ending `.local` are
    rejected by pydantic `EmailStr`; demo uses `.demo.traya` / `.responder.traya`.

### Security

32. **Biometric embeddings are encrypted at rest (Fernet) and never returned to
    clients.** There is no endpoint that returns a vector, and **no agent may add
    one**. Never log raw vectors. Never log unredacted clinical detail. Both
    invariants are asserted against the whole source tree in
    `tests/test_security_phase11.py`, not only against the paths that exist
    today, so adding the offending endpoint later fails the build.
33. **Never log or commit secrets.** `SECRET_KEY` / `ENCRYPTION_KEY` come from
    `.env`; see `.env.example`. A test refuses a `service_role` string anywhere
    in `frontend/src` — it bypasses RLS, which is the whole authorization model.
34. **`ENCRYPTION_KEY` is derived from `SECRET_KEY` if unset.** Rotating
    `SECRET_KEY` without setting `ENCRYPTION_KEY` makes every stored embedding
    **permanently unreadable**. Set both, together, deliberately.
35. **An upload is attacker-supplied.** `MAX_UPLOAD_BYTES` is defeated by a small
    file declaring enormous dimensions, so `MAX_IMAGE_PIXELS` and
    `MAX_IMAGE_ASPECT_RATIO` are checked *before* `Image.load()`. Do not move
    that check after the decode.
36. **Rate limiting is per-process.** The window is a dict in the app process,
    so the effective limit is `limit * workers`. It is keyed on IP *and*, for
    identification, on the decoded (not verified) bearer `sub`. It must move to
    a shared store before horizontal scaling.

---

## 4. COMMANDS

Run from the repo root unless noted.

| Task | Command |
|---|---|
| Run everything (dev) | `npm run dev:all` — backend :8000 + vite :5173 |
| **Verify docs** | `npm run docs:check` (alias `npm run verify`) |
| **Backend tests** | `cd backend; .venv\Scripts\python.exe -m pytest` |
| Backend only | `cd backend; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000` |
| Frontend only | `cd frontend; npm run dev` (http://localhost:5173) |
| Frontend typecheck | `cd frontend; npm run typecheck` |
| Frontend build | `cd frontend; npm run build` |
| Backend tests on Postgres | `cd backend; $env:TRAYA_TEST_DATABASE_URL="postgresql+psycopg://postgres:traya_local_dev@127.0.0.1:54329/traya_test"; .venv\Scripts\python.exe -m pytest` |
| Local Postgres (pgvector) | `docker run -d --name traya-pg -p 54329:5432 -e POSTGRES_PASSWORD=traya_local_dev -e POSTGRES_USER=postgres -e POSTGRES_DB=traya pgvector/pgvector:pg16` |
| Migrate to head | `cd backend; .venv\Scripts\python.exe -m alembic upgrade head` |
| Migration drift | `cd backend; .venv\Scripts\python.exe -m alembic upgrade head; .venv\Scripts\python.exe -m alembic check` |
| New migration | `cd backend; .venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."` |
| Re-seed demo | `cd backend; .venv\Scripts\python.exe -m app.services.demo.seed` |
| Inspect hosted RLS | `cd backend; .venv\Scripts\python.exe scripts/inspect_hosted_rls.py` — read-only |
| Apply + verify hosted RLS | `cd backend; .venv\Scripts\python.exe scripts/apply_and_verify_hosted_rls.py` — **writes to the database**; run `inspect_hosted_rls.py` first |
| Verify hosted app + anon denial | `cd backend; .venv\Scripts\python.exe scripts/verify_hosted_app.py` |

### Verification is mandatory

| Change | Must pass |
|---|---|
| Any backend change | backend test suite |
| Any frontend change | `npm run typecheck` **and** `npm run build` |
| Adding/renaming a component, endpoint, model, table, migration, setting, role, permission, page, icon, API method or exported type | `npm run docs:check` |
| Editing `migrations/supabase/*.sql` | backend suite on Postgres (the policies are executed verbatim), **and** reapply + re-verify if the change targets hosted |

**A change is not done until the relevant commands pass.** Report the actual
result, not an expectation.

---

## 5. REPO LAYOUT

```
C:\Traya\
  AGENTS.md                  this file — read first
  backend\                   FastAPI + SQLAlchemy + Alembic
    app\
      api\                   admin, auth, biometric, demo, emergency, hospitals, users
      config\                pydantic-settings
      database\              session + service.py (Supabase probe / SQLite fallback)
      models\entities.py     19 ORM models
      repositories\          the only layer that touches the database
      schemas\               Pydantic schemas
      security\              auth, password, crypto (Fernet), permissions, rate_limit, tokens
      services\
        identification\       engine, pipeline, registry, confidence  ← the core
        biometric\            enrollment (guided capture lifecycle)
        demo\                 seed + synthetic image generation
        medical, notification, location, hospital, audit_service
      main.py                app factory, lifespan, health, SPA serving
    migrations\              Alembic (4 versions)
    tests\                   pytest, 414 tests on Postgres / 385 + 29 skipped on SQLite
    scripts\                 inspect_hosted_rls.py, apply_and_verify_hosted_rls.py,
                             verify_hosted_app.py — all read database state, none
                             deploy schema
  frontend\
    src\
      pages\                 10 pages, all routed
      components\            Layout, Guards, Sheet, Tabs, StatusBadge, QualityPanel,
                             EnrollWizard, icons
      context\               AuthContext, EmergencyContext
      hooks\                 useCamera, useGeolocation
      api\                   client.ts (the only network boundary), types.ts
      i18n\                  locales/en.json + ta.json – 440 keys each, UTF-8 no BOM;
                             strings.ts is a typed re-export over them
      theme\                 ThemeProvider
  docs\                      31 pages — see §6
  scripts\                   dev-all.mjs, check-docs.mjs
```

**App URLs:** dev `http://localhost:5173` · API `http://localhost:8000`
(`/docs` for OpenAPI). The API also serves `frontend/dist` at `/`, so rebuild
the frontend to see UI changes there.

---

## 6. DOCS — READ THE DOC, NOT THE CODE

**`npm run docs:check` fails the build when the docs drift from the code.** This
is the contract, and it is the reason you should trust `docs/` over your own
reading of the source.

Every router endpoint, ORM model, table, migration, repository method, service
function, settings field, permission, role, page, component, icon, API client
method and exported TypeScript type **must be named on its owning page.**

| Page | Covers |
|---|---|
| **[docs/AUDIT.md](docs/AUDIT.md)** | **Verified current state, ranked bugs, reusable assets, what I could not verify** |
| **[docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md)** | **The destination: schema, RLS, API, pipeline, model selection** |
| **[docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md)** | **13 phases, gates, dependency graph, rollback** |
| **[docs/NON_TECHNICAL.md](docs/NON_TECHNICAL.md)** | **For reviewers and non-technical readers** |
| **[docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md)** | **Evaluation protocol; results pending by design** |
| **[docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md)** | **Threats, controls, deliberate absences** |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System overview, trust boundaries |
| [docs/backend/api.md](docs/backend/api.md) | All 47 endpoints |
| [docs/backend/security.md](docs/backend/security.md) | 7 roles, 18 permissions, tokens, crypto |
| [docs/backend/data-model.md](docs/backend/data-model.md) | Every table and migration |
| [docs/backend/services.md](docs/backend/services.md) | Every service module |
| [docs/backend/repositories.md](docs/backend/repositories.md) | Every repository class and method |
| [docs/backend/configuration.md](docs/backend/configuration.md) | Every settings field |
| [docs/frontend/routing.md](docs/frontend/routing.md) | Routes, guards, provider order |
| [docs/frontend/pages.md](docs/frontend/pages.md) | Every page, with its defects |
| [docs/frontend/components.md](docs/frontend/components.md) | Every component and icon |
| [docs/frontend/state-and-data.md](docs/frontend/state-and-data.md) | Contexts, hooks, client, types |
| [docs/frontend/design-system.md](docs/frontend/design-system.md) | Tokens, spacing, theme, i18n |
| [docs/operations/README.md](docs/operations/README.md) | Dev, seeding, testing, deploying |
| [docs/decisions/README.md](docs/decisions/README.md) | ADRs 0001–0008 — why the system is the way it is |

### Writing rules

- **Document the reason, not the obvious.** "Calls the database" is noise.
  "Never commits implicitly, so the domain write and its audit row share one
  transaction" prevents a future bug.
- **Record the sharp edges.** Every page, component and service has at least one
  behaviour that will surprise a reasonable reader. Write it down.
- **Never document intent that is not implemented.** If a feature is incomplete
  or dead code, say so plainly. An aspirational doc is worse than no doc.
- **Copy names and signatures from source.** When code and docs disagree, the
  code is right and the doc is a bug.
- One `# H1` per page, at least one `## H2`, and a breadcrumb to
  [docs/README.md](docs/README.md).

---

## 7. KNOWN GAPS — DO NOT REDISCOVER

Full detail in [docs/README.md](docs/README.md#accuracy-status). The short list:

**Fixed in Phase 1** — no longer a gap, do not re-report: the emergency flow no
longer 403s, the Match Result tab renders, Logout is unreachable from
`/emergency/*`, the `<alpha-value>` fix landed so opacity utilities emit CSS,
and `ink-*`/`slate-*` are gone from every component. Details in
[docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md#phase-1) and the Phase 1 outcome
section of [docs/AUDIT.md](docs/AUDIT.md).

**Fixed in Phase 2** — do not re-report: `.tap` is no longer purged, the app bar
and tab bar are opaque, five colour tokens now clear 4.5:1 on every background
they render on, and contrast is asserted by `backend/tests/test_contrast.py`
instead of being eyeballed.

**Fixed in Phase 4** — do not re-report: RLS policies exist and are applied, the
`traya_api` role has grants (without them the policies were decorative), roles
resolve live so deactivation revokes access immediately, responder clinical
access is scoped to the incident's subject, and the two table-reading helpers are
`SECURITY DEFINER` (as invoker functions they read nothing and silently deny).
Four escalating-tamper tests are in `backend/tests/test_auth.py`.

**Fixed after Phase 7** — do not re-report: `incident_events` was on the hosted
project with **RLS off and no `traya_api` grant**, because `005_enable_rls.sql`
sweeps the tables that exist when it runs and this one arrived afterwards. A
correct policy and a correct grant had been created on a table whose RLS was
never enabled, which is inert, and every behavioural probe passed because the
probes run as the role that had a policy to not violate. `007` now enables it
explicitly and ends with an assertion that raises if any policy-carrying table
still has RLS off; the hosted project verifies `23 of 23`. Details in
[docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md#rls-is-enabled-on-all-23-tables-and-it-filters).


**Fixed in Phase 5** — do not re-report: there is a real face detector and a real
128D face embedding (YuNet + SFace, five-landmark alignment, cosine similarity),
selected by `BIOMETRIC_ENGINE`; templates carry the engine's version so the two
vector spaces cannot be compared; a dimension mismatch raises instead of
returning a low score; and `opencv` is a warned alias rather than a lie. Details
in [ADR 0008](docs/decisions/0008-real-biometric-engine.md).

**Fixed in Phase 6** — do not re-report: enrollment is guided end to end, so the
2-4 file upload is gone from `Profile.tsx`; the template is the **normalised
centroid** of the accepted samples rather than N templates; `complete` refuses a
capture set whose own samples disagree, because per-image quality gates cannot
detect a wrong person; and a committed template **purges the pending sample
vectors in the same transaction** (a *refused* set keeps them — that is the only
diagnostic an unexplained 422 has). Details in
[docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md#outcome---phase-6-complete).

1. **The thresholds are the simulation's, and nothing is calibrated.** The real
   engine exists and is measured on three photographs of two people
   (0.8977 same, 0.2792 worst cross), which is a smoke test and **not** an
   accuracy claim. FAR, FRR, EER, the per-condition breakdown and latency are
   unmeasured; the seeded `system_settings` values are unchanged from Phase 0.
   **`ENROLLMENT_MIN_SELF_SIMILARITY` (0.62) is a placeholder too**, copied from
   `REVIEW_THRESHOLD` rather than measured. See §1 and
   [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md).
2. **No client path uses the RLS policies, and there is no pgvector.** RLS is on
   for all 23 tables with 19 policies written for the `traya_api` role, and the
   hosted `public` schema is verified as filtering. But `traya_api` is `NOLOGIN`
   and nothing connects as it, while the application connects as the table owner
   and **bypasses its own policies** — `FORCE ROW LEVEL SECURITY` is deliberately
   off. So production traffic is still authorized in Python alone. Also still
   absent: plaintext pgvector and the Supabase SDK. `database/*.sql` still does
   not exist; the policies live in `migrations/supabase/006_claims.sql` and
   `007_rls_policies.sql`. See [ADR 0007](docs/decisions/0007-rls-claims-and-live-role-resolution.md).
3. **The silent SQLite fallback is gone** — `DATABASE_ALLOW_FALLBACK` defaults
   to `false` and `DEMO_MODE=false` refuses it outright, so real medical data
   cannot land in a local file unless somebody deliberately opts in. **Supabase
   is now live and is the configured primary**: all 4 migrations applied, 22
   tables, 7 roles / 18 permissions, emergency flow verified at 0.995. What is
   still open: deleting the local `traya.db` is deliberately undone, and
   **bucket retention policies** are dashboard work with no portable SQL.
4. ~~**Five pages still hardcode English.**~~ **Fixed in Phase 9** — do not
   re-report: `EmergencyHub`, `Profile`, `Admin`, `Demo` and `Privacy` all resolve
   their copy through `t()`, and
   `test_no_page_or_component_hardcodes_user_visible_english` fails the build if
   one reintroduces a literal. `Privacy` now renders the `privacy.title` key that
   had existed and was unused.
5. **The i18n catalogue is 440 keys each, and Phase 9 consumed the
   `hub.*`/`analytics.*`/`result.*` namespaces plus `emergency.*`, `contact.*`,
   `location.*`, `dashboard.*`, `profile.*`, `medical.*`, `admin.*`, `demo.*`
   and `privacy.*`.** `useCamera`/`useGeolocation` return codes mapped through
   `CAMERA_ERROR_KEYS`/`GEO_ERROR_KEYS` rather than English.
   `test_both_catalogues_carry_identical_keys` asserts the two catalogues are
   identical in shape, so a gap is a page that does not call `t()`, not a missing
   key. The permanent Tamil guard asserts no foreign script, no digit adjacent to
   Tamil, and no untranslated Latin, with `TRAYA`, `English`, `SMS`,
   `Latitude`, `Longitude` and ABO/Rh notation allowed by name.
   **What it cannot check is meaning**: no native speaker has reviewed the Tamil,
   so a fluent-but-wrong translation passes every assertion here.
6. ~~**`backend/.env.example` documents 20 of 36 settings.**~~ **Fixed in Phase
   11** — all 48 are documented, and a test fails the build if one is added
   without a line here. Do not re-report.
7. **No frontend test runner.** Frontend changes are verified by typecheck and
   build. `backend/tests/test_frontend_contract.py` exists to catch client/server
   literal mismatches — put new ones there.
8. **Tokens live in `localStorage`** and there is no CSP. Moving to httpOnly
   cookies needs CSRF protection and touches every authenticated request; it is
   recorded as the remaining T6 weakness rather than rushed in.
9. **No browser, camera or E2E run has happened.** The emergency flow is fixed
   by contract test, not observed working in a hand. The real engine has been run
   against three photographs, never against a live camera.

---

## 8. WHAT NOT TO DO

1. **Do not claim a feature works unless you ran it and saw it work.**
2. **Do not present the simulation as a biometric, and do not present the real
   engine as a validated one.** Every result carries `engine_mode` and
   `demo_mode`; keep that disclosure impossible to miss. A real detector does not
   make the thresholds right.
3. **Do not claim accuracy without a measurement.** Numbers go in
   [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) with the command that
   produced them. When a result is bad, publish it.
3a. **Do not pin `BIOMETRIC_ENGINE=yunet` in `conftest.py` and expect the suite
   to pass.** The suite drives `render_face`, and YuNet correctly finds no face
   in a synthetic drawing. The suite pins `simulation`; the real engine is
   tested in `tests/test_real_engine.py` against photographs.
4. **Do not claim TRAYA is globally unique.** Prior art exists. A formal
   gap analysis is future work.
5. **Do not add a "128-bit embedding".** It is **128-dimensional**. A 128D
   float32 vector is 512 bytes; dimensionality is how many numbers, bit size is
   how many bits each.
6. **Do not add an endpoint that returns embeddings.** Ever.
7. **Do not move thresholds by editing `.env` on a seeded database.** Seeded
   `system_settings` rows override the env vars, so the edit does nothing.
8. **Do not add a role check only in React.** Frontend checks hide buttons;
   RLS decides access.
9. **Do not hardcode UI strings.** Use an i18n key in both `en` and `ta`.
10. **Do not write `AI-generated dashboard` aesthetics.** Monochrome, semantic
    colour only where it carries meaning.
11. **Do not silently fall back to a local database.**
12. **Do not rewrite working functionality.** Refactor. The audit lists what is
    reusable and it is a long list — the pipeline logic, the quality scoring,
    the permission matrix, the crypto, the API client, the design system and the
    documentation contract all survive.
13. **Do not use `&&` in PowerShell.**
14. **Do not declare a backend value as a bare `string` on the frontend.** Five
    of the Phase 1 defects were a wrong literal against a loose type: consent
    `"granted"` vs `"active"`, role `"registered"` vs `"registered_user"`, status
    `"ENROLLED"` vs `"enrolled"`, location `"manual"` for a GPS fix. Typecheck
    passed through all of them. Use the union, and assert it in
    `backend/tests/test_frontend_contract.py`.

---

## 9. WORKING ON A PHASE

1. **Read** the phase in [docs/MIGRATION_PLAN.md](docs/MIGRATION_PLAN.md) and the
   relevant design in [docs/TARGET_ARCHITECTURE.md](docs/TARGET_ARCHITECTURE.md).
2. **Check the gate.** Each phase has one. Finish it or revert it — do not merge
   half a phase.
3. **Make the smallest change that passes the gate.** Refactor, do not rewrite.
4. **Run the verification** required by §4. Report the real output.
5. **Update the docs** in the same change. `npm run docs:check` is not
   optional.
6. **Update this file** if a project fact changed — a new dependency, a changed
   command, a new hard-won rule.

### The three irreversible actions, none of which belong to a phase

1. Deleting the SQLite database.
2. Turning off the SQLite fallback.
3. Replacing the biometric engine.

The first two are Phase 3. The third is Phase 5. **Until each phase's gate
passes, the rollback path is still there.** Preserve it.

**Update, Phase 3.** Item 2 is done: `DATABASE_ALLOW_FALLBACK` now defaults to
**false**, and `DEMO_MODE=false` refuses the fallback even when the flag is
true. The rollback is one env var, not a code change —
`DATABASE_ALLOW_FALLBACK=true` restores the old behaviour exactly. Do not
"fix" a fallback you did not expect by setting that flag on a deployment
without understanding that it is the data-loss switch. Items 1 and 3 are
untouched.