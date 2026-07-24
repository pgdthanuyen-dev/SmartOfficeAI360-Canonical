# Project overview

Updated: 2026-07-24

SmartOfficeAI360-Canonical automates office workflows and provides a controlled QLVB path for finding and downloading official documents. The QLVB integration is one bounded subsystem; it does not authorize broad crawling or unrelated automation.

The current main application integration is represented by commit `768dcebc07eddf5c704e395b7eaad8426b286c91`, with originating live-verified R49 commit `50fd0db8403026c65f06b94323b67e90164b31b4`. Evidence includes source-level live acceptance PASS and focused QLVB checks (`156 passed`). The latest full suite was not fully green; repository-wide PASS must not be claimed.

Memory is tool-agnostic Markdown/YAML so Codex, Antigravity, IDE assistants, and human operators can share the same constraints.
