# G05 task cardinality and assignment governance

Updated: 2026-07-25

## Approved business policy

**APPROVED_BUSINESS_POLICY:** one source document has exactly one active assignment draft and, after Planner KPI synchronization, exactly one draft task. G04 may have multiple proposals/action items; G05 aggregates them into one document-level recommendation. Those action items remain task content, checklist, or detail within that one draft task.

**APPROVED_BUSINESS_POLICY:** one recommendation has exactly one `lead_unit`, at most one nullable `primary_assignee`, and zero or more deduplicated `coordinating_units`. The lead unit cannot also be coordinating. Missing reliable unit/personnel data, rule conflict, low confidence, or tied candidates requires manual review with reasons; no assignee may be invented.

**APPROVED_BUSINESS_POLICY:** SmartOfficeAI360 produces proposals and drafts only. Office staff review, edit, and approve in Planner KPI. Unit/personnel data is tenant-scoped, from an approved source, and has an accountable maintainer. Uncontrolled spreadsheet imports are prohibited. Unnecessary phone, email, or sensitive personal data must not enter logs, warnings, or prompts.

## Source alignment and limits

**CODE_FACT:** G04 allows multiple proposals (`tools/qlvb_downloader/ai_proposal_models.py`, `ai_proposal_service.py`). G05A models lead/coordinating units and roles (`assignment_rule_models.py`); G05B selects personnel from tenant-scoped data (`personnel_directory_models.py`, `personnel_selection_engine.py`); G05C builds a review-pending draft (`assignment_draft_builder.py`).

**TEST_VERIFIED:** focused G05A/G05B/G05C tests exercise rules, personnel selection, and draft service behavior. They do not establish the approved one-document-one-active-draft policy end to end.

**KNOWN_GAP:** current code does not yet implement the document-level `AssignmentRecommendation` contract or prove exactly one Planner draft task per source document.
