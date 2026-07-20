from __future__ import annotations

import pytest

from tools.qlvb_downloader.assignment_draft_service import AssignmentDraftService, AssignmentDraftServiceError


def test_missing_active_tenant_is_rejected_before_database_access(tmp_path):
    service = AssignmentDraftService(str(tmp_path))
    with pytest.raises(AssignmentDraftServiceError, match="Chua xac dinh"):
        service.list_pending_drafts("")


def test_service_has_no_network_client_imports():
    import inspect
    import tools.qlvb_downloader.assignment_draft_service as module

    source = inspect.getsource(module)
    assert "requests" not in source and "socket" not in source and "http" not in source
