"""Binary-detection metrics for face verification.

Every function here is deliberately independent of TRAYA: no database, no
engine, no settings. That is what makes them testable against hand-computed
answers, which is the only way to know a metric is right before trusting it with
a number that will be quoted.

**A metric implementation is not an accuracy claim.** Passing
``tests/test_evaluation.py`` proves the arithmetic. It proves nothing about
whether a face is recognised. Those are separate questions and the docs keep
them separate.

Definitions used throughout, stated because "recall" is ambiguous in this field:

- **Trial** - one comparison of a probe against one template. A trial is
  *impostor* if the two belong to different people, *genuine* otherwise.
- **FAR** - false accept rate. Fraction of impostor trials that score at or
  above threshold. This is the security-relevant number: it is the probability
  that a stranger is reported as a match.
- **FRR** - false reject rate. Fraction of genuine trials that score below
  threshold. This is the usability-relevant number.
- **Decision** - ``score >= threshold``. Inclusive, so the threshold is the
  smallest score that is accepted. Getting this backwards inverts every rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence


# --------------------------------------------------------------------- rates
def confusion_counts(
    scores: Sequence[float], labels: Sequence[bool], threshold: float
) -> tuple[int, int, int, int]:
    """Return ``(tp, tn, fp, fn)`` where the positive class is "match".

    ``labels[i]`` is True when trial ``i`` is genuine.
    """
    if len(scores) != len(labels):
        raise ValueError(
            f"{len(scores)} scores but {len(labels)} labels - a misaligned "
            "pair is worse than no data, so this refuses rather than zipping"
        )
    tp = tn = fp = fn = 0
    for score, is_genuine in zip(scores, labels):
        accepted = score >= threshold
        if is_genuine:
            if accepted:
                tp += 1
            else:
                fn += 1
        else:
            if accepted:
                fp += 1
            else:
                tn += 1
    return tp, tn, fp, fn


def rates(
    scores: Sequence[float], labels: Sequence[bool], threshold: float
) -> dict[str, float | None]:
    """FAR, FRR, precision, recall, specificity and F1 at one threshold.

    A rate over an empty class is reported as ``None``, never 0.0. "No impostor
    trials were run" and "no impostor was accepted" are different facts, and
    collapsing them is how a small dataset gets reported as a perfect score.
    """
    tp, tn, fp, fn = confusion_counts(scores, labels, threshold)
    n_genuine = tp + fn
    n_impostor = fp + tn

    far = (fp / n_impostor) if n_impostor else None
    frr = (fn / n_genuine) if n_genuine else None
    recall = (tp / n_genuine) if n_genuine else None
    specificity = (tn / n_impostor) if n_impostor else None

    precision: float | None = None
    if tp + fp:
        precision = tp / (tp + fp)

    f1: float | None = None
    if precision and recall and (precision + recall):
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "threshold": threshold,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "n_genuine": n_genuine,
        "n_impostor": n_impostor,
        "far": far,
        "frr": frr,
        "precision": precision,
        "recall": recall,
        "specificity": specificity,
        "f1": f1,
        "accuracy": (tp + tn) / len(scores) if scores else None,
    }


def far_at_threshold(scores, labels, threshold) -> float | None:
    return rates(scores, labels, threshold)["far"]


def frr_at_threshold(scores, labels, threshold) -> float | None:
    return rates(scores, labels, threshold)["frr"]


# ------------------------------------------------------------------ ROC / EER
def roc_curve(scores: Sequence[float], labels: Sequence[bool]) -> list[tuple[float, float]]:
    """``[(threshold, far)]`` at every distinct score, ordered by descending FAR.

    The threshold returned is the smallest score that would be accepted, which
    makes the point directly usable: sweep this to choose an operating point.

    AUC is trapezoidal over these points and is reported alongside, because a
    curve with no area under it tells you nothing about separability.
    """
    candidates = sorted({float(s) for s in scores}, reverse=True)
    curve: list[tuple[float, float]] = []
    for t in candidates:
        far = far_at_threshold(scores, labels, t)
        if far is not None:
            curve.append((t, far))
    return curve


def roc_points(scores: Sequence[float], labels: Sequence[bool]) -> list[tuple[float, float]]:
    """``[(far, tpr)]`` including both endpoints, ascending in FAR.

    This is the form AUC is integrated over. The endpoint (0, 0) is prepended
    and (1, 1) appended because the sweep in `roc_curve` only produces the
    thresholds actually present in the data, and a curve missing its endpoints
    has a systematically wrong area.
    """
    curve = roc_curve(scores, labels)
    if not curve:
        return []
    points = [(far, 1.0 - _frr_at(scores, labels, t)) for t, far in curve]
    points.sort(key=lambda p: p[0])
    full = [(0.0, 0.0), *points]
    if full[-1][0] < 1.0:
        full.append((1.0, 1.0))
    return full


def _frr_at(scores, labels, threshold) -> float:
    r = rates(scores, labels, threshold)
    value = r["frr"]
    return 0.0 if value is None else value


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    """Area under the ROC, by the trapezoidal rule. ``None`` if a class is absent.

    Integrated over the FAR axis, which is the only correct choice: weighting by
    the *threshold* gap instead gives an area that depends on the units of the
    score, so adding 0.1 to every score would change the reported AUC of an
    unchanged, identically-ranked system.
    """
    points = roc_points(scores, labels)
    if len(points) < 2:
        return None
    total = 0.0
    for (f0, t0), (f1, t1) in zip(points, points[1:]):
        total += (f1 - f0) * (t0 + t1) / 2
    return total


def eer(scores: Sequence[float], labels: Sequence[bool]) -> tuple[float, float] | None:
    """Equal error rate point as ``(threshold, eer)``, or ``None``.

    Defined as ``min over t of max(FAR(t), FRR(t))`` rather than as "where FAR
    crosses FRR". The difference is not academic: on an anti-correlated set
    (every impostor ranked above every genuine) FAR and FRR are *equal at 1.0*,
    so a crossing search returns EER = 1.0 by finding a point where every single
    trial is wrong. `max` never prefers that, and the answer is the honest 0.5.

    The threshold is the geometric midpoint of the bracketing scores, so it is
    one an operator could actually type in.
    """
    if not any(labels) or all(labels):
        return None

    impostor = sorted(float(s) for s, g in zip(scores, labels) if not g)
    genuine = sorted(float(s) for s, g in zip(scores, labels) if g)

    def far_below(t: float) -> float:
        return sum(1 for s in impostor if s >= t) / len(impostor)

    def frr_above(t: float) -> float:
        return sum(1 for s in genuine if s < t) / len(genuine)

    candidates = sorted({*impostor, *genuine})
    best: tuple[float, float] | None = None
    best_worst = math.inf

    for lo, hi in zip(candidates, candidates[1:]):
        for threshold, far, frr in (
            (lo, far_below(lo), frr_above(lo)),
            (hi, far_below(hi), frr_above(hi)),
            ((lo + hi) / 2, far_below((lo + hi) / 2), frr_above((lo + hi) / 2)),
        ):
            worst = max(far, frr)
            if worst < best_worst:
                best_worst = worst
                best = (threshold, (far + frr) / 2)

    return best


# ------------------------------------------------------------------ margins
@dataclass
class ScoreMargin:
    """Separation between the best impostor score and the worst genuine score.

    This is the quantity a *matching* system needs, and it is not the same as
    EER. In 1:N matching there is no per-trial threshold; the system must rank,
    so what matters is whether the correct person is ranked first. A negative
    margin means the top impostor outscored the worst genuine - the two
    distributions overlap.
    """

    worst_genuine: float | None
    best_impostor: float | None
    margin: float | None
    overlaps: bool

    def as_dict(self) -> dict:
        return {
            "worst_genuine": self.worst_genuine,
            "best_impostor": self.best_impostor,
            "margin": self.margin,
            "overlaps": self.overlaps,
        }


def score_margin(scores: Sequence[float], labels: Sequence[bool]) -> ScoreMargin:
    genuine = [float(s) for s, g in zip(scores, labels) if g]
    impostor = [float(s) for s, g in zip(scores, labels) if not g]
    if not genuine or not impostor:
        return ScoreMargin(
            worst_genuine=min(genuine) if genuine else None,
            best_impostor=max(impostor) if impostor else None,
            margin=None,
            overlaps=True,
        )
    worst_g, best_i = min(genuine), max(impostor)
    return ScoreMargin(
        worst_genuine=worst_g,
        best_impostor=best_i,
        margin=worst_g - best_i,
        overlaps=best_i >= worst_g,
    )


def percentiles(values: Sequence[float], points: Sequence[float]) -> dict[str, float]:
    """Nearest-rank percentiles. Empty input gives an empty dict, not zeros."""
    if not values:
        return {}
    ordered = sorted(float(v) for v in values)
    out: dict[str, float] = {}
    for p in points:
        rank = max(1, math.ceil(p / 100 * len(ordered)))
        out[f"p{p:g}"] = ordered[min(rank, len(ordered)) - 1]
    return out


# --------------------------------------------------------------- statistics
def wilson_interval(
    successes: int, trials: int, z: float = 1.96
) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion.

    Used instead of the normal approximation because every rate that matters
    here is near 0 or near 1 with a small denominator, which is exactly where
    the normal approximation produces intervals that dip below zero.

    Returns ``None`` for zero trials rather than ``(0.0, 0.0)``: "no evidence"
    and "perfect" are not the same result, and conflating them is how a 20-trial
    smoke test gets published as a 0% false-accept rate.
    """
    if trials <= 0:
        return None
    p = successes / trials
    denom = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denom
    margin = (
        z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denom
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def summarize_rate(successes: int, trials: int) -> dict:
    """A rate with its confidence interval, or an explicit "not measured"."""
    interval = wilson_interval(successes, trials)
    return {
        "value": (successes / trials) if trials else None,
        "numerator": successes,
        "denominator": trials,
        "ci95": list(interval) if interval else None,
    }
