# G03 extraction, OCR, and cache safety

Updated: 2026-07-25

## Evidence labels

- **CODE_FACT** is anchored to `extraction_service.py`, `extraction_repository.py`, `extraction_models.py`, and `ocr_adapter.py`.
- **TEST_VERIFIED** is anchored to `tests/test_g03_extraction_ocr.py`; the focused run recorded **33 passed**.
- **NOT_LIVE_VERIFIED** means source and focused tests do not establish an operator-run OCR or production acceptance result.
- **KNOWN_GAP** identifies a boundary not established by the source or focused tests.

## Entry and accepted inputs

**CODE_FACT:** `ExtractionService.extract_attachment` is the G03 entry point. It requires an existing attachment associated with the supplied document, a validated attachment state, an existing local file, and a matching SHA-256 when the attachment has one. Magic-byte detection accepts PDF, DOCX, UTF-8 text, PNG, and JPEG. HTML payloads, ZIP containers, and unsupported binaries receive bounded unsupported outcomes rather than extraction.

**CODE_FACT:** PDF pages are read with `pdfminer.six`; direct page text is normalized. DOCX paragraphs and table rows are read through `python-docx`. PNG and JPEG use the configured OCR adapter. `normalize_extracted_text` is used before page hashes and persistence. Each extracted page has a one-based page number, normalized text hash, character count, method, and optional confidence or dimensions.

## Optional OCR and PDF fallback

**CODE_FACT:** `OptionalTesseractOcrAdapter` uses locally available Tesseract with `pytesseract` and Pillow. PDF-page OCR additionally requires PyMuPDF. A PDF page uses OCR when direct normalized text is below the configured threshold or when `force_ocr` is requested; otherwise direct text remains available even if OCR is unavailable.

**TEST_VERIFIED:** fake adapters cover blank-PDF fallback, PNG/JPEG OCR, unavailable OCR behavior, and the condition that fallback only runs when needed.

**NOT_LIVE_VERIFIED:** the focused tests use `FakeOcrAdapter`. They do not prove a local Tesseract installation, language pack, real document quality, or live acceptance.

## Result, page, and attempt persistence

**CODE_FACT:** G03 stores a result in `extraction_results`, ordered page records in `extracted_pages`, and audit-style execution records in `extraction_attempts`. The schema includes foreign keys and a unique cache identity:

`attachment_id + source_file_sha256 + extractor_name + extractor_version + ocr_version`.

**CODE_FACT:** a non-forced call returns a cached successful, successful-with-warnings, or no-text result for that identity. `force=True` bypasses that lookup. A successful write replaces the matching result, writes its pages, and records a successful attempt inside one SQLite transaction. The repository rolls back when any step fails.

**TEST_VERIFIED:** cache hit, forced replacement, failed forced replacement preserving the prior cache, failed-first-run attempt recording, migration idempotency, page insertion rollback, and no partial-page cache after failure are covered by the focused G03 suite.

## Failure and repeat-execution limits

**CODE_FACT:** extraction exceptions are returned as a failed result with `EXTRACTION_FAILED`; expected preconditions have explicit bounded codes including attachment-not-found, document/attachment mismatch, validation failure, file-not-found, and hash mismatch. Failed extraction creates an attempt record rather than a successful result/page cache. Error text is truncated before attempt persistence.

**CODE_FACT:** the cache identity and database uniqueness constraint provide repeat-execution identity for one attachment content and extractor/OCR versions. This is not a general distributed idempotency protocol.

**KNOWN_GAP:** source and focused tests do not establish a concurrency guarantee for simultaneous writers using the same cache identity.

**KNOWN_GAP:** source/test evidence does not establish a complete retention, redaction, or access-control policy for persisted extracted text and diagnostic material. Failure to record an attempt is downgraded to a warning, so audit completeness is not guaranteed.

## Evidence boundary

This document does not claim a full-suite pass, live OCR acceptance, production cache recovery, or a production database migration. It stores no source document content, identifiers, file names, credentials, or local paths.
