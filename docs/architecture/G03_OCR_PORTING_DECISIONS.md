# G03 OCR Porting Decisions

## Source B Review

Reviewed read-only source:

- `D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST\core\ai\vanban_ai_core.py`

Observed ideas:

- Optional OCR imports: `pytesseract`, Pillow and PyMuPDF.
- Tesseract discovery through common executable locations and `shutil.which`.
- Vietnamese OCR language preference: `vie+eng`.
- PDF scan fallback after direct text extraction returns too little text.
- Render PDF pages to images before OCR.
- Return direct text when OCR is unavailable or fails and some direct text exists.

## What Was Reimplemented

No Source B module was copied. G03 reimplements the ideas in Canonical style:

- `OcrAdapter` interface with `is_available()`, `extract_image()`, `extract_pdf_page()`, and `version()`.
- `OptionalTesseractOcrAdapter` as a local optional implementation.
- `ExtractionService` decides when OCR is needed.
- Tests use `FakeOcrAdapter`, so CI does not require Tesseract, PyMuPDF, Pillow or external OCR data.

## Dependency Decision

No dependency was installed or added.

Used existing Canonical dependencies:

- `pdfminer.six` for PDF direct text
- `python-docx` for DOCX paragraphs and simple tables
- `reportlab` only in tests to generate fake PDFs

Optional runtime dependencies are imported only if already installed:

- `pytesseract`
- `PIL`
- `fitz`/PyMuPDF

If those optional pieces are missing, direct extraction still works and OCR-specific paths return structured warnings or `NO_TEXT`.

## Why Not Copy Source B

Source B couples OCR with the AI prompt workflow and GUI-oriented processing. G03 needs an attachment-domain layer that is safe before AI/review/sync exists. Copying Source B would also pull prompt handling, folder conventions and live workflow assumptions outside G03 scope.

## Production OCR Enablement Criteria

Before production OCR is enabled by default:

- Tesseract executable path must be configured or reliably detected.
- Vietnamese language pack `vie` must be present.
- PyMuPDF/Pillow/Tesseract versions must be pinned in release packaging.
- A health check must expose OCR availability and language status.
- OCR timeouts and page limits must be enforced for large scanned PDFs.
- Real-data pilot must run in dry-run mode before any AI or Planner KPI stage consumes OCR text.

## Backlog

- Harden `user_unit_mappings` NULL-role uniqueness in G06, as noted in the G02 merge report.
- Add DOC binary conversion only if a safe local converter is approved.
- Add ZIP member extraction in a later stage with path traversal protection and size limits.

## Cache Safety R2

The cache-safety repair is Canonical-specific design work, not ported from Source B. Source B was useful for OCR fallback ideas, but it did not provide the attachment-domain split between cacheable extraction results and attempt history.

Canonical now stores successful extraction output in `extraction_results` plus `extracted_pages`, while every run can be audited in `extraction_attempts`. A failed forced refresh records a FAILED attempt without deleting the previous successful result. This keeps downstream AI/review stages from losing the last known-good text when a retry fails midway.
