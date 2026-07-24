# SmartOfficeAI360 project context

This repository is the canonical SmartOfficeAI360 project: office-workflow automation with a QLVB document retrieval and download path. The durable project memory is in [`ai-memory/INDEX.md`](ai-memory/INDEX.md); read it for domain, architecture, engineering, operations, decisions, current state, and handoff details.

The proven QLVB flow uses an already authenticated Edge instance through CDP at `127.0.0.1:9223`. It keeps browser ownership outside the automation process and never launches or closes that browser. The default categories are Văn bản vào sổ, Đã chuyển xử lý, and Đã xử lý; Chờ xử lý is not part of the default workflow.

The workflow scopes exact normalized menu labels, guards against mojibake, waits within bounded limits after navigation, validates the visible document grid, obtains a document identifier only from the selected table row, calls the legacy NeoRemoting contract, parses safely without dynamic evaluation, and downloads through an authenticated direct request with HTTP, signature, and integrity checks.

Security is conservative: logs are redacted, credentials and session-bearing URLs are never recorded, and user document data is not stored in project memory. Stable commit `ea39c35a27b399fe5c049b3d4545db2322142ac9` contains the verified CDP/NeoRemoting integration. Source-level live acceptance passed and focused tests passed (`146 passed`); the latest full-suite run was not entirely green, so do not generalize that result to the whole repository.
