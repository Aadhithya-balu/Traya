r"""Download and verify the ONNX face models. Idempotent, and safe to re-run.

The two models are third-party artefacts with their own licences, so they are
fetched rather than committed: 38 MB of binary in git is a permanent cost for
every clone, and vendoring someone else's weights into this repository makes
the licence question harder to answer, not easier. What *is* committed is the
pin - URL and SHA-256 - so a fetch is reproducible and a substituted file is
detected rather than trusted.

    cd backend
    .venv\Scripts\python.exe scripts\fetch_biometric_models.py

Run this before the Phase 5 gate or any real-embedding test. Without the models
the engine resolves to the simulation provider, which is the correct default and
is loudly reported, not a silent one.

Why `raw.githubusercontent.com` will not work: opencv_zoo stores its models in
Git LFS, so that URL returns a 131-byte pointer file that looks like a download
and fails much later, inside OpenCV, as a model that cannot be parsed. The
`media.githubusercontent.com` host serves the real object. That failure mode is
why this script exists rather than a README line saying "download the models".
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.config.settings import settings  # noqa: E402

LFS = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"

MODELS = {
    settings.FACE_DETECTOR_MODEL: {
        "url": f"{LFS}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "name": "YuNet face detector",
        "licence": "MIT",
        "source": "opencv/opencv_zoo models/face_detection_yunet",
    },
    settings.FACE_RECOGNIZER_MODEL: {
        "url": f"{LFS}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "name": "SFace recognizer (MobileFaceNet + SFace loss)",
        "licence": "Apache-2.0",
        "source": "opencv/opencv_zoo models/face_recognition_sface",
    },
}

NOTICE = """TRAYA biometric models
====================

Fetched by scripts/fetch_biometric_models.py. Not committed to the repository.

face_detection_yunet_2023mar.onnx
  {det_name}
  Licence: {det_licence}
  {det_source}
  https://github.com/opencv/opencv_zoo - paper: "YuNet: A tiny
  millisecond-level face detector" (IJCAI 2021 preprint, Springer 2023).

face_recognition_sface_2021dec.onnx
  {rec_name}
  Licence: {rec_licence}
  {rec_source}
  https://github.com/opencv/opencv_zoo - paper: "SFace: A Lightweight
  Single-Shot Face Recognition Model" (arXiv 2205.12010).

Both licences are permissive and permit redistribution and commercial use with
attribution, which is the only reason this project uses them. The licences are
the licences of the weights as distributed by opencv_zoo; no training data
redistribution rights are claimed or implied.

SHA-256 of the exact files verified by the fetch script:

  {det_sha}  face_detection_yunet_2023mar.onnx
  {rec_sha}  face_recognition_sface_2021dec.onnx
"""


def model_dir() -> pathlib.Path:
    return pathlib.Path(settings.FACE_MODELS_DIR).resolve()


def sha256_of(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(name: str, spec: dict, root: pathlib.Path) -> bool:
    target = root / name
    if target.exists():
        actual = sha256_of(target)
        if actual == spec["sha256"]:
            print(f"  [ok]   {name} already present and matches its pin")
            return True
        print(f"  [stale] {name} is present but does not match its pin; refetching")
        target.unlink()

    print(f"  [get]   {name} <- {spec['url']}")
    with httpx.stream("GET", spec["url"], follow_redirects=True, timeout=300) as response:
        response.raise_for_status()
        if "content-length" in response.headers:
            print(f"          {int(response.headers['content-length']) // 1024} KB")
        partial = target.with_suffix(target.suffix + ".part")
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 20):
                handle.write(chunk)
    actual = sha256_of(partial)
    if actual != spec["sha256"]:
        partial.unlink()
        print(f"  [FAIL] {name} sha256 {actual} does not match the pin {spec['sha256']}")
        return False
    partial.replace(target)
    print(f"  [ok]   {name} verified")
    return True


def main() -> int:
    root = model_dir()
    root.mkdir(parents=True, exist_ok=True)
    print(f"model directory: {root}")
    results = [fetch(name, spec, root) for name, spec in MODELS.items()]

    det = MODELS[settings.FACE_DETECTOR_MODEL]
    rec = MODELS[settings.FACE_RECOGNIZER_MODEL]
    (root / "NOTICE.txt").write_text(
        NOTICE.format(
            det_name=det["name"],
            det_licence=det["licence"],
            det_source=det["source"],
            det_sha=det["sha256"],
            rec_name=rec["name"],
            rec_licence=rec["licence"],
            rec_source=rec["source"],
            rec_sha=rec["sha256"],
        ),
        encoding="utf-8",
    )

    if not all(results):
        print("\nFAILED: at least one model is missing or does not match its pin.")
        return 1
    print("\nboth models present and verified.")
    print("Set BIOMETRIC_ENGINE=yunet to require the real engine, or leave it at")
    print("`auto` to use the real engine when these files exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
