# ADR-003: Use authenticated direct download

Status: Accepted
Date: 2026-07-24

## Context

Attachment retrieval must retain the authenticated browser session while allowing response validation before persistence.

## Decision

Download the first eligible attachment through an authenticated request bound to the live page context, without relying on a UI download. Validate HTTP status, session/login markers, and body presence before a final file exists. Write a recognized body to a same-filesystem temporary file, validate integrity on that file, then use atomic `os.replace` only after PASS. Cleanup the temporary file on validation failure or persistence error.

## Rationale

The direct download contract preserves the authenticated session and produces a response that can be checked before persistence.

## Consequences

Each response must pass HTTP, session/login, body, signature, and integrity checks. PDF and ZIP use format-specific integrity checks; OLE is accepted only under its current compound-file magic-header policy. Unknown signatures are rejected. Invalid or unexpected bodies never become final documents, reducing persisted login/error pages and interrupted-write artifacts.

## Alternatives considered

Unauthenticated requests, browser-owned downloads without validation, and accepting HTML error bodies were rejected.

## Related files/tests

`tools/qlvb_downloader/cdp_workflow.py`, `tests/test_cdp_workflow.py`, `tests/test_neoremoting_download.py`.
