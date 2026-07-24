# Download pipeline

Updated: 2026-07-24

The authenticated page-context request for `download.jsp` follows this persistence contract:

1. Check HTTP status and classify authorization/session failures before persistence.
2. Read the body; reject empty, login, HTML, and error-like responses.
3. Detect a supported PDF, ZIP, or OLE signature; reject `UNKNOWN`.
4. Create a sanitized same-directory temporary file, write, flush, and close it.
5. Confirm disk size equals body length and apply the PDF/ZIP/OLE integrity policy to the temporary file.
6. On PASS, atomically replace a non-conflicting final path; only then report `persisted`.
7. On failure or exception, remove the temporary file and leave no new final file.

Body validation, signature validation, file integrity, and persistence success are separate states. HTTP 200 alone never authorizes persistence.
