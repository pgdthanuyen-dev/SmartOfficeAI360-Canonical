# Subsystem catalog

Updated: 2026-07-24

Evidence labels: `CODE_FACT` names repository modules inspected for R51. `TEST_VERIFIED` names an existing test family. `HISTORICAL` and `LIVE_VERIFIED` are limited to evidence already recorded in project memory. An entry point is an observed module API or executable path, not a guarantee of operator readiness.

## QLVB retrieval path

### QLVB CDP navigation — SUBSTANTIAL

- Purpose: attach to an authenticated, externally owned Edge session and navigate the bounded incoming categories.
- Entry point: `python -m tools.qlvb_downloader.runner --cdp-three-category-smoke`.
- Main modules: `cdp_workflow.py`, `runner.py`, `downloader.py`, `config.py`.
- Data flow: existing page/frame → exact sidebar category → validated visible document grid → selected row.
- Dependencies: Playwright CDP and QLVB configuration; no browser launcher in this path.
- Primary test: `tests/test_cdp_workflow.py` and CDP/navigation cases in `tests/test_neoremoting_download.py`.
- Current state: **LIVE_VERIFIED** only for the bounded R49 source smoke; see `07-current/CURRENT_STATE.md`.
- Related memory: `CDP_ARCHITECTURE.md`, `ENTRY_POINTS.md`, `RUNBOOK_CDP.md`, ADR-001 and ADR-004.

### NeoRemoting attachment discovery — SUBSTANTIAL

- Purpose: obtain attachment metadata from a validated row through the legacy callback contract.
- Entry point: `NeoRemotingAttachmentDiscoveryAdapter` in `neoremoting.py`.
- Main modules: `neoremoting.py`, `models.py`, `cdp_workflow.py`.
- Data flow: row-scoped identifier → suitable QLVB frame → `getRSet.call` callback → bounded normalized attachment records.
- Dependencies: an already supplied QLVB page/frame; standard-library parsing helpers.
- Primary test: `tests/test_neoremoting_download.py`.
- Current state: code and focused evidence are present; no separate live contract claim is recorded.
- Related memory: `NEOREMOTING_CONTRACT.md`, `ERROR_MODEL.md`, ADR-002.

### Authenticated download persistence — SUBSTANTIAL

- Purpose: retrieve one eligible attachment through the page-context request and persist only validated bodies.
- Entry point: `download_one` in `cdp_workflow.py`.
- Main modules: `cdp_workflow.py`, `neoremoting.py`.
- Data flow: authenticated request → HTTP/login/body/signature checks → same-directory temporary file → integrity check → atomic replacement.
- Dependencies: Playwright request context, filesystem, PDF/ZIP/OLE validation policy.
- Primary test: atomic and rejection cases in `tests/test_cdp_workflow.py`.
- Current state: **LIVE_VERIFIED** R49 recorded three integrity-pass downloads; it is not a retention or repository-wide acceptance claim.
- Related memory: `DOWNLOAD_PIPELINE.md`, `ERROR_MODEL.md`, `TEST_COVERAGE_MAP.md`, ADR-003.

### Legacy parser and downloader — PARTIAL

- Purpose: normalize legacy QLVB rows, validate records, and support the non-CDP downloader path.
- Entry point: `QLVBDownloader` in `downloader.py`; parser helpers in `parser.py`.
- Main modules: `downloader.py`, `parser.py`, `models.py`, `report.py`.
- Data flow: page rows/actions → canonical record and attachment metadata → storage/reporting or CDP delegation.
- Dependencies: Playwright legacy flow, configuration, storage, parser validators.
- Primary test: `tests/test_parser_validation.py`, `tests/test_navigation_menu.py`, `tests/test_javascript_download_adapter.py`.
- Current state: source/test evidence exists; the R49 live evidence applies only to its CDP source-level scope.
- Related memory: `MODULE_MAP.md`, `TEST_COVERAGE_MAP.md`; expansion target in the roadmap.

## Domain, extraction, and proposal path

### G02 domain schema — PARTIAL

