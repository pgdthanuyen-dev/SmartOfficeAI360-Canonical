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
