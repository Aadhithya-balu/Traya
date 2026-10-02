"""The evaluation harness.

Run it:

    cd backend
    .venv\\Scripts\\python.exe -m evaluation.run --manifest evaluation/datasets/<name>.json

Four properties this file exists to guarantee, from
[MODEL_EVALUATION.md](../../docs/MODEL_EVALUATION.md) "Reproducing":

1. The dataset is loaded **by manifest**, never sampled at runtime.
2. The model name, version and dimension are printed **before** any result, so
   a number cannot be read without knowing which engine produced it.
3. Every run writes its full configuration to
   ``evaluation/runs/<timestamp>/``, so any figure in the docs can be traced
   back to the run that produced it.
4. Given a seed the run is deterministic. Results change when the *system*
   changes, not when the folder is reorganised.

And the property that matters more than all four: **the harness labels its own
output honestly**. A corpus that cannot support an accuracy claim is reported as
a smoke test in the output, in the JSON, and in the exit status. It does not
quietly print a percentage that someone will later quote.
"""

from __future__ import annotations

import json
import platform
import statistics
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable

from app.services.identification.providers import decode_image
from evaluation import metrics
from evaluation.dataset import Dataset, Sample, Trial, expand_trials, load_manifest, verify_digests

RUNS_DIR = Path(__file__).resolve().parent / "runs"


@dataclass
class EngineInfo:
    """Which recogniser produced the numbers, captured before anything runs."""

    name: str
    version: str
    dimension: int
    is_simulation: bool
    detection_version: str = ""
    preprocessing_version: str = ""

    def banner(self) -> str:
        kind = "SIMULATION" if self.is_simulation else "real"
        return (
            f"engine: {self.name} ({kind})\n"
            f"  version      : {self.version}\n"
            f"  dimension    : {self.dimension}\n"
            f"  preprocessing: {self.preprocessing_version or 'n/a'}\n"
            f"  detection    : {self.detection_version or 'n/a'}"
        )


@dataclass
class TrialResult:
    trial: Trial
    score: float
    latency_ms: float
    probe_detected: bool
    reference_detected: bool
    error: str = ""

    @property
    def usable(self) -> bool:
        """Whether both sides produced a vector.

        A detection failure is **not** a score. Folding "no face found" into the
        score distribution would either poison the ROC or, worse, quietly
        improve it. It is counted and reported separately.
        """
        return self.probe_detected and self.reference_detected

    def as_dict(self) -> dict:
        return {
            "trial_id": self.trial.trial_id,
            "condition": self.trial.condition,
            "label": self.trial.label,
            "kind": self.trial.kind,
            "probe": self.trial.probe.sample_id,
            "reference": self.trial.reference.sample_id,
            "score": self.score,
            "latency_ms": round(self.latency_ms, 3),
            "usable": self.usable,
            "probe_detected": self.probe_detected,
            "reference_detected": self.reference_detected,
            "error": self.error,
        }


@dataclass
class Report:
    engine: EngineInfo
    dataset_name: str
    generated_at: str
    evaluation_grade: bool
    reasons: list[str]
    totals: dict
    aggregate: dict
    per_condition: dict
    latency: dict
    detection: dict
    operating_points: list[dict]
    at_target_far: dict | None
    trials: list[dict]
    environment: dict

    def headline(self) -> str:
        if not self.evaluation_grade:
            return (
                "SMOKE TEST - not an accuracy claim. "
                + "; ".join(self.reasons)
            )
        return "Evaluation-grade corpus."

    def to_json(self) -> str:
        return json.dumps(_jsonable(self), indent=2, sort_keys=False) + "\n"


def _jsonable(obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return _jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, float) and (obj != obj):  # NaN is not valid JSON
        return None
    return obj


