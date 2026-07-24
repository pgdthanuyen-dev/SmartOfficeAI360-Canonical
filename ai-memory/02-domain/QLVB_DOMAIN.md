# QLVB domain

Updated: 2026-07-24

The default document workflow visits these categories in order:

1. Văn bản vào sổ
2. Đã chuyển xử lý
3. Đã xử lý

Chờ xử lý is intentionally excluded from the default workflow. Only rows in the validated business table are eligible. A document identifier is row-scoped and must never be inferred from a neighboring action, a different category, or an unvalidated page.

The workflow selects the exact normalized category label inside the correct left menu group, tolerates a numeric count suffix, and rejects decoy text in dialogs, templates, or main-content controls. It stops at configured document and file bounds.
