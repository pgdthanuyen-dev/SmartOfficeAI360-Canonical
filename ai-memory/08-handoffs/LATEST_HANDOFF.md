# Latest handoff

Updated: 2026-07-24

## Mục tiêu đã hoàn thành

Ổn định hóa QLVB CDP/NeoRemoting authenticated download path và tạo bộ project memory dùng chung.

## Trạng thái trước

Commit ổn định là `ea39c35a27b399fe5c049b3d4545db2322142ac9`. `main` chứa commit này. Bốn file ứng dụng ngoài phạm vi và các thư mục chẩn đoán bẩn vẫn được bảo toàn.

## File mã nguồn của commit

Commit gồm đúng tám file: hai focused tests và sáu module trong `tools/qlvb_downloader/` liên quan CDP, config, downloader, models, NeoRemoting và runner.

## Evidence và kiểm thử

Source-level live acceptance PASS; ba danh mục, ba phản hồi HTTP thành công và ba integrity checks đã PASS. Focused tests: `146 passed`. Full suite gần nhất chưa xanh hoàn toàn.

## Remote và việc còn lại

Remote repository chưa được xác minh hoặc push. Bộ memory này được quản lý bằng Git trong commit bàn giao riêng; phiên tiếp theo cần thực hiện post-commit verification, cập nhật ngày/trạng thái khi có bằng chứng mới, và không suy diễn thành repository-wide PASS.

## Điều cấm

Không lưu dữ liệu phiên, credential, dữ liệu văn bản hoặc thông tin người dùng; không reset/stash/clean dirty worktree; không live run, push, deploy hay migration nếu chưa được cho phép.
