# ADR-003: Use authenticated direct download

Status: Accepted
Date: 2026-07-24

## Context

Attachment retrieval must retain the authenticated browser session while allowing response validation before persistence.

## Decision

Download the first eligible attachment through an authenticated request bound to the live page context.

## Rationale

The direct download contract preserves the authenticated session and produces a response that can be checked before persistence.

## Consequences

Each response must pass HTTP, login-page/signature, and integrity checks. Invalid or unexpected bodies are never saved as documents.

## Alternatives considered

Unauthenticated requests, browser-owned downloads without validation, and accepting HTML error bodies were rejected.

## Related files/tests

`tools/qlvb_downloader/downloader.py`, `tests/test_neoremoting_download.py`.
