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
| `complete_enrollment` | 422 with fewer than 3 accepted samples. Calls `ProfileRepository.replace_embeddings` - re-enrollment **replaces**, never appends - and audits `biometric.enrolled`. |
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

## Identification engine - `app/services/identification/engine.py`

`app/services/identification/engine.py`. **The engine is a simulation, not a
production recogniser** - see
[ADR 0001](../decisions/0001-simulation-biometric-engine.md). Read that before
trusting anything in this section.

### Public surface

| Function | Purpose |
|---|---|
| `decode_image` | Magic-byte validation; accepts JPEG, PNG and WebP. |
| `to_gray_np` | Grayscale `numpy` array. |
| `skin_mask` | HSV skin segmentation at a 1/4 downscale; returns mask and component boxes. |
| `analyze_quality` | The quality gate. Returns a `QualityReport` (`to_dict`). |
| `detect_faces` | Haar cascade when available and `BIOMETRIC_ENGINE` is `auto` or `opencv`; otherwise simulation. Returns boxes plus a mode string. |
| `extract_embedding` | 12 explicit darkness features, per-feature scaled, zero-padded to `EMBEDDING_DIM` (320). |
| `estimate_pose` | Normalised darkness asymmetry in (-1, 1) with a confidence. **Not degrees.** |
| `direction_against` | Resolves a `PoseEstimate` to `front`/`left`/`right`/`up`/`down` given an optional baseline. |
| `pose_step_key` | The step a pose represents; `unknown` when unconfident. |
| `compare` | `clamp(1 - ||a - b|| / 3.0, 0, 1)`. |
| `get_template` | The template layer; a passthrough in simulation. |
| `mean_center` | No-op passthrough. |
| `compare_centered` | Delegates to `compare`. |
| `get_engine` | The module-level `BiometricEngine` singleton. |

Class `BiometricEngine`: `mode` (`simulation` or `opencv`), `is_simulation`, and
`process(image_bytes)`, `embed(image_bytes, box)`, `pose(image_bytes, box)`,
`similarity(a, b)`.

Private: `_label` (4-connected components), `_variance_of_laplacian`,
`_simulate_detect`, `_asymmetry`.

### Data classes

Four `@dataclass` results carry data out of the module. None of them has any
behaviour beyond serialisation or a derived property.

| Class | Fields / properties |
|---|---|
| `FaceBox` | `x`, `y`, `w`, `h`; `area` (derived, `w * h`) and `to_dict()`. |
| `QualityReport` | The five quality scores plus `usable_for_matching`, `reasons`, `reason_codes`; `to_dict()`. |
| `DetectionResult` | `face_boxes`, `quality`, `engine_mode`, `faces_found`. |
| `PoseEstimate` | `asymmetry`, `confidence`, `direction()` and `is_frontal()`. |

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

### Pose

`estimate_pose` returns normalised asymmetry, not an angle. Constants
`TURNED_OFFSET = 0.03` and `MAX_MEASURABLE_ASYMMETRY = 0.6`. Low confidence
(`face_too_small`, `low_contrast`, `no_structure`, `one_side_dominated`)
yields `unknown` - never a false `front`, and never a rejection.

### Why this is not a biometric

- The embedding is 12 darkness features. It is a deterministic image
  descriptor, not a learned face representation, and it is not biometrically
  meaningful.
- `compare` measures how similar two images are in brightness.
- **Measured over the synthetic corpus:** clean same-identity 0.986-0.995,
  degraded same-identity 0.711-0.866, impostor 0.000-0.817 with a mean of
  0.309. The impostor range overlaps the degraded same-identity range, and
  6 of 30 impostor pairs exceed the 0.62 review threshold. Two demo identities
  collide at 0.817.
- OpenCV 5.x ships no cascade data in this environment, so `detect_faces` runs
  in simulation mode and the boxes are synthetic too.

`mode` and `is_simulation` exist so no caller can quietly present this as a
working recogniser. Every API result carries `engine_mode` and `demo_mode`, and
the UI renders a simulation banner.

**Known defect:** `estimate_pose` has unreachable code after its first `return`
(a duplicate return with a different reason, lines 523-526). It is dead, not
harmful, but it should be deleted.

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
