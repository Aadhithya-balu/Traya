# TRAYA Current State Audit

[docs/README.md](README.md) · Phase 1 of the rebuild. **No code changed to produce
this page.** Every claim below was read from source, or measured by running the
code, on this repository at commit `497e7af`.

## How to read this

If you are an agent about to change TRAYA, this page tells you what is true
today. Read it once, then read
[TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) for where things are going and
[MIGRATION_PLAN.md](MIGRATION_PLAN.md) for the order of work.

Do not re-derive these facts by reading the codebase. They are recorded here
because they are expensive to establish and easy to get wrong. Where a claim
needs re-verification, the page says how to verify it.

## Executive summary

TRAYA is a **well-organised prototype with a broken centre**. The engineering
scaffolding around it is unusually good for a first-stage project: a documented
47-endpoint API, a 19-table schema with migrations, a 7-role permission matrix,
an append-only audit trail, a real quality-assessment pipeline, and a
documentation contract enforced by CI. That work is worth keeping.

The centre is not real. **There is no face detection and no face embedding.**
The thing the project is named for does not exist yet.

| Layer | State | Verdict |
| --- | --- | --- |
| Documentation | 23 pages, 20 automated checks, all passing | **Keep.** Best asset in the repo. |
| Test suite | 130 tests, all passing, 68s | **Keep.** Genuine coverage. |
| Frontend architecture | Centralised API client, typed, typecheck clean | **Keep.** |
| API design | 47 endpoints, consistent Pydantic schemas | **Keep, restructure.** |
| RBAC | 7 roles, 18 permissions, seeded to DB, enforced in Python | **Keep, move to RLS.** |
| Audit trail | Append-only, written with domain writes | **Keep.** |
| **Face detection** | **Does not run. OpenCV 5 removed the API the code calls.** | **Replace.** |
| **Embedding** | **12 brightness features, zero-padded to 320.** Not a biometric. | **Replace.** |
| **Face alignment** | **Zero lines of code. No landmarks at all.** | **Build.** |
| **Database** | **SQLite by default. No pgvector, no RLS, no Supabase Auth.** | **Migrate.** |
| **Embedding dimension** | **320, via zero-padding.** Requirement says 128D. | **Rebuild.** |

## Verified environment

Measured, not assumed. Run to reproduce:

```powershell
cd backend; .venv\Scripts\python.exe -m pytest
```

    130 passed, 8 warnings in 68.47s   EXITCODE=0

ML library availability in `backend\.venv`:

| Package | Status | Consequence |
| --- | --- | --- |
| `cv2` | **5.0.0 present** | See below - presence is not capability. |
| `dlib` | **missing** | Cannot use the 128D face descriptor model. |
| `face_recognition` | **missing** | dlib wrapper unavailable. |
| `insightface` | **missing** | Cannot use ArcFace. |
| `onnxruntime` | **missing** | Cannot run any ONNX model. |
| `mediapipe` | **missing** | Cannot use face-mesh landmarks. |
| `torch` | **missing** | No deep model runtime. |
| `numpy` | 2.5.2 | Fine. |
| `PIL` | 12.3.0 | Fine. |
| `psycopg` | 3.3.4 | Postgres reachable. |
| `supabase` | **missing** | No Supabase SDK at all. |
| `pgvector` | **missing** | No vector similarity at the DB layer. |

**Only NumPy and Pillow are usable for the ML pipeline as configured.** Every
option for a real 128D embedding requires installing something first.

### Why OpenCV being installed is not the same as face detection working

This is the single most important finding in the audit, and it is subtle
enough that reasonable people get it wrong.

`engine.py:37` decides the engine's mode with:

```python
_HAS_CV2 = bool(hasattr(cv2, "CascadeClassifier"))
```

Measured on this machine:

```
cv2.__version__            -> 5.0.0
hasattr(cv2, 'data')       -> True
os.path.isdir(cv2.data.haarcascades) -> True
os.listdir(cv2.data.haarcascades)    -> ['__init__.py', '__pycache__']
hasattr(cv2, 'CascadeClassifier')    -> False
```

Two independent reasons the real path never executes:

