"""CLI for the evaluation harness.

    cd backend
    .venv\\Scripts\\python.exe -m evaluation.run --manifest evaluation/datasets/smoke.json

Exit codes are meaningful, because CI is the only thing that will enforce this
when a human is not looking:

- ``0`` - ran, and either produced an evaluation-grade result or clearly
  labelled a smoke test.
- ``1`` - the run failed, or the corpus is not evaluation-grade and
  ``--require-grade`` was passed.

The engine banner prints **before** any number. That is the whole point: a
similarity of 0.8977 means nothing at all unless the reader knows whether it
came from a 128-dimensional real model or from twelve brightness statistics
padded with 308 zeros.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evaluation.dataset import expand_trials, load_manifest, verify_digests
from evaluation.harness import EngineInfo, TrialRunner, build_report, write_run


def engine_info() -> EngineInfo:
    """Describe the active provider without running a single measurement."""
    from app.services.identification.providers import get_provider

    provider = get_provider()
    return EngineInfo(
        name=type(provider).__name__,
        version=provider.version,
        dimension=provider.dimension,
        is_simulation=bool(getattr(provider, "is_simulation", False)),
        detection_version=getattr(provider, "detection_version", ""),
        preprocessing_version=getattr(provider, "preprocessing_version", ""),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evaluation.run",
        description="Run the biometric evaluation harness against a dataset manifest.",
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to a dataset manifest (JSON).",
    )
    parser.add_argument(
        "--target-far",
        type=float,
        default=0.01,
        help="FAR the operator point should land near. Default 0.01.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        action="append",
        default=[],
        help="Extra threshold to report. Repeatable.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print the report without writing a run directory.",
    )
    parser.add_argument(
        "--require-grade",
        action="store_true",
        help="Exit 1 unless the corpus can support an accuracy claim.",
    )
    parser.add_argument(
        "--verify-digests",
        action="store_true",
        help="Fail if an image does not match its recorded sha256.",
    )
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"no such manifest: {args.manifest}", file=sys.stderr)
        return 1

    dataset = load_manifest(args.manifest)

    if args.verify_digests:
        bad = verify_digests(dataset)
        if bad:
            print("image digest mismatch:", file=sys.stderr)
            for line in bad:
                print(f"  {line}", file=sys.stderr)
            return 1

    info = engine_info()
    print(info.banner())
    print()
    print(f"dataset: {dataset.name} ({len(dataset.samples)} samples, "
          f"{len(dataset.subjects)} subjects, {len(dataset.conditions)} conditions)")
    if dataset.consent:
        print(f"consent: {dataset.consent}")
    else:
        print("consent: NOT RECORDED - this corpus cannot support an accuracy claim")
    gaps = dataset.coverage_gaps()
    if gaps:
        print(f"coverage gaps: {', '.join(gaps)}")
    print()

    provider = None
    from app.services.identification.providers import get_provider

    provider = get_provider()

    trials = expand_trials(dataset)
    print(f"expanded {len(trials)} trial(s) from the manifest")

    runner = TrialRunner(provider)
    results = [runner.run(t, dataset.root) for t in trials]

    # Seeded thresholds are the current production values, so a run without
    # --threshold still answers "what would today's settings do on this corpus".
    from app.config.settings import settings

    seeds = [
        settings.HIGH_CONFIDENCE_THRESHOLD,
        settings.REVIEW_THRESHOLD,
        settings.FALLBACK_FACE_THRESHOLD,
        *args.threshold,
    ]

    report = build_report(
        dataset,
        info,
        results,
        seeds,
        target_far=args.target_far,
        embed_latencies=runner.latencies,
    )

    print()
    print(report.headline())
    print()
    print(f"trials: {report.detection['trials_usable']} usable, "
          f"{report.detection['trials_dropped']} dropped (no detection)")
    print(f"genuine: {report.totals['n_genuine']}  impostor: {report.totals['n_impostor']}")

    from evaluation.harness import render_markdown

    print()
    print(render_markdown(report))

    if not args.no_write:
        out = write_run(report, extra={"argv": sys.argv, "manifest": str(args.manifest)})
        print(f"wrote {out}")

    if args.require_grade and not report.evaluation_grade:
        print(
            "refusing to certify: " + "; ".join(report.reasons),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
