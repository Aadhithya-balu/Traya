# TRAYA Model Evaluation

[docs/README.md](README.md) · **Status: methodology defined; real-engine smoke
tests measured; accuracy results not yet measured.** This page exists so the
numbers have a home and a fixed format *before* they are produced, which is what
stops an unmeasured claim from entering the README.

Current state: two engines exist behind one interface. A real one (YuNet plus
SFace 128D) and the original simulation, selected by `BIOMETRIC_ENGINE`. See
[ADR 0008](decisions/0008-real-biometric-engine.md) and
[ADR 0001](decisions/0001-simulation-biometric-engine.md).

## Rules for this page

Three rules, taken from the rebuild prompt and enforced by review:

1. **No number appears here without the command that produced it.**
2. **No average is reported without its per-condition breakdown.** An aggregate
   across lighting and occlusion hides exactly the cases that matter in an
   emergency.
3. **When a result is bad, it is published as bad.** The response to a poor FAR
   is to say so, not to widen the threshold until the number looks better.

A claim in any other document that contradicts this page is a bug in that
document.

## Why the simulation engine cannot be evaluated as a biometric

Recorded here so the numbers below are never quoted out of context. **This
section describes the simulation, which still exists and is still selectable
with `BIOMETRIC_ENGINE=simulation`.** It does not describe the real engine; see
[Phase 5 measurements](#phase-5-measurements-real-engine) below.

| Property | Value |
| --- | --- |
| Embedding | 12 brightness statistics, **zero-padded to 320** |
| Detector | Skin-tone HSV segmentation, not face detection |
| Alignment | **None.** No landmarks exist. |
| Metric | L2 distance mapped by `1 - d/3.0`, not cosine |
| Corpus | Synthetic renders |
| Measured impostor similarity | **up to 0.817** |
| Impostor pairs above the 0.62 review threshold | **6 of 30** |

A 0.817 impostor score is far above the 0.62 review threshold. Two demo
identities collide outright. This is a brightness comparator, not a biometric,
and no accuracy figure derived from it means anything about face recognition.

**Therefore the results tables below have no simulation baseline rows.** They
are empty because the protocol has not been run, not because rows were omitted.

## Phase 5 measurements: real engine

**These are smoke tests of a pipeline, not an accuracy evaluation.** Three
photographs of two people cannot produce a false-accept rate. They are recorded
here because rule 1 says a number does not appear without the command that made
it, and because the alternative - a real recogniser in the codebase with no
recorded observations - is how unmeasured claims get made later.

Engine under test: **YuNet detection + SFace 128D on the OpenCV DNN runtime**
([ADR 0008](decisions/0008-real-biometric-engine.md)). Corpus:
`backend/tests/fixtures/faces/`, three photographs (`same-person-a`,
`same-person-b` are one person, `other-person` is a second), Apache-2.0 from the
OpenCV sample set.

Reproduce everything in this section:

```
cd backend; .venv\Scripts\python.exe -m pytest tests\test_real_engine.py
```

| Property | Value | Asserted by |
| --- | --- | --- |
| Embedding dimension | **128**, every coordinate non-zero | `test_embedding_is_128_dimensional_and_not_padded` |
| L2 norm | 1.0 (normalised) | `test_embedding_is_l2_normalised` |
| Metric | cosine similarity, [0, 1] | `test_similarity_is_symmetric_and_bounded` |
| Alignment | 5 landmarks to a 112x112 template, `estimateAffinePartial2D` | `test_alignment_corrects_roll` |
| Same-identity similarity | **0.8977** | `test_same_identity_beats_cross_identity` |
| Cross-identity similarity | **0.2573** and **0.2792** | same test |
| Separation | same minus worst cross = **0.6185** | same test |
| Descriptor version | `sface-128d-v1` | `test_model_provenance_is_pinned` |
| Preprocessing version | `aligned112-rgb-v1` | same test |

### Alignment ablation

The measured reason alignment exists, on a rolled copy of the test face with
the face region upscaled so detection is not the limiting factor:

| Roll | Aligned | Unaligned box crop |
| --- | --- | --- |
| 0 degrees | 1.0000 | 0.3791 |
| 10 degrees | 0.9529 | 0.4732 |
| 20 degrees | 0.9192 | 0.3581 |

Aligned similarity holds above 0.91 out to 20 degrees; the unaligned crop never
exceeds 0.48. Without alignment the descriptor would be largely a function of
how the phone was held. Asserted in `test_alignment_corrects_roll`.

### Pose: a measured bias, and what it forced

Three frontal faces from three different people, raw landmark yaw proxy:
**+0.4292, +0.4512, +0.5347**. All three read "left" if taken absolutely, and
all three are far past the `TURNED_OFFSET = 0.03` threshold. The bias is
per-identity (a nose tip sits off the midpoint of its own eyes), so:

- a landmark reading **with no baseline returns `unknown`**, not a direction;
- with a baseline from the same person, both axes are read as a **delta**, so
  the bias cancels.

Asserted in `test_landmark_yaw_is_not_absolute_and_says_unknown_without_a_baseline`.
Roll needs no baseline and is reported in degrees. The simulation's asymmetry
reader is unchanged and is a different measurement.

### What is still missing, and why no threshold is claimed

The real engine's measured scores happen to straddle the seeded thresholds
comfortably - 0.8977 genuine against at most 0.2792 impostor, versus
`HIGH_CONFIDENCE_THRESHOLD = 0.82` and `REVIEW_THRESHOLD = 0.62`. **This is not
evidence that those thresholds are correct.** It is evidence about three
phototographs. The tables below stay empty until the protocol above is run on a
corpus with enough identities to compute FAR, and the seeded thresholds in
`system_settings` remain the simulation's until then.

Specifically not yet measured: FAR and FRR at any threshold, EER, the
per-condition breakdown across lighting, pose, expression, distance, occlusion,
resolution, glasses and camera, latency p50/p95, and the quality-gate's own
precision. Those are Phase 10.

## Validation dataset

### Structure

Paired trials. Every subject contributes genuine samples and impostor samples:

- **Genuine** - same person, different capture.
- **Impostor** - different person, same conditions.

Both counts are reported. **FAR is computed on impostor trials and FRR on
genuine trials**; quoting either without the other is meaningless, because any
threshold can be tuned to move either one.

### Conditions

The prompt requires evaluation under varied capture conditions. Each condition
is a separate slice, reported separately:

| Condition | Levels |
| --- | --- |
| Lighting | normal, low, backlit, harsh side |
| Pose | frontal, ±15°, ±30° |
| Expression | neutral, mouth open, eyes closed |
| Distance | near, nominal, far |
| Occlusion | none, partial (bandage, hand), heavy |
| Resolution | 720p, 1080p, 480p |
| Glasses | none, thin-frame, thick-frame |
| Camera | at least two different devices |

### Substrate

The current corpus is synthetic renders. That is acceptable for pipeline
regression testing and **not** acceptable for accuracy claims: synthetic faces do
not reproduce real skin texture, real lens behaviour, real motion blur, or real
lighting falloff.

**Gate before this page reports accuracy:** either a consented real-face
dataset with proper consent records, or a capture campaign. Fictional synthetic
data is fine for the demo and must stay fictional; it cannot support an accuracy
number.

## Metrics

| Metric | Definition | Why it matters here |
| --- | --- | --- |
| **FAR** | impostor trials accepted ÷ impostor trials | **The dangerous error.** A stranger shown as a victim. Drives the threshold. |
| **FRR** | genuine trials rejected ÷ genuine trials | The costly error. A missed match delays care. |
| **Precision** | TP ÷ (TP + FP) | How much of what we show is right. |
| **Recall** | TP ÷ (TP + FN) | How much of the right we find. |
| **F1** | harmonic mean | Single-number summary, reported with both others. |
| **ROC** | TPR vs FPR across thresholds | Justifies the threshold choice. |
| **EER** | TPR = FPR crossing point | The operating balance, as a single comparable number. |
| **Score margin** | top-1 minus top-2 similarity | Feeds the `MULTIPLE_CANDIDATES` rule, which the current pipeline cannot evaluate. |
| **Latency p50 / p95** | embed + search time | Runs on a phone during an emergency. |
| **Quality-gate precision** | captures correctly rejected ÷ total rejected | Whether the quality gates reject what they should. |

### Threshold selection

The threshold is **read off the ROC curve at an explicitly stated FAR target**,
not chosen by feel. The target must be written down before the number is read,
otherwise the target moves to justify the threshold.

Candidate target: **FAR ≤ 0.001** for auto-accept, with the FRR that costs
stated alongside. Whether 0.001 is the right target for this product is a
judgement call about emergency medicine, and it belongs to a domain expert, not
to a developer reading a curve.

**The FRR that follows is a real cost.** A stricter FAR means more genuine
victims fall through to `REVIEW_REQUIRED` and fallback. That trade is
acceptable - a human checking a candidate costs seconds; a wrong identity
misleads an ambulance - but the number must be published so the trade is
visible rather than assumed.

## Results

**Every cell below is still `_pending_`, and that is the honest state.** The
[Phase 5 measurements](#phase-5-measurements-real-engine) above are not results
in this sense: they are three photographs of two people, which is enough to prove
the pipeline runs and the descriptor separates two identities, and nowhere near
enough to compute a rate. The gap between those two statements is the whole
subject of Phase 10.

Reproduce the commands before filling any cell.

### Headline

| Metric | Value | Reproduce with |
| --- | --- | --- |
| Model | SFace 128D + YuNet (from [Phase 5](#phase-5-measurements-real-engine)) | `pytest tests/test_real_engine.py` |
| Embedding dimension | 128 | same |
| Metric | cosine similarity | same |
| Genuine trials | _pending_ | _pending_ |
| Impostor trials | _pending_ | _pending_ |
| FAR @ auto-accept | _pending_ | _pending_ |
| FRR @ auto-accept | _pending_ | _pending_ |
| EER | _pending_ | _pending_ |
| Threshold | _pending_ | _pending_ |
| Threshold version | _pending_ | _pending_ |
| Latency p50 / p95 | _pending_ | _pending_ |

### Per condition

| Condition | FAR | FRR | n | Notes |
| --- | --- | --- | --- | --- |
| Normal lighting | _pending_ | _pending_ | | |
| Low lighting | _pending_ | _pending_ | | |
| Backlit | _pending_ | _pending_ | | |
| Frontal | _pending_ | _pending_ | | |
| ±15° pose | _pending_ | _pending_ | | |
| ±30° pose | _pending_ | _pending_ | | |
| Partial occlusion | _pending_ | _pending_ | | |
| Heavy occlusion | _pending_ | _pending_ | | |
| Glasses | _pending_ | _pending_ | | |
| Low resolution | _pending_ | _pending_ | | |

### Quality gates

| Gate | Precision | Recall | Rejects correctly | Notes |
| --- | --- | --- | --- | --- |
| `NO_FACE` | _pending_ | _pending_ | | Real detector, not skin segmentation |
| `MULTIPLE_FACES` | _pending_ | _pending_ | | |
| `LOW_LIGHT` | _pending_ | _pending_ | | |
| `BLURRY_IMAGE` | _pending_ | _pending_ | | |
| `FACE_TOO_FAR` | _pending_ | _pending_ | | |
| `FACE_TOO_SMALL` | _pending_ | _pending_ | | |
| `EXTREME_POSE` | _pending_ | _pending_ | | |
| `FACE_OCCLUDED` | _pending_ | _pending_ | | |

Blur and lighting are already implemented as real measurements
([AUDIT.md](AUDIT.md#quality-assessment--the-genuinely-real-part)). Occlusion
and size depend on detection quality and are **not** trustworthy until the
detector is real.

## Model comparison

The rebuild selects a 128D model to satisfy an explicit project requirement. The
better-accuracy option is 512D. That tradeoff is measured, not asserted.

| Model | Dim | Satisfies 128D requirement | FAR | FRR | EER | Latency | Selected |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Selected 128D ONNX | 128 | yes | _pending_ | _pending_ | _pending_ | _pending_ | yes |
| ArcFace R50 (512D) | 512 | **no** | _pending_ | _pending_ | _pending_ | _pending_ | no |
| Current simulation | 320 (padded) | not applicable | 0.817 impostor | n/a | n/a | n/a | **no** |

If ArcFace-512D performs materially better, **publish that and still ship the
128D model**, because the requirement is explicit. If the requirement is ever
relaxed, the provider interface is the only thing that changes - no caller, no
UI change, and a re-enrollment data migration.

## Reproducing

```powershell
cd backend; .venv\Scripts\python.exe -m pytest tests\test_evaluation.py -v
```

The evaluation harness must:

1. Load the dataset by manifest, never a random sample at runtime.
2. Print the model name, version and dimension before any result.
3. Write results to `backend/evaluation/runs/<timestamp>/` with the full
   configuration, so a number can always be traced to the run that produced it.
4. Be deterministic given a seed, so a change in results means a change in the
   system.

## Limitations

Stated up front, so they are not read as caveats after a number:

- **A synthetic corpus cannot support an accuracy claim.** See "Substrate"
  above.
- **Single-corpus results do not generalise.** A number measured on one dataset
  describes that dataset.
- **N is small.** Every percentage here comes from a trial count, and the
  confidence interval on FAR at 0.001 with 1000 impostor trials is wide.
  Report the interval.
- **The enrolled population is not the population that matters.** Enrolment is
  self-selected. Adversarial cases - a deliberately similar-looking impostor -
  are not sampled by a random corpus.
- **FAR in the lab is not FAR in an ambulance.** Pressure, motion blur,
  bystanders in frame and a shouted-at interface all change the input
  distribution.