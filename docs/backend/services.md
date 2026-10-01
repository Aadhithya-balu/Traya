[../README.md](../README.md) | [Backend index](README.md) | [API reference](api.md)

# Services

Domain logic. Routers validate and delegate; services decide; repositories
fetch and persist. A rule that could surprise a reader belongs here.

| Module | Responsibility |
|---|---|
| [`app/services/audit_service.py`](#audit-service) | The audit funnel. |
| [`app/services/biometric/enrollment.py`](#guided-biometric-enrollment) | Coached multi-pose enrollment. |
| [`app/services/demo/demo_images.py`](#synthetic-image-generation) | Deterministic synthetic faces. |
| [`app/services/demo/seed.py`](#demo-seed) | Idempotent demo data. |
| [`app/services/identification/engine.py`](#identification-engine) | The biometric engine. **Simulation.** |
| [`app/services/identification/confidence.py`](#thresholds) | Threshold resolution. |
| [`app/services/identification/registry.py`](#enrolled-registry) | Enrolled profile loading. |
| [`app/services/identification/pipeline.py`](#matching-pipeline) | The multi-tier match. |
| [`app/services/location/location_service.py`](#location) | Haversine and hospital search. |
| [`app/services/medical/medical_service.py`](#medical-summary) | What a responder may see. |
| [`app/services/notification/notification_service.py`](#notifications) | Notification rows. |

---

## Audit service - `app/services/audit_service.py`

`app/services/audit_service.py`. Every write in the system funnels through here
so there is exactly one place that knows the audit contract.

| Function | Purpose |
|---|---|
| `write_audit` | The single write path. Keyword-only: `actor_type`, `action`, and optional `actor_id`, `resource_type`, `resource_id`, `session_id`, `details`, `ip`, `commit`. |
| `log_user_action` | `write_audit` with `actor_type="user"`. |
| `log_session_action` | `write_audit` with `actor_type="public_session"`, setting both `actor_id` and `session_id`. |

`SENSITIVE_ACTIONS` enumerates the 33 action strings that must always be
present; treat adding an action outside that set as a review event.

**`commit=False` is the point.** It lets a domain write and its audit row commit
in one transaction, so there is no window where a successful write left no
trail. See [ADR 0006](../decisions/0006-audit-on-every-sensitive-action.md).

**Gap:** `settings.SESSION_RETENTION_DAYS` (90) is applied to sessions only.
Audit rows have no retention job, so the table grows without bound.

---

## Guided biometric enrollment - `app/services/biometric/enrollment.py`

`app/services/biometric/enrollment.py`. The coached five-pose flow, with a
dataclass `SampleVerdict` (`to_dict`) as the per-sample result.

Constants: `ENROLLMENT_TTL_MINUTES = 20`, `MIN_ACCEPTED_SAMPLES = 3`,
`POSE_STEPS` = `front, left, right, up, down` with `STEP_KEYS`,
`STEP_INSTRUCTIONS` and `GUIDANCE_BY_REASON`.

| Function | Purpose |
|---|---|
| `guidance_for` | Maps engine `reason_codes` to UI guidance codes. The engine stays the single source of truth for usability. |
| `start_enrollment` | Requires `active_consent(user.id, "biometric")` or raises 409. Resumes a live in-progress enrollment; marks stale ones `abandoned`. |
| `add_sample` | Returns `(enrollment, verdict)`. 404 not owner, 409 not in progress, 410 past TTL. |
| `normalized` | L2-normalises a vector. Applied to the centroid because the matcher compares with cosine, and an un-normalised mean is not a unit vector. Raises on a zero vector, which no quality-accepted sample produces. |
| `consistency_report` | Every unordered pair of the person's own samples through the live engine's `similarity`, returning `min_pairwise`, `mean_pairwise`, `pairs` and the `threshold` the minimum was tested against. Fewer than two samples yields `min_pairwise = 0.0`, which reads as maximally inconsistent rather than unknown. |
| `complete_enrollment` | 422 with fewer than 3 accepted samples. Refuses a set whose `min_pairwise` is below `ENROLLMENT_MIN_SELF_SIMILARITY`. Stores the normalised centroid through `ProfileRepository.replace_embeddings` - re-enrollment **replaces**, never appends - **deletes the pending sample rows in the same transaction**, and audits `biometric.enrolled` with `sample_vectors_purged` and `intra_person_similarity`. |
| `abort_enrollment` | Marks the enrollment `abandoned`. Silently returns if not the owner. |
| `enrollment_state` | Serializable progress: `steps[]`, `current_instruction`, `can_complete`. |

Private helpers: `_baseline_for`, `_record_report` (keeps the last 20 verdicts),
`_is_stale`.

### Design decisions worth knowing

- **Quality gates reject; pose does not.** A sample failing the engine's quality
  gates is rejected. A pose mismatch is *reported* and the step still advances.
  The pose estimator is a darkness-asymmetry heuristic (see below) and must not
  be able to block a good capture.
- **The vertical baseline is measured, not assumed.** The first accepted
  `front` sample stores `baseline_offset_y`; `up` and `down` are judged relative
  to it. Horizontal directions need no baseline.
- **Samples are stored encrypted while in progress**, so an abandoned
  enrollment never leaves plaintext templates behind.
- **The template is the centroid, not the samples.** One unit vector per person
  means N-to-1 comparison at match time and a single score, instead of a max over
  N templates - and a max is a description of the luckiest capture, not of the
  person. `num_samples` still reports how many samples were contributed, because
  that is the useful provenance and not the number of rows that resulted.
- **Per-image quality gates cannot detect a wrong person.** Four individually
  good photos of two different faces satisfy every gate in the engine, so
  `complete` compares the person's own samples against each other and refuses
  the set. Without that check an enrollment assembled carelessly becomes a
  template that represents nobody, and at the review threshold could match a
  stranger.
- **Purging is tied to a committed template, not to an attempt.** A successful
  `complete` deletes every `biometric_enrollment_samples` row for the enrollment
  in the same transaction that stores the centroid, accepted and rejected alike:
  each of those was a biometric derived from someone's face and existed only to
  build the mean. The enrollment row survives as the audit record, keeping its
  per-sample quality and pose reports and no vectors. A **refused** set keeps its
  samples, because that is the one failure where they are the only diagnostic -
  the person cannot see their own pairwise scores, so an unexplained 422 would
  otherwise be impossible to investigate. `sample_vectors_purged` is in the audit
  details so the count is checkable after the fact.

---

## Synthetic image generation - `app/services/demo/demo_images.py`

`app/services/demo/demo_images.py`. Deterministic faces built with PIL, used by
the demo and the tests.

| Function | Purpose |
|---|---|
| `render_face` | `seed` drives per-capture randomness; `identity` drives geometry and colour. Accepts `faces`, `noise`, `blur`, `dark`, `bright`, `occluded`, `small_face`, and `head_yaw` in (-1, 1), which turns the head and shades the trailing side. |
| `render_enrollment` | One identity, four rotating noise variants. |
| `to_base64` | JPEG quality 90. |
| `to_bytes` | Raw bytes. |

**Identity strings must be deterministic and stable.** The face feature space is
small, so arbitrary identity strings collide - `unknown-person-X9` versus
`test-identity` measured 0.807, which is above the 0.62 review threshold and
made the suite flaky. Never introduce a random UUID-based identity into
enrollment. `enroll-demo-charlie-99` was chosen because its maximum similarity
to any enrolled demo face is 0.436.

---

## Demo seed - `app/services/demo/seed.py`

`app/services/demo/seed.py`. Idempotent seeding; safe to run on every boot.

| Function | Purpose |
|---|---|
| `seed_roles` | Idempotent role creation. |
| `seed_settings` | Threshold and retention settings. |
| `seed_hospitals` | 9 fictional hospitals (Mumbai and New Delhi). |
| `seed_user` | Creates a user and assigns roles. |
| `seed_medical` | Medical profile for a seeded user. |
| `seed_contact` | One emergency contact. |
| `seed_features` | Visible identifying features. |
| `seed_consent` | Grants biometric consent - enrollment requires it. |
| `seed_biometric` | **Clears stale embeddings before re-enrolling.** Warns and skips with fewer than 2 usable samples. |
| `seed_all` | `init_db()` then everything, then `ensure_permission_matrix`. |

`seed_all(skip_if_seeded=True)` uses the existence of
`aarav.kumar@demo.traya` as its sentinel and returns immediately when demo data
is present, which keeps cold boots at roughly 3 seconds. A first boot on a fresh
database costs about 7 seconds for the one-time biometric render.
`ensure_permission_matrix` runs on **both** paths, so a fast boot still
reconciles the access model.

Runnable as `python -m app.services.demo.seed`.

Constants: `DEMO_PASSWORD = "TrayaDemo#2026"`, `DEMO_USERS` (4 fictional
citizens), `DEMO_RESPONDERS` (5), `HOSPITALS` (9), `SETTINGS` (6). All demo
data is fictional and must stay that way.

---

## Biometric providers - `app/services/identification/providers.py`

`app/services/identification/providers.py`. **Two interchangeable
implementations of one interface.** The real one is YuNet (detection, with five
landmarks) plus SFace (a 128-dimensional descriptor), both running on the OpenCV
DNN runtime. The simulation one is the pre-Phase-5 engine, kept deliberately so
the demo and the test suite remain runnable on a machine with no model files.

| Class | Role |
|---|---|
| `FaceEmbeddingProvider` | The `Protocol`. `detect`, `embed`, `pose`, `similarity`, `align`, `is_simulation`, `mode`, `name`, `version`, `preprocessing_version`, `dimension`. |
| `YuNet128Provider` | The real engine. `is_simulation = False`, `mode = "yunet"`, `name = "sface"`. |
| `SimulationProvider` | 12 darkness features zero-padded to 320. `is_simulation = True`, `mode = "simulation"`. |
| `AlignedFace` | An aligned 112x112 crop plus the `roll_degrees` that alignment removed. |
| `FaceBox` | `x`, `y`, `w`, `h`, `score`, `landmarks` (5 points or `None`), `source`. |

Module functions: `get_provider(reload=False)` resolves and caches the
configured provider; `reset_provider()` drops the cache; `models_present()`
reports whether both weight files are on disk.

**The image helpers moved here** and are re-exported by `engine.py`, so
`engine.decode_image` is the same object. They are provider plumbing now: the
real engine needs the NumPy grayscale array that the OpenCV runtime wants, and
the simulation needs the skin mask.

| Function | Purpose |
|---|---|
| `decode_image` | Magic-byte validation; accepts JPEG, PNG and WebP. |
| `to_gray_np` | Grayscale `numpy` array. |
| `skin_mask` | HSV skin segmentation at a 1/4 downscale; returns mask and component boxes. |
| `variance_of_laplacian` | The blur metric the quality gate scores on. |

`FaceBox` has two derived properties beyond `area`: `has_landmarks` reports
whether the five points are present, which is what decides if pose can be read
geometrically. `dimension` is a provider class attribute (128 real, 320
simulation) and is the number the storage layer should be checked against.

### The two settings that decide which engine runs

`BIOMETRIC_ENGINE` accepts `auto`, `yunet` or `simulation`. **`opencv` is
retained only as an alias for `yunet`, and it logs a warning**, because that
value used to promise real detection and silently deliver the simulation -
OpenCV 5 removed the `CascadeClassifier` API it was gated on. See
[ADR 0001](../decisions/0001-simulation-biometric-engine.md) for that history
and [ADR 0008](../decisions/0008-real-biometric-engine.md) for the replacement.

`auto` uses the real engine **only if the weight files are present**, and
otherwise logs a warning that names the simulation as what it is. `yunet` is
strict: it raises if the weights are missing, on the grounds that a deployment
which asked for a recogniser and got a simulation is the worst failure this
system has. Weights are fetched by
`backend/scripts/fetch_biometric_models.py`, which verifies a pinned SHA-256
per file and writes a `NOTICE` beside them. They are not committed.

### The two engines are not interchangeable at the data level

A YuNet descriptor and a simulation vector are different lengths in different
units, so the provider refuses to compare across engines:

- **Real:** 128 dimensions, L2-normalised, cosine similarity in [0, 1]. Every
  coordinate is non-zero.
- **Simulation:** 320 dimensions of which 12 are real and 308 are zero padding.

`similarity()` raises `ValueError` on a length mismatch rather than returning a
low score, and templates are stored with the engine's `version` so a real
descriptor is never compared against a simulation vector that happens to be in
the same table. `version` and `preprocessing_version` are the reason a stored
template is comparable or not; changing either invalidates it.

---

## Identification engine - `app/services/identification/engine.py`

`app/services/identification/engine.py`. A thin facade over whichever provider
is configured, holding the quality gate and the pose rules. The engine no longer
knows how a face is found or described - it delegates to a provider and owns the
decisions that must behave identically on both engines.

### Public surface

| Function | Purpose |
|---|---|
| `decode_image`, `to_gray_np`, `skin_mask` | Re-exported from `providers` - the same objects, not copies. |
| `analyze_quality` | The quality gate. Returns a `QualityReport` (`to_dict`). |
| `detect_faces` | Delegates to the provider. Returns boxes plus a mode string. |
| `extract_embedding` | Delegates to the provider. Dimension follows the engine. |
| `estimate_pose` | Landmarks when the provider has them, asymmetry otherwise. |
| `direction_against` | Resolves a `PoseEstimate` to `front`/`left`/`right`/`up`/`down` given an optional baseline. |
| `pose_step_key` | The step a pose represents; `unknown` when unconfident. |
| `compare` | Delegates to the provider's `similarity`. |
| `get_template` | The template layer; a passthrough in simulation. |
| `get_engine` | The module-level `BiometricEngine` singleton. |
| `get_provider` | Re-exported from `providers`, so callers need one import. |

Class `BiometricEngine`: `mode`, `is_simulation`, `algo_version`, `dimension` and
`process(image_bytes)`, `embed(image_bytes, box)`, `pose(image_bytes, box)`,
`similarity(a, b)`.

**`dimension` is a property, not a constant**, and that is deliberate. It reads
through to whichever provider is active, so a caller sizing a buffer gets 128 on
the real engine and 320 on the simulation without branching. Anything that
persists a vector should read it rather than trusting `settings.EMBEDDING_DIM`,
which only ever describes the simulation.

Private: `_label` (4-connected components), `_variance_of_laplacian`,
`_simulate_detect`, `_asymmetry`, `_pose_from_landmarks`.

### Data classes

Four `@dataclass` results carry data out of the module.

| Class | Fields / properties |
|---|---|
| `FaceBox` | `x`, `y`, `w`, `h`; `area` (derived, `w * h`) and `to_dict()`. Re-exported from `providers`. |
| `QualityReport` | The five quality scores plus `usable_for_matching`, `reasons`, `reason_codes`; `to_dict()`. |
| `DetectionResult` | `face_boxes`, `quality`, `engine_mode`, `faces_found`. |
| `PoseEstimate` | `offset_x`, `offset_y`, `confident`, `roll_degrees`, `source`; `direction` and `is_frontal` derived. |

`area` is a `@property`, not a field, so it is available on every box without
the detector computing it. `direction` and `is_frontal` are the same idea for
pose: the classifier is decided once, at the edge, and every caller reads the
same answer.

`process` returns a `DetectionResult`; `pose` returns a `PoseEstimate`. Those two
return types are the module's actual public contract - the module-level
functions above are the pieces they are built from.

### Quality gate

`analyze_quality` measures blur (variance of Laplacian), lighting, contrast,
face visibility and occlusion, and emits both human `reasons` and **stable
`reason_codes`**: `no_face`, `multiple_faces`, `blurry`, `too_dark`,
`face_too_small`, `occluded`, `low_quality`.

A capture is `usable_for_matching` only when `image_quality_score >= 0.5`,
`face_visibility_score >= 0.45`, `occlusion_score <= 0.75`, **and exactly one
face is present**. `reason_codes` is what the UI and the enrollment coach both
read, so the engine remains the single authority on usability.

**The gate is engine-dependent in one place worth knowing.** A real detector
returns a face box but not a skin-density measurement, so `face_visibility_score`
is derived from the box's share of the frame and is never `0.0` on the real
engine. The simulation, which produces its own boxes, measures skin coverage
directly. A capture can therefore be judged `face_too_small` on the simulation
and pass on the real engine for the same picture.

### Pose

Two readers, distinguished by `PoseEstimate.source`.

**Real engine (`source = "landmarks"`).** `offset_x` and `offset_y` are the
horizontal and vertical position of the nose tip relative to the midpoint of the
eyes, taken from the detector's five landmarks. `roll_degrees` is the measured
eye-line angle and needs no baseline.

**The bias, measured.** Three frontal faces from three different people gave
`offset_x` of +0.43, +0.45 and +0.53 - all of them "left" if read absolutely, and
all of them far past the `TURNED_OFFSET = 0.03` threshold. A real nose tip sits
off the midpoint of its own eyes by a per-identity amount.

**So a landmark reading with no baseline returns `unknown`, not a direction.**
`direction_against` enforces it, and when a baseline *is* supplied both axes are
read as a delta from that baseline, so the bias cancels. `unknown` is the honest
answer: the measurement happened and is not interpretable without knowing where
this person's centre is. This is what keeps Phase 6's guided wizard from asking
someone to turn their head while they are already facing the camera.

**Simulation (`source = "asymmetry"`).** Normalised brightness asymmetry between
the halves of the crop. Documented in ADR 0001; it measures how lopsided the dark
regions are, not where the head is pointing, and it says so. Its left/right
reading is signed by the crop, so it does not need a baseline for horizontal.

When the provider returns no landmarks, the engine falls back to the asymmetry
reader so a box without points still gets a reading. Low confidence
(`face_too_small`, `low_contrast`, `no_structure`, `one_side_dominated`) yields
`unknown` - never a false `front`, and never a rejection.

### What the numbers do and do not say

Every result carries `engine_mode` and `is_simulation`, so no caller can present
one engine's output as the other's, and the UI renders a simulation banner from
the same fields. Measured figures for both engines, with the commands that
produced them, are in
[MODEL_EVALUATION.md](../MODEL_EVALUATION.md).

**Neither engine's thresholds are calibrated.** The real engine's figures come
from three photographs of two people. That is enough to show the descriptor
separates those identities and that alignment works, and nowhere near enough to
state a false-match rate. Calibration is Phase 10, on a proper corpus, and the
thresholds in `system_settings` are still the simulation's.

---

## Thresholds - `app/services/identification/confidence.py`

`app/services/identification/confidence.py`.

`Thresholds` is a frozen dataclass - `high`, `review`, `face_fallback`,
`context_boost`, `secondary_boost` - with `as_dict()`. Defaults come from
`settings`; the attribute names match the setting keys exactly.

`thresholds_from_settings(db, fallback)` overlays live `SystemSetting` rows on
the static defaults, and falls back silently on any exception, so a database
problem degrades to the compiled-in values rather than failing an
identification.

Live values: `HIGH_CONFIDENCE_THRESHOLD` 0.82, `REVIEW_THRESHOLD` 0.62,
`FALLBACK_FACE_THRESHOLD` 0.60, `CONTEXT_BOOST` 0.05,
`SECONDARY_FEATURE_BOOST` 0.06. These are seeded into `system_settings` and are
editable at runtime through `PUT /api/admin/settings/{key}`.

---

## Enrolled registry - `app/services/identification/registry.py`

`app/services/identification/registry.py`. A thin domain wrapper over
`RecognitionRepository`, exported as `EnrolledProfile`, `load_enrolled`,
`serialize_embedding`.

`load_enrolled(db)` returns only `status == "enrolled"` profiles belonging to
active users, decrypting each embedding. `serialize_embedding(vector)` is
`float64` `.tobytes()`.

**Fail-soft by design:** a blob that cannot be decrypted is skipped, not fatal.
That is what lets the encryption key survive a partial corruption - and the flip
side of [ADR 0005](../decisions/0005-biometric-encryption-at-rest.md) is that a
key rotation silently degrades those profiles to "not enrolled".

---

## Matching pipeline - `app/services/identification/pipeline.py`

`app/services/identification/pipeline.py`. The multi-tier match and the status
band that the whole product keys off.

Class `PipelineResult` with `to_dict(session_id)`, which always emits
`engine_mode` and `demo_mode`.

| Function | Purpose |
|---|---|
| `run_identification` | The whole flow. Keyword-only: `image_bytes`, `session`, and optional `secondary_features`, `lat`, `lng`, `engine`. |
| `confirm_candidate` | Records a human decision. Raises `ValueError` (-> 404) for a missing attempt or candidate. On accept sets `confidence_category = "HUMAN_CONFIRMED"`. |

Private: `_match_features` (tier 2, text match over visible features),
`_context_match` (tier 3, haversine to the person's home - 1.0 within 10 km,
0.4 within 40 km, else 0.0), `_max_similarity`, `_persist_attempt`.

### Gate order

```
MULTIPLE_FACES -> NO_FACE -> POOR_QUALITY -> no enrolled profiles (NO_MATCH)
              -> tier 1 face match -> status band
```

Order matters: multiple faces is reported before poor quality because telling a
responder to move to a better angle is useless when two people are in frame.

### Statuses and what they mean

| Status | Meaning | Session |
|---|---|---|
| `HIGH_CONFIDENCE` | Similarity at or above 0.82. | `completed`, `identified_user_id` set. |
| `REVIEW_REQUIRED` | 0.62 to 0.82. A human must confirm. | stays `active`. |
| `LOW_CONFIDENCE` | Below 0.62 but a candidate exists. | stays `active`. |
| `NO_MATCH` | Nothing above the fallback threshold. | stays `active`. |
| `NO_FACE` / `MULTIPLE_FACES` / `POOR_QUALITY` | Retake the photo. | stays `active`. |

The session is marked `completed` **only** on `HIGH_CONFIDENCE` or a human
confirmation, and `identified_user_id` is auto-set **only** on
`HIGH_CONFIDENCE`. That is what keeps the medical summary gated behind a real
match.

`fallback_used` is set when the best similarity is below
`face_fallback + 0.08` **and** a non-face method contributed, so a UI can warn
that a weak result leaned on context rather than the face.

`MAX_CANDIDATES = 3`; `HUMAN_READABLE` maps each status to responder-facing
prose.

---

## Location - `app/services/location/location_service.py`

`app/services/location/location_service.py`, with `EARTH_RADIUS_KM` re-exported
from the package `__init__`.

| Function | Purpose |
|---|---|
| `haversine_km` | Great-circle distance in km. |
| `travel_minutes` | ETA at an assumed 40 km/h; `None` for zero distance. |
| `find_nearby_hospitals` | Returns up to `limit` hospitals within `radius_km` as dicts, nearest first. |

`NearbyHospital` is the dataclass result. **Loads all hospitals and sorts in
Python** - no SQL filtering. Fine for 9 demo rows; a city-scale registry needs a
PostGIS `ST_DWithin` query.

`availability_verified` is reported exactly as stored. Availability is never
inferred, because a responder acting on a fabricated "open" is worse than one
seeing no data.

---

## Medical summary - `app/services/medical/medical_service.py`

`app/services/medical/medical_service.py`. **This module is the privacy
boundary**: it decides what a given audience may see.

`PublicSummary` is the dataclass result (`to_dict`).

| Function | Audience | Returns |
|---|---|---|
| `get_public_summary` | anyone holding session access | Blood group, critical allergies, conditions, medications, synthesized `emergency_warnings`, the primary emergency contact, `photo_available: false`. |
| `get_responder_profile` | `view_emergency_profile` | The public summary plus `additional` (`emergency_notes`, `preferred_hospital`), `visible_features` and `all_contacts`. |

Private: `_age`.

`RESPONDER_VISIBLE_KEYS` is `{"emergency_notes", "preferred_hospital",
"home_lat", "home_lng"}`, but only the first two are copied - `home_lat` and
`home_lng` are declared and unused, because exposing a home address is a
different decision from exposing a preferred hospital and has not been made
yet.

The primary contact is read through `ProfileRepository.primary_contact`, which
falls back to the first contact when none is flagged, so a medical summary is
never silently contact-less because of a data-entry slip.

---

## Notifications - `app/services/notification/notification_service.py`

`app/services/notification/notification_service.py`.

| Function | Purpose |
|---|---|
| `create_notification` | Inserts and commits. |
| `get_unread` | Returns recent notifications. **Does not filter on `read`** despite the name. |
| `mark_read` | Marks read and commits, only if found. |

`GET /api/users/notifications` has no UI yet, and `NotificationRepository` is the
newer path used by `users.py`. Both should be reconciled before either is
relied on.
