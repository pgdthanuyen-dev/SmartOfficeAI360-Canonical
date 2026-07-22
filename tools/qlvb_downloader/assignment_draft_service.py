"""Local UI adapter for G05C draft storage and Office review."""

from __future__ import annotations

from time import monotonic
from typing import Any

from .assignment_draft_repository import (
    AssignmentDraftRepository,
    PlannerHandoffAttempt,
    init_assignment_draft_schema,
)
from .assignment_draft_planner_handoff import build_planner_handoff
from .assignment_draft_review import AssignmentDraftReviewError, AssignmentDraftReviewService, PENDING_OFFICE_REVIEW
from .index_db import open_db
from .planner_draft_handoff_client import PlannerDraftHandoffClient, PlannerHandoffOutcome, PlannerHandoffResult
from .domain_models import utc_now_iso


class AssignmentDraftServiceError(ValueError):
    pass


class AssignmentDraftService:
    def __init__(self, data_dir: str, handoff_client: PlannerDraftHandoffClient | None = None) -> None:
        self.data_dir = data_dir
        self._handoff_client = handoff_client or PlannerDraftHandoffClient()

    def list_pending_drafts(self, active_tenant_id: str, limit: int = 50):
        return self._with_repository(active_tenant_id, lambda repo: repo.list_pending_drafts(active_tenant_id, limit))

    def get_draft_detail(self, active_tenant_id: str, draft_id: str):
        return self._with_repository(active_tenant_id, lambda repo: repo.get_draft_by_id(active_tenant_id, draft_id))

    def get_draft_review_state(self, active_tenant_id: str, draft_id: str):
        return self._with_review(active_tenant_id, lambda review: review.get_current_review_state(active_tenant_id, draft_id))

    def revise_draft(self, active_tenant_id: str, draft_id: str, edits: dict[str, Any], reviewer: str, reason: str | None):
        return self._with_review(active_tenant_id, lambda review: review.create_office_revision(active_tenant_id, draft_id, reviewer, reason, edits))

    def approve_draft(self, active_tenant_id: str, draft_id: str, reviewer: str, reason: str | None = None):
        return self._with_review(active_tenant_id, lambda review: review.approve_draft(active_tenant_id, draft_id, reviewer, reason))

    def reject_draft(self, active_tenant_id: str, draft_id: str, reviewer: str, reason: str):
        return self._with_review(active_tenant_id, lambda review: review.reject_draft(active_tenant_id, draft_id, reviewer, reason))

    def send_draft_to_planner(self, active_tenant_id: str, draft_id: str) -> PlannerHandoffResult:
        """Load the immutable snapshot server-side and hand it to Planner once."""

        self._tenant(active_tenant_id)
        connection = open_db(self.data_dir)
        try:
            init_assignment_draft_schema(connection)
            repository = AssignmentDraftRepository(connection)
            draft = repository.get_draft_by_id(active_tenant_id, draft_id)
            if draft is None:
                raise AssignmentDraftServiceError("Khong tim thay du thao.")
            if draft.current_status != PENDING_OFFICE_REVIEW:
                raise AssignmentDraftServiceError("Du thao khong con cho gui Planner.")
            started_at, started = utc_now_iso(), monotonic()
            try:
                handoff = build_planner_handoff(draft)
                handoff.to_planner_receiver_payload()
            except Exception:
                attempt = PlannerHandoffAttempt(
                    started_at=started_at, completed_at=utc_now_iso(), result=PlannerHandoffOutcome.VALIDATION_ERROR.value,
                    planner_draft_id=None, correlation_id="local-validation", http_status=None,
                    duration_ms=max(0, int((monotonic() - started) * 1000)), error_code=PlannerHandoffOutcome.VALIDATION_ERROR.value,
                    error_message="SmartOffice source metadata did not satisfy the Planner draft contract.",
                    idempotency_key_hash=build_planner_handoff(draft).idempotency_key,
                )
                repository.record_planner_handoff_attempt(active_tenant_id, draft_id, attempt)
                return PlannerHandoffResult(
                    PlannerHandoffOutcome.VALIDATION_ERROR, "local-validation",
                    message="SmartOffice source metadata did not satisfy the Planner draft contract.",
                )
            result = self._handoff_client.send(handoff)
            attempt = PlannerHandoffAttempt(
                started_at=started_at, completed_at=utc_now_iso(), result=result.outcome.value,
                planner_draft_id=result.planner_draft_id, correlation_id=result.correlation_id,
                http_status=result.http_status, duration_ms=max(0, int((monotonic() - started) * 1000)),
                error_code=None if result.outcome in {PlannerHandoffOutcome.CREATED, PlannerHandoffOutcome.DUPLICATE} else result.outcome.value,
                error_message=result.message, idempotency_key_hash=handoff.idempotency_key,
            )
            try:
                repository.record_planner_handoff_attempt(active_tenant_id, draft_id, attempt)
            except Exception:
                return PlannerHandoffResult(
                    PlannerHandoffOutcome.LOCAL_PERSISTENCE_ERROR, result.correlation_id,
                    result.planner_draft_id, result.planner_status,
                    message="Planner responded, but SmartOffice could not persist the handoff result.",
                    http_status=result.http_status,
                )
            return result
        except AssignmentDraftServiceError:
            raise
        except Exception as exc:
            raise AssignmentDraftServiceError(self._message(exc)) from None
        finally:
            connection.close()

    def planner_draft_url(self, planner_draft_id: str | None) -> str | None:
        return self._handoff_client.planner_draft_url(planner_draft_id)

    def _with_repository(self, tenant: str, callback):
        self._tenant(tenant)
        connection = open_db(self.data_dir)
        try:
            init_assignment_draft_schema(connection)
            return callback(AssignmentDraftRepository(connection))
        except Exception as exc:
            raise AssignmentDraftServiceError(self._message(exc)) from None
        finally:
            connection.close()

    def _with_review(self, tenant: str, callback):
        self._tenant(tenant)
        connection = open_db(self.data_dir)
        try:
            init_assignment_draft_schema(connection)
            return callback(AssignmentDraftReviewService(connection))
        except Exception as exc:
            raise AssignmentDraftServiceError(self._message(exc)) from None
        finally:
            connection.close()

    @staticmethod
    def _tenant(value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise AssignmentDraftServiceError("Chua xac dinh don vi lam viec.")

    @staticmethod
    def _message(exc: Exception) -> str:
        if isinstance(exc, AssignmentDraftReviewError):
            return str(exc)
        return "Khong the xu ly du thao."
