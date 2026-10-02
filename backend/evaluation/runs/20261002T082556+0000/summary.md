# Evaluation run - smoke-3photos-2people

**SMOKE TEST - not an accuracy claim. only 2 subject(s); 5 is the floor for a rate; subject(s) with fewer than 2 samples: [2]; only 1 condition(s); an aggregate alone hides which capture instruction to change**

- Generated: `2026-10-02T08:25:56+00:00`
- Engine: `YuNet128Provider` / `sface-128d-v1` / 128D

## Trials

- Samples: 3 across 2 subject(s)
- Genuine: 1
- Impostor: 2
- Dropped (no detection): 0 (0.0%)
- Coverage gaps: lighting, pose, expression, distance, occlusion, resolution, accessories

## Aggregate

- EER: 0.0000 at threshold 0.8977
- AUC: 1.0000
- Margin: 0.6185

## Per condition

| Condition | Genuine | Impostor | Mean genuine | Mean impostor | EER |
| --- | --- | --- | --- | --- | --- |
| ideal | 1 | 2 | 0.8977 | 0.2682 | 0.0000 at threshold 0.8977 |

## Latency

- Embedding (detect + align + 128D): p50 30.59 ms, p95 79.42 ms over 3 image(s)
- Match (cosine over cached vectors): p50 0.058 ms, p95 0.072 ms

The embedding figure is the one that matters for an in-emergency flow. The match figure excludes detection and alignment and is reported only to show the search itself is not the bottleneck.

## Nearest operating point to the FAR target

- Threshold: `0.600000`
- FAR: 0.000000 (95% CI [0.0000, 0.6576])
- FRR: 0.000000 (95% CI [0.0000, 0.7935])