1. **`cv2.CascadeClassifier` does not exist in OpenCV 5.** The classic Haar
   cascade API was removed. So `_HAS_CV2` is `False`.
2. **Even if the class existed, the cascade directory is empty.** It contains a
   Python stub and a cache directory - **no `.xml` cascade files**. There is
   nothing to load.

The guard at `engine.py:282` is therefore never entered:

```python
if _HAS_CV2 and settings.BIOMETRIC_ENGINE in ("auto", "opencv"):
```

Note the compound condition. Setting `BIOMETRIC_ENGINE=opencv` in `.env`
satisfies the second clause and satisfies nothing about the first. The engine
falls through to `_simulate_detect` and reports `source="simulation"` anyway.

> **Consequence for planning:** OpenCV is present and *does* still offer
> `FaceDetectorYN` (YuNet DNN detector) and a working `dnn` module. A real
> detector is available in the already-installed dependency. It needs a model
> file, not a new package.

## The biometric engine, exactly as written

`backend/app/services/identification/engine.py`, 602 lines.

### What detection does

`detect_faces()` (line 280) tries Haar, fails as shown above, and falls to
`_simulate_detect()` (line 302). That function:

1. Downscales the image 4x.
2. Converts RGB to a hand-rolled HSV, keeping **only hue and saturation**
   (lines 132-141) - no brightness channel.
3. Thresholds `h in [0,60]`, `sat in (18,225)`, `val > 25` for a "skin" mask
   (line 145).
4. Runs a pure-Python BFS connected-components labeler (`_label`, line 167) -
   **O(W x H) interpreted Python loop over every pixel**.
5. Rejects blobs over 55% of the frame or touching 3+ borders as "background"
   (lines 314-316).
6. Drops blobs under 1.5% of frame area.

This is skin-tone segmentation, not face detection. It cannot tell a face from
a hand, an arm, or a wall lit warmly. It will report a forearm as a face.

### What the embedding is

`extract_embedding()` (line 336) crops the detected box, resizes to a 16x16
luminance grid, and computes **12 scalar features** (lines 359-381):

```python
skin_mean, skin_std, hair_dark,
eye_left, eye_mid, eye_right,
brow, mouth, beard,
symmetry, aspect, float(lum.mean())
```

Then the decisive line (line 389):

```python
if features.size < settings.EMBEDDING_DIM:
    features = np.pad(features, (0, settings.EMBEDDING_DIM - features.size))
```

`EMBEDDING_DIM` defaults to **320** (`settings.py:59`). So the stored "320-
dimensional embedding" is **12 real numbers followed by 308 zeros.**

Consequences that follow directly:

- Two people whose 12 brightness statistics are similar get vectors 308 zeros
  apart. Nothing is learned from a model.
- The dimension is a **presentation choice, not a property of any model**. It
  is not a 128D embedding and not a 320D embedding; it is 12 numbers.
- Padding is why the impostor collision exists. Recorded in
  [ADR 0001](decisions/0001-simulation-biometric-engine.md): impostor pairs
  reach **0.817** similarity, and 6 of 30 impostor pairs exceed the 0.62
  review threshold.

### What similarity is

`compare()` (line 534):

```python
d = float(np.linalg.norm(embedding_a - embedding_b))
return max(0.0, min(1.0, 1.0 - d / 3.0))
```

An L2-distance-to-linearity map with a hand-picked divisor. Not cosine
similarity, which is the correct metric for normalised face descriptors.

### What alignment is

**Nothing.** Searching the backend for `align`, `landmark`, `affineTransform`,
`similarityTransform`, `dlib` returns no alignment implementation. There is no
68-point or 5-point landmark model, no eye-line normalisation, no roll
correction. Faces go into the pipeline unaligned.

`PoseEstimate` (line 398) is honest about what it is - normalised darkness
asymmetry per axis, explicitly documented as *not* a landmark solver, with
`confident: False` when unmeasurable. That docstring is good work. It is still
not pose estimation.

### What the engine abstraction looks like

