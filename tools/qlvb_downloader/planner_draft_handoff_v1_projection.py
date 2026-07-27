"""Pure, deterministic construction of the read-only Planner handoff projection."""
from __future__ import annotations

from types import MappingProxyType

from .assignment_draft_repository import StoredAssignmentDraft
from .assignment_recommendation_models import AssignmentRecommendation
from .planner_draft_handoff_v1_models import *


class PlannerDraftHandoffProjectionError(ValueError):
    pass


def _ordered(values):
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _citation_key(citation):
    """Order only by persisted provenance fields; ``None`` is comparable and stable."""
    return tuple("" if citation.get(name) is None else str(citation.get(name)) for name in (
        "attachment_id", "page_start", "page_end", "excerpt_sha256", "source_text_sha256", "id",
    ))


def _normalized_citations(citations):
    normalized = []
    seen = set()
    for citation in citations or ():
        item = dict(citation)
        key = _citation_key(item)
        # Do not collapse provenance with neither an id nor a persisted hash.
        dedupe_key = key if any(key[3:]) else None
        if dedupe_key is not None and dedupe_key in seen:
            continue
        if dedupe_key is not None:
            seen.add(dedupe_key)
        normalized.append(MappingProxyType(item))
    return tuple(sorted(normalized, key=_citation_key))


def build_planner_draft_handoff_projection_v1(*, draft: StoredAssignmentDraft, recommendation: AssignmentRecommendation | None, proposals=(), source_draft_version: int | None = None) -> PlannerDraftHandoffProjectionV1:
    if source_draft_version is not None and draft.draft_version != source_draft_version:
        raise PlannerDraftHandoffProjectionError("SOURCE_DRAFT_VERSION_MISMATCH")
    if recommendation and (recommendation.tenant_id != draft.tenant_id):
        raise PlannerDraftHandoffProjectionError("TENANT_BOUNDARY_MISMATCH")
    if recommendation and (recommendation.source_document_id != draft.source_document_id):
        raise PlannerDraftHandoffProjectionError("SOURCE_DOCUMENT_BOUNDARY_MISMATCH")
    warnings = set()
    if not all((draft.document_number, draft.subject, draft.issuing_agency, draft.issued_date)):
        warnings.add(SOURCE_DOCUMENT_METADATA_INCOMPLETE)
    rec = recommendation
    lead = rec.lead_unit if rec else draft.lead_unit_source_key
    primary = rec.primary_assignee if rec else None
    units = _ordered((rec.coordinating_units if rec else draft.participating_unit_source_keys))
    units = tuple(unit for unit in units if unit != lead)
    review_reasons = _ordered(rec.review_reasons if rec else ())
    assignment_reason = rec.assignment_reason.strip() if rec else None
    source_rules = _ordered(rec.source_rules if rec else ())
    manual = bool(rec.manual_review_required) if rec else True
    if not rec:
        warnings.add(ASSIGNMENT_PROVENANCE_INCOMPLETE)
    elif not assignment_reason or not source_rules:
        warnings.add(ASSIGNMENT_PROVENANCE_INCOMPLETE)
    if not primary:
        warnings.add(PRIMARY_ASSIGNEE_UNRESOLVED)
    if not units:
        warnings.add(COORDINATING_UNITS_UNAVAILABLE)
    action_items = []
    proposal_ids = []
    for proposal in sorted(proposals, key=lambda p: (str(p.get("external_proposal_id", "")), str(p.get("proposal_item_id", "")))):
        if proposal.get("tenant_id") != draft.tenant_id:
            raise PlannerDraftHandoffProjectionError("TENANT_BOUNDARY_MISMATCH")
        if proposal.get("document_id") != draft.source_document_id:
            raise PlannerDraftHandoffProjectionError("SOURCE_DOCUMENT_BOUNDARY_MISMATCH")
        proposal_ids.append(proposal.get("external_proposal_id") or proposal.get("proposal_item_id"))
        action = {key: proposal.get(key) for key in ("proposal_item_id", "action_id", "action_title", "action_description", "proposed_unit_id", "proposed_assignee_id", "proposed_due_date", "expected_output", "priority") if proposal.get(key) is not None}
        if proposal.get("citations") is not None:
            action["citations"] = _normalized_citations(proposal["citations"])
        if not action.get("action_id") or not action.get("citations"):
            warnings.add(ACTION_ITEM_PROVENANCE_INCOMPLETE)
        action_items.append(MappingProxyType(action))
    if draft.source_attachments:
        warnings.add(SAFE_ATTACHMENT_URL_UNAVAILABLE)
    warning_codes = _ordered(warnings)
    manual = manual or bool(warning_codes) or bool(review_reasons)
    return PlannerDraftHandoffProjectionV1(
        CONTRACT_VERSION, draft.tenant_id, draft.tenant_id, SOURCE_SYSTEM, draft.source_document_id, draft.id, draft.draft_version,
        draft.document_number, draft.subject, draft.issuing_agency, draft.issued_date, None, draft.summary, None, tuple(action_items),
        lead, primary, units, assignment_reason, rec.confidence if rec else None,
        source_rules, manual, review_reasons, draft.proposed_due_date, draft.priority, (),
        _ordered(proposal_ids + list(rec.source_proposal_ids if rec else ())), draft.builder_version, warning_codes, not warning_codes,
    )
