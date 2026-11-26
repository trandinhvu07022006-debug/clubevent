# KMG AI — Danh mục Ý định (Intent Catalog)

| Mã Intent | Nhóm đối tượng | Đăng nhập | Nguồn xử lý | Mô tả |
|---|---|---|---|---|
| `upcoming_events` | Khách / Tất cả | Không | DB (`events.Event`) | Sự kiện sắp diễn ra |
| `seats_left` | Khách / Tất cả | Không | DB (`events.TicketType`) | Số chỗ / vé còn lại |
| `how_to_register` | Khách / Tất cả | Không | Rules + Settings | Hướng dẫn đặt vé & thanh toán VietQR |
| `how_to_checkin` | Khách / Tất cả | Không | Rules | Hướng dẫn check-in mã QR |
| `cancel_ticket` | Khách / Tất cả | Không | Rules + Settings | Quy định hủy vé |
| `club_departments` | Khách / Tất cả | Không | DB (`organization.Department`) | Cơ cấu 3 Ban của KMG |
| `recruitment_info` | Khách / Tất cả | Không | DB (`recruitment.RecruitmentRound`) | Đợt tuyển thành viên |
| `my_tickets` | Khách đã ĐN / TV | Có | DB (`registrations.Ticket`) | Vé cá nhân & mã QR |
| `my_recruitment_status` | Ứng viên | Có | DB (`recruitment.Application`) | Trạng thái hồ sơ & lịch casting |
| `my_tasks` | Thành viên / BTC | Có | DB (`operations.ClubTask`) | Công việc được giao & deadline |
| `my_practice` | Thành viên | Có | DB (`programs.PracticeSession`) | Lịch tập cá nhân & CLB |
| `my_training` | Thành viên | Có | DB (`programs.TrainingEnrollment`, `UserSkill`) | Khóa đào tạo & kỹ năng |
| `my_evaluations` | Thành viên | Có | DB (`evaluations.MemberEvaluation`) | Kết quả đánh giá định kỳ |
| `department_ops` | Trưởng/Phó ban, BCN | Có + Quyền | DB (`operations.ClubTask`) | Tổng hợp tiến độ công việc Ban/CLB |
| `finance_summary` | BCN / Tài chính | Có + Quyền | DB (`finance.FinancialTransaction`) | Tổng hợp thu chi sổ quỹ đã duyệt |
| `club_analytics` | BCN / Cố vấn / Admin | Có + Quyền | DB (`ClubMembership`, `ClubTask`, `Event`) | Chỉ số vận hành CLB |
| `music_tutor` | Sinh viên / TV | Tùy | `music_tutor.py` + `MusicLearningProfile` | Guitar, Thanh nhạc, Nhạc lý, Lộ trình 7/30 ngày |
| `student_companion` | Sinh viên / TV | Không | `music_tutor.py` | Đồng hành tâm lý, cân bằng thi cử, hòa nhập |
| `security_deny` | Ngoại lệ / Tấn công | — | `router.py` | Chặn jailbreak, giả mạo vai trò, dò bí mật |
| `ai` / `unknown` | Tất cả | — | Hybrid RAG + LLM / Fallback | Câu hỏi mở hoặc ngoài phạm vi |
