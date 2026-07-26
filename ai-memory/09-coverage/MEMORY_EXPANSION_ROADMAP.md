# Memory expansion roadmap

Updated: 2026-07-24

This roadmap prioritizes documentation work only. A wave must be sourced from code, focused tests, approved business decisions, or new redacted live evidence. It does not authorize a production change, live QLVB run, OCR/AI call, migration, push, deployment, or data access.

## P0 — establish canonical foundations

- Sources and tests: `domain_*` modules, `tests/test_g02_domain_schema.py`, QLVB architecture/ADR/test files, and the current security validators/tests.
- Memory to create: G02 schema/state document, QLVB operator error mapping, and cross-boundary security classification.
- Acceptance criterion: every claim names an evidence label; no live, migration, or full-suite claim is added without separate evidence.
- Risk if absent: incorrect lifecycle/state assumptions can cause unsafe migrations, handling, or evidence overclaims.

1. **G02 domain schema — completed in R52.** Source/test anchored domain, migration, and compatibility documents now cover the in-repository contract; this is not production migration evidence.
2. **Storage/queue lifecycle — completed source documentation.** R53 records manifest ownership, validated-attachment readiness, compatibility, and recovery limits. Retention, backup/restore, and operator policy remain P0 gaps.
3. **QLVB change control.** Keep the existing CDP, NeoRemoting, and download documents as the only live-verified scope; add a concise operator error mapping only if it can cite source/tests.

Exit evidence: validator passes; no claim that G02 migrations have been run against live data; storage/queue retention remains the next P0 evidence task.

## P1 — document content and persistence boundaries

- Sources and tests: `extraction_*`, `ocr_adapter.py`, `storage.py`, `index_db.py`, `audit_queue.py`, `parser.py`, `downloader.py`, and their G03/storage/parser tests.
- Memory to create: extraction/OCR contract, extraction-cache transaction guide, legacy/CDP boundary map, and storage/queue/manifest lifecycle guide.
- Acceptance criterion: cache replacement/rollback, optional OCR, and compatibility limits are separately documented with no real content.
- Risk if absent: operators may treat stale cache, failed extraction, or legacy fallback as safe without evidence.

1. **G03 extraction/OCR.** Source-anchored contract now documents attachment eligibility, magic-byte format handling, cache key, attempt history, transaction/rollback behavior, optional Tesseract dependency, and no-AI boundary. Remaining P1 work is an approved dependency/recovery/retention runbook and any separately authorized concurrency scope; no real-Tesseract or live acceptance is inferred.
2. **Legacy parser/CDP boundary.** Map `parser.py` and `downloader.py` responsibilities to the bounded CDP path without presenting fallback behavior as live-proven.
3. **Storage/queue/manifest lifecycle.** Document queue states, ready-marker behavior, index rebuild, audit/quarantine, repair proposal, and preservation limits from source/tests.

Exit evidence: exact module/test references, no extracted text or real document examples, and no unsupported rollback guarantee.

## P2 — document proposal and assignment decision boundaries

- Sources and tests: `ai_proposal_*`, `assignment_rule_*`, `personnel_*`, `assignment_draft_*`, handoff client, and the G04/G05 test families.
- Memory to create: JSON/citation contract, idempotency/rollback guide, rule/personnel boundary, and draft-review/handoff lifecycle.
- Acceptance criterion: proposal-only status, tenant boundaries, idempotency conflicts, and external-call limits are explicit.
- Risk if absent: AI or deterministic recommendations could be misrepresented as approvals or assignments.

1. **G04 AI proposal.** Source-anchored boundary documentation now records strict validation, citation verification, deduplication, idempotency conflict handling, per-proposal transaction scope, fake-provider-only status, and intentional partial batches. Remaining work requires approved provider, prompt-safety, redaction/retention, review, and operational scope; no live acceptance is inferred.
2. **G05A assignment rules.** Approved cardinality/governance and a planned integration contract are documented. Next implementation scope must enforce document-level aggregation, tenant/provenance, manual review, and one active draft without claiming live approval.
3. **G05B personnel selection.** Record tenant/effective-date/availability filtering, substitution limits, privacy constraints, and proposal-only result.
4. **G05C assignment drafts.** Record immutable snapshots, review state, bounded handoff attempts, and the difference between a draft receiver and an official task.

Exit evidence: no prompts, model credentials, real directory data, raw AI responses, or personal availability reasons are added.

## P3 — operational integrations and support surfaces

- Sources and tests: `sync_client.py`, `gui_tk.py`, `doctor.py`, `diagnostics.py`, `tests/test_sync_*.py`, QC-003 tests, and launcher/package manifests.
- Memory to create: Planner integration split, GUI map, diagnostics runbook, QC-003 note, and test/release operations reference.
- Acceptance criterion: legacy upload and G05C handoff are never conflated; credentials remain external and full-suite state remains unclaimed.
- Risk if absent: support staff may use the wrong retry, configuration, or UI path.

1. **Planner KPI.** G06 now freezes a source-anchored v1 draft contract and separates legacy upload from G05C handoff. Next work must implement source-document cardinality, version semantics, credential-to-tenant binding, and focused compatibility tests without claiming remote acceptance.
2. **GUI.** Create a screen/module map and operator journey based on `gui_tk.py` and narrow UI tests; label unsupported UI flows as unknown.
3. **Doctor/diagnostics.** Document safe checks, masking/redaction expectations, report locations at a generic level, and what requires operator escalation.

Exit evidence: no endpoint, credential, tenant, or output-data values; no claim of live remote integration success.

## P4 — future integration planning only

- Sources and tests: approved future business/security materials only; no current SharePoint/OneDrive module or focused test exists.
- Memory to create: an ADR and pre-implementation contract after approval, then an integration test plan.
- Acceptance criterion: the future design states ownership, identity, retention, idempotency, error handling, and test boundaries before implementation.
- Risk if absent: a future connector could be built without an approved data/security boundary.

1. **SharePoint/OneDrive.** Before implementation, create an ADR and bounded contract for identity, scopes, ownership, data classification, retention, idempotency, error handling, and tests.
2. **Cross-system lifecycle.** Only after approved contracts exist, relate QLVB, extraction, AI proposals, review, Planner, and any future storage target through redacted state diagrams.

Exit evidence: approved business owner, explicit security review, test plan, and no inference from the absence of a module.

## Sequencing rules

- Do not promote a subsystem to `COMPLETE` without current business, architecture, code/API, focused tests, operations, security, and appropriate live evidence.
- Update `07-current/CURRENT_STATE.md` only when a verified state changes; a documentation-only wave does not create live acceptance.
- Keep `09-coverage` as a deep reference so standard onboarding remains short.
