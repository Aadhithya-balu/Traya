# TRAYA Target Architecture

[docs/README.md](README.md) · Phase 2 of the rebuild. This is the destination
described by the rebuild prompt. The current state is in
[AUDIT.md](AUDIT.md); the order of work is in
[MIGRATION_PLAN.md](MIGRATION_PLAN.md).

## Principles

Six rules decide every argument below. When two designs conflict, these win.

1. **The match is evidence, not identity.** The system never states a person's
   name as fact on model output alone. Below the calibrated threshold it says
   "possible match" and requires a human. This is a safety property, not a UI
   preference.
2. **Embeddings never leave the backend.** The browser sends an image; it
   receives a decision. There is no endpoint that returns a vector, and none
   will be added.
3. **Authorization is enforced at the data, not in the interface.** React
   checks are for hiding buttons. RLS and permission checks decide access.
4. **Local storage is cache, never truth.** `localStorage` may hold a UI
   preference or a draft. It never holds the authoritative record of anything.
5. **Everything measured is versioned.** Model, preprocessing, threshold set and
   registration procedure each carry a version, and every decision records which
   versions produced it.
6. **No silent degradation.** If the system cannot do what it claims, it says
   so - loudly, in the API response and in the UI. The current SQLite fallback
   violates this and is removed.

## System shape

```
                    TRAYA
                      |
          +-----------+-----------+
          |                       |
      Frontend                 Backend
   React + TS              FastAPI + Pydantic
   (no biometric logic)          |
          |          +-----------+-----------+
          |          |                       |
          |      Service Layer           ML/CV Pipeline
          |    (biometric, emergency,   (detect -> align ->
          |     incident, profile,      embed -> search ->
          |     audit, admin)           threshold -> result)
          |          |                       |
          +----------+---------------+-------+
                             |
                    Supabase (PostgreSQL)
              Auth · Postgres · Storage · pgvector
                             |
                              RLS
```

The frontend sends an image and receives a decision. It never computes an
embedding, never sees a threshold, never holds a vector.

### Trust boundaries

| Boundary | What crosses | What must not |
| --- | --- | --- |
| Browser to API | Session cookie or JWT, image bytes, declared secondary features | Ever receive an embedding, a raw threshold, or another person's record |
| API to Supabase | Service-role connection, scoped by permission | Reach the database with a client-supplied role string |
| API to model | Cropped, aligned, normalised face | Run on unvalidated image bytes |
| Responder to victim data | Role-filtered emergency profile | Show clinical detail to a role without `view_medical_alerts` |

## Database architecture

Supabase is the single source of truth. One schema, PostgreSQL, RLS on every
table.

### Tables

The current 19 tables are a good foundation. The target schema renames a few
things for accuracy and adds the columns that make model migration possible.

```
auth.users                    (Supabase-managed)
        |
        +-- profiles                1:1   identity + language + status
        +-- user_roles              1:N   role assignment (not a column)
        |
        +-- emergency_profiles       1:1   blood group, allergies, conditions
        +-- emergency_contacts      1:N   ordered, verification_status
        +-- visible_features        1:N   tier-2 supporting evidence
        +-- consents                1:N   versioned, revocable
        |
        +-- biometric_profiles      1:1   status + template metadata
        |     +-- face_samples      1:N   accepted registration samples
        |     +-- face_embeddings   1:N   pgvector, encrypted, versioned
        +-- biometric_enrollments   1:N   in-progress guided capture
        |     +-- enrollment_samples 1:N  pending samples
        |
        +-- emergency_incidents     1:N   one per emergency workflow
        |     +-- incident_events   1:N   ordered, append-only
        |     +-- locations         1:N   per incident fix
        |     +-- contacts_notified 1:N   who was reached, when, how
        |
        +-- identification_attempts 1:N   every decision, with confidence
        |     +-- candidates        1:N   ranked, with per-candidate status
        |
        +-- hospitals               1:1   routing
        +-- system_settings         1:N   thresholds, versioned
        +-- audit_logs              1:N   append-only, actor + resource
        +-- notifications           1:N   delivery record
```

