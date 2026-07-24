# ADR-004: Do not close the externally owned browser

Status: Accepted
Date: 2026-07-24

## Context

The browser belongs to the operator and carries the authenticated session used by CDP.

## Decision

The CDP workflow never calls browser, context, or page close operations.

## Rationale

Edge belongs to the operator and carries the authenticated session. Closing it would be an unsafe side effect outside the runner's scope.

## Consequences

The process disconnects naturally when its Python code ends. Cleanup is limited to runner-owned data and redacted diagnostics.

## Alternatives considered

Closing or recreating browser resources was rejected because it creates unsafe side effects and can destroy authentication state.

## Related files/tests

`tools/qlvb_downloader/cdp_workflow.py`, `tests/test_cdp_workflow.py`.