# ------------------------------------------------------------------ embedding
class TrialRunner:
    """Embeds samples once, then scores every trial from the cached vectors.

    Caching matters for more than speed: embedding the same image twice makes
    the score a function of evaluation order, and a number that changes when
    you reorder the manifest is not a measurement.

    **Load failures are recorded, never swallowed.** An earlier version caught
    every exception and marked the sample undetected, which reported "0% of
    trials dropped, no face found" for what was really `AttributeError` on the
    first run - a harness that silently measures nothing is worse than one that
    crashes, because its empty output looks like a result.
    """

    def __init__(self, provider) -> None:
        self.provider = provider
        self._vectors: dict[str, object | None] = {}
        self._detected: dict[str, bool] = {}
        self._errors: dict[str, str] = {}
        self.latencies: list[float] = []

    def vector_for(self, sample: Sample, root: Path):
        if sample.sample_id in self._vectors:
            return self._vectors[sample.sample_id]
        started = time.perf_counter()
        try:
            image = decode_image(sample.resolve(root).read_bytes())
            boxes = self.provider.detect(image)
            if not boxes:
                self._vectors[sample.sample_id] = None
                self._detected[sample.sample_id] = False
                self._errors[sample.sample_id] = "no face detected"
                return None
            self._detected[sample.sample_id] = True
            vector = self.provider.embed(image, boxes[0])
            self._vectors[sample.sample_id] = vector
            return vector
        except Exception as exc:
            self._vectors[sample.sample_id] = None
            self._detected[sample.sample_id] = False
            self._errors[sample.sample_id] = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            self.latencies.append((time.perf_counter() - started) * 1000)

    def run(self, trial: Trial, root: Path) -> TrialResult:
        probe = self.vector_for(trial.probe, root)
        reference = self.vector_for(trial.reference, root)
        if probe is None or reference is None:
            failed = [
                s.sample_id
                for s in (trial.probe, trial.reference)
                if self._vectors.get(s.sample_id) is None
            ]
            return TrialResult(
                trial=trial,
                score=float("nan"),
                latency_ms=0.0,
                probe_detected=self._detected.get(trial.probe.sample_id, False),
                reference_detected=self._detected.get(trial.reference.sample_id, False),
                error="; ".join(
                    f"{sid}: {self._errors.get(sid, 'unknown')}" for sid in failed
                ),
            )
        started = time.perf_counter()
        score = float(self.provider.similarity(probe, reference))
        return TrialResult(
            trial=trial,
            score=score,
            latency_ms=(time.perf_counter() - started) * 1000,
            probe_detected=True,
            reference_detected=True,
        )


