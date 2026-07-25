# Command reference

Updated: 2026-07-24

Commands are **CODE_FACT** where they map to `runner.py`; replace placeholders locally and never place authentication values on a command line.

## Memory checks

```text
python scripts/validate_ai_memory.py
python -m pytest tests/test_ai_memory.py -q
git diff --check
```

## G03 focused extraction checks

```text
python -m pytest tests/test_g03_extraction_ocr.py -q -p no:cacheprovider
```

- **TEST_VERIFIED**: this is the focused G03 extraction/cache suite. It uses generated fixtures and a fake OCR adapter.
- It is not a command to run live OCR and does not establish real-Tesseract or production acceptance.

## CDP smoke entry

```text
python -m tools.qlvb_downloader.runner --config <config-file> --cdp-three-category-smoke --cdp-output-dir <output-directory>
```

- **CODE_FACT**: the smoke entry attaches to the externally running CDP endpoint configured in source and returns nonzero when `LIVE_ACCEPTANCE` is not `PASS`.
- **BUSINESS_CONFIRMED**: run this only with explicit operator authorization and an already authenticated external Edge session.
- **CODE_FACT**: `--print-config` prints normalized configuration; review output carefully because it includes operational paths and should remain outside shared memory.
