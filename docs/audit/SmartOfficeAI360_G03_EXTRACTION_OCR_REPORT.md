# SmartOfficeAI360 Canonical - G03 Extraction OCR Report

Thoi gian lap bao cao: 2026-07-19T09:43:28.3111693+07:00
Repository: D:\Laptrinh\SmartOfficeAI360-Canonical
Branch: feature/g03-extraction-ocr
Base commit: 8f36dcd360b136c1cff181f902a29804d1d76485
G03 HEAD/tag target: 5ed53731daac75477ce1f251a4d4f84d3adacc76
Tag: canonical-g03-extraction-ocr-20260719

## 1. Precheck

Commands:

`	ext
git branch --show-current
git rev-parse HEAD
git status --short
git remote -v
python -m pytest tests -q
`

Result before branch creation:

- branch: main
- HEAD: 8f36dcd360b136c1cff181f902a29804d1d76485
- working tree: clean
- remote: none
- tests: 133 passed in 56.23s

Created branch:

`	ext
git switch -c feature/g03-extraction-ocr
`

## 2. Survey Map

| Function | Canonical before G03 | Source B | G03 approach |
| --- | --- | --- | --- |
| Legacy extractor | 	ools/qlvb_downloader/extractor.py extracts PDF/DOCX/TXT into manifest excerpt fields | Source B extracts text as part of AI prompt workflow | Keep legacy extractor unchanged; add attachment-domain extraction layer |
| PDF direct text | pdfminer.six in extractor.py | pypdf path in Source B | Use installed pdfminer.six, page-by-page |
| PDF scan fallback | legacy extractor returns OCR-required warning | pytesseract + PyMuPDF rendering | Add OcrAdapter; use fake OCR in tests and optional local adapter at runtime |
| OCR Vietnamese | none in Canonical dependency set | ie+eng in Source B | Optional adapter defaults to ie+eng when available |
| Multiple pages | legacy PDF loops pages but returns one text excerpt | Source B loops pages | G03 stores extracted_pages with page_number starting at 1 |
| DOCX tables | legacy only paragraphs | Source B paragraph oriented | G03 reads paragraphs and simple tables |
| Persistence | document index stores full_text excerpt/status only | Source B writes working files | G03 adds extraction_results, extracted_pages |
| Cache | none | not isolated as attachment-domain cache | unique key: attachment + source hash + extractor version + OCR version |

Source B reviewed read-only evidence:

- core/ai/vanban_ai_core.py:79-90 optional imports for pytesseract and Pillow.
- core/ai/vanban_ai_core.py:92-96 optional PyMuPDF import.
- core/ai/vanban_ai_core.py:127-150 Tesseract discovery.
- core/ai/vanban_ai_core.py:166-174 OCR language ie+eng, fallback eng.
- core/ai/vanban_ai_core.py:376-405 PDF page rendering and OCR.
- core/ai/vanban_ai_core.py:957-1001 direct text first, OCR fallback for PDF/image.

No Source B module was copied.

## 3. Implementation

New files:

- 	ools/qlvb_downloader/extraction_models.py
- 	ools/qlvb_downloader/extraction_repository.py
- 	ools/qlvb_downloader/extraction_service.py
- 	ools/qlvb_downloader/ocr_adapter.py
- 	ests/test_g03_extraction_ocr.py
- docs/architecture/G03_EXTRACTION_OCR.md
- docs/architecture/G03_OCR_PORTING_DECISIONS.md

No existing production file was modified.

## 4. Domain And Validation

- Extraction schema version: 1.0.0.
- Extractor version: g03.1.
- Models: ExtractionResult, ExtractedPage.
- Methods: DIRECT_TEXT, OCR, MIXED, UNSUPPORTED.
- Statuses: PENDING, PROCESSING, SUCCEEDED, SUCCEEDED_WITH_WARNINGS, NO_TEXT, UNSUPPORTED, FAILED.
- Page numbers must start at 1.
- Confidence must be within 0.0-1.0 when present.
- Datetimes are UTC ISO-8601 with timezone using G02 utc_now_iso().
- Error messages are truncated to 1000 characters.
- Text normalization applies NFC, LF line endings and control-char removal without spelling correction or summarization.