- Purpose: represent documents, attachments, action items, citations, reviews, sync events, and user/unit mappings in additive SQLite schema.
- Entry point: `init_domain_schema` and `DomainRepository` in `domain_repository.py`.
- Main modules: `domain_models.py`, `domain_validation.py`, `domain_repository.py`.
- Data flow: validated document/attachment → domain rows → later extraction, proposal, review, and sync boundaries.
- Dependencies: SQLite and existing document/index compatibility.
- Primary test: `tests/test_g02_domain_schema.py`.
- Current state: **CODE_FACT** and **TEST_VERIFIED**; source-anchored domain/lifecycle and migration compatibility memory completed in R52. No runtime migration or business-data live claim.
- Related memory: `DOMAIN_SCHEMA_AND_LIFECYCLE.md`, `SCHEMA_MIGRATION_AND_COMPATIBILITY.md`, and the repository design in `docs/architecture/G02_DOMAIN_SCHEMA.md`.

### G03 extraction and OCR — PARTIAL

- Purpose: extract attachment content by direct text or optional local OCR and cache bounded results.
- Entry point: `ExtractionService.extract_attachment` in `extraction_service.py`.
- Main modules: `extraction_models.py`, `extraction_repository.py`, `extraction_service.py`, `ocr_adapter.py`.
- Data flow: validated attachment → magic-byte classification → direct extraction/OCR fallback → normalized pages/results → SQLite cache and attempt history.
- Dependencies: `pdfminer.six`, `python-docx`, optional Tesseract adapter, SQLite.
- Primary test: `tests/test_g03_extraction_ocr.py`.
- Current state: code/test boundary exists; no live OCR, installation, or provider claim.
- Related memory: roadmap target; detailed repository design is `docs/architecture/G03_EXTRACTION_OCR.md`.

### G03 extraction cache and transaction safety — PARTIAL

- Purpose: retain successful extraction results by a bounded cache key and keep failed refreshes from replacing prior success.
- Entry point: repository calls used by `ExtractionService.extract_attachment`.
- Main modules: `extraction_repository.py`, `extraction_service.py`, `extraction_models.py`.
- Data flow: attachment hash/version key → cache lookup or replacement transaction → result/pages plus append-only attempt.
- Dependencies: G02 attachment data and SQLite transactions.
- Primary test: cache, force-refresh, and rollback cases in `tests/test_g03_extraction_ocr.py`.
- Current state: code/test evidence; no operational cache-recovery or live claim.
- Related memory: P1 roadmap; G03 repository design.

### G04 AI proposal boundary — PARTIAL

- Purpose: validate, cite, deduplicate, and persist proposal-only action items from JSON responses.
- Entry point: `ingest_ai_proposal_response` and `AiProposalService` in `ai_proposal_service.py`.
- Main modules: `ai_proposal_models.py`, `ai_proposal_validation.py`, `ai_proposal_repository.py`, `ai_proposal_service.py`.
- Data flow: JSON response → strict validation → extracted-page citation verification → fingerprint/dedupe → transactional proposed action items.
- Dependencies: G02/G03 SQLite data; fake provider protocol for tests.
- Primary test: `tests/test_g04_ai_proposal_boundary.py`.
- Current state: no production AI provider, prompt execution, or live AI claim.
- Related memory: roadmap target; detailed repository design is `docs/architecture/G04_AI_PROPOSAL_BOUNDARY.md`.

### G04 JSON contract and citation validation — PARTIAL

- Purpose: reject malformed proposal payloads and verify citations against extracted pages before persistence.
- Entry point: `parse_ai_proposal_json` and `validate_ai_proposal_envelope`.
- Main modules: `ai_proposal_validation.py`, `ai_proposal_service.py`, `ai_proposal_models.py`.
- Data flow: JSON object → strict schema limits → citation/page/excerpt verification → accepted proposal or bounded error.
- Dependencies: G03 extracted pages and G02 document/attachment rows.
- Primary test: schema and citation cases in `tests/test_g04_ai_proposal_boundary.py`.
- Current state: no production provider or live proposal claim.
- Related memory: P2 roadmap; G04 repository design.

### G04 deduplication and idempotency — PARTIAL

- Purpose: distinguish exact/possible duplicate proposals and protect idempotency keys from conflicting reuse.
- Entry point: `proposal_fingerprint` and `AiProposalService` ingestion path.
- Main modules: `ai_proposal_models.py`, `ai_proposal_repository.py`, `ai_proposal_service.py`.
- Data flow: normalized proposal → fingerprint/idempotency comparison → existing batch, warning, new transaction, or conflict.
- Dependencies: SQLite uniqueness constraints and G04 validation.
- Primary test: duplicate, key-reuse, race, and rollback cases in `tests/test_g04_ai_proposal_boundary.py`.
- Current state: source/test evidence only; no production retry or live claim.
- Related memory: P2 roadmap; G04 repository design.

