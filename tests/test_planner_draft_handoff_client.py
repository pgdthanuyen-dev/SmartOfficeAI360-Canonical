from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools.qlvb_downloader.assignment_draft_planner_handoff import PLANNER_RECEIVER_PATH, build_planner_handoff
from tools.qlvb_downloader.planner_draft_handoff_client import PlannerDraftHandoffClient, PlannerHandoffConfig, PlannerHandoffOutcome


def _handoff():
    draft = SimpleNamespace(
        tenant_id="tenant-a", source_system="qlvb", source_document_id="DOC-1", source_revision="REV-1",
        id="draft-1", draft_version=1, task_title="Demo", task_description="Description", lead_unit_source_key="UNIT-A",
        proposed_start_date=None, proposed_due_date=None, priority="NORMAL",
        personnel=(SimpleNamespace(role_type="LEAD_EXECUTOR", personnel_source_key="P-1", is_substitute=False, confidence=90, item_order=0),),
        deliverables=(), checklist_items=(), milestones=(), warnings=(), overall_confidence=90,
        source_input_fingerprint="a" * 64, draft_content_fingerprint="b" * 64,
    )
    return build_planner_handoff(draft)


def _client(response):
    captured = {}

    def transport(url, headers, payload, timeout):
        captured.update(url=url, headers=headers, payload=payload, timeout=timeout)
        if isinstance(response, BaseException):
            raise response
        return response

    client = PlannerDraftHandoffClient(PlannerHandoffConfig(True, "https://planner.example", "secret-value"), transport)
    return client, captured


def test_created_posts_once_to_exact_receiver_with_secret_header_and_json_idempotency_key():
    client, captured = _client((201, {"success": True, "draftId": "planner-1", "status": "PENDING_OFFICE_REVIEW", "duplicate": False}))
    result = client.send(_handoff())
    assert result.outcome is PlannerHandoffOutcome.CREATED
    assert captured["url"] == "https://planner.example" + PLANNER_RECEIVER_PATH
    assert captured["headers"] == {"Content-Type": "application/json", "X-SmartOffice-Secret": "secret-value"}
    assert json.loads(captured["payload"])["idempotencyKey"] == _handoff().idempotency_key


@pytest.mark.parametrize(("status", "body", "outcome"), [
    (200, {"success": True, "draftId": "planner-1", "status": "PENDING_OFFICE_REVIEW", "duplicate": True}, PlannerHandoffOutcome.DUPLICATE),
    (400, {"error": "invalid_smartoffice_draft_payload"}, PlannerHandoffOutcome.VALIDATION_ERROR),
    (401, {"error": "unauthorized"}, PlannerHandoffOutcome.AUTH_ERROR),
    (503, {"error": "smartoffice_integration_unavailable"}, PlannerHandoffOutcome.PLANNER_UNAVAILABLE),
    (201, {"success": True, "draftId": "planner-1", "status": "PENDING_OFFICE_REVIEW", "duplicate": True}, PlannerHandoffOutcome.UNKNOWN_RESULT),
])
def test_receiver_response_classification(status, body, outcome):
    client, _ = _client((status, body))
    assert client.send(_handoff()).outcome is outcome


def test_timeout_is_unknown_and_client_does_not_retry_post():
    calls = {"count": 0}

    def timeout(*_args):
        calls["count"] += 1
        raise TimeoutError()

    client = PlannerDraftHandoffClient(PlannerHandoffConfig(True, "https://planner.example", "secret"), timeout)
    assert client.send(_handoff()).outcome is PlannerHandoffOutcome.UNKNOWN_RESULT
    assert calls["count"] == 1


def test_disabled_or_incomplete_config_never_attempts_a_post():
    client = PlannerDraftHandoffClient(PlannerHandoffConfig(False, "https://planner.example", "secret"), lambda *_: pytest.fail("post called"))
    assert client.send(_handoff()).outcome is PlannerHandoffOutcome.PLANNER_UNAVAILABLE


def test_url_normalization_does_not_create_api_api_path():
    config = PlannerHandoffConfig(True, "https://planner.example/api", "secret")
    assert config.receiver_url() == "https://planner.example/api/integrations/smartoffice/drafts"
