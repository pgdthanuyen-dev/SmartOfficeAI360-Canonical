# Engineering rules

Updated: 2026-07-24

- Keep changes narrow and preserve unrelated dirty files.
- Use the pinned project interpreter when running verification.
- Prefer explicit paths and focused tests; avoid broad cleanup.
- Normalize labels before exact comparison and reject mojibake before navigation.
- Treat page, frame, menu, table, response, and attachment states as untrusted input.
- Do not use dynamic code evaluation in parsing or validation.
- Redact logs: no credentials, cookies, session-bearing query strings, document contents, identifiers, filenames, or personal data.
- A focused PASS is evidence only for the focused scope. The latest full suite is not a green baseline.
- Preserve backward-compatible model/config contracts when extending download behavior.