### What changes and why

| Change | Reason |
| --- | --- |
| `users` -> `profiles` + Supabase `auth.users` | Auth identity belongs to Supabase. Splitting it is what makes RLS expressible in `auth.uid()`. |
| `users.role` column -> `user_roles` table | The prompt requires roles not hard-coded anywhere, and a user may hold more than one. |
| `biometric_embeddings.embedding_blob` -> `embedding vector(128)` | Real ANN search instead of a full table scan in Python. |
| Add `embedding_model`, `embedding_version`, `preprocessing_version`, `embedding_dimension`, `registration_version` | **The current schema records none of these.** Without them a model change silently corrupts every stored vector. |
| Add `threshold_version` to `identification_attempts` | A decision must be reproducible: same inputs, same thresholds, same outcome. |
| New `face_samples` table | The prompt asks for stored samples. Current `biometric_enrollment_samples` holds *pending embeddings*, not images. |
| Rename `consents` -> keep name, extend | Already correct. Add `ip`/`user_agent` and a `superseded_at` so withdrawal history is preserved rather than overwritten. |
| New `incident_events` | The prompt asks for it explicitly. Currently incident state is spread across `emergency_sessions.status` and derived from attempts. |
| `roles` + `permissions` tables -> keep, seed from code | Already correct: the matrix is in code and seeded so it is auditable. |