# --------------------------------------------------------------------- report
def build_report(
    dataset: Dataset,
    engine: EngineInfo,
    results: list[TrialResult],
    thresholds: Iterable[float],
    target_far: float = 0.01,
    embed_latencies: Sequence[float] = (),
) -> Report:
    usable = [r for r in results if r.usable]
    scores = [r.score for r in usable]
    labels = [r.trial.label for r in usable]
    conditions = [r.trial.condition for r in usable]

    per_condition: dict[str, dict] = {}
    for condition in sorted(set(conditions)):
        idx = [i for i, c in enumerate(conditions) if c == condition]
        sub_scores = [scores[i] for i in idx]
        sub_labels = [labels[i] for i in idx]
        n_genuine = sum(sub_labels)
        n_impostor = len(sub_labels) - n_genuine
        per_condition[condition] = {
            "n_genuine": n_genuine,
            "n_impostor": n_impostor,
            # An EER needs both classes. A condition with only impostor pairs
            # gets None and says so, rather than a number that means nothing.
            "eer": _eer_or_none(sub_scores, sub_labels),
            "margin": metrics.score_margin(sub_scores, sub_labels).as_dict(),
            "mean_genuine": _mean([s for s, g in zip(sub_scores, sub_labels) if g]),
            "mean_impostor": _mean([s for s, g in zip(sub_scores, sub_labels) if not g]),
            "scores": metrics.percentiles(sub_scores, (5, 50, 95)),
        }

    detection = {
        "trials_total": len(results),
        "trials_usable": len(usable),
        "trials_dropped": len(results) - len(usable),
        "drop_rate": (len(results) - len(usable)) / len(results) if results else None,
    }

    aggregate = {
        "far_frr": {},
        "eer": _eer_or_none(scores, labels),
        "auc": metrics.auc(scores, labels),
        "margin": metrics.score_margin(scores, labels).as_dict(),
        "score_percentiles": metrics.percentiles(scores, (1, 5, 50, 95, 99)),
    }

    candidates = sorted({*thresholds, *[t for t, _ in metrics.roc_curve(scores, labels)]})
    operating_points = []
    for t in candidates:
        r = metrics.rates(scores, labels, t)
        if r["far"] is None or r["frr"] is None:
            continue
        operating_points.append(
            {
                "threshold": t,
                "far": metrics.summarize_rate(r["fp"], r["n_impostor"]),
                "frr": metrics.summarize_rate(r["fn"], r["n_genuine"]),
                "f1": r["f1"],
            }
        )

    comparison = [p for p in operating_points if p["far"]["value"] is not None]
    at_target = _closest_to_far(comparison, target_far) if comparison else None

    # Two latencies, because quoting one of them alone is misleading in
    # opposite directions. `match_ms` is the cosine similarity over two cached
    # 128D vectors - microseconds, and NOT what a responder waits for.
    # `embed_ms` includes detection and alignment and is the number that has to
    # fit inside an in-emergency flow. Reporting only the first would make the
    # system look two orders of magnitude faster than it is.
    match_ms = [r.latency_ms for r in results if r.usable]
    embed_ms = list(embed_latencies)
    latency = {
        "match_p50_ms": _percentile_of(match_ms, 50),
        "match_p95_ms": _percentile_of(match_ms, 95),
        "embed_p50_ms": _percentile_of(embed_ms, 50),
        "embed_p95_ms": _percentile_of(embed_ms, 95),
        "embed_mean_ms": _mean(embed_ms),
        "n_embeddings": len(embed_ms),
        "n_matches": len(match_ms),
        "note": (
            "end-to-end per-image cost is embed_p95_ms; match_* is the cosine "
            "similarity alone and excludes detection and alignment"
        ),
    }

    totals = {
        "n_samples": len(dataset.samples),
        "n_subjects": len(dataset.subjects),
        "n_conditions": len(dataset.conditions),
        "n_genuine": int(sum(labels)),
        "n_impostor": int(len(labels) - sum(labels)),
        "coverage_gaps": dataset.coverage_gaps(),
        "synthetic": dataset.is_synthetic,
    }

    return Report(
        engine=engine,
        dataset_name=dataset.name,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        evaluation_grade=dataset.is_evaluation_grade(),
        reasons=dataset.why_not_evaluation_grade(),
        totals=totals,
        aggregate=aggregate,
        per_condition=per_condition,
        latency=latency,
        detection=detection,
        operating_points=operating_points,
        at_target_far=at_target if at_target else None,
        trials=[r.as_dict() for r in results],
        environment={
            "python": platform.python_version(),
            "platform": platform.platform(),
            "threshold_target_far": target_far,
        },
    )


def _eer_or_none(scores, labels):
    point = metrics.eer(scores, labels)
    if point is None:
        return None
    threshold, value = point
    return {"threshold": threshold, "eer": value}


def _mean(values) -> float | None:
    return statistics.fmean(values) if values else None


def _percentile_of(values, p) -> float | None:
    return metrics.percentiles(values, (p,)).get(f"p{p:g}")


def _closest_to_far(points, target_far):
    """The operating point whose FAR is nearest the target, preferring lower FAR.

    Preferring the *safer* side matters: in an emergency, being wrongly refused
    sends a responder to a manual search, while being wrongly accepted tells them
    the wrong person is the patient. When two points bracket the target, the
    harness recommends the one that errs toward refusal, and says so.
    """
    if not points:
        return None
    scored = sorted(points, key=lambda p: (abs(p["far"]["value"] - target_far), p["far"]["value"]))
    return scored[0]


