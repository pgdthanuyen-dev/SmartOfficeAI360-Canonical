# ADR-001: Use external Edge CDP

Status: Accepted
Date: 2026-07-24

## Context

QLVB authentication and CAPTCHA state live in an operator-owned Edge session.

## Decision

Attach to the operator-owned authenticated Edge through CDP at `127.0.0.1:9223`.

## Rationale

Authentication and CAPTCHA state stay in the operator's browser. Reusing that state avoids a second unauthenticated automation page and keeps browser ownership explicit.

## Consequences

The runner must tolerate existing tabs and frames, use bounded polling, and never launch or close the browser. An operator must keep Edge running for the duration of a live check.

## Alternatives considered

Launching a fresh browser or silently falling back to a legacy launcher was rejected because it loses the authenticated session.

## Related files/tests

`tools/qlvb_downloader/cdp_workflow.py`, `tests/test_cdp_workflow.py`.
