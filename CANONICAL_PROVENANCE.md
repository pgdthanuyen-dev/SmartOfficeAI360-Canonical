# SmartOfficeAI360 Canonical Provenance

- Project: SmartOfficeAI360 Canonical
- Canonical created: 2026-07-19
- Canonical source: Source A
- Source A path: D:\Laptrinh\SmartOfficeAI360
- Source A reference commit: 19ff09329fae5c0ce8b800688a3fc36122484082
- Baseline Canonical commit: 67efa8426833e54c1dc6bcf097882ff379ddae97
- Baseline tag: canonical-baseline-a-pre-g01-20260718
- EOL policy commit: $eol
- G01 portable patch: D:\Laptrinh\SmartOfficeAI360_G01_DOWNLOADER_HARDENING_PORTABLE.patch
- G01 commit: $g01
- G01 tag: canonical-g01-downloader-hardened-20260719

## Line Ending Policy

Canonical uses .gitattributes to keep Python, documentation and configuration text files on LF, while Windows command scripts remain CRLF. G01 files were normalized to LF in Canonical.

Source A has mixed LF/CRLF line endings in the G01 files, so raw SHA-256 is not used as the acceptance criterion for G01. The accepted criterion is normalized SHA-256 after converting CRLF/CR to LF plus AST equivalence for the five Python files.

## G01 Validation

The following five G01 files matched Source A by normalized SHA-256 and AST after line-ending normalization:

- 	ools/qlvb_downloader/models.py
- 	ools/qlvb_downloader/storage.py
- 	ools/qlvb_downloader/downloader.py
- 	ests/test_javascript_download_adapter.py
- 	ests/test_storage_queue.py

Canonical G01 validation results:

- Verify repo tests: 111 passed
- Canonical tests: 111 passed
- Compileall: PASS
- git diff --check: PASS
- Canonical G01 file EOL: LF

## Source B Boundary

Source B is reference-only:

D:\Laptrinh\SmartOfficeAI360_V18_9_5_FINAL_FULL_PILOT_TEST

No Source B code was imported wholesale. Future study may review NeoRemoting discovery, download.jsp adapter ideas, OCR, prompt/task schema, GUI review/routing, and M365/Planner field model through separate interface and test design.

## Data and Secret Boundary

Data, browser profiles, sessions, cookies, tokens, private configuration and real document dossiers must not be committed to Canonical Git. All future development should happen in this Canonical repository only.