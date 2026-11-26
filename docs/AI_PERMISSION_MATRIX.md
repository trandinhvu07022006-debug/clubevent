# KMG AI — Ma trận Phân quyền & Bảo mật Dữ liệu (Permission Matrix)

Mọi kiểm tra quyền thực thi tại **backend** qua `organization.permissions.PermissionEngine` dựa trên `request.user` đã xác thực — **không bao giờ suy ra quyền từ chức danh tự khai trong câu hỏi**.

| Nhóm người dùng | Tri thức RAG được đọc | Dữ liệu nghiệp vụ được tra | Cloud LLM Egress (`egress.py`) |
|---|---|---|---|
| **Khách tham quan** | `PUBLIC` (`APPROVED`) | Sự kiện `PUBLIC`, số vé, Ban chuyên môn, Tuyển thành viên | Chỉ payload `PUBLIC` đã che PII |
| **Ứng viên** | `PUBLIC` (`APPROVED`) | Như Khách + `Application` của chính mình (`user=user`) | Chỉ dữ liệu `PUBLIC`; dữ liệu cá nhân đi nhánh nội bộ |
| **Thành viên** | `PUBLIC` + `INTERNAL` (nếu có `club.event.view_internal`) | Lịch tập (`PracticeSession`), Đào tạo & Kỹ năng, Công việc cá nhân (`ClubTask`), Đánh giá cá nhân | `INTERNAL` / `PRIVATE_PII` bị chặn gửi Cloud LLM |
| **Trưởng/Phó ban & BTC** | `PUBLIC` + `INTERNAL` | Như Thành viên + Tổng hợp công việc (`club.task.assign`) | Chặn Cloud LLM cho `INTERNAL` |
| **BCN & Tài chính** | `PUBLIC` + `INTERNAL` + `CONFIDENTIAL` (nếu có `club.document.manage_confidential`) | Như trên + Sổ quỹ (`finance.transaction.view`) + Chỉ số vận hành (`club.event.approve`) + AI Studio | Chặn Cloud LLM cho `INTERNAL` / `CONFIDENTIAL` |
| **Cố vấn & Admin** | Theo quyền `PermissionEngine` thực tế | Giám sát & phân tích trong phạm vi quyền được cấp | Fail-closed theo `DataClassification` |
