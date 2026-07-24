# AI memory index

This directory is the vendor-neutral source of truth for project context. Keep entries factual, dated, and free of credentials or live document data.

## Required reading order

1. `01-project/PURPOSE.md`, then `01-project/PROJECT_OVERVIEW.md`
2. `02-domain/QLVB_BUSINESS_WORKFLOW.md`, then `02-domain/QLVB_DOMAIN.md`
3. `03-architecture/SYSTEM_ARCHITECTURE.md`, `MODULE_MAP.md`, `ENTRY_POINTS.md`, `CONFIGURATION_CONTRACT.md`, `ERROR_MODEL.md`, `CDP_ARCHITECTURE.md`, `NEOREMOTING_CONTRACT.md`, `DOWNLOAD_PIPELINE.md`, then `ARCHITECTURE.md`
4. `04-engineering/FORBIDDEN_ACTIONS.md`, `TEST_STRATEGY.md`, `TEST_COVERAGE_MAP.md`, `SECURITY_RULES.md`, then `ENGINEERING_RULES.md`
5. `05-operations/RUNBOOK_CDP.md`, `COMMAND_REFERENCE.md`, `TROUBLESHOOTING.md`, then `OPERATIONS.md`
6. `06-decisions/ADR-001-USE-EXTERNAL-EDGE-CDP.md` through `ADR-004-DO-NOT-CLOSE-EXTERNALLY-OWNED-BROWSER.md`
7. `07-current/CURRENT_STATE.md`
8. `08-handoffs/LATEST_HANDOFF.md`, then `08-handoffs/HANDOFF_TEMPLATE.md`

## Memory rules

- Update `CURRENT_STATE.md` whenever verified state changes.
- Record evidence and uncertainty separately.
- Never store credentials, cookies, session URLs, document identifiers, document text, filenames, or personal data.
- The short named entries above are canonical onboarding aliases; the longer overview files retain consolidated detail without duplicating history.
- ADR history is append-only: supersede an old decision with a new ADR instead of deleting it.
