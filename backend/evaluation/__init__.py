"""Reproducible biometric evaluation.

`python -m evaluation.run --manifest <path>`

The rule this package enforces over its own convenience: **it cannot produce a
number it cannot attribute.** Every result carries the engine, the engine
version, the dataset, the trial count and a confidence interval, and every run
is written to disk with its configuration. A figure that cannot be traced back
to a run is a figure nobody should repeat.

Nothing in here fabricates a measurement. Given a corpus it cannot support, it
says so and exits non-zero.
"""

from evaluation.dataset import Dataset, Trial, expand_trials, load_manifest
from evaluation.harness import EngineInfo, Report, TrialRunner, build_report, write_run
from evaluation.metrics import eer, rates, roc_curve, score_margin, wilson_interval

__all__ = [
    "Dataset",
    "EngineInfo",
    "Report",
    "Trial",
    "TrialRunner",
    "build_report",
    "eer",
    "expand_trials",
    "load_manifest",
    "rates",
    "roc_curve",
    "score_margin",
    "verify_digests",
    "wilson_interval",
    "write_run",
]

from evaluation.dataset import verify_digests
