# G05 assignment integration contract

Updated: 2026-07-25

## Boundary

**PLANNED_CONTRACT:** G04 proposal ingestion feeds G05A rule matching, then G05B personnel selection, then G05C draft construction. This is a design contract, not implemented application behavior.

## Minimal AssignmentRecommendation

```text
tenant_id
source_document_id
source_proposal_ids
lead_unit
primary_assignee
coordinating_units
assignment_reason
confidence
source_rules
manual_review_required
review_reasons
action_items
provenance
contract_version
```

**PLANNED_CONTRACT:** `lead_unit` is single-valued. `primary_assignee` is nullable and single-valued. `coordinating_units` is deduplicated and excludes the lead unit. Proposal ids must belong to the same source document. Action items are aggregated without discarding citation/provenance. Invalid matches leave assignee empty. Manual review is mandatory for missing data, conflict, low confidence, or tied candidates.

## Source anchors

**CODE_FACT:** `AiProposal` has proposed unit/assignee/supervisor fields (`ai_proposal_models.py`). `AssignmentRuleUnit` and `AssignmentRuleRole` express unit/role mappings (`assignment_rule_models.py`). `PersonnelSelectionRequest` resolves a lead unit and required roles (`personnel_selection_engine.py`). `AssignmentDraftBuilder` accepts G05A/G05B proposals and emits one candidate with lead/participating units (`assignment_draft_builder.py`).

**TEST_VERIFIED:** `tests/test_g05a_assignment_rule_engine.py`, `tests/test_g05b_personnel_selection_engine.py`, and `tests/test_g05c_assignment_draft_service.py` are focused component evidence, not end-to-end implementation of this contract.

**KNOWN_GAP:** no source module currently joins G04 proposals to this contract or enforces active-draft/Planner-task cardinality.
