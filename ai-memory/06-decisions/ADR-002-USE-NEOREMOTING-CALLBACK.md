# ADR-002: Use the legacy NeoRemoting callback

Status: Accepted
Date: 2026-07-24

## Context

The QLVB application exposes validated document metadata through its established callback surface.

## Decision

Use the validated legacy `getRSet.call` callback contract after selecting a document row.

## Rationale

The QLVB application exposes its document metadata through this established contract. Keeping the call shape stable avoids an unverified API path.

## Consequences

Only row-scoped identifiers may be passed. Response shape is captured and normalized safely; failures are fatal for the bounded item rather than silently accepted.

## Alternatives considered

An unverified replacement API or broad page scraping was rejected.

## Related files/tests

`tools/qlvb_downloader/neoremoting.py`, `tests/test_neoremoting_download.py`.
