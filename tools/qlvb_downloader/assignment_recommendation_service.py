"""Document-level, transaction-owned G04 -> G05 assignment orchestration."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from .assignment_draft_builder import AssignmentDraftBuilder
from .assignment_draft_models import AssignmentDraftBuildRequest
from .assignment_draft_repository import AssignmentDraftRepository, StoredAssignmentDraft
from .assignment_recommendation_models import AssignmentRecommendation
from .assignment_recommendation_repository import AssignmentRecommendationRepository
from .assignment_recommendation_repository import AssignmentRecommendationConflict
from .assignment_rule_engine import DocumentAssignmentSignals
from .personnel_selection_engine import PersonnelSelectionRequest


LOW_CONFIDENCE_THRESHOLD = 75.0


class AssignmentOrchestrationError(RuntimeError):
    """Safe, code-only failure suitable for callers and logs."""


@dataclass(frozen=True)
class AssignmentOrchestrationRequest:
    tenant_id: str
    source_document_id: str
    contract_version: str
    signals: DocumentAssignmentSignals
    draft_request: AssignmentDraftBuildRequest
    personnel_request_factory: Callable[[Any], PersonnelSelectionRequest] | None = None


@dataclass(frozen=True)
class AssignmentOrchestrationResult:
    recommendation: Any
    draft: StoredAssignmentDraft | None
    created: bool


class AssignmentRecommendationService:
    """Compose existing G05 components; it does not call an AI provider or Planner."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        proposal_repository: Any,
        rule_engine: Any,
        personnel_engine: Any,
        recommendation_repository: AssignmentRecommendationRepository | None = None,
        draft_builder: AssignmentDraftBuilder | None = None,
        draft_repository: AssignmentDraftRepository | None = None,
    ) -> None:
        self.connection = connection
        self.proposal_repository = proposal_repository
        self.rule_engine = rule_engine
        self.personnel_engine = personnel_engine
        self.recommendation_repository = recommendation_repository or AssignmentRecommendationRepository(connection)
        self.draft_builder = draft_builder or AssignmentDraftBuilder()
        self.draft_repository = draft_repository or AssignmentDraftRepository(connection)

    def orchestrate(self, request: AssignmentOrchestrationRequest) -> AssignmentOrchestrationResult:
        self._validate_request(request)
        proposals = self.proposal_repository.list_accepted_proposals_for_tenant_document(
            tenant_id=request.tenant_id, document_id=request.source_document_id
        )
        if any(
            row.get("tenant_id") not in (None, request.tenant_id)
            or row.get("document_id") not in (None, request.source_document_id)
            for row in proposals
        ):
            raise AssignmentOrchestrationError("G04_TENANT_DOCUMENT_MISMATCH")
        try:
            rule_evaluation = self.rule_engine.evaluate(request.signals, persist_matches=False)
        except Exception:
            raise AssignmentOrchestrationError("G05A_RULE_EVALUATION_FAILED") from None
        rule_recommendation = getattr(rule_evaluation, "recommendation", rule_evaluation)
        try:
            personnel_recommendation = self._select_personnel(request, rule_recommendation)
        except Exception:
            raise AssignmentOrchestrationError("G05B_PERSONNEL_SELECTION_FAILED") from None
        recommendation = self._recommendation(request, proposals, rule_recommendation, personnel_recommendation)

        self.connection.execute("BEGIN IMMEDIATE")
        try:
            persisted = self.recommendation_repository.create_or_get(recommendation)
            existing_draft = self.draft_repository.get_active_for_document(request.tenant_id, request.source_document_id)
            if existing_draft is not None:
                self.connection.commit()
                return AssignmentOrchestrationResult(persisted, existing_draft, False)
            candidate = self.draft_builder.build(self._draft_request(request, rule_recommendation, personnel_recommendation))
            draft = self.draft_repository.save_draft_candidate(candidate, manage_transaction=False)
            self.connection.commit()
        except AssignmentRecommendationConflict:
            self.connection.rollback()
            raise
        except Exception:
            self.connection.rollback()
            raise AssignmentOrchestrationError("ASSIGNMENT_ORCHESTRATION_PERSISTENCE_FAILED") from None
        return AssignmentOrchestrationResult(persisted, draft, True)

    def _select_personnel(self, request: AssignmentOrchestrationRequest, rule_recommendation: Any) -> Any:
        if not getattr(rule_recommendation, "lead_unit_key", None) or request.personnel_request_factory is None:
            return _empty_personnel_recommendation(rule_recommendation)
        return self.personnel_engine.evaluate(request.personnel_request_factory(rule_recommendation), persist_matches=False)

    def _recommendation(self, request: AssignmentOrchestrationRequest, proposals: list[dict[str, Any]], rule: Any, personnel: Any) -> AssignmentRecommendation:
        review = []
        lead = getattr(rule, "lead_unit_key", None)
        confidence = min(float(getattr(rule, "confidence", 0)), float(getattr(personnel, "overall_confidence", 0))) if lead else 0.0
        if not proposals: review.append("G04_PROPOSALS_MISSING_OR_EXCLUDED")
        if any(int(row.get("citation_count", 0)) <= 0 for row in proposals): review.append("PROVENANCE_INCOMPLETE")
        if not lead: review.append("LEAD_UNIT_UNRESOLVED")
        if confidence < LOW_CONFIDENCE_THRESHOLD: review.append("LOW_CONFIDENCE")
        if getattr(rule, "conflicting_rules", ()): review.append("RULE_CONFLICT")
        if getattr(personnel, "conflicting_roles", ()): review.append("PERSONNEL_TIE")
        if getattr(personnel, "unresolved_roles", ()): review.append("PERSONNEL_UNRESOLVED")
        action_ids = tuple(str(row["action_item_id"]) for row in proposals if row.get("action_item_id"))
        proposal_ids = tuple(str(row.get("proposal_item_id") or row.get("external_proposal_id")) for row in proposals)
        provenance = {
            "proposal_count": len(proposals),
            "citation_counts": {str(row.get("proposal_item_id")): int(row.get("citation_count", 0)) for row in proposals},
            "citation_ids": {
                str(row.get("proposal_item_id")): tuple(filter(None, str(row.get("citation_ids") or "").split(",")))
                for row in proposals
            },
        }
        primary = _primary_assignee(personnel)
        if confidence < LOW_CONFIDENCE_THRESHOLD or getattr(personnel, "conflicting_roles", ()):
            primary = None
        if primary is None: review.append("PRIMARY_ASSIGNEE_UNRESOLVED")
        return AssignmentRecommendation(
            tenant_id=request.tenant_id, source_document_id=request.source_document_id,
            source_proposal_ids=proposal_ids, lead_unit=lead, primary_assignee=primary,
            coordinating_units=tuple(getattr(rule, "coordinating_unit_keys", ()) or ()),
            assignment_reason=str(getattr(rule, "explanation", "")), confidence=confidence,
            source_rules=tuple(str(getattr(item, "rule_code", item)) for item in getattr(rule, "conflicting_rules", ()))
                + ((str(getattr(getattr(rule, "primary_rule", None), "rule_code", "")),) if getattr(rule, "primary_rule", None) else ()),
            manual_review_required=bool(review), review_reasons=tuple(dict.fromkeys(review)),
            action_items=action_ids, provenance=provenance, contract_version=request.contract_version,
        )

    @staticmethod
    def _draft_request(request: AssignmentOrchestrationRequest, rule: Any, personnel: Any) -> AssignmentDraftBuildRequest:
        return AssignmentDraftBuildRequest(**{**request.draft_request.__dict__, "g05a_proposal": rule, "g05b_proposal": personnel})

    @staticmethod
    def _validate_request(request: AssignmentOrchestrationRequest) -> None:
        if request.tenant_id != request.signals.tenant_id or request.source_document_id != request.signals.document_id:
            raise ValueError("tenant/document mismatch between orchestration request and signals")
        if request.tenant_id != request.draft_request.tenant_id or request.source_document_id != request.draft_request.source_document_id:
            raise ValueError("tenant/document mismatch between orchestration request and draft")


def _primary_assignee(personnel: Any) -> str | None:
    for item in getattr(personnel, "role_recommendations", ()):
        value = getattr(item, "selected_source_person_key", None)
        if value:
            return str(value)
    return None


def _empty_personnel_recommendation(rule: Any) -> Any:
    return type("EmptyPersonnelRecommendation", (), {"overall_confidence": 0.0, "role_recommendations": (), "conflicting_roles": (), "unresolved_roles": tuple(getattr(rule, "required_roles", ()) or ())})()