## Assignment and external integration path

### G05A assignment rule engine — PARTIAL

- Purpose: deterministically evaluate normalized document signals against assignment rules.
- Entry point: `evaluate_assignment_rules` and `AssignmentRuleEngine` in `assignment_rule_engine.py`.
- Main modules: `assignment_rule_models.py`, `assignment_rule_validation.py`, `assignment_rule_repository.py`, `assignment_rule_engine.py`.
- Data flow: document signals + active rules → ranked candidates → unit/role recommendation and optional append-only history.
- Dependencies: G02-style document identifiers, SQLite rule repository.
- Primary test: `tests/test_g05a_assignment_rule_engine.py` and schema tests.
- Current state: library boundary only; no person selection or external call.
- Related memory: roadmap target; repository design is `docs/architecture/G05A_ASSIGNMENT_RULE_ENGINE.md`.

### G05B personnel selection — PARTIAL

- Purpose: produce deterministic, reviewable personnel recommendations from G05A context and tenant-scoped directory records.
- Entry point: `PersonnelSelectionEngine` in `personnel_selection_engine.py`.
- Main modules: `personnel_directory_models.py`, `personnel_directory_validation.py`, `personnel_directory_repository.py`, `personnel_selection_engine.py`.
- Data flow: rule recommendation + directory → effective/available candidate filtering → ranked personnel proposal → optional history.
- Dependencies: G05A models and SQLite directory repository.
- Primary test: `tests/test_g05b_personnel_selection_engine.py` and directory-schema tests.
- Current state: proposal-only; no Planner identity mapping or live personnel data claim.
- Related memory: roadmap target; repository design is `docs/architecture/G05B_PERSONNEL_SELECTION_ENGINE.md`.

### G05C assignment drafts and Planner draft handoff — PARTIAL

- Purpose: create reviewable assignment drafts and send a tenant-scoped immutable draft to the Planner receiver when configured.
- Entry point: `AssignmentDraftService.send_draft_to_planner` and `PlannerDraftHandoffClient.send`.
- Main modules: `assignment_draft_*.py`, `planner_draft_handoff_client.py`.
- Data flow: G05A/G05B/G04 context → draft candidate/snapshot/review → receiver payload → one handoff attempt and persisted bounded result.
- Dependencies: SQLite and environment-only handoff configuration; standard-library HTTP client.
- Primary test: `tests/test_g05c_assignment_draft_*.py`, `tests/test_planner_draft_handoff_client.py`.
- Current state: code/test contract exists; no official Planner task, callback, or live handoff claim.
- Related memory: roadmap target; repository design is `docs/architecture/G05C_PLANNER_DRAFT_HANDOFF_B7.md`.

### Planner KPI legacy sync — PARTIAL

- Purpose: upload queue packages to the existing Planner KPI ingest endpoint and record bounded manifest status.
- Entry point: `sync_upload` and `sync_batch` in `sync_client.py`.
- Main modules: `sync_client.py`, `config.py`, `storage.py`, `gui_tk.py`.
- Data flow: ready queue manifest/files → authenticated HTTP upload/polling → redacted manifest sync status.
- Dependencies: `requests`, configured Planner endpoint and credential outside memory.
- Primary test: `tests/test_sync_client.py`, `tests/test_sync_retry.py`, `tests/test_sync_auth_failed.py`.
- Current state: implementation differs from G05C draft handoff; no live remote success claimed.
- Related memory: roadmap target; this distinction must remain explicit.

### SharePoint/OneDrive — PLANNED_ONLY

- Purpose: future external-content integration is mentioned only as excluded scope in G02/G03/G04/G05 designs.
- Entry point: none found in the bounded `tools/`, `tests/`, `scripts/`, and `docs/` inventory.
- Main modules: none found.
- Data flow/dependencies: not specified by an approved implementation contract.
- Primary test: none found.
- Current state: **PLANNED**; do not describe it as implemented.
- Related memory: coverage matrix and P4 roadmap only.

## Local operations and persistence

### Storage, queue, manifest, index, and audit — PARTIAL

- Purpose: persist validated records/files, queue ready work, index data, and inspect/repair queue state.
- Entry point: `StorageManager`, `open_db`, `run_audit`, and `repair_queue_mapping.main`.
- Main modules: `storage.py`, `index_db.py`, `audit_queue.py`, `repair_queue_mapping.py`.
- Data flow: document record/files → queue manifest/ready marker → SQLite index → audit, quarantine, or repair proposal.
- Dependencies: filesystem and SQLite; legacy extractor enriches manifests.
- Primary test: `tests/test_storage_queue.py`, `tests/test_audit_validation.py`, `tests/test_index_db.py`.
- Current state: source/test evidence, but no consolidated operations memory or live audit claim.
- Related memory: R49 download persistence docs cover only a narrow upstream stage.

