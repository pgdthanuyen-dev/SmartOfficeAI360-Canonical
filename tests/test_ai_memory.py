from pathlib import Path

from scripts.validate_ai_memory import REQUIRED, sensitive_findings, validate


ROOT = Path(__file__).resolve().parents[1]


def test_required_memory_files_exist():
    assert all((ROOT / path).is_file() for path in REQUIRED)


def test_memory_validator_passes():
    assert validate(ROOT) == []


def test_manifest_commit_is_stable():
    text = (ROOT / "ai-memory/memory-manifest.yaml").read_text(encoding="utf-8")
    assert "ea39c35a27b399fe5c049b3d4545db2322142ac9" in text
    assert "768dcebc07eddf5c704e395b7eaad8426b286c91" in text
    assert "50fd0db8403026c65f06b94323b67e90164b31b4" in text


def test_security_scan_ignores_guidance_but_rejects_secret_assignments():
    assert sensitive_findings("Never expose credentials or cookies.") == []
    assert sensitive_findings("access_" + "token=live-value")


def test_latest_handoff_and_adr_set_are_present():
    assert (ROOT / "ai-memory/08-handoffs/LATEST_HANDOFF.md").is_file()
    assert len(list((ROOT / "ai-memory/06-decisions").glob("ADR-*.md"))) == 4


def test_coverage_memory_is_deep_reference_not_onboarding_requirement():
    manifest = (ROOT / "ai-memory/memory-manifest.yaml").read_text(encoding="utf-8")
    assert "09-coverage/MEMORY_COVERAGE_MATRIX.md" in manifest
    required_order = manifest.split("deep_reference:", 1)[0]
    assert "09-coverage/" not in required_order


def test_g02_and_trust_memory_is_registered_and_source_anchored():
    manifest = (ROOT / "ai-memory/memory-manifest.yaml").read_text(encoding="utf-8")
    for path in (
        "02-domain/DOMAIN_SCHEMA_AND_LIFECYCLE.md",
        "03-architecture/SCHEMA_MIGRATION_AND_COMPATIBILITY.md",
        "04-engineering/TRUST_BOUNDARIES_AND_DATA_HANDLING.md",
    ):
        assert path in manifest
        assert "LIVE_VERIFIED" not in (ROOT / "ai-memory" / path).read_text(encoding="utf-8")


def test_storage_lifecycle_memory_is_registered():
    assert (ROOT / "ai-memory/03-architecture/STORAGE_QUEUE_MANIFEST_LIFECYCLE.md").is_file()


def test_g03_extraction_memory_is_registered_and_not_overclaimed():
    path = ROOT / "ai-memory/03-architecture/G03_EXTRACTION_OCR_CACHE_SAFETY.md"
    text = path.read_text(encoding="utf-8")
    assert "NOT_LIVE_VERIFIED" in text
    assert "33 passed" in text
    assert "FakeOcrAdapter" in text
    assert "03-architecture/G03_EXTRACTION_OCR_CACHE_SAFETY.md" in (
        ROOT / "ai-memory/memory-manifest.yaml"
    ).read_text(encoding="utf-8")


def test_g04_proposal_memory_is_registered_and_not_overclaimed():
    path = ROOT / "ai-memory/03-architecture/G04_AI_PROPOSAL_BOUNDARY.md"
    text = path.read_text(encoding="utf-8")
    assert "NOT_LIVE_VERIFIED" in text
    assert "42 passed" in text
    assert "FakeAiProposalProvider" in text
    assert "03-architecture/G04_AI_PROPOSAL_BOUNDARY.md" in (
        ROOT / "ai-memory/memory-manifest.yaml"
    ).read_text(encoding="utf-8")