`BiometricEngine` (line 558) exposes `process`, `embed`, `pose`, `similarity`,
`is_simulation`, `mode`. **This is the right shape and it must be preserved.**
A real provider can be dropped in behind it.

Two dead members are in the way and must go:

- `mean_center()` (line 547) **ignores its arguments and returns the input
  unchanged.** A reader would reasonably assume centering happens.
- `compare_centered()` (line 551) calls `compare()` - no centering involved.

And `estimate_pose()` (line 488) contains **unreachable dead code**: lines
523-527 are a second `return` statement after the function has already returned
at line 521. Harmless at runtime, and a strong signal the file is unreviewed
at the tail.

## The identification pipeline

`backend/app/services/identification/pipeline.py`, 345 lines.

`run_identification()` (line 136) is a defensible **four-tier** design and it
is worth keeping:

- **Tier 1** face similarity - the only tier allowed to produce an identity.
- **Tier 2** secondary visible features - supporting evidence, max `0.06` boost.
- **Tier 3** geographic context - supporting evidence, max `0.05` boost.
- **Tier 4** human confirmation - forced whenever confidence is insufficient.

The guard rails are real and correctly placed:

| Line | Behaviour |
| --- | --- |
| 163 | More than one face -> `MULTIPLE_FACES`, no attempt to guess. |
| 169 | No face -> `NO_FACE`. |
| 174 | Quality not usable -> `POOR_QUALITY`. |
| 195 | Candidate below `face_fallback` is dropped before ranking. |
| 212 | Only the top 3 candidates are returned. |
| 235 | Below `high` -> `REVIEW_REQUIRED` + `requires_human_confirmation`. |
| 245 | Weak face score plus any fallback signal -> human must decide. |

`medical_alerts_available` is gated on `HIGH_CONFIDENCE` **and** a non-empty
candidate list (line 72). Correct - clinical data does not leak on a weak match.

`_persist_attempt()` (line 260) writes an `IdentificationAttempt` plus one
`IdentificationCandidate` row per candidate, and stamps the session's outcome.
Every decision is therefore auditable. Good.

The pipeline's logic is sound. **Its input is not an embedding.** Fixing the
provider fixes the pipeline.

## Quality assessment - the genuinely real part

`analyze_quality()` (line 198) is not simulated. It computes real numbers:

- **Blur** via a variance-of-Laplacian proxy (line 188), log-scaled.
- **Lighting** from mean luminance distance from 127.
- **Contrast** from grayscale standard deviation.
- **Occlusion** from skin density inside the detected box.
- **Visibility** combining density and relative face area.

It emits stable machine-readable `reason_codes` (line 249): `no_face`,
`multiple_faces`, `blurry`, `too_dark`, `face_too_small`, `occluded`,
`low_quality`. The docstring at line 245 explains why they exist - so that
guided enrollment and the emergency quality panel cannot disagree about whether
a capture is acceptable.

This is good engineering and should survive the migration. **One caveat:** three
of the codes depend on `face_boxes`, which is simulated output. The blur and
lighting scores are real; the occlusion and size scores inherit from a
skin-tone blob.

## Database and persistence

### What exists

19 tables (`backend/app/models/entities.py`), 4 Alembic migrations, and a
`DatabaseService` (`app/database/service.py`) that resolves one engine at
startup with a Supabase/Postgres primary and a **silent SQLite fallback**.

The fallback is the problem. `service.py:114-130`: if the Postgres probe
fails and `DATABASE_ALLOW_FALLBACK` is true (the default), it starts on local
SQLite and sets `degraded=True, reason="primary_unavailable"`.

There is a mitigation - `_connection_state()` (`main.py:92`) returns
`"demo_offline"`, `/api/health` reports it, and the UI shows it. The design
honesty is real.

The operational risk remains: **a deployment pointed at Supabase can silently
persist real medical and biometric data into a local SQLite file** if the
network blips at boot. The prompt's rule "do not silently fall back to local
DB" is violated by the current default.

### What is absent

