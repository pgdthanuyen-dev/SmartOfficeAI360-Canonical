"""Validate the vendor-neutral AI project memory without touching application code."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ai-memory" / "memory-manifest.yaml"
HASH_RE = re.compile(r"\b[0-9a-f]{40}\b")
DATE_RE = re.compile(r"^Updated:\s*\d{4}-\d{2}-\d{2}\s*$", re.MULTILINE)
SENSITIVE_RE = re.compile(
    r"(?:cookie|password|passwd|secret|access[_-]?token|session(?:id|_url)?|authorization)\s*[:=]\s*[^\s`]+",
    re.IGNORECASE,
)
LINK_RE = re.compile(r"\]\(([^)#]+(?:#[^)]+)?)\)")
ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)")
VALID_COVERAGE_STATUSES = {"COMPLETE", "SUBSTANTIAL", "PARTIAL", "MINIMAL", "NOT_DOCUMENTED", "PLANNED_ONLY", "NOT_APPLICABLE"}


REQUIRED = [
    "AGENTS.md",
    "AI_CONTEXT.md",
    "ai-memory/INDEX.md",
    "ai-memory/memory-manifest.yaml",
    "ai-memory/01-project/PROJECT_OVERVIEW.md",
    "ai-memory/01-project/PURPOSE.md",
    "ai-memory/02-domain/QLVB_DOMAIN.md",
    "ai-memory/02-domain/QLVB_BUSINESS_WORKFLOW.md",
    "ai-memory/02-domain/DOMAIN_SCHEMA_AND_LIFECYCLE.md",
    "ai-memory/03-architecture/ARCHITECTURE.md",
    "ai-memory/03-architecture/SYSTEM_ARCHITECTURE.md",
    "ai-memory/03-architecture/MODULE_MAP.md",
    "ai-memory/03-architecture/ENTRY_POINTS.md",
    "ai-memory/03-architecture/CONFIGURATION_CONTRACT.md",
    "ai-memory/03-architecture/ERROR_MODEL.md",
    "ai-memory/03-architecture/CDP_ARCHITECTURE.md",
    "ai-memory/03-architecture/NEOREMOTING_CONTRACT.md",
    "ai-memory/03-architecture/DOWNLOAD_PIPELINE.md",
    "ai-memory/03-architecture/SCHEMA_MIGRATION_AND_COMPATIBILITY.md",
    "ai-memory/03-architecture/STORAGE_QUEUE_MANIFEST_LIFECYCLE.md",
    "ai-memory/03-architecture/G03_EXTRACTION_OCR_CACHE_SAFETY.md",
    "ai-memory/03-architecture/G04_AI_PROPOSAL_BOUNDARY.md",
    "ai-memory/02-domain/G05_TASK_CARDINALITY_AND_ASSIGNMENT_GOVERNANCE.md",
    "ai-memory/03-architecture/G05_ASSIGNMENT_INTEGRATION_CONTRACT.md",
    "ai-memory/03-architecture/G06_PLANNER_DRAFT_HANDOFF_CONTRACT.md",
    "ai-memory/04-engineering/ENGINEERING_RULES.md",
    "ai-memory/04-engineering/FORBIDDEN_ACTIONS.md",
    "ai-memory/04-engineering/TEST_STRATEGY.md",
    "ai-memory/04-engineering/TEST_COVERAGE_MAP.md",
    "ai-memory/04-engineering/SECURITY_RULES.md",
    "ai-memory/04-engineering/TRUST_BOUNDARIES_AND_DATA_HANDLING.md",
    "ai-memory/05-operations/OPERATIONS.md",
    "ai-memory/05-operations/RUNBOOK_CDP.md",
    "ai-memory/05-operations/COMMAND_REFERENCE.md",
    "ai-memory/05-operations/TROUBLESHOOTING.md",
    "ai-memory/06-decisions/ADR-001-USE-EXTERNAL-EDGE-CDP.md",
    "ai-memory/06-decisions/ADR-002-USE-NEOREMOTING-CALLBACK.md",
    "ai-memory/06-decisions/ADR-003-USE-AUTHENTICATED-DIRECT-DOWNLOAD.md",
    "ai-memory/06-decisions/ADR-004-DO-NOT-CLOSE-EXTERNALLY-OWNED-BROWSER.md",
    "ai-memory/07-current/CURRENT_STATE.md",
    "ai-memory/08-handoffs/HANDOFF_TEMPLATE.md",
    "ai-memory/08-handoffs/LATEST_HANDOFF.md",
    "ai-memory/09-coverage/MEMORY_COVERAGE_MATRIX.md",
    "ai-memory/09-coverage/SUBSYSTEM_CATALOG.md",
    "ai-memory/09-coverage/MEMORY_EXPANSION_ROADMAP.md",
    "scripts/validate_ai_memory.py",
    "tests/test_ai_memory.py",
]

ADR_NAMES = [
    "ADR-001-USE-EXTERNAL-EDGE-CDP.md",
    "ADR-002-USE-NEOREMOTING-CALLBACK.md",
    "ADR-003-USE-AUTHENTICATED-DIRECT-DOWNLOAD.md",
    "ADR-004-DO-NOT-CLOSE-EXTERNALLY-OWNED-BROWSER.md",
]
MANIFEST_KEYS = {
    "memory_version",
    "project",
    "language",
    "required_read_order",
    "deep_reference",
    "last_verified_commit",
    "last_verified_application_commit",
    "verification",
    "protected_invariants",
    "forbidden_actions",
    "validation_commands",
}


def _parse_manifest(text: str) -> object:
    try:
        import yaml  # type: ignore
    except ImportError:
        # A conservative fallback confirms the required top-level keys.
        keys = {line.split(":", 1)[0].strip() for line in text.splitlines() if ":" in line and not line.startswith(" ")}
        required = MANIFEST_KEYS
        if not required <= keys:
            raise ValueError("manifest missing required keys")
        return keys
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("manifest must be a mapping")
    return parsed


def sensitive_findings(text: str) -> list[str]:
    """Return only assignment-like secret/session findings, not security guidance words."""
    findings = list(SENSITIVE_RE.findall(text))
    findings.extend(re.findall(r"[?&](?:sid|session|token|jsessionid|access_token|refresh_token)=[^\s`#)]+", text, re.IGNORECASE))
    return findings


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    required = [root / path for path in REQUIRED]
    for path in required:
        if not path.is_file():
            errors.append(f"missing required file: {path.relative_to(root)}")

    if errors:
        return errors

    manifest_text = (root / "ai-memory/memory-manifest.yaml").read_text(encoding="utf-8")
    try:
        manifest = _parse_manifest(manifest_text)
    except Exception as exc:  # pragma: no cover - exact parser error is environment-specific
        errors.append(f"manifest parse failed: {exc}")
        manifest = {}

    if isinstance(manifest, dict):
        for key in MANIFEST_KEYS:
            if key not in manifest:
                errors.append(f"manifest missing key: {key}")
        verified = str(manifest.get("last_verified_commit", ""))
        if not HASH_RE.fullmatch(verified):
            errors.append("manifest last_verified_commit is not a 40-character hash")
        application_commit = str(manifest.get("last_verified_application_commit", ""))
        if not HASH_RE.fullmatch(application_commit):
            errors.append("manifest last_verified_application_commit is not a 40-character hash")
        verification = manifest.get("verification")
        if not isinstance(verification, dict):
            errors.append("manifest verification must be a mapping")
        else:
            for key in ("main_commit", "originating_live_verified_commit", "focused_tests", "live_acceptance"):
                if key not in verification:
                    errors.append(f"manifest verification missing key: {key}")
            for key in ("main_commit", "originating_live_verified_commit"):
                if not HASH_RE.fullmatch(str(verification.get(key, ""))):
                    errors.append(f"manifest verification {key} is not a 40-character hash")
        deep_reference = manifest.get("deep_reference")
        if not isinstance(deep_reference, list) or not all(isinstance(item, str) for item in deep_reference):
            errors.append("manifest deep_reference must be a list of relative paths")

    memory_files = [path for path in required if path.suffix.lower() in {".md", ".yaml"}]
    for path in memory_files:
        text = path.read_text(encoding="utf-8")
        if len(text.splitlines()) > 500:
            errors.append(f"memory file exceeds 500 lines: {path.relative_to(root)}")
        if sensitive_findings(text):
            errors.append(f"sensitive assignment-like material found: {path.relative_to(root)}")
        if ABSOLUTE_PATH_RE.search(text):
            errors.append(f"absolute machine path found in memory: {path.relative_to(root)}")
        for target in LINK_RE.findall(text):
            target_path = target.split("#", 1)[0]
            if "://" in target_path or target_path.startswith("mailto:"):
                continue
            resolved = (path.parent / target_path).resolve()
            if not resolved.is_file():
                errors.append(f"broken internal link in {path.relative_to(root)}: {target}")

    current = (root / "ai-memory/07-current/CURRENT_STATE.md").read_text(encoding="utf-8")
    if not DATE_RE.search(current):
        errors.append("CURRENT_STATE.md has no Updated: YYYY-MM-DD line")
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    if "ai-memory/INDEX.md" not in agents:
        errors.append("AGENTS.md does not link to ai-memory/INDEX.md")
    if len(agents.splitlines()) > 200:
        errors.append("AGENTS.md exceeds 200 lines")
    context = (root / "AI_CONTEXT.md").read_text(encoding="utf-8")
    if len(context.splitlines()) > 150:
        errors.append("AI_CONTEXT.md exceeds 150 lines")

    if isinstance(manifest, dict):
        for item in manifest.get("required_read_order", []):
            if not (root / "ai-memory" / str(item)).is_file():
                errors.append(f"manifest read-order target missing: {item}")
        for item in manifest.get("deep_reference", []):
            if not (root / "ai-memory" / str(item)).is_file():
                errors.append(f"manifest deep-reference target missing: {item}")
        if any(re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", str(value)) for value in manifest.values()):
            errors.append("absolute machine path found in manifest")

    matrix = (root / "ai-memory/09-coverage/MEMORY_COVERAGE_MATRIX.md").read_text(encoding="utf-8")
    for line in matrix.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) == 16 and parts[1] not in {"Subsystem", "---"} and parts[11] not in VALID_COVERAGE_STATUSES:
            errors.append(f"invalid coverage overall status: {parts[11]}")
    for relative in (
        "ai-memory/02-domain/DOMAIN_SCHEMA_AND_LIFECYCLE.md",
        "ai-memory/03-architecture/SCHEMA_MIGRATION_AND_COMPATIBILITY.md",
        "ai-memory/04-engineering/TRUST_BOUNDARIES_AND_DATA_HANDLING.md",
        "ai-memory/03-architecture/G04_AI_PROPOSAL_BOUNDARY.md",
    ):
        if re.search(r"(?<!NOT_)LIVE_VERIFIED", (root / relative).read_text(encoding="utf-8")):
            errors.append(f"unsupported live-verified claim in source-anchored memory: {relative}")

    adr_dir = root / "ai-memory/06-decisions"
    titles: set[str] = set()
    for name in ADR_NAMES:
        text = (adr_dir / name).read_text(encoding="utf-8")
        title = next((line.strip() for line in text.splitlines() if line.startswith("# ")), "")
        if not title or title in titles:
            errors.append(f"duplicate or missing ADR title: {name}")
        titles.add(title)
        if not re.search(r"^Status:\s*(Accepted|Superseded|Deprecated)\s*$", text, re.MULTILINE):
            errors.append(f"invalid ADR status: {name}")
        for heading in ("## Context", "## Decision", "## Consequences", "## Alternatives considered", "## Related files/tests"):
            if heading not in text:
                errors.append(f"ADR missing {heading}: {name}")
        if not re.search(r"^Date:\s*\d{4}-\d{2}-\d{2}\s*$", text, re.MULTILINE):
            errors.append(f"ADR missing date: {name}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"AI_MEMORY_ERROR: {error}")
        return 1
    print("AI_MEMORY_VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