### pgvector

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE face_embeddings (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_id            uuid NOT NULL REFERENCES biometric_profiles(id) ON DELETE CASCADE,
    embedding             vector(128) NOT NULL,
    embedding_model       text NOT NULL,
    embedding_version     text NOT NULL,
    embedding_dimension   smallint NOT NULL CHECK (embedding_dimension = 128),
    preprocessing_version text NOT NULL,
    registration_version  text NOT NULL,
    source_sample_id      uuid REFERENCES face_samples(id) ON DELETE SET NULL,
    created_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ON face_embeddings
    USING hnsw (embedding vector_cosine_ops);
```

HNSW, cosine distance. The metric matches the embedding space and supports
approximate nearest-neighbour search, which is what a growing enrolment base
needs.

**On encryption.** The current design encrypts embeddings with Fernet at rest
and stores opaque bytes. That is genuinely stronger, and losing it would be a
regression. It is also incompatible with pgvector's ANN index, which needs to
read the vectors.

Resolution: the vector column is `pgcrypto`-encrypted **per row** using a key
held outside the database, and the candidate search runs through a
`SECURITY DEFINER` function that decrypts server-side, computes cosine distance,
and returns only `(profile_id, score)`. If ANN turns out not to be needed at
this scale - a few thousand enrolments is fine with a sequential scan - the
encrypted-bytes design stands unchanged. **This decision is deferred to the
measurement in Phase 10, and whichever way it lands, no API ever returns a
vector.**

### Storage buckets

| Bucket | Contents | Retention |
| --- | --- | --- |
| `registration-samples` | Accepted enrollment images | Until template created, then purgeable |
| `incident-evidence` | The capture that produced a decision | Per jurisdiction policy, default 30 days |
| `evidence` | Nothing by default | Explicit admin action only |

**No bucket holds a video stream.** Frames are captured client-side, sent, and
discarded. The prompt's free-tier constraint (§33) makes this mandatory: storing
frames would exhaust the bucket in hours.

## Row Level Security

Every table gets policies. Authorization is expressed once, in the database,
where a compromised frontend cannot bypass it.

The role model carries over from `ROLE_PERMISSIONS`, which is already the single
source of truth in `app/security/permissions.py`. The migration seeds it into
Postgres so RLS and the application agree by construction.

```sql
-- Helper: the caller's effective roles, from the JWT.
CREATE FUNCTION caller_roles() RETURNS SETOF text
LANGUAGE sql STABLE AS $$
  SELECT unnest(coalesce(
    auth.jwt() -> 'app_metadata' -> 'roles', ARRAY[]::text[]
  ));
$$;

CREATE FUNCTION caller_has(p text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT p = ANY(SELECT un_array FROM caller_roles())
$$;
```

### Policy intent

| Table | Own record | Others' records | Responder | Admin |
| --- | --- | --- | --- | --- |
| `profiles` | read, update | **deny** | identity only, in an active incident | all |
| `emergency_profiles` | read, update | **deny** | requires `view_medical_alerts` **and** an active incident | all |
| `emergency_contacts` | read, write | **deny** | requires `view_emergency_contact` | all |
| `face_embeddings` | **deny** | **deny** | **deny** | metadata only, never vectors |
| `face_samples` | delete own | **deny** | **deny** | metadata only |
| `biometric_profiles` | own status only | **deny** | enrolment status of an incident subject | all |
| `emergency_incidents` | own created | **deny** | incidents they are assigned | all |
| `audit_logs` | **deny** | **deny** | **deny** | read |

Three rules carry most of the weight:

1. **No policy anywhere grants a client direct read of `face_embeddings`.**
   Search goes through the `SECURITY DEFINER` function and returns scores only.
2. **Responder access to clinical data requires an active incident**, not just
   a role. Standing clinical access to every enrolled person is the exact
   failure mode RLS exists to prevent.
3. **Users cannot read their own vectors.** A stolen session token must not
   exfiltrate biometrics.

## API architecture

Versioned under `/api/v1`. The current 47 endpoints move behind it with
behaviour preserved where it is already correct.

```
POST   /api/v1/auth/register              POST /api/v1/biometric/enrollments
POST   /api/v1/auth/login                 GET  /api/v1/biometric/enrollments/{id}
POST   /api/v1/auth/refresh               POST /api/v1/biometric/enrollments/{id}/samples
GET    /api/v1/auth/me                    POST /api/v1/biometric/enrollments/{id}/complete
                                           DELETE /api/v1/biometric/enrollments/{id}
GET    /api/v1/users/profile              POST /api/v1/emergency/sessions
PUT    /api/v1/users/profile              GET  /api/v1/emergency/sessions/{id}
GET    /api/v1/users/medical              POST /api/v1/emergency/sessions/{id}/capture
PUT    /api/v1/users/medical              POST /api/v1/emergency/sessions/{id}/identify
GET    /api/v1/users/contacts             POST /api/v1/emergency/sessions/{id}/confirm
POST   /api/v1/users/contacts             GET  /api/v1/emergency/sessions/{id}/medical-summary
PUT    /api/v1/users/contacts/{id}        GET  /api/v1/emergency/sessions/{id}/timeline
DELETE /api/v1/users/contacts/{id}        POST /api/v1/emergency/sessions/{id}/contacts/{c}/notify
                                           POST /api/v1/emergency/sessions/{id}/location

GET    /api/v1/users/consents             GET  /api/v1/incidents
POST   /api/v1/users/consents             GET  /api/v1/incidents/{id}
                                           PATCH /api/v1/incidents/{id}

GET    /api/v1/biometric/status           GET  /api/v1/hospitals/nearby
POST   /api/v1/biometric/verify

GET    /api/v1/admin/users                GET  /api/v1/admin/audit
PATCH  /api/v1/admin/users/{id}/roles     GET  /api/v1/admin/analytics
PATCH  /api/v1/admin/users/{id}/active    GET  /api/v1/admin/settings
GET    /api/v1/admin/sessions             PUT  /api/v1/admin/settings/{key}
```

### Response envelope

Every response, success or failure. Implemented once as middleware so no router
can forget.

```json
{ "success": true, "data": {}, "error": null, "request_id": "01J8..." }
```

```json
{
  "success": false,
  "data": null,
  "error": { "code": "LOW_IMAGE_QUALITY", "message": "Please move closer to the camera.", "i18n_key": "error.lowQuality" },
  "request_id": "01J8..."
}
```

`error.code` is machine-readable and drives the UI state; `message` is a
plain-language fallback; `i18n_key` lets the frontend localise without the
backend knowing about languages. **`error.message` never contains a stack
trace, a driver error, or a SQL fragment** - the global handler in `main.py:64`
already does this correctly and extends.

## Authentication

Supabase Auth replaces the custom JWT.

| Concern | Decision |
| --- | --- |
| Session storage | **httpOnly cookie** for the refresh token. Fixes audit finding 19. |
| Access token | In memory only. Never `localStorage`. |
| Email verification | Required before enrolment. |
| Password recovery | Supabase recovery email + redirect. |
| MFA | Optional, admin and responder roles. |
| Session restore | `getSession()` on boot; a `loading` state distinct from signed-out. |

The current bug where a transient `/auth/me` failure reads as "logged out"
(`AuthContext.tsx:30-37`) is fixed structurally: the auth state machine has
`loading`, `authenticated`, `unauthenticated`, and `error` as distinct states,
and only an explicit sign-out moves to `unauthenticated`.

**Emergency Mode is a workflow state and never touches authentication.** The
emergency session is a separate server-side object with its own scoped token -
which is what the current backend already models at `emergency.py:142`, and
what the frontend currently fails to carry (audit finding 1).

## Biometric pipeline

The interface stays. The implementation behind it becomes real.

```
Camera
  ↓  Frame Capture            client, canvas, one frame, discarded after send
  ↓  Image Validation         magic bytes, decode limits, pixel-bomb guard
  ↓  Face Detection           OpenCV FaceDetectorYN (YuNet) - already installed
  ↓  Quality Assessment       real: blur, lighting, size, occlusion
  ↓  Landmark Detection       5-point from YuNet
  ↓  Face Alignment           similarityTransform, eye-line + roll corrected
  ↓  Preprocessing            112x112, RGB, normalised
  ↓  Embedding Generation     128D descriptor
  ↓  Normalization            L2
  ↓  Vector Similarity Search pgvector HNSW, cosine
  ↓  Candidate Generation     top-K, K=5
  ↓  Threshold Evaluation     calibrated, versioned
  ↓  Confidence Assessment    margin-aware, not raw score
  ↓  Final Result             status + candidates + required next action
```

### The 128D requirement

The prompt is explicit and correct: **128-dimensional (128D)**, not 128-bit.
Dimensionality is how many numbers the vector holds; bit size is how many bits
each is stored in. A 128D float32 vector is 512 bytes. They are different
quantities and the distinction is recorded so nobody has to re-derive it.

### Model selection

The constraint is real: **no deep-learning runtime is installed.** `torch`,
`onnxruntime`, `insightface`, `dlib` and `mediapipe` are all absent
(verified in [AUDIT.md](AUDIT.md)). Options:

| Model | Dim | Needs | Verdict |
| --- | --- | --- | --- |
| **dlib `face_recognition` 128D** | 128 | `dlib` | Native 128D. But dlib on Python 3.14 needs a build, and `dlib` is a heavy, ageing dependency. |
| **ArcFace / `insightface` R50** | 512 | `insightface` + `onnxruntime` | Best accuracy by a wide margin. **512D - does not satisfy the requirement.** |
| **YuNet + custom 128D head** | 128 | training data | Needs a training set this project does not have. |
| **YuNet detection + ONNX 128D model** | 128 | `onnxruntime` | **Selected.** |

**Selected: YuNet for detection and 5-point landmarks, plus an ONNX face
embedding model producing 128D, executed through `onnxruntime`.**

Rationale, honestly stated:

- `onnxruntime` is a **wheel-only, dependency-light** install. No compiler, no
  `dlib` build against Python 3.14. This matters on Windows.
- YuNet ships as a small ONNX file and OpenCV 5 **already provides
  `FaceDetectorYN`** - verified present on this machine - so detection needs no
  new Python package at all, only a model download.
- It gives real landmarks, which is what makes alignment possible. This is the
  single biggest capability gap in the current engine.
- It satisfies 128D as required.

**The tradeoff, documented rather than hidden:** ArcFace-512D would identify
better. It is rejected because it violates an explicit project requirement, not
because it is worse. If the requirement is ever relaxed, the provider interface
is the only thing that changes - no caller, no schema migration for callers, no
UI change. The 512D ArcFace numbers should be measured anyway and recorded in
[Model Evaluation](MODEL_EVALUATION.md) so the comparison is on evidence.

### Provider interface

```python
class FaceEmbeddingProvider(Protocol):
    name: str
    version: str
    dimension: int
    preprocessing_version: str

    def detect(self, image: DecodedImage) -> list[FaceDetection]: ...
    def landmarks(self, image: DecodedImage, det: FaceDetection) -> FaceLandmarks: ...
    def align(self, image: DecodedImage, lm: FaceLandmarks) -> AlignedFace: ...
    def embed(self, face: AlignedFace) -> np.ndarray: ...   # L2-normalised, 128D
```

Implemented by `YuNetDlib128Provider` (production) and
`SimulationProvider` (tests, demos). The pipeline, the search, the thresholds
and the UI are identical against either. **The simulation stays, clearly
labelled** - it is what makes the demo honest and the tests fast.

## Registration

Guided, multi-sample, resumable. A single selfie is not enrolment.

```
START REGISTRATION
  ↓  Consent check (a real consent record, revocable)
  ↓  Camera permission, with plain-language guidance
  ↓  Step 1  Front-facing
  ↓  Step 2  Slight left
  ↓  Step 3  Slight right
  ↓  Step 4  Slight up / down
  ↓  Step 5  Natural expression
  ↓  Per-sample quality gate     reject and re-prompt with a specific reason
  ↓  Embed each accepted sample  128D, model-stamped
  ↓  Consistency validation      pairwise similarity must clear a bound
  ↓  Build template              centroid + spread measurement
  ↓  Encrypt, store, record versions
```

`BiometricEnrollment` already models this - `current_step`, `status`,
per-sample rows. **The backend lifecycle is reusable; only the sample content
changes**, from a file upload to a guided camera capture. The 25 unused `enroll.*`
i18n keys are already written for this UI.

Consistency validation is the part that is usually skipped and should not be:
if the five samples of one face do not resemble each other, something is wrong
with the capture or the detection, and the template must not be created.

## Matching and thresholds

### Statuses

```python
CONFIDENT_MATCH      # above calibrated threshold, margin clear
REVIEW_REQUIRED     # plausible, human must decide
NO_CONFIDENT_MATCH  # nothing plausible
LOW_QUALITY         # image unusable, retry with guidance
MULTIPLE_CANDIDATES # several within margin, cannot rank
NO_FACE             # nothing detected
```

Distinct from the current 7, and deliberately: `MULTIPLE_CANDIDATES` is
separated from `REVIEW_REQUIRED` because "we found three people who look alike"
is a **different instruction to the responder** than "we found one person who
might be right".

### Thresholds are calibrated, not chosen

Current thresholds (`settings.py:62-66`): `HIGH 0.82`, `REVIEW 0.62`,
`FALLBACK_FACE 0.60`, `CONTEXT_BOOST 0.05`, `SECONDARY_FEATURE_BOOST 0.06`.

These were set for a 12-feature brightness vector over a synthetic corpus. With
a real model and cosine similarity on real faces they are **meaningless and must
be re-derived** from the validation set. Every threshold is stored in
`system_settings` with a `threshold_version`, and every decision records the
version used.

### False-match safety

Encoded as rules, not as UI copy:

1. Never force a match. Below threshold, the answer is uncertainty.
2. Never present an unverified AI match as an identity. The UI says "possible
   match" until a human confirms.
3. **Use the margin, not just the score.** If the top two candidates are close,
   the result is `MULTIPLE_CANDIDATES` even when the top score clears the
   threshold. The current pipeline ranks but never inspects the gap - a real
   defect once real embeddings exist.
4. Log every decision with scores, versions and the rule that fired.
5. `REVIEW_REQUIRED` **and** `MULTIPLE_CANDIDATES` both force
   `requires_human_confirmation = True`.

The existing pipeline already forces human confirmation below threshold
(`pipeline.py:238-251`). That logic is right and is extended, not replaced.

## Emergency workflow

Emergency Mode is a **workflow state**. It is orthogonal to authentication and
cannot affect it.

```
Authenticated user  ──▶  Emergency session (separate scoped token)
                            │
                            ├─ capture ─▶ detect ─▶ quality gate
                            │                          │
                            │                     unusable ─▶ specific retry guidance
                            │                          │
                            │                       usable
                            │                          ↓
                            │                   embed ─▶ search ─▶ thresholds
                            │                          │
                            │              ┌───────────┴───────────┐
                            │        confident match        no confident match
                            │              ↓                        ↓
                            │     role-filtered profile        FALLBACK
                            │              ↓                        ↓
                            │      incident + events      manual/assisted path
                            │              ↓                        ↓
                            └──────────────┴────────────────────────┘
                                           ↓
                              Return to authenticated state
                                           ↓
                              Auth state unchanged. Verified by test.
```

**The auth-preservation invariant gets a regression test** (Journey 4): sign in,
run a full emergency cycle, return, assert the session is still valid and the
user object is unchanged. The prompt calls this out as Phase 8, and it is a
test, not a code change.

### Information shown is role-filtered

The requirement is to show the **minimum for the role**:

| Data | `public` | `registered_user` (self) | `police_responder` | `medical_responder` | `hospital` |
| --- | --- | --- | --- | --- | --- |
| Name | on confident match | own | yes | yes | yes |
| Blood group | no | own | **no** | yes | yes |
| Allergies / critical | no | own | **no** | yes | yes |
| Medications | no | own | **no** | yes | yes |
| Emergency contacts | no | own | yes | yes | yes |
| Identity confirmation | no | n/a | **yes** | yes | **no** |

Police get identity and contacts - who to call, where to take them. They do not
get the medical chart. This is the `police_responder` vs `medical_responder`
split that already exists in `ROLE_PERMISSIONS` and must be enforced in RLS, not
only in Python.

## Fallback identification

Per prompt §16. The system must stay useful when recognition fails, and must
**never pretend** that it identified someone.

| Reason | Fallback |
| --- | --- |
| Face obstructed or injured | Manual entry by a responder; tier-2 visible features |
| Poor lighting | Re-capture guidance, then manual |
| No registration | Manual search by responder with incident audit trail |
| Extreme pose | Re-capture with pose guidance, then manual |
| Failed recognition | `REVIEW_REQUIRED` with ranked candidates for a human |
| Multiple candidates | Human chooses from the shortlist |
| Service unavailable | Manual incident creation still works |

Every fallback path writes an `incident_event`. **A fallback is a legitimate
outcome with a full audit trail - never a dead end, never a silent failure.**

## UI architecture

### Emergency mode removes distraction

Not a dashboard with a red button. During an active emergency the UI shows only:

```
WHAT TO DO NOW     the single next instruction
WHAT IS HAPPENING  current state, plainly named
RESULT             what was found, and how certain it is
NEXT STEP          the action available from here
```

No analytics, no profile chrome, no technical vocabulary. No "embedding", no
"cosine similarity", no "confidence score" - "Possible match" and "Check this
person's ID" instead.

### Result states

| State | Meaning | Next action offered |
| --- | --- | --- |
| Scanning | Camera active, seeking a face | Reposition guidance |
| Processing | Server working | Wait, with a cancel |
| Possible match | Above review threshold | Verify identity, or reject |
| Confirmed | Human verified, or above high threshold with clear margin | Contact, route, resolve |
| No confident match | Nothing plausible | Fallback options |
| Poor quality | Image unusable | Specific retry guidance |
| Multiple candidates | Ambiguous | Choose from shortlist |
| Service unavailable | Backend or network failure | Retry, or offline-capable fallback |

Every state offers a next action. A dead end is a design bug.

### Design tokens

The existing monochrome ramp is sound and stays. Two corrections:

1. **Add `<alpha-value>` to every ramp colour.** This fixes 19 silently dead
   utilities including both fixed bars' backgrounds. CSS variables become
   space-separated RGB channels; Tailwind can then compose them.
2. **Extend the spacing table** with the values the UI already assumes
   (`5.5`, `13`). The table is currently `replace`, so anything missing compiles
   to nothing.

Light and dark are already separately designed - every cross-theme pair differs,
and `color-scheme` is set per theme. That is not inversion; keep it.

### Contrast

`--c-faint` fails WCAG AA for normal text in both themes (3.43:1 light,
3.67:1 dark against 4.5:1 required). Either darken it to clear 4.5:1 or reserve
it for large text and non-text use. Metadata and counts are body-sized, so the
first option is correct.

## Accessibility

Baseline: **WCAG 2.1 AA**, verified rather than asserted.

| Requirement | Implementation |
| --- | --- |
| Keyboard navigation | Every flow completable by keyboard; visible focus ring (already present) |
| Dialogs | Focus trap **and** focus restore in `Sheet` - currently missing |
| Tabs | Roving tabindex, arrow keys - currently missing |
| Screen readers | Live region announcing each capture and identification state |
| Touch targets | 44px minimum, **enforced** via a class that is actually generated |
| Contrast | AA verified with a tool, not computed by hand |
| Motion | `prefers-reduced-motion` honoured by **all** animations, not just sheet entry |
| Labels | Every input programmatically associated; no orphan `.label` divs |
| No colour-only state | Every state carries text and an icon |
| Language | `<html lang>` follows the locale; Tamil is a first-class path |

## Localization

English and Tamil, both first-class.

Move the catalogue to `locales/en.json` and `locales/ta.json` - separate files
rather than one 600-line `strings.ts`. Keep the two things the current system
gets right: **Tamil is structurally complete**, and **the key set is type-safe**
(`StringKey = keyof typeof en`, so a missing key is a compile error).

Emergency instructions are **rewritten for Tamil UX, not word-for-word
translated**. "Face too far" is not a Tamil sentence a panicking bystander can
act on. Each message names the action.

Nine states to cover per the prompt: `NO_FACE`, `MULTIPLE_FACES`, `LOW_LIGHT`,
`BLURRY_IMAGE`, `FACE_TOO_FAR`, `FACE_TOO_SMALL`, `EXTREME_POSE`,
`FACE_OCCLUDED`, `GOOD_QUALITY`.

## ML evaluation

A real validation set, real metrics, published numbers. This is an ML project;
"it works" is not a result.

### Dataset

Synthetic renders today; **real or realistically-simulated capture conditions**
after the migration. Classes across lighting (normal, low, backlit), pose
(frontal, ±15°, ±30°), expression, distance, occlusion (partial, heavy),
resolution, and **glasses**.

### Metrics

| Metric | Why it matters here |
| --- | --- |
| **FAR** | The dangerous error. A stranger shown as a victim is the failure that must drive the threshold up. |
| **FRR** | The costly error. A missed match delays care. |
| Precision, recall, F1 | Standard, reported per condition. |
| ROC, and **EER** | Threshold choice is a trade-off between FAR and FRR; EER locates the balance. |
| **Score margin distribution** | Feeds the `MULTIPLE_CANDIDATES` rule, which the current pipeline cannot evaluate. |
| Inference latency | p50 and p95, because this runs on a phone in an emergency. |
| Quality-gate precision | How often the quality gates correctly reject an unusable capture. |

Reported **per condition**, not just as one aggregate. An average across
lighting and occlusion hides exactly the cases that matter.

### Calibration

The threshold comes from the ROC, chosen at an explicitly stated FAR target,
and stored as a `threshold_version`. The dataset, model, metric, method and both
error rates are documented with it.

## Security

| Concern | Decision |
| --- | --- |
| Session storage | httpOnly refresh cookie; access token in memory |
| Authorization | RLS + application permissions, both enforced |
| Embeddings | No client read path, ever. Encrypted at rest. |
| Secrets | Server-side only. **No Supabase service key in frontend code, ever.** |
| Uploads | Magic-byte validation, decode limits, pixel-bomb guard, size cap |
| Rate limiting | Per-IP and per-user; identification is expensive and enumerable |
| CORS | Explicit origin allowlist, never `*` with credentials |
| Audit | Append-only; actor, action, resource, metadata, request_id |
| Logging | **Never log raw vectors.** Never log medical detail in plaintext. |
| Biometric enumeration | Identification is the only expensive operation; rate-limit it hard and audit every attempt |

### Threats specific to TRAYA

- **Biometric enumeration** - someone repeatedly submits photos to discover who
  is enrolled. Mitigated by rate limiting, attempt auditing, and by the fact
  that a low result reveals nothing about non-matches.
- **Over-trust in a match** - the responder acts on a false positive. Mitigated
  by `REVIEW_REQUIRED`, the margin rule, and a UI that never states an
  unverified AI result as an identity.
- **Silent degradation** - the current SQLite fallback, which could put real
  medical data in a local file. **Removed.** A production deployment that
  cannot reach Postgres fails to start.

## Free-tier architecture

Supabase Free has real limits. The design fits inside them deliberately.

| Resource | Budget | Design response |
| --- | --- | --- |
| Database | 500 MB | Embeddings are 512 bytes each. 100k enrolments is 51 MB. Fits. |
| Storage | 1 GB | No frame storage. Retention windows on evidence. |
| Egress | 5 GB/month | 512-byte embeddings; images are the only large payload and are transient |
| Auth MAU | 50,000 | Well above any realistic MVP population |

**The 1 GB storage limit is the binding constraint**, which is why frames are
never persisted. Store the profile, the emergency profile, the embeddings, the
metadata, the selected registration samples, incident metadata and the audit
data. Everything else is transient.

## What is being kept

Rewriting working functionality is explicitly out of scope.

**Kept as-is** - the 47-endpoint router structure; `BiometricEngine`'s provider
interface; `run_identification`'s four-tier logic and its human-confirmation
guards; `analyze_quality`'s real blur and lighting scoring and its stable
`reason_codes`; `ROLE_PERMISSIONS`; Fernet encryption at rest; cascade-delete
biometric schema; audit-on-every-decision discipline; repositories that flush
but never commit; the demo seed's idempotency; `api/client.ts` as the single
network boundary; `index.css` colour tokens and both themes; `Layout.tsx` app
bar, tab bar and safe-area handling; `Guards.tsx`; `useCamera.ts`; the
`enroll.*` translations already written; the documentation contract.

**Replaced** - the simulation engine's internals; SQLite as the default;
custom JWTs; the absence of RLS; the absence of alignment.

**Removed** - the silent database fallback; `mean_center()` and
`compare_centered()`; the unreachable branch in `estimate_pose`.

## Documentation set

The rebuild requires 26 technical documents and a non-technical set. Rather
than scatter them across the repo, they live under `docs/`, indexed from
`docs/README.md`, and follow the existing contract: one H1, a breadcrumb, and a
named mention of every endpoint, model, table, migration, repository method,
service function, setting, role, permission, page, component, icon, API method
and exported type.

| Document | Covers |
| --- | --- |
| `AUDIT.md` | Current state, verified findings, ranked bugs |
| `TARGET_ARCHITECTURE.md` | This page |
| `MIGRATION_PLAN.md` | Phase order, gates, rollback |
| `MODEL_EVALUATION.md` | FAR, FRR, EER, ROC, latency, calibration |
| `SECURITY_MODEL.md` | Threats, controls, RLS rationale |
| `NON_TECHNICAL.md` | For reviewers, faculty and non-technical stakeholders |