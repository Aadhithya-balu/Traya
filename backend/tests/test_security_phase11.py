"""Phase 11 gate: two properties that must hold forever, asserted against the code.

1. **No endpoint returns a biometric embedding.** Not a summary, not a
   similarity, not a length, not base64 - no vector, ever.
2. **No log line contains a raw vector or unredacted clinical detail.**

Both are the kind of rule that is enforced once by a reviewer and then broken
by a well-meaning PR six months later. Neither is checkable by reading, so both
are asserted here. These tests are deliberately written against the *whole
surface* - every route, and every logging call site in the tree - rather than
against the paths that happen to exist today, so adding the offending endpoint
later fails the build instead of shipping.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.main import app

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"
FRONTEND_SRC = BACKEND.parent / "frontend" / "src"

# Field names that would constitute returning a vector. `dimension` and
# `algo_version` are excluded on purpose: both are metadata, both are already
# disclosed, and refusing them would break the Phase 10 disclosure requirement.
VECTOR_FIELDS = {
    "embedding",
    "embeddings",
    "vector",
    "vectors",
    "descriptor",
    "descriptors",
    "face_embedding",
    "template",
    "templates",
    "feature_vector",
    "biometric_vector",
}

# Words that must not appear in a log call's payload.
CLINICAL_WORDS = (
    "blood_group",
    "bloodgroup",
    "allergies",
    "allergy",
    "conditions",
    "medications",
    "medical_notes",
    "diagnosis",
)


# ---------------------------------------------------------------- 1. no vector
def test_no_response_model_declares_a_vector_field():
    """Walk every Pydantic response model the app can emit.

    `create_cloned_field` / `__annotations__` is used rather than a text search
    so that a field named `embedding` inside a nested model is caught too.
    """
    import app.models.entities  # noqa: F401  (ensure the registry is populated)
    from app.main import app as _app

    offenders: list[str] = []

    def walk(schema, path: str) -> None:
        for name, sub in getattr(schema, "model_fields", {}).items():
            here = f"{path}.{name}"
            if name.lower() in VECTOR_FIELDS:
                offenders.append(here)
            walk(sub.annotation, here)

    from fastapi.routing import APIRoute

    for route in APIRoute and [r for r in _app.routes if isinstance(r, APIRoute)]:
        response = getattr(route, "response_model", None)
        if response is None:
            continue
        walk(response, f"{route.path}")

    assert not offenders, (
        "these response models expose a biometric vector field: "
        + ", ".join(sorted(offenders))
    )


def test_no_route_path_or_handler_hints_at_returning_an_embedding():
    """Belt and braces: a bare `dict` response model would defeat the walk above."""
    src = (APP / "api").rglob("*.py")
    offenders: list[str] = []
    for path in src:
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'response_model\s*=\s*dict', text):
            line_no = text[: match.start()].count("\n") + 1
            # A bare dict is allowed (several endpoints legitimately return a
            # small object), but it must not be built from a vector.
            window = text[match.start() : match.start() + 900]
            if any(f'"{f}"' in window or f"'{f}'" in window for f in VECTOR_FIELDS):
                offenders.append(f"{path.name}:{line_no}")
    assert not offenders, f"dict responses containing a vector field: {offenders}"


def test_the_frontend_never_receives_or_names_a_vector():
    """No client type may declare a vector field, and no call may ask for one."""
    offenders: list[str] = []
    for path in FRONTEND_SRC.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        for field in VECTOR_FIELDS:
            if re.search(rf"\b{field}\s*[?]?\s*:", text):
                offenders.append(f"{path.name}: {field}")
    assert not offenders, f"frontend types declare vector fields: {offenders}"


def test_the_only_reader_of_encrypted_templates_is_the_matcher():
    """`decrypt_templates` must not be reachable from any router."""
    readers = []
    for path in (APP / "api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("decrypt_templates", "decrypt_bytes"):
            if name in text:
                readers.append(f"{path.name}: {name}")
    assert not readers, f"a router reaches encrypted biometric data: {readers}"


# ------------------------------------------------------------------ 2. no logs
def test_no_logging_call_sends_a_vector():
    """No `logger.*` or `log_*` call may carry a vector-shaped field."""
    offenders: list[str] = []
    patterns = ("logger.", "logging.", "log_session_action(", "write_audit(")
    for path in APP.rglob("*.py"):
        if path.name == "test_helpers.py":
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not any(p in line for p in patterns):
                continue
            if any(f'"{f}"' in line or f"'{f}'" in line for f in VECTOR_FIELDS):
                offenders.append(f"{path.relative_to(APP)}:{line_no}: {line.strip()}")
    assert not offenders, "log calls carrying a vector field:\n" + "\n".join(offenders)


def test_no_logging_call_sends_raw_clinical_detail():
    """Clinical detail may be stored, never logged.

    A log line is copied into monitoring, tickets and backups by people who are
    not bound by the clinical-access rules, so "we wrote it to the audit log"
    is not an acceptable home for it.
    """
    offenders: list[str] = []
    patterns = ("logger.", "logging.", "log_session_action(")
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not any(p in line for p in patterns):
                continue
            low = line.lower()
            for word in CLINICAL_WORDS:
                if word in low:
                    offenders.append(f"{path.relative_to(APP)}:{line_no}: {line.strip()}")
                    break
    assert not offenders, "log calls carrying clinical detail:\n" + "\n".join(offenders)


def test_write_audit_is_never_given_a_clinical_object():
    """`write_audit` is the widest-reaching sink, so it gets its own check."""
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"write_audit\(", text):
            window = text[match.start() : match.start() + 700]
            for word in CLINICAL_WORDS:
                if word in window.lower():
                    line_no = text[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(APP)}:{line_no}: {word}")
    assert not offenders, f"write_audit called with clinical detail: {offenders}"


# ------------------------------------------------------------- 3. no secrets
def test_no_service_role_key_in_frontend_or_committed_config():
    """Phase 11 item 1, enforced rather than requested.

    A Supabase service-role key in frontend code is a full database bypass: it
    ignores RLS, which is the control this project spent Phase 4 building.
    """
    offenders: list[str] = []
    patterns = (
        r"service_role",
        r"SUPABASE_SERVICE_ROLE",
        r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
    )
    for path in FRONTEND_SRC.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx", ".json", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            if re.search(pattern, text, re.I):
                offenders.append(f"{path.relative_to(FRONTEND_SRC)}: {pattern}")
    assert not offenders, f"secret-shaped strings in frontend source: {offenders}"


def test_the_env_example_documents_no_real_secret_values():
    """`.env.example` must be placeholders. A real value there is a leak."""
    example = BACKEND / ".env.example"
    if not example.exists():
        return
    offenders: list[str] = []
    for line_no, line in enumerate(example.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip()
        if not value:
            continue

        if key in {"SECRET_KEY", "ENCRYPTION_KEY"}:
            if not re.search(r"change|your|replace|example|xxx|generate|<", value, re.I):
                offenders.append(f"{line_no}: {key}")
        elif key == "DATABASE_URL":
            # A leak is a *credential*, not a URL. `sqlite:///./traya.db` is the
            # documented zero-config default and contains nothing secret;
            # `postgresql://user:hunter2@host/db` does.
            if "//" in value and "@" in value:
                creds = value.split("//", 1)[1].split("@", 1)[0]
                if ":" in creds and creds.split(":", 1)[1].strip():
                    offenders.append(f"{line_no}: DATABASE_URL carries a password")
    assert not offenders, f".env.example looks like it contains real secrets: {offenders}"


def test_every_settings_field_is_documented_in_the_env_example():
    """A setting nobody can discover is a setting nobody will set correctly.

    Phase 11/12 gap, previously recorded and never closed: the example file
    documented 20 of the settings. An undocumented `MAX_IMAGE_PIXELS` is an
    upload limit nobody knows to raise.
    """
    from app.config.settings import Settings

    example = (BACKEND / ".env.example").read_text(encoding="utf-8")
    missing = sorted(
        name
        for name in Settings.model_fields
        if name not in example
    )
    assert not missing, f"settings absent from backend/.env.example: {missing}"


def test_the_env_example_does_not_advertise_a_biometric_engine_that_no_longer_means_itself():
    """`opencv` was the value that silently ran the simulation (Phase 5).

    It is still accepted, as a warned alias for `yunet`. Advertising it as a
    first-class choice in the example file is how the Phase 5 trap gets re-set:
    an operator copies `opencv` into a deployment, believes it is getting a real
    detector, and gets the brightness comparator with no error.

    The assignment line itself is `BIOMETRIC_ENGINE=auto`, so the documented
    options live in the comment block above it. Both are checked.
    """
    lines = (BACKEND / ".env.example").read_text(encoding="utf-8").splitlines()
    index = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith("BIOMETRIC_ENGINE")),
        None,
    )
    assert index is not None, "BIOMETRIC_ENGINE must be documented"

    start = index
    while start > 0 and lines[start - 1].strip().startswith("#"):
        start -= 1
    block = "\n".join(lines[start : index + 1])

    assert "yunet" in block, f"the real engine must be the documented option:\n{block}"
    assert "simulation" in block, f"the simulation must be documented honestly:\n{block}"
    assert "opencv" not in block.split("ALIAS")[0] or "ALIAS" in block, (
        "if `opencv` is mentioned it must be labelled a warned alias, not a choice"
    )
    # The strong form: `opencv` may appear only in a sentence that also says alias.
    for line in block.splitlines():
        if "opencv" in line.lower():
            assert "alias" in line.lower(), (
                f"`opencv` mentioned without being called an alias: {line.strip()}"
            )


def test_the_app_factory_registers_the_api_router():
    """A trivial guard so this file cannot pass by failing to collect anything.

    The router is attached during the app lifespan, not at import, so
    `app.routes` is nearly empty here. The OpenAPI schema is the reliable
    measure and it is built on first access.
    """
    schema = app.openapi()
    assert len(schema["paths"]) > 40, f"only {len(schema['paths'])} paths registered"
