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
system are real and good — keep all of it. **There is no real face detection and
no real face embedding.** Everything else in this plan is built around fixing
that honestly.

---

## 1. THE ONE THING YOU MUST NOT GET WRONG

> **`opencv-python` is installed, and face detection still does not run.**

This is stated here first because it is the trap that makes reasonable agents
wrong.

`engine.py:37` decides the engine mode with
`bool(hasattr(cv2, "CascadeClassifier"))`. Measured on this machine:

```
cv2.__version__                    -> 5.0.0     (installed)
hasattr(cv2, 'data')               -> True      (present)
os.listdir(cv2.data.haarcascades)  -> ['__init__.py', '__pycache__']   (EMPTY)
hasattr(cv2, 'CascadeClassifier')  -> False     (REMOVED in OpenCV 5)
```

Two independent reasons the real path never executes:

1. **`cv2.CascadeClassifier` was removed in OpenCV 5.** The classic Haar cascade
   API is gone, so `_HAS_CV2` is `False`.
2. **The cascade directory contains no `.xml` files.** There is nothing to load
   even if the class existed.

So the guard at `engine.py:282` is never entered:

```python
if _HAS_CV2 and settings.BIOMETRIC_ENGINE in ("auto", "opencv"):
```

**Setting `BIOMETRIC_ENGINE=opencv` in `.env` does not give you real detection.**
It satisfies the second clause of that `and` and nothing about the first. The
engine falls through to `_simulate_detect` and reports `source="simulation"`
anyway. Do not "fix" this by changing the setting.

**What the engine actually is** — `extract_embedding`, `engine.py:336`:

```python
if features.size < settings.EMBEDDING_DIM:
    features = np.pad(features, (0, settings.EMBEDDING_DIM - features.size))
```

Twelve real numbers (skin mean, skin std, hair darkness, three eye bands, brow,
mouth, beard, symmetry, aspect, luminance), **zero-padded to 320**. That is the
entire embedding. Not 128D. Not 320D. Twelve numbers and 308 zeros.

**Consequence, and it matters:** nothing is wrong with the *design*. `BiometricEngine`
exposes `process` / `embed` / `pose` / `similarity` / `is_simulation`, and that
interface is correct and must be preserved. What is wrong is the implementation
behind it. A real provider drops in behind the same interface and every caller
keeps working.

**Also absent: face alignment.** There is no alignment code anywhere in the
backend. No landmarks, no `estimateAffinePartial2D`, no 68-point or 5-point
model. `PoseEstimate` (`engine.py:398`) is normalised brightness asymmetry and
its own docstring says so. Real alignment is a Phase 5 deliverable, not an
existing feature.

---

## 2. CURRENT HARD FACTS

Verified by running the code at commit `497e7af`. Full detail and reproduction
commands in [docs/AUDIT.md](docs/AUDIT.md).

