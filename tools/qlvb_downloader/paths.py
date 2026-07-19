from __future__ import annotations

from pathlib import Path
import os


import sys

def project_root() -> Path:
    """Return the package/project root when running from the V22.1 folder."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).resolve().parents[2]


def resolve_path(value: str | None, default: str) -> Path:
    root = project_root()
    raw = value or default
    p = Path(raw)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def ensure_tree(root: Path) -> None:
    for rel in [
        "Data/config",
        "Data/files/incoming",
        "Data/files/outgoing",
        "Data/queue/incoming",
        "Data/queue/outgoing",
        "Data/logs/errors",
        "Data/runtime/playwright_profile",
    ]:
        (root / rel).mkdir(parents=True, exist_ok=True)


def configure_bundled_playwright() -> Path | None:
    """Point Playwright at Chromium shipped beside frozen executables."""
    if not getattr(sys, "frozen", False):
        return None
    for candidate in (
        Path(sys.executable).parent / "_internal" / "ms-playwright",
        Path(sys.executable).parent / "ms-playwright",
    ):
        if candidate.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            return candidate
    return None