## 5. Format Detection And Extraction

- PDF: magic bytes %PDF-, direct text by pdfminer.six page layout.
- DOCX: ZIP magic plus [Content_Types].xml and word/document.xml.
- TXT: UTF-8/UTF-8-SIG text without null bytes.
- PNG/JPEG: magic bytes only, then OCR adapter.
- ZIP: detected but not extracted in G03.
- HTML disguised as PDF/ZIP: rejected as unsupported.
- INVALID/DOWNLOAD_FAILED/non-VALIDATED attachments: rejected before extraction.
- File hash mismatch: rejected before extraction.

## 6. OCR Adapter

OcrAdapter interface:

- is_available()
- extract_image(...)
- extract_pdf_page(...)
- ersion()

OptionalTesseractOcrAdapter imports pytesseract, Pillow and PyMuPDF only if already installed. Missing OCR does not crash direct extraction. Tests use FakeOcrAdapter.

## 7. Persistence

Migration version: g03_extraction_schema_1.

Tables:

- extraction_results
- extracted_pages

Properties:

- additive and idempotent;
- FK to documents(doc_id) and ttachments(id);
- indexes by attachment_id, document_id, status;
- cache unique key by ttachment_id, source_file_sha256, extractor_name, extractor_version, ocr_version;
- result plus pages saved atomically;
- if page insert fails, partial pages are rolled back and a failed result is recorded.

## 8. Tests

G03 tests: 	ests/test_g03_extraction_ocr.py, 26 tests.

Coverage includes:

1. PDF fake with text, multiple pages.
2. PDF fake without text, Fake OCR.
3. PNG Fake OCR.
4. JPEG Fake OCR.
5. DOCX paragraph.
6. DOCX basic table.
7. UTF-8 Vietnamese TXT.
8. Non-VALIDATED attachment rejected.
9. Hash mismatch rejected.
10. HTML disguised PDF rejected.
11. Unsupported binary format.
12. ZIP detected but not extracted.
13. Page numbering starts at 1.
14. Unicode NFC.
15. LF line ending and stable text hash.
16. Confidence validation.
17. OCR unavailable does not crash direct PDF.
18. OCR fallback only when needed.
19. Cache hit does not extract again.
20. Force extraction bypasses cache.
21. Migration first run.
22. Migration idempotent.
23. Legacy G02 DB keeps data.
24. Transaction rollback when page insert fails.
25. No partial pages when OCR unavailable/no text.
26. Schema/version constants.

Full suite after implementation:

- python -m pytest tests -q: 159 passed in 58.92s
- python -m compileall tools tests: PASS
- git diff --check: PASS
- git status --short: clean after commits

## 9. Commits And Tag

Commits:

`	ext
50f5771 feat: add document extraction domain and direct text pipeline
5a4771b feat: add OCR fallback and extraction persistence
5ed5373 test: validate G03 extraction compatibility and caching
`

Tag:

`	ext
canonical-g03-extraction-ocr-20260719 -> 5ed53731daac75477ce1f251a4d4f84d3adacc76
`

No merge into main. main remains 8f36dcd360b136c1cff181f902a29804d1d76485.

## 10. Safety Notes

- No dependency install or upgrade.
- No QLVB live access.
- No real document folder was read.
- No AI/API call.
- No Planner KPI call.
- No migration on real Data.
- No build.
- No remote created.
- No push.
- No G04 started.

Implementation note: during file creation, the patch tool initially used Source B as its implicit cwd and created five new G03 files there. They were immediately deleted before testing/commit. Final verification shows those five paths are absent in Source B, and Source B is not a Git repository.

Source A was read for status only. It retains its pre-existing dirty state; no G03 file was written there.

## 11. Residual Risks And Backlog

- Production OCR still requires approved local Tesseract/PyMuPDF/Pillow packaging and a health check.
- ZIP extraction remains intentionally out of scope.
- DOC binary conversion remains out of scope.
- User/unit mapping NULL-role uniqueness from G02 remains backlog for G06, not changed in G03.
- ExtractionService.extract_attachment(...) is service-level API; GUI wiring is not implemented in G03.

## 12. Recommendation

RECOMMENDATION: G03_READY_FOR_REVIEW