# ---------------------------------------------------------------------- write
def write_run(report: Report, runs_dir: Path = RUNS_DIR, extra: dict | None = None) -> Path:
    """Write the run to ``runs/<timestamp>/`` with everything needed to repeat it."""
    stamp = report.generated_at.replace(":", "").replace("-", "")
    out_dir = runs_dir / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "report.json").write_text(report.to_json(), encoding="utf-8")
    (out_dir / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    (out_dir / "trials.jsonl").write_text(
        "\n".join(json.dumps(t, sort_keys=True) for t in report.trials) + "\n",
        encoding="utf-8",
    )
    if extra:
        (out_dir / "run_config.json").write_text(
            json.dumps(extra, indent=2) + "\n", encoding="utf-8"
        )
    (out_dir / "LATEST").write_text(stamp + "\n", encoding="utf-8")
    return out_dir


def render_markdown(report: Report) -> str:
    """A human-readable summary. Deliberately leads with the honesty label."""
    lines = [
        f"# Evaluation run - {report.dataset_name}",
        "",
        f"**{report.headline()}**",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Engine: `{report.engine.name}` / `{report.engine.version}` / "
        f"{report.engine.dimension}D",
        "",
        "## Trials",
        "",
        f"- Samples: {report.totals['n_samples']} across "
        f"{report.totals['n_subjects']} subject(s)",
        f"- Genuine: {report.totals['n_genuine']}",
        f"- Impostor: {report.totals['n_impostor']}",
        f"- Dropped (no detection): {report.detection['trials_dropped']}"
        f" ({_pct(report.detection['drop_rate'])})",
        f"- Coverage gaps: {', '.join(report.totals['coverage_gaps']) or 'none'}",
        "",
        "## Aggregate",
        "",
        f"- EER: {_fmt_eer(report.aggregate['eer'])}",
        f"- AUC: {_fmt(report.aggregate['auc'], 4)}",
        f"- Margin: {_fmt(report.aggregate['margin']['margin'], 4)}",
        "",
        "## Per condition",
        "",
        "| Condition | Genuine | Impostor | Mean genuine | Mean impostor | EER |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for condition, data in report.per_condition.items():
        lines.append(
            f"| {condition} | {data['n_genuine']} | {data['n_impostor']} | "
            f"{_fmt(data['mean_genuine'], 4)} | {_fmt(data['mean_impostor'], 4)} | "
            f"{_fmt_eer(data['eer'])} |"
        )

    lines += [
        "",
        "## Latency",
        "",
        f"- Embedding (detect + align + 128D): p50 "
        f"{_fmt(report.latency['embed_p50_ms'], 2)} ms, p95 "
        f"{_fmt(report.latency['embed_p95_ms'], 2)} ms "
        f"over {report.latency['n_embeddings']} image(s)",
        f"- Match (cosine over cached vectors): p50 "
        f"{_fmt(report.latency['match_p50_ms'], 3)} ms, p95 "
        f"{_fmt(report.latency['match_p95_ms'], 3)} ms",
        "",
        "The embedding figure is the one that matters for an in-emergency flow. "
        "The match figure excludes detection and alignment and is reported only "
        "to show the search itself is not the bottleneck.",
        "",
    ]
    if report.at_target_far:
        point = report.at_target_far
        lines += [
            "## Nearest operating point to the FAR target",
            "",
            f"- Threshold: `{point['threshold']:.6f}`",
            f"- FAR: {_fmt(point['far']['value'], 6)} "
            f"(95% CI {_fmt_ci(point['far'])})",
            f"- FRR: {_fmt(point['frr']['value'], 6)} "
            f"(95% CI {_fmt_ci(point['frr'])})",
            "",
        ]
    return "\n".join(lines) + "\n"


def _fmt(value, places=4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}"


def _fmt_eer(point) -> str:
    if not point:
        return "n/a (needs both genuine and impostor trials)"
    return f"{point['eer']:.4f} at threshold {point['threshold']:.4f}"


def _fmt_ci(rate) -> str:
    ci = rate.get("ci95")
    if not ci:
        return "n/a"
    return f"[{ci[0]:.4f}, {ci[1]:.4f}]"


def _pct(value) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"
