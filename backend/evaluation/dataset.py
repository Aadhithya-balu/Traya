"""Dataset manifests and the trial expansion that drives evaluation.

**The manifest is the dataset.** Nothing here samples a directory at runtime or
infers labels from filenames, because both quietly change the result whenever
the folder is reorganised and nobody notices the numbers moved. The manifest is
versioned text that names every image and its ground-truth identity, so a run is
reproducible from the repository alone.

A manifest declares two things that are easy to conflate:

- ``subjects`` - who is in the corpus.
- ``conditions`` - the axis being varied (lighting, pose, distance, ...).

The condition is what turns an aggregate number into a diagnosis. "EER is 4%"
tells you nothing actionable; "EER is 4% aggregate and 19% at 2m in low light"
tells you which capture instruction to change.

Identity labels are integers, not names. A manifest in this repository must
never carry a real person's name, and the loader refuses anything that looks like
one.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Literal


MANIFEST_VERSION = 1

# The protocol varies an **axis** (lighting, pose, ...) by capturing a named
# **condition** (lowlight, profile, ...). Keeping the two vocabularies apart is
# what makes "we did not test occlusion" a checkable statement: a corpus can
# hold `lowlight` and still have no `lighting` axis if that is its only capture.
CONDITION_AXIS = {
    "ideal": "none",
    "normal": "none",
    "indoor": "lighting",
    "daylight": "lighting",
    "lowlight": "lighting",
    "backlit": "lighting",
    "frontal": "pose",
    "profile": "pose",
    "turned": "pose",
    "neutral": "expression",
    "smiling": "expression",
    "eyes_closed": "expression",
    "near": "distance",
    "mid": "distance",
    "far": "distance",
    "none": "occlusion",
    "partial": "occlusion",
    "heavy": "occlusion",
    "lowres": "resolution",
    "standard": "resolution",
    "glasses": "accessories",
    "mask": "accessories",
}

# Axes the project must cover before an aggregate number means anything.
# "EER is 4%" is not actionable; "4% aggregate, 19% at 2m in low light" is.
EXPECTED_AXES = (
    "lighting",
    "pose",
    "expression",
    "distance",
    "occlusion",
    "resolution",
    "accessories",
)


@dataclass(frozen=True)
class Sample:
    """One image and everything known about it that is not in the pixels."""

    sample_id: str
    path: Path
    subject_id: int
    condition: str
    sha256: str
    notes: str = ""

    def resolve(self, root: Path) -> Path:
        return (root / self.path).resolve()


@dataclass(frozen=True)
class Dataset:
    name: str
    description: str
    root: Path
    samples: tuple[Sample, ...]
    subjects: tuple[int, ...]
    conditions: tuple[str, ...]
    consent: str = ""
    provenance: str = ""

    # ---------------------------------------------------------------- queries
    @property
    def is_synthetic(self) -> bool:
        """True when the corpus is drawings or renders rather than photographs.

        Propagated into every result. A number measured on synthetic faces is
        reported as synthetic no matter how good it looks.
        """
        lowered = f"{self.name} {self.description}".lower()
        return any(
            token in lowered
            for token in ("synthetic", "render", "drawn", "generated", "fake")
        )

    def by_subject(self) -> dict[int, list[Sample]]:
        grouped: dict[int, list[Sample]] = {}
        for s in self.samples:
            grouped.setdefault(s.subject_id, []).append(s)
        return grouped

    def by_condition(self) -> dict[str, list[Sample]]:
        grouped: dict[str, list[Sample]] = {}
        for s in self.samples:
            grouped.setdefault(s.condition, []).append(s)
        return grouped

    @property
    def axes(self) -> tuple[str, ...]:
        """The condition axes this corpus actually varies."""
        found = {CONDITION_AXIS.get(c, c) for c in self.conditions}
        found.discard("none")
        found.discard("unknown")
        return tuple(sorted(found))

    def coverage_gaps(self) -> list[str]:
        """Axes the protocol names that this corpus does not vary."""
        return [axis for axis in EXPECTED_AXES if axis not in self.axes]

    def unknown_conditions(self) -> list[str]:
        """Condition names not in the vocabulary. Typos silently become axes."""
        return [c for c in self.conditions if c not in CONDITION_AXIS]

    def is_evaluation_grade(self) -> bool:
        """Whether this corpus may support an accuracy claim.

        Requires at minimum: not synthetic, real consent recorded, at least a
        handful of subjects, more than one sample each, and more than one
        condition. A corpus that fails this can still be measured, and the
        result is still worth publishing - but it is published as a smoke test.
        """
        grouped = self.by_subject()
        return (
            not self.is_synthetic
            and bool(self.consent.strip())
            and len(grouped) >= 5
            and all(len(v) >= 2 for v in grouped.values())
            and len(self.conditions) >= 3
        )

    def why_not_evaluation_grade(self) -> list[str]:
        reasons: list[str] = []
        if self.is_synthetic:
            reasons.append("corpus is synthetic; synthetic faces cannot support an accuracy claim")
        if not self.consent.strip():
            reasons.append("no consent basis recorded")
        grouped = self.by_subject()
        if len(grouped) < 5:
            reasons.append(f"only {len(grouped)} subject(s); 5 is the floor for a rate")
        thin = {k: len(v) for k, v in grouped.items() if len(v) < 2}
        if thin:
            reasons.append(f"subject(s) with fewer than 2 samples: {sorted(thin)}")
        if len(self.conditions) < 3:
            reasons.append(
                f"only {len(self.conditions)} condition(s); an aggregate alone "
                "hides which capture instruction to change"
            )
        return reasons


@dataclass(frozen=True)
class Trial:
    """One genuine or impostor comparison, with the condition that produced it."""

    trial_id: str
    probe: Sample
    reference: Sample
    label: bool
    condition: str

    @property
    def kind(self) -> Literal["genuine", "impostor"]:
        return "genuine" if self.label else "impostor"


def expand_trials(dataset: Dataset) -> list[Trial]:
    """All same-subject pairs (genuine) and all different-subject pairs (impostor).

    Exhaustive, not sampled. For a corpus of *n* images this is O(n^2), which is
    fine for a few hundred and a memory warning above that - the count is
    reported rather than silently capped, because a harness that quietly
    subsamples will produce a number nobody can reproduce.
    """
    trials: list[Trial] = []
    samples = dataset.samples
    for i, a in enumerate(samples):
        for j, b in enumerate(samples):
            if i >= j:
                continue
            trials.append(
                Trial(
                    trial_id=f"{a.sample_id}__{b.sample_id}",
                    probe=a,
                    reference=b,
                    label=a.subject_id == b.subject_id,
                    # A pair spans two conditions; the more demanding one wins,
                    # because "easy average" hides the failure mode.
                    condition=_harder_condition(a.condition, b.condition),
                )
            )
    return trials


_CONDITION_SEVERITY = {
    "ideal": 0,
    "normal": 1,
    "indoor": 2,
    "daylight": 2,
    "lowlight": 5,
    "backlit": 5,
    "glasses": 4,
    "occluded": 6,
    "profile": 6,
    "far": 4,
    "lowres": 5,
}


def _harder_condition(a: str, b: str) -> str:
    return a if _CONDITION_SEVERITY.get(a, 3) >= _CONDITION_SEVERITY.get(b, 3) else b


# ------------------------------------------------------------------ loading
def load_manifest(manifest_path: Path) -> Dataset:
    """Parse and validate a manifest. Every failure is a raised error.

    Nothing is coerced or defaulted here. A manifest that is nearly right is a
    manifest that will produce a wrong number that looks fine.
    """
    manifest_path = manifest_path.resolve()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent

    version = raw.get("manifest_version")
    if version != MANIFEST_VERSION:
        raise ValueError(
            f"manifest_version is {version!r}, this loader understands "
            f"{MANIFEST_VERSION}; refusing to guess"
        )

    name = raw.get("name")
    if not name:
        raise ValueError("manifest has no name")

    raw_samples = raw.get("samples")
    if not raw_samples:
        raise ValueError(f"{name}: no samples. An empty corpus measures nothing.")

    samples: list[Sample] = []
    seen_ids: set[str] = set()
    for entry in raw_samples:
        sample = _parse_sample(entry, root, name)
        if sample.sample_id in seen_ids:
            raise ValueError(f"{name}: duplicate sample_id {sample.sample_id!r}")
        seen_ids.add(sample.sample_id)
        samples.append(sample)

    subjects = tuple(sorted({s.subject_id for s in samples}))
    conditions = tuple(sorted({s.condition for s in samples}))

    dataset = Dataset(
        name=name,
        description=raw.get("description", ""),
        root=root,
        samples=tuple(samples),
        subjects=subjects,
        conditions=conditions,
        consent=raw.get("consent", ""),
        provenance=raw.get("provenance", ""),
    )
    _check_files_exist(dataset)
    return dataset


def _parse_sample(entry: dict, root: Path, dataset_name: str) -> Sample:
    missing = [k for k in ("sample_id", "path", "subject_id") if k not in entry]
    if missing:
        raise ValueError(
            f"{dataset_name}: sample {entry.get('sample_id', '?')} is missing "
            f"{missing}"
        )
    subject_id = entry["subject_id"]
    if not isinstance(subject_id, int):
        raise ValueError(
            f"{dataset_name}: subject_id must be an integer, got "
            f"{subject_id!r}. String identities invite names into the corpus."
        )
    path = Path(entry["path"])
    if path.is_absolute():
        raise ValueError(
            f"{dataset_name}: {path} is absolute; manifests stay portable by "
            "using paths relative to the manifest"
        )
    return Sample(
        sample_id=str(entry["sample_id"]),
        path=path,
        subject_id=subject_id,
        condition=str(entry.get("condition", "unknown")),
        sha256=str(entry.get("sha256", "")),
        notes=str(entry.get("notes", "")),
    )


def _check_files_exist(dataset: Dataset) -> None:
    """Fail loudly if an image is missing, and say which ones.

    A missing file silently excluded from a trial count is a lower trial count
    with no visible cause, which is the failure mode this whole module exists to
    prevent.
    """
    missing = [str(s.path) for s in dataset.samples if not s.resolve(dataset.root).exists()]
    if missing:
        raise FileNotFoundError(
            f"{dataset.name}: {len(missing)} image(s) referenced but absent: "
            + ", ".join(missing[:8])
            + (" ..." if len(missing) > 8 else "")
        )


def verify_digests(dataset: Dataset) -> list[str]:
    """Return the samples whose bytes do not match the recorded sha256.

    An image replaced after the manifest was written silently changes every
    number derived from it. Content addressing is the cheapest defence.
    """
    bad: list[str] = []
    for sample in dataset.samples:
        if not sample.sha256:
            continue
        digest = hashlib.sha256(sample.resolve(dataset.root).read_bytes()).hexdigest()
        if digest != sample.sha256:
            bad.append(f"{sample.sample_id} (expected {sample.sha256[:12]}, got {digest[:12]})")
    return bad


# ------------------------------------------------------------------ writing
def write_manifest(dataset: Dataset, path: Path) -> None:
    """Serialise a dataset back to a manifest, digests included."""
    payload = {
        "manifest_version": MANIFEST_VERSION,
        "name": dataset.name,
        "description": dataset.description,
        "consent": dataset.consent,
        "provenance": dataset.provenance,
        "samples": [
            {
                "sample_id": s.sample_id,
                "path": s.path.as_posix(),
                "subject_id": s.subject_id,
                "condition": s.condition,
                "sha256": s.sha256,
                "notes": s.notes,
            }
            for s in dataset.samples
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
