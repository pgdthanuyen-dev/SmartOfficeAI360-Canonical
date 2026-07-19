from pathlib import Path
import shutil

import pytest


_RUNTIME_TEST_DIRS = (
    "Data_auth_test",
    "Data_dup_test",
    "Data_extractor_test",
    "Data_index_test",
    "Data_sync_retry_test",
)


@pytest.fixture(autouse=True)
def isolate_legacy_runtime_test_dirs():
    """Legacy tests use fixed paths; isolate them so order/re-runs are deterministic."""
    for name in _RUNTIME_TEST_DIRS:
        path = Path(name)
        if path.exists():
            shutil.rmtree(path)
    yield
    for name in _RUNTIME_TEST_DIRS:
        path = Path(name)
        if path.exists():
            shutil.rmtree(path)