| Target requirement | Status |
| --- | --- |
| Supabase as source of truth | **No.** SQLite is the default. |
| Supabase Auth | **No.** Custom JWT, `app/security/tokens.py`. |
| Supabase Storage | **No.** No bucket, no uploads. |
| pgvector | **No.** Package missing, column not used. |
| Row Level Security | **No.** `database/rls.sql` is referenced in a docstring (`permissions.py:10`) but **the file does not exist**. |
| `face_samples` table | **Partly** - `biometric_enrollment_samples` (line 236) holds pending embeddings, not stored images. |
| `consent_records` | **Yes** - `consents` (line 270). Good model: versioned, revocable, timestamped. |
| `audit_logs` | **Yes** (line 404). Append-only. |
| `incident_events` | **Yes** - `identification_attempts` + `timeline` built from them. |
| `embedding_dimension` column | **No.** `BiometricEmbedding` (line 178) stores `embedding_blob` and `algo_version` only. **The dimension is not persisted.** |
| `embedding_model` / `embedding_version` | **Partly** - `algo_version` (line 186). No model name, no preprocessing version, no registration version. |

The last row is the quiet one. `settings.BIOMETRIC_ALGO_VERSION` appears in
`/api/health`, and `BiometricEmbedding.algo_version` is stored per row - so
versioning is *partly* there. But because the vector is 12 numbers plus zeros,
there is nothing meaningful to version, and **a dimension change would
silently corrupt every stored vector** because nothing records it.

### Biometric storage security - this part is good

- Embeddings are **encrypted at rest with Fernet** (`app/security/crypto.py`).
- They are stored as opaque `bytes` blobs, never as queryable floats.
- **No endpoint returns an embedding.** Verified across all 47 routes: the
  biometric router exposes `enroll`, `status`, and the enrollment lifecycle only.
  `users.py:243` `biometric-status` returns `status`, `sample_count`,
  `enrolled_at` - counts and status, never vectors.
- Deletion cascades: `biometric_profiles -> biometric_embeddings` is
  `ondelete="CASCADE"` plus `cascade="all, delete-orphan"` (line 174).

This is correct and should be preserved exactly.

## Authentication

Custom JWT (`app/security/tokens.py`, 41 lines). Access token carries `sub`,
`type`, `iat`, `exp`; refresh carries the same with a longer expiry. HS256 via
`settings.SECRET_KEY`. No revocation list, no jti, no rotation.

`auth.py` exposes `register`, `login`, `refresh`, `me`, `permissions`. Refresh
is a real rotation path - the frontend holds a refresh cookie and replays the
failed request once (`api/client.ts:57-93`).

Authorization is a genuine permission matrix, not a role string comparison -
`ROLE_PERMISSIONS` (`permissions.py:50`) is the single source of truth, seeded
into `permissions` and `role_permissions` tables so administrators can audit it.

**7 roles:** `public`, `registered_user`, `medical_responder`,
`police_responder`, `hospital`, `auditor`, `admin`.

**18 permissions** in four groups: identification (7), incidents (3), self
service (3), administration (5).

The design is better than most prototypes manage. The gap is that it is
**Python-only**. Nothing stops a direct Postgres client from reading
`medical_profiles`. For a system holding blood groups and biometrics, the
prompt is right that this belongs in RLS.

## The frontend

### What is good

- **`api/client.ts` is a real client.** Repo-wide grep for `fetch(` across
  `src/**/*.{ts,tsx}` returns **exactly two hits, both inside the client.** No
  scattered fetches. The prompt's complaint #4 does not apply to this repo.
- **Typecheck passes.** `npm run typecheck` exits 0 on strict TS with
  `noUnusedLocals`.
- **Tailwind-first monochrome design system.** Real CSS custom properties, real
  light and dark values, every cross-theme pair distinct, `color-scheme` set per
  theme so native controls follow, and a pre-paint theme script in `index.html`
  that prevents a dark-mode flash.
- **Mobile-first authoring.** Base styles are the phone; `sm:`/`md:`/`lg:`
  upgrade. Bottom tab bar, `viewport-fit=cover` with safe-area insets,
  `overflow-x-auto` on every table.
- **i18n is complete and type-safe.** 186 keys, 20 namespaces, **Tamil has all
  186 keys**, `StringKey = keyof typeof en` makes a typo a compile error, and an
  import-time loop throws on any missing Tamil key.
