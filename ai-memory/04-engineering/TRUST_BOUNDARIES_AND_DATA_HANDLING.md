# Trust boundaries and data handling

Updated: 2026-07-24

`CODE_FACT` names source boundaries; `TEST_VERIFIED` names focused evidence; `PLANNED` has no implementation. This is neither a penetration test nor a production security assessment.

| Boundary | Input trust | Validation | Persistence | Sensitive data | Known controls | Known gaps | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| QLVB session → automation | external runtime state | host/page/menu/table/row checks | redacted summary | session state/URL | external CDP ownership, query masking | session lifecycle runbook | CODE_FACT; TEST_VERIFIED |
| Attachment → local download | HTTP body/name untrusted | HTTP/login/body/signature/integrity/name checks | temp then atomic final path | body/name/URL | cleanup, collision protection, invalid rejection | retention policy | CODE_FACT; TEST_VERIFIED |
| Raw attachment → extraction/OCR | file/type untrusted | validation status, hash, magic bytes, bounds | G03 result/pages/attempts | text/file metadata | optional local OCR, unsupported rejection | setup/production data handling | CODE_FACT; TEST_VERIFIED |
| Extracted text → AI proposal | untrusted proposal input | strict JSON, citation/page/excerpt checks | batches/items/warnings | text/proposal metadata | no production provider; raw body not stored | no prompt-injection control, outbound-redaction, retention, or access-control policy | CODE_FACT; TEST_VERIFIED |
| G05 recommendation → draft task | policy and tenant-scoped rule/directory inputs | planned cardinality, source/provenance, and manual-review rules | planned recommendation then draft | unit/personnel references | proposal-only boundary | approved source stewardship and end-to-end enforcement not implemented | APPROVED_BUSINESS_POLICY; PLANNED_CONTRACT |
| AI output → domain | untrusted output | schema, ownership, ranges, dedupe/idempotency | proposal/domain SQLite rows | proposal/citations | JSON parsing, no dynamic evaluation | no G02 aggregate transaction | CODE_FACT; TEST_VERIFIED |
| Domain → queue/storage | incomplete legacy/domain record | entity and validated-attachment checks | files/manifest/ready/index | metadata/files | missing valid attachment blocks ready queue | direct manifest/cross-store rollback | CODE_FACT; TEST_VERIFIED |
| SmartOffice → Planner | config/remote response untrusted | bounded receiver payload, safe-link, and idempotency checks | handoff attempts and Planner draft receipt | credentials/headers/remote ID/source metadata | values stay outside memory; no binary transfer | document cardinality, credential-to-tenant binding, rotation/replay, and live success are gaps | CODE_FACT; TEST_VERIFIED; PLANNED_CONTRACT |
| SmartOffice → SharePoint | PLANNED | none | none | identity/content/retention | none | all behavior needs ADR | PLANNED |
| Configuration → runtime | operational input untrusted | loader and boundary validation | local config outside memory | endpoint/credential | validator rejects assigned secrets/paths | governance/rotation | CODE_FACT; TEST_VERIFIED |
| Logs → operator | diagnostic context untrusted | bounded/redacted where implemented | local reports | URL/id/error context | masking and memory scanner | no whole-system logging audit | CODE_FACT; TEST_VERIFIED |

## Control review

| Area | Recorded result | Evidence |
| --- | --- | --- |
| Path/output containment | controlled CDP download resolves sanitized targets; queue copies source file names | CODE_FACT; TEST_VERIFIED |
| Deserialization and dynamic evaluation | NeoRemoting uses bounded `ast.literal_eval`; G04 parses JSON; verified adapter contract excludes `eval` | CODE_FACT; TEST_VERIFIED |
| Credentials and sessions | memory forbids assigned secrets/session URLs; QLVB query diagnostics are masked | CODE_FACT; TEST_VERIFIED |
| Schema/AI/queue validation | G02 validators precede repository saves; G04 validates before proposal persistence; ready queue requires validated attachments | CODE_FACT; TEST_VERIFIED |
| Rollback boundary | G03/G04 have focused transaction tests; G02/legacy queue aggregate rollback is not established | TEST_VERIFIED; known gap |

Known gaps: no approved retention/classification policy for stored content, no whole-system logging audit, no production migration/rollback evidence, and no atomic aggregate guarantee across G02 plus queue/index persistence. These are documentation/security gaps, not confirmed exploitable vulnerabilities.

Never put credentials, cookies, session URLs, raw document text, identifiers, filenames, personal data, raw AI output, or local machine paths in memory. SharePoint/OneDrive remains planned; do not infer production migration, remote integration, or full-suite success.
