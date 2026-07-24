# Operations

Updated: 2026-07-24

Before a live run, an operator must authenticate Edge manually and confirm the QLVB page is present. The runner may attach over CDP but must not launch or close the externally owned browser. The default endpoint is `127.0.0.1:9223`.

Operational bounds are explicit: process the three configured categories in order, do not include Chờ xử lý by default, select only validated rows, and stop at the configured document/file limits. Fail closed on login pages, malformed responses, invalid signatures, integrity failures, ambiguous menus, or uncertain ownership.

Reports contain statuses and redacted diagnostics only. Never persist live session material or user document data in memory artifacts.