- **`useCamera.ts` is well written** - support detection, separate
  permission-denied branch, tracks stopped on unmount, object URL revoked.

### What is broken

**1. The emergency flow cannot complete. This is the blocker.**

The backend issues a per-session token at `emergency.py:180` and then **requires
it as an `X-TRAYA-Session-Token` header** on every capture, identify, location
and confirm (`emergency.py:57-58`, checked at `:90-91`).

The frontend never receives it:

- `api/types.ts:96-103` `EmergencyStartOut` has **no `session_token` field**.
- `api/client.ts:135-137` `startSession` cannot return one.
- `request()` has no per-call header hook.
- Grep for `session_token` or `X-TRAYA` across `frontend/src`: **zero hits.**

Step 1 returns 200 with a token. Step 2 returns 403. `Emergency.tsx:76-80` sets
`"check failed"`. **The public emergency identification flow does not work.**

**2. The logout bug - root cause found.**

No emergency page calls `logout`, `clearTokens`, or `EmergencyContext.clear` on
mount. There is no automatic session destruction. Three real mechanisms exist:

- **A reachable Log out button in the emergency header.** `Layout.tsx:169-181`
  renders `moreItems` unconditionally - no `isAuthed` gate - so `admin` and
  `logout` appear on `/emergency/*`. Line 175 calls `logout()`. One mis-tap
  during an emergency destroys the session. This is deterministic from code
  alone.
- **`refreshUser` treats any failure as logged out.** `AuthContext.tsx:30-37`
  nulls the user on *any* throw, and `isAuthed` is `!!user`, not token presence.
  A 500 or an offline blip renders the logged-out UI while both tokens remain
  in `localStorage`.
- Because mechanism 1 makes the flow fail (finding 1), users hit the error path
  repeatedly and go looking for a logout button.

**3. The Match Result tab can never render.** `Emergency.tsx:82` passes the
result via router `state`. `EmergencyHub.tsx:26` reads `EmergencyContext` and
**never calls `useLocation()`.** `result` is null forever, the tab is empty,
and `Confirm identity` is unreachable. `setSession` has **zero call sites**.

**4. Ramp colours cannot take opacity modifiers.** `tailwind.config.js:9-31`
maps colours to bare `var(--c-*)` strings with **no `<alpha-value>`**. Tailwind
emits nothing for `bg-ok/15`. **19 utility occurrences in source generate zero
CSS** - confirmed by compiling the repo's own `index.css` through the installed
Tailwind 3.4.19 and cross-checking the shipped bundle. Affected: every status
badge tint, every quality meter, the emergency error strip, **and the app bar
and tab bar backgrounds** - content scrolls visibly under both.

**5. Five pages are off-palette.** `EmergencyHub` (10), `Admin` (5), `Profile`
(4), `Demo` (2), `Privacy` (1) still use removed `ink-*` classes - which
**generate nothing at all** - plus 112 `slate-*` classes that render but bypass
the theme entirely.

**6. `Profile` compares against values the backend never returns.**
`bio?.status === "ENROLLED"` (line 389) against a backend that returns
`"enrolled"`; consent `=== "granted"` against a backend returning
`"active"`/`"withdrawn"`. Result: **consent can never be withdrawn from the
UI.** `Dashboard.tsx:48` uses the correct value, so two pages disagree about
the same user.

**7. A rejected refresh is cached forever.** `client.ts:57-70` assigns
`refreshPromise` with no `finally`, so one rejection poisons every later 401
retry until reload.

**8. `.tap` - the documented 44px touch target - is purged.** No `.tsx` uses
it, so Tailwind drops it. Touch sizing is currently accidental rather than
guaranteed.

**9. 94 of 186 i18n keys (50.5%) are unreferenced.** The entire 25-key
`enroll.*` namespace is dead - `Profile` does a 2-4 file upload instead of
guided capture, so the translations were written for a page that does not exist.

## Bugs, ranked

Ordered by how much damage they do if left alone.

