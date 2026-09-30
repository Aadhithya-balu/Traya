# TRAYA Model Evaluation

[docs/README.md](README.md) · **Status: methodology defined, results not yet
measured.** This page exists so the numbers have a home and a fixed format
*before* they are produced, which is what stops an unmeasured claim from
entering the README.

Current state: the engine is a simulation. See
[AUDIT.md](AUDIT.md#the-biometric-engine-exactly-as-written) and
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

## Why the current engine cannot be evaluated as a biometric

Recorded here so the numbers below are never quoted out of context:

| Property | Value |
| --- | --- |
| Embedding | 12 brightness statistics, **zero-padded to 320** |
| Detector | Skin-tone HSV segmentation, not face detection |
| Alignment | **None.** No landmarks exist. |
| Metric | L2 distance mapped by `1 - d/3.0`, not cosine |
| Corpus | Synthetic renders |
| Measured impostor similarity | **up to 0.817** |
| Impostor pairs above the 0.62 review threshold | **6 of 30** |

A 0.817 impostor score is **above the 0.82 high-confidence threshold's
neighbourhood** and far above the 0.62 review threshold. Two demo identities
collide outright. This is a brightness comparator, not a biometric, and no
accuracy figure derived from it means anything about face recognition.

**Therefore there are no baseline rows in the results tables below.** They are
empty because they are not measurable yet, not because they were omitted.

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

Empty until measured. Reproduce the commands before filling any cell.

### Headline

| Metric | Value | Reproduce with |
| --- | --- | --- |
| Model | _pending_ | _pending_ |
| Embedding dimension | _pending_ | _pending_ |
| Metric | _pending_ | _pending_ |
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