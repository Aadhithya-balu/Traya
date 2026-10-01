[../README.md](../README.md) | [Decisions](README.md)

# ADR 0008: A real recogniser, chosen from what this machine can actually run

- **Status:** Accepted
- **Date:** 2026-10-01
- **Affects:** `app/services/identification/providers.py`, `app/services/identification/engine.py`, `app/config/settings.py`, `scripts/fetch_biometric_models.py`
- **Supersedes:** nothing. [ADR 0001](0001-simulation-biometric-engine.md) remains
  accurate about the simulation, which is still in the codebase and still
  selected by configuration. What changed in Phase 5 is that it is no longer the
  only engine.

## Context

[ADR 0001](0001-simulation-biometric-engine.md) recorded that `opencv-python` 5.x
removed `CascadeClassifier`, so the "real" path in the engine had never executed
and the simulation was the only reachable behaviour. The embedding was twelve
real numbers zero-padded to 320.

Phase 5 has to put a genuine recogniser behind the same interface. The
constraint that shaped the decision is not accuracy, it is the runtime: this is
Python 3.14.2 on Windows with `opencv-python` 5.0.0, and no compiler.

That rules out the obvious candidates before they can be evaluated:

- `dlib` and `face_recognition` have no Python 3.14 wheels and no prebuilt
  Windows wheels either. They would need a C++ toolchain.
- `torch` is a 2.7 GB dependency for one model.
- `mediapipe` requires `protobuf` constraints that conflict with the installed
  set.
- `insightface` requires `onnxruntime`, which is available - but only
  because of the next entry.

`onnxruntime` *is* installable here: version 1.30.0 publishes a `cp314` win_amd64
wheel. It was downloaded and confirmed importable-shaped, then **not** used. See
Consequences.

## Decision

Use **YuNet** for detection and **SFace** for recognition, both on the OpenCV DNN
runtime that is already installed, and keep the simulation as a second
implementation of the same interface.

1. **YuNet** (`face_detection_yunet_2023mar.onnx`, MIT). `cv2.FaceDetectorYN` is
   present in OpenCV 5.0.0, so no new dependency. It returns a box, a confidence
   score, and **five landmarks** - which is what makes alignment possible at all.
2. **SFace** (`face_recognition_sface_2021dec.onnx`, Apache-2.0).
   `cv2.FaceRecognizerSF` produces a **128-dimensional** descriptor, satisfying
   the 128D requirement with no extra runtime. ArcFace-512D would score higher but
   is rejected: the requirement is 128 dimensions, and 512D was not measured
   because it does not meet the stated requirement.
3. **Align, then embed.** The five landmarks are mapped to a 112x112 template
   with `cv2.estimateAffinePartial2D`, which removes roll and normalises eye
   spacing and eye-to-mouth distance. The descriptor is taken from the aligned
   crop, not the raw box.
4. **Both engines live behind `FaceEmbeddingProvider`.** `YuNet128Provider` and
   `SimulationProvider` implement the same `detect` / `embed` / `pose` /
   `similarity` / `align` surface. `get_provider()` resolves one, cached per
   process, and every result carries `engine_mode`.
5. **A descriptor is tagged with its version.** Real templates store
   `sface-128d-v1`; simulation templates store `traya-pseudo-embedding-v2`. The
   two vector spaces are incomparable, so a template is only ever compared
   against candidates of the same version - and `similarity` raises rather than
   returning a meaningless low score on a length mismatch.
6. **Weights are fetched, not committed.** `scripts/fetch_biometric_models.py`
   verifies a pinned SHA-256 per file and writes a `NOTICE` recording upstream
   URL, licence and version. `BIOMETRIC_ENGINE=yunet` raises if the weights are
   missing; `auto` falls back to the simulation **and says so in the log**.

## Consequences

**Good.** The engine is real, and the measurements in
[MODEL_EVALUATION.md](../MODEL_EVALUATION.md) are of a real descriptor: 128
dimensions, every coordinate non-zero, L2-normalised. Alignment demonstrably
does its job - on a rolled copy of a test face, aligned similarity holds at
0.9192 at 20 degrees where the unaligned crop is at 0.3581. Two identities
separate at 0.8977 versus 0.2792.

**The thresholds are still not calibrated.** Those figures come from three
photographs of two people. They demonstrate the pipeline works; they cannot
support a false-match rate, which is what Phase 10 measures on a real corpus. The
seeded `system_settings` thresholds remain the simulation's.

**`opencv` is now an alias, not a value.** It used to name a code path that
never ran. It maps to `yunet` and logs a warning on every resolution, so an old
`.env` cannot quietly keep meaning "give me a simulation".

**Pose got more honest and more awkward.** The landmark yaw proxy carries a
per-identity bias of +0.43 to +0.53 on frontal faces - all of which read "left"
if taken absolutely. So a landmark reading with no baseline returns `unknown`
rather than a direction, and becomes interpretable only against a baseline from
the same person. The simulation's asymmetry reader is unchanged, because it
measures something different and is already labelled as such.

**No `onnxruntime`, so no second runtime.** This is the main cost of the
decision: a new ONNX model would need a dependency added, and the OpenCV DNN
runtime is the only inference path available. Accepted, with the reasoning
recorded so the next person does not re-derive it.

**Not accepted, recorded so the option stays open:** ArcFace-512D (does not meet
the 128D requirement), an ensemble, and a commercial matcher. Each is a Phase 10
conversation, not a Phase 5 one.