| # | Severity | Defect | Location |
| --- | --- | --- | --- |
| 1 | **Critical** | Emergency flow 403s - session token never sent | `client.ts:135` vs `emergency.py:57` |
| 2 | **Critical** | No real face detection or embedding exists | `engine.py:389` |
| 3 | **Critical** | Match Result tab permanently empty | `Emergency.tsx:82` / `EmergencyHub.tsx:26` |
| 4 | **Critical** | SQLite is the default database; Supabase absent | `service.py:114` |
| 5 | **High** | Logout reachable inside the emergency UI | `Layout.tsx:169-181` |
| 6 | **High** | Any `/auth/me` failure reads as logged out | `AuthContext.tsx:34` |
| 7 | **High** | 19 opacity utilities emit nothing; bars have no background | `tailwind.config.js:9-31` |
| 8 | **High** | Consent cannot be withdrawn | `Profile.tsx:177` |
| 9 | **High** | `Profile` status check never matches | `Profile.tsx:389` |
| 10 | **Medium** | Rejected refresh promise cached forever | `client.ts:66-70` |
| 11 | **Medium** | No timeout or cancellation on `identify` | `client.ts:78` |
| 12 | **Medium** | 22 `ink-*` + 112 `slate-*` classes off-system | 5 pages |
| 13 | **Medium** | 94 unused i18n keys | `strings.ts` |
| 14 | **Medium** | `mean_center()` is a no-op; `compare_centered()` lies | `engine.py:547-552` |
| 15 | **Low** | Unreachable second return in `estimate_pose` | `engine.py:523-527` |
| 16 | **Low** | `Admin` role list uses `registered`, omits `hospital` | `Admin.tsx:7` |
| 17 | **Low** | `sendLocation` always hardcodes `source:"manual"` | `EmergencyHub.tsx:396` |
| 18 | **Low** | `-translate-x-5.5` not in the spacing table; knob stuck | `Layout.tsx:163` |
| 19 | **Low** | Tokens in `localStorage`; no CSP | `client.ts:27` |

## Reusable assets

Per the prompt's "refactor rather than duplicate", this survives intact:

**Backend** - the 47-endpoint router layout; `DatabaseService` engine resolution
(the *idea* is sound, the silent fallback is not); `BiometricEngine`'s provider
interface; `run_identification`'s four-tier logic and its human-confirmation
guards; `analyze_quality`'s blur/lighting scoring and stable `reason_codes`;
`ROLE_PERMISSIONS`; Fernet encryption at rest; the cascade-delete biometric
schema; `_persist_attempt`'s audit-every-decision discipline; repositories that
flush but never commit; the demo seed's idempotency.

**Frontend** - `api/client.ts` as the single network boundary; `index.css`
colour tokens and the two real themes; `tailwind.config.js` `ramp` mapping
(needs `<alpha-value>`); `Layout.tsx` app bar, tab bar and safe-area handling;
`Guards.tsx`; `useCamera.ts`; `i18n/strings.ts` catalogue and its type
enforcement; `Sheet`, `StatusBadge`, `QualityPanel`, `icons.tsx`; the composed
`@layer components` classes.

**Process** - the documentation contract in `docs/README.md`, enforced by
`npm run docs:check`. Every agent should inherit it rather than reinvent it.

## What I could not verify

Stated plainly, per the documentation contract.

- **The logout chain is a static trace.** I did not run the app and observe a
  logout. Mechanism 5 is deterministic from code; mechanisms 6 and the
  cross-tab `storage` listener are plausible contributors I cannot confirm.
- **Impostor numbers (0.817, 6 of 30) are cited from ADR 0001**, not
  re-measured in this audit. Re-run before making threshold decisions.
- **`faint` contrast ratios** (`#8a8a92` on white = 3.43:1, below the 4.5:1 AA
  requirement) are computed from declared hex values, not measured in a browser.
- **No Postgres was reachable**, so the schema was read as SQLAlchemy models,
  not as live DDL. Nothing here proves the migrations apply cleanly to
  Supabase.
- **No frontend runtime was executed.** No browser, no camera, no E2E. All
  frontend findings are static analysis plus a Tailwind compile cross-check.