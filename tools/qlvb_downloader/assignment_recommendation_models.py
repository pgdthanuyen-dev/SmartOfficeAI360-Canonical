from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ASSIGNMENT_RECOMMENDATION_CONTRACT_VERSION = "1.0.0"


class AssignmentRecommendationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class AssignmentRecommendation:
    tenant_id: str
    source_document_id: str
    source_proposal_ids: tuple[str, ...] = ()
    lead_unit: str | None = None
    primary_assignee: str | None = None
    coordinating_units: tuple[str, ...] = ()
    assignment_reason: str = ""
    confidence: float = 0.0
    source_rules: tuple[str, ...] = ()
    manual_review_required: bool = True
    review_reasons: tuple[str, ...] = ()
    action_items: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    contract_version: str = ASSIGNMENT_RECOMMENDATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.source_document_id.strip():
            raise AssignmentRecommendationValidationError("tenant_id and source_document_id are required")
        units = tuple(dict.fromkeys(value.strip() for value in self.coordinating_units if value.strip()))
        proposals = tuple(dict.fromkeys(value.strip() for value in self.source_proposal_ids if value.strip()))
        if self.lead_unit and self.lead_unit in units:
            units = tuple(value for value in units if value != self.lead_unit)
        if not 0 <= float(self.confidence) <= 100:
            raise AssignmentRecommendationValidationError("confidence must be between 0 and 100")
        if (not self.lead_unit or self.review_reasons) and not self.manual_review_required:
            raise AssignmentRecommendationValidationError("manual review is required for missing lead or review reasons")
        if any(key.lower() in {"email", "phone", "credential", "token", "password"} for key in self.provenance):
            raise AssignmentRecommendationValidationError("sensitive provenance is not allowed")
        object.__setattr__(self, "coordinating_units", units)
        object.__setattr__(self, "source_proposal_ids", proposals)
