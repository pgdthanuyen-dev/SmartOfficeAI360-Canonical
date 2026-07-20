"""Local UI adapter for G05C draft storage and Office review."""

from __future__ import annotations

from typing import Any

from .assignment_draft_repository import AssignmentDraftRepository, init_assignment_draft_schema
from .assignment_draft_review import AssignmentDraftReviewError, AssignmentDraftReviewService
from .index_db import open_db


class AssignmentDraftServiceError(ValueError):
    pass


class AssignmentDraftService:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir

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