| Fact | Value |
|---|---|
| Backend tests | **189 passed** at commit `497e7af`. **207 passed** after Phase 3, ~40s, exit 0 |
| Backend tests on real Postgres | **207 passed**, same count. Runs in a throwaway `traya_test` schema, **never `public`** — `TRAYA_TEST_DATABASE_URL` — see [operations/README.md](docs/operations/README.md#testing) |
| Hosted Supabase | **Live and verified.** PostgreSQL 17.11, 22 tables, 7 roles / 18 permissions, full emergency flow returns HIGH_CONFIDENCE 0.995 |
| Frontend typecheck | **passes**, exit 0, strict TS |
| `npm run docs:check` | **passes**, 29 pages |
| Endpoints | **47** across 7 routers |
| Tables | **19**, 4 Alembic migrations |
| Roles / permissions | **7** / **18** |
| Default database | **SQLite** (`sqlite:///./traya.db`) |
| `EMBEDDING_DIM` | **320** (12 real + 308 zeros) |
| Thresholds | HIGH 0.82, REVIEW 0.62, FALLBACK_FACE 0.60, BOOST 0.05/0.06 |
| Max impostor similarity | **0.817** — 6 of 30 impostor pairs exceed the 0.62 review threshold |
| Rows in `face_embeddings` / pgvector | **none** — the column does not exist |
| RLS policies | **none** — `database/rls.sql` is referenced in a docstring but does not exist. The `anon` grant that made this exploitable **is revoked** (`004_revoke_anon.sql`); the anon key now gets 401 on every app table |
| Storage buckets | **2, private**, created on the hosted project. Retention policies still to set in the dashboard |
| Supabase SDK | **not installed** — the app connects with `psycopg` as `postgres`, so nothing needs it |
| Frontend test runner | **none** |

### ML libraries available in `backend\.venv`

| Available | Missing |
|---|---|
| `cv2` 5.0.0 (no cascade API) | `dlib`, `face_recognition`, `insightface` |
| `numpy` 2.5.2, `PIL` 12.3.0 | `onnxruntime`, `mediapipe`, `torch` |
| `psycopg` 3.3.4 | `supabase`, `pgvector` |

**Only NumPy and Pillow are usable for ML as configured.** Any real 128D
embedding needs an install first. Phase 5 selects **YuNet** (`cv2.FaceDetectorYN`,
already available, needs only a model file) plus an **ONNX 128D embedding model**
via `onnxruntime` — wheel-only, no compiler on Windows. ArcFace-512D would be
more accurate and is **rejected because the 128D requirement is explicit**; it
must still be measured and recorded, not dismissed.

### The bugs that will bite you

Ranked in [docs/AUDIT.md](docs/AUDIT.md#bugs-ranked). The five that matter:

1. **The emergency flow 403s and cannot complete.** The backend issues a
   `session_token` (`emergency.py:180`) and requires it as an
   `X-TRAYA-Session-Token` header (`emergency.py:57-58`). The frontend has **no
   `session_token` field in its types** and never sends the header. Step 1
   returns 200, every step after returns 403. The product does not work.
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
2. Vite binds `localhost` (IPv6 `::1`); uvicorn binds `127.0.0.1` (IPv4). Probe
   with an explicit host.
3. **`uvicorn --reload` spawns orphaned `multiprocessing-fork` workers** that
   inherit the listening socket and survive parent kills, holding port 8000.
   `dev-all.mjs` deliberately runs uvicorn **without** `--reload`. To clear a
   stuck port, kill processes whose commandline matches `uvicorn app.main:app`.
4. Python is 3.14.2. Use `.venv\Scripts\python.exe`, not bare `python`.

### Code style

5. **Do not add comments to code unless the user asks.**
6. **No emojis** in code, docs or replies unless the user asks.
7. **Prefer a composed class** from `@layer components` (`.btn`, `.card`,
   `.input`, `.badge`, `.tap`, `.eyebrow`, `.scroll-x`) over a long `className`.
8. **No `dark:*` variants.** Light and dark share one class name via CSS custom
   properties. `ink-*` / `slate-*` were **removed** — five pages still use them
   and are migrating.
9. **`theme.spacing` is `replace`, not `extend`.** `0.5` is 0.125rem, there is
   no `5.5` and no `13`. Anything outside the table **compiles to nothing** — the
   same silent failure as an opacity modifier on a ramp colour.
10. **44px minimum touch targets** via `.tap`. Phase 2 applied it, so it is no
    longer purged. An `@layer components` class that no component references
    emits **no CSS at all** — the same silent failure as a bare `var()` colour.
    Do not add a class and leave it unused.
11. **Contrast is measured, not eyeballed.** `backend/tests/test_contrast.py`
    asserts 4.5:1. A **tinted** pairing is always the worst case: `bg-{tone}/15`
    pulls the background toward `text-{tone}`, so light `--c-warn` measured
    5.20:1 on every plain surface and 4.26:1 on its own badge. Check the tinted
    pair.
12. **Do not name a Tailwind class inside a comment.** The content scanner does
    not strip comments, so a class mentioned in prose is a class the build emits
    a rule for. `test_no_utility_name_appears_only_in_a_comment` fails the build
    on it. Describe the utility in words instead.

### Frontend architecture

13. **All network calls go through `src/api/client.ts`.** Repo-wide, `fetch(`
    appears exactly twice, both inside the client. Never add a third outside it.
14. **Layout routes render `<Outlet />`, not `{children}`.** `App.tsx` wraps
    pages in `<Route element={<Layout />}>`.
15. **`EmergencyContext` is a guarded `JSON.parse`** against `sessionStorage`.
    Keep the guard.
16. **Every user-visible string is an i18n key.** Five pages still hardcode
    English (see the gap list in §7).

### Backend architecture

17. **New queries go in `app/repositories/`.** Never in a router or a service.
18. **Repositories flush but never commit.** The caller owns the transaction, so
    a domain write and its audit row land together. A repository that commits
    breaks that invariant.
19. **New tables or columns require an Alembic migration**
    (`alembic revision --autogenerate`) **plus a check that the demo seed is
    still idempotent** on the migrated schema.
20. **Authentication is `Depends(get_current_user)` plus a permission helper**
    from `app/security/permissions.py`. Authorization is a data question, not a
    role-string comparison.

### Testing

21. **`pytest` env vars go at the very top of `tests/conftest.py`, before any
    `app` import** — `TESTING=1`, `DEMO_MODE=1`, `DATABASE_URL`. The suite uses a
    fresh temp SQLite DB, removed per run.
22. **`TestClient.delete()` has no `json=` kwarg.** Use
    `client.request("DELETE", url, headers=..., json=...)`.
23. **`pytest.ini` sets `addopts = -q`.** Passing another `-q` yields `-qq`,
    which suppresses the `N passed` summary. Judge success by `$LASTEXITCODE`,
    not by the missing summary.

### Biometric determinism

24. **Synthetic face seeds must be deterministic.** The face feature space is
    small, so arbitrary identity strings collide — observed
    `unknown-person-X9` vs `test-identity` = 0.807. **Never introduce a
    random UUID-based identity into enrollment; it made the suite flaky.** The
    demo no-match identity is `enroll-demo-charlie-99`.
25. `app/api/demo.py` seeds the demo-enroll face from `user.email`, and
    `test_demo_enroll_works_with_consent` uses a fixed account. On purpose.
26. **All demo data is fictional and must stay that way.** No real names,
    addresses, phone numbers or medical histories. Emails ending `.local` are
    rejected by pydantic `EmailStr`; demo uses `.demo.traya` / `.responder.traya`.

### Security

27. **Biometric embeddings are encrypted at rest (Fernet) and never returned to
    clients.** There is no endpoint that returns a vector, and **no agent may add
    one**. Never log raw vectors. Never log unredacted clinical detail.
28. **Never log or commit secrets.** `SECRET_KEY` / `ENCRYPTION_KEY` come from
    `.env`; see `.env.example`.
29. **`ENCRYPTION_KEY` is derived from `SECRET_KEY` if unset.** Rotating
    `SECRET_KEY` without setting `ENCRYPTION_KEY` makes every stored embedding
    **permanently unreadable**. Set both, together, deliberately.

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

### Verification is mandatory

| Change | Must pass |
|---|---|
| Any backend change | backend test suite |
| Any frontend change | `npm run typecheck` **and** `npm run build` |
| Adding/renaming a component, endpoint, model, table, migration, setting, role, permission, page, icon, API method or exported type | `npm run docs:check` |

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
    tests\                   pytest, 189 tests
  frontend\
    src\
      pages\                 10 pages, all routed
      components\            Layout, Guards, Sheet, Tabs, StatusBadge, QualityPanel, icons
      context\               AuthContext, EmergencyContext
      hooks\                 useCamera, useGeolocation
      api\                   client.ts (the only network boundary), types.ts
      i18n\                  strings.ts — 186 keys, en + ta, type-safe
      theme\                 ThemeProvider
  docs\                      29 pages — see §6
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
| [docs/decisions/README.md](docs/decisions/README.md) | ADRs 0001–0006 — why the system is the way it is |

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

1. **The biometric engine is a simulation.** See §1. Recorded in
   [ADR 0001](docs/decisions/0001-simulation-biometric-engine.md).
2. **No RLS, no pgvector, no Supabase SDK.** Authorization is Python-only.
   `database/*.sql` does not exist, and `public` on the hosted project still has
   `rowsecurity` off on all 22 tables. What changed in Phase 3 is that the
   exposure is no longer open: `004_revoke_anon.sql` revokes the default `anon`
   grants, so the public key reads nothing. Real RLS is Phase 4.
3. **The silent SQLite fallback is gone** — `DATABASE_ALLOW_FALLBACK` defaults
   to `false` and `DEMO_MODE=false` refuses it outright, so real medical data
   cannot land in a local file unless somebody deliberately opts in. **Supabase
   is now live and is the configured primary**: all 4 migrations applied, 22
   tables, 7 roles / 18 permissions, emergency flow verified at 0.995. What is
   still open: deleting the local `traya.db` is deliberately undone, and
   **bucket retention policies** are dashboard work with no portable SQL.
4. **Five pages still hardcode English**: `EmergencyHub`, `Profile`, `Admin`,
   `Demo`, `Privacy`. Their colours are migrated; their strings are not.
5. **94 of 186 i18n keys are unreferenced.** The whole 25-key `enroll.*`
   namespace is dead — `Profile` does a file upload instead of guided capture.
6. **`backend/.env.example` documents 20 of 36 settings.**
7. **No frontend test runner.** Frontend changes are verified by typecheck and
   build. `backend/tests/test_frontend_contract.py` exists to catch client/server
   literal mismatches — put new ones there.
8. **Tokens live in `localStorage`** and there is no CSP.
9. **No face alignment exists.** Nothing in the backend aligns a face.
10. **No browser, camera or E2E run has happened.** The emergency flow is fixed
    by contract test, not observed working in a hand.

---

## 8. WHAT NOT TO DO

1. **Do not claim a feature works unless you ran it and saw it work.**
2. **Do not present the simulation as a biometric.** Every result already carries
   `engine_mode` and `demo_mode`; keep that disclosure impossible to miss.
3. **Do not claim accuracy without a measurement.** Numbers go in
   [docs/MODEL_EVALUATION.md](docs/MODEL_EVALUATION.md) with the command that
   produced them. When a result is bad, publish it.
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