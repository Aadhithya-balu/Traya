[../README.md](../README.md) | [Decisions](README.md)

# ADR 0001: The biometric engine is a simulation, not a production recogniser

- **Status:** Accepted
- **Date:** 2026-08-15
- **Affects:** `app/services/identification/engine.py`, `app/config/settings.py`, `app/schemas`

## Context

TRAYA's premise is that a photograph of an unresponsive person identifies them
against pre-enrolled citizen biometrics. That requires a face recogniser.

The dependency is `opencv-python` 5.x, which ships no cascade data in this
environment, so Haar cascade detection is unavailable and the engine would have
no way to locate a face. Shipping a "face matcher" that is actually a brightness
comparison would be dishonest and, in an emergency context, dangerous: a false
accept could cause responders to act on the wrong person's medical data.

## Decision

The engine is explicitly a **simulation**, and the system says so everywhere.

1. `BiometricEngine.mode` is `"simulation"` or `"opencv"`, and
   `is_simulation` is exposed for callers.
2. `extract_embedding` produces 12 explicit darkness-derived features, scaled and
   zero-padded to 320 dimensions. It is a deterministic feature vector, not a
   learned representation, and it is not biometrically meaningful.
3. `similarity(a, b) = clamp(1 - ||a - b|| / 3.0, 0, 1)`. This measures image
   darkness similarity.
4. Every identification result carries `engine_mode` and `demo_mode`.
5. The UI shows a `SimulationNotice` on every result.
6. `settings.BIOMETRIC_ENGINE` accepts `auto`, `simulation` or `opencv`. There is
   no value that would imply a trained model is present.

## Consequences

**Good.** The entire end-to-end flow - quality gates, candidate ranking, consent,
medical surfacing, contact notification, hospital routing, audit - is real,
testable and demonstrable without a GPU, a camera, or a licensed model. Swapping
in a real embedder later is a change to one module behind a stable interface.

**Bad, and stated plainly.** The matcher false-accepts. Measured over the
synthetic corpus: same-identity clean similarity 0.986-0.995, same-identity
degraded 0.711-0.866, impostor 0.000-0.817 with a mean of 0.309. The impostor
range **overlaps** the degraded same-identity range, and 6 of 30 impostor pairs
score above the 0.62 `REVIEW` threshold. Two demo identities collide at 0.817.
This is a functioning demonstration, not a working biometric.

**Therefore:** this repository must not be deployed as an identification system.
`engine_mode` exists so that no deployment, screenshot or integration can quietly
present this as a working recogniser. See
[ADR 0004](../decisions/README.md) and the "Accuracy status" section of the
docs index.
