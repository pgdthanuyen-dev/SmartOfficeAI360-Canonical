# Architecture

Updated: 2026-07-24

The live QLVB path attaches to an already authenticated external Edge through CDP endpoint `127.0.0.1:9223`. The automation process reuses the authenticated page and does not launch, close, or take ownership of the browser, context, or page.

Navigation uses exact normalized menu matching, mojibake detection, actionable-ancestor resolution, group expansion guards, delayed submenu rescans, and bounded post-click polling. Validation scans frames as needed and recognizes the visible `#div_data_list` document grid structurally rather than relying on fragile row text or a fixed table identifier.

After selecting one validated row, the workflow calls the legacy NeoRemoting `getRSet.call` contract. Attachment metadata is parsed by the safe parser without `eval` or `exec`. The first eligible attachment is fetched through an authenticated request associated with the live page, then checked for HTTP success, non-login/signature validity, and integrity.