### Manifest and document lifecycle — PARTIAL

- Purpose: preserve record status and synchronization metadata across queue, index, and integration boundaries.
- Entry point: `StorageManager.get_queue_item_files`, `open_db`, and sync helpers.
- Main modules: `storage.py`, `index_db.py`, `sync_client.py`, `audit_queue.py`.
- Data flow: validated record → manifest/ready queue → index and sync status → audit/repair view.
- Dependencies: filesystem, SQLite, and legacy manifest compatibility.
- Primary test: `tests/test_storage_queue.py`, `tests/test_index_db.py`, and G02 compatibility cases.
- Current state: implementation exists; retention/recovery operations are not yet memory-documented.
- Related memory: P1 roadmap.

### Desktop GUI — MINIMAL

- Purpose: provide Tk/CustomTkinter configuration and operational screens.
- Entry point: `gui_tk.main` and launcher scripts.
- Main modules: `gui_tk.py`, `assignment_draft_ui.py`, `assignment_draft_ui_state.py`.
- Data flow: configuration and local services → GUI status/actions; selected draft can invoke service boundary.
- Dependencies: CustomTkinter, local configuration, service modules.
- Primary test: UI-focused G05C tests; broad GUI acceptance is not recorded.
- Current state: implementation exists; no memory-level screen map or live UI claim.
- Related memory: roadmap target.

### Doctor and diagnostics — MINIMAL

- Purpose: inspect configuration/environment and produce support-oriented checks/reports.
- Entry point: `doctor.main`, `diagnostics.main`, and launcher scripts.
- Main modules: `doctor.py`, `diagnostics.py`, `tools/launchers/*`.
- Data flow: configuration/environment → masked checks → local report/support package.
- Dependencies: filesystem, optional installed modules, configuration parsing.
- Primary test: no dedicated doctor test file found in the bounded test inventory.
- Current state: source exists; supported remediation and generated-report contract need documentation.
- Related memory: roadmap target.

### QC-003 downloader/configuration — PARTIAL

- Purpose: validate selected downloader route and metadata mapping boundaries used by the legacy workflow.
- Entry point: downloader configuration and fixed-route validation helpers.
- Main modules: `downloader.py`, `config.py`, `models.py`.
- Data flow: configured route/category → route validation → scoped downloader behavior.
- Dependencies: QLVB configuration and legacy downloader models.
- Primary test: `tests/test_qc003_matrix.py`, `tests/test_fix_qc_004.py`.
- Current state: source/test evidence; no standalone memory or live claim.
- Related memory: P3 roadmap.

### Security and privacy controls — PARTIAL

- Purpose: keep secret/session material and untrusted payloads out of logs, memory, and bounded persistence paths.
- Entry point: redaction helpers and validators across QLVB, proposal, and personnel modules.
- Main modules: `models.py`, `neoremoting.py`, `ai_proposal_validation.py`, `personnel_directory_validation.py`.
- Data flow: untrusted values → allowlist/bounds/redaction → safe record, error, or rejection.
- Dependencies: standard-library parsing/regular expressions and per-boundary models.
- Primary test: redaction/safety cases in QLVB, G04, and G05 test families.
- Current state: source-anchored trust/data-boundary memory completed in R52; cross-system retention and incident procedures remain gaps.
- Related memory: `SECURITY_RULES.md`, `TRUST_BOUNDARIES_AND_DATA_HANDLING.md`, ADRs, P0 roadmap.

### Test and release operations — MINIMAL

- Purpose: provide focused regression evidence and local packaging/launcher support.
- Entry point: `pytest` test modules, `requirements.txt`, launcher scripts, and `SmartOfficeAI360.spec`.
- Main modules: `tests/`, `tools/launchers/`, package/packaging manifests.
- Data flow: source change → focused test/compile/validation evidence → optional packaging route.
- Dependencies: pinned Python environment and declared third-party libraries.
- Primary test: subsystem-specific tests; no current full-suite green baseline.
- Current state: focused QLVB result is historical; release process memory is incomplete.
- Related memory: `TEST_STRATEGY.md`, `COMMAND_REFERENCE.md`, P3 roadmap.
