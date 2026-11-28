# Kiến trúc Sản phẩm KMG (Product Architecture — Consolidation 4.0)

**Mục tiêu:** Tổ chức lại toàn bộ chức năng KMG thành một sản phẩm thống nhất theo **nhu cầu người dùng và vai trò thực tế**, thay cho cách chia rời rạc theo tên app Django.

---

## 1. Cấu trúc Điều hướng 6 Nhóm Nghiệp vụ

| Nhóm | Mục đích | Mục điều hướng chính | Đối tượng hiển thị |
|---|---|---|---|
| **Tổng quan** | Nắm nhanh việc cần xử lý, lịch gần nhất, thông báo quan trọng | `Tổng quan` (`pages:dashboard`), `Không gian CLB` (`organization:workspace_home`) | Tất cả (Không gian CLB cho thành viên đã kích hoạt) |
| **Công việc** | Nhận việc, nộp bài, theo dõi tiến độ & giao việc theo Ban | `Việc của tôi` (`operations:task_list` / `organizing:my_tasks`), `Giao việc` (`organizing:assign`) | Thành viên CLB / BTC / Trưởng & Phó ban |
| **Tổ chức** | Cơ cấu Ban, tuyển thành viên, đánh giá, đề xuất & tài liệu | `Các Ban` (`organizing:department_list` / `organization:workspace_home`), `Tuyển thành viên` (`recruitment:home` / `recruitment:review_list`), `Đánh giá` (`evaluations:hub`), `Đề xuất` (`programs:proposal_hub`), `Kho tài liệu` (`programs:document_hub`) | Theo vai trò & quyền thực tế |
| **Hoạt động và âm nhạc** | Sự kiện, lịch, vé, đào tạo kỹ năng, lịch tập Band & playlist | `Sự kiện` (`events:list`), `Lịch sự kiện` (`events:calendar`), `Vé của tôi` (`registrations:my_tickets`), `Đào tạo & Tập Band` (`programs:training_practice_hub`), `Playlist & Tặng nhạc` (`social:music_hub`) | Công khai (Sự kiện/Lịch/Vé); Thành viên CLB (Đào tạo/Tập Band/Playlist) |
| **Cộng đồng** | Bảng tin nội bộ, nhắn tin bảo mật, thông báo | `Bảng tin nội bộ` (`social:feed`), `Nhắn tin bảo mật` (`social:chat_hub`), `Thông báo` (`notifications:list`) | Thông báo: tất cả; Bảng tin & Nhắn tin: Thành viên CLB |
| **Quản lý** | Vận hành, tài chính, kiểm soát AI, tài khoản & nhật ký | `Xác nhận thanh toán` (`registrations:payment_list`), `Quỹ & Tài chính` (`finance:hub`), `Thống kê` (`events:dashboard`), `Giám sát CLB` (`organization:advisor_overview`), `Quản trị & Phân quyền` (`organization:governance_center`), `Huấn luyện AI` (`aiassist:studio`), `Tài khoản` (`accounts:user_list`), `Nhật ký thao tác` (`accounts:audit_log`) | Theo phân quyền Backend (`PermissionEngine`) |
| **Xuyên suốt** | Trợ lý AI hợp nhất (Gia sư nhạc + Bạn đồng hành + Trợ lý CLB) | `Trợ lý KMG` (`aiassist:chat`) | Mọi người dùng (lọc tri thức & truy vấn theo quyền) |
| **Menu tài khoản** | Hồ sơ cá nhân, bảo mật & giao diện | `Trang cá nhân` (`accounts:profile`), `Đổi mật khẩu` (`accounts:password_change`), `Giao diện Sáng/Tối`, `Trang giới thiệu` (`pages:home`), `Đăng xuất` (`accounts:logout`) | Mọi tài khoản đã đăng nhập |

> **Nguyên tắc hiển thị:**
> - Không ẩn cảnh báo quan trọng (cảnh báo chuyên cần, vé sắp hết hạn thanh toán, công việc quá hạn).
> - Không xóa tính năng đã có; các chức năng ít dùng hằng ngày (Đề xuất, Tài liệu, Quỹ, Đánh giá, Phân tích) được đặt trong nhóm mở rộng (`<details>`) hoặc trang chuyên biệt tại `workspace_home`.

---

## 2. Ma trận Vai trò → Nhu cầu → Chức năng → Quyền hạn → Nguồn dữ liệu → Điểm truy cập

### 2.1 Khách & Ứng viên (`GUEST` / Chưa đăng nhập)
| Nhu cầu | Chức năng | Quyền hạn | Nguồn dữ liệu | Điểm truy cập |
|---|---|---|---|---|
| Tìm hiểu CLB & sự kiện | Xem trang giới thiệu, danh sách & lịch sự kiện công khai | Public | `pages`, `events.Event (PUBLIC)` | `/`, `/portal/`, `/sukien/`, `/sukien/lich/` |
| Đặt vé & theo dõi vé | Đăng ký vé, thanh toán VietQR, xem QR check-in, hủy/chuyển vé | Đăng nhập (`@login_required`) | `registrations.Registration`, `Ticket` | `/ve/cua-toi/`, `/sukien/<slug>/` |
| Gia nhập CLB | Xem đợt tuyển, nộp đơn ứng tuyển | Đăng nhập (`GUEST`) | `recruitment.Application`, `organization.MembershipApplication` | `/tuyen-thanh-vien/`, `/workspace/ung-tuyen/` |
| Hỏi đáp & học nhạc cơ bản | Trò chuyện với Trợ lý KMG (tri thức `PUBLIC`, gia sư âm nhạc) | Public / Đăng nhập | `aiassist.ClubKnowledge (PUBLIC)` | `/troly/` |

### 2.2 Thành viên chính thức (`MEMBER` + `ClubMembership ACTIVE`)
| Nhu cầu | Chức năng | Quyền hạn | Nguồn dữ liệu | Điểm truy cập |
|---|---|---|---|---|
| Xem việc cần làm & lịch gần nhất | Dashboard tổng quan & Không gian CLB | `club_member_required` | `operations.ClubTask`, `programs.PracticeSession`, `events` | `/tong-quan/`, `/workspace/` |
| Nhận & nộp nhiệm vụ | Xem nhiệm vụ Ban, cập nhật tiến độ, nộp bài vào vault | `dept.task.view_personal_self` | `operations.ClubTask`, `TaskSubmission` | `/congviec/nhiem-vu/` |
| Tham gia đào tạo & tập Band | Đăng ký khóa học, xác nhận lịch tập (RSVP), tự khai báo kỹ năng | `club.event.view_internal` | `programs.TrainingCourse`, `PracticeSession`, `organization.UserSkill` | `/workspace/dao-tao/` |
| Giao lưu cộng đồng & âm nhạc | Đăng bài, bình luận, nhắn tin E2EE, tạo playlist, tặng nhạc | `club_member_required` | `social.SocialPost`, `Conversation`, `MusicPlaylist` | `/workspace/cong-dong/`, `/workspace/nhan-tin/`, `/workspace/am-nhac/` |
| Đóng quỹ & xem đánh giá cá nhân | Xem đóng góp cá nhân, xem phiếu đánh giá đã chốt & phản hồi | `member=user` | `finance.MemberContribution`, `evaluations.MemberEvaluation` | `/workspace/tai-chinh/`, `/workspace/danh-gia/` |
| Học nhạc cá nhân hóa | Hồ sơ học nhạc, nhật ký luyện tập, gia sư AI | Consent-based (`User`) | `aiassist.MusicLearningProfile`, `MusicPracticeLog` | `/troly/` |

### 2.3 Thành viên BTC (`STAFF`)
| Nhu cầu | Chức năng | Quyền hạn | Nguồn dữ liệu | Điểm truy cập |
|---|---|---|---|---|
| Phối hợp tổ chức sự kiện | Check-in QR vé, xác nhận thanh toán VietQR, xử lý việc BTC | `is_staff_btc` | `registrations`, `organizing.Task`, `operations.ClubTask` | `/ve/thanh-toan/`, `/congviec/viec-cua-toi/` |

### 2.4 Trưởng ban & Phó ban (`DEPT_HEAD` / `DEPUTY_HEAD`)
| Nhu cầu | Chức năng | Quyền hạn | Nguồn dữ liệu | Điểm truy cập |
|---|---|---|---|---|
| Điều phối công việc trong Ban | Tạo/giao/duyệt nộp việc trong phạm vi Ban phụ trách | `dept.task.assign`, `dept.task.review` (theo `Department`) | `operations.ClubTask` (lọc theo Ban) | `/congviec/nhiem-vu/`, `/congviec/giao/` |
| Đào tạo & xác minh kỹ năng | Xác minh `UserSkill` (không tự xác minh của mình — `INV-03`), lập lịch tập | `dept.skill.verify`, `BUNDLE_TRAINING_CONTENT` | `organization.UserSkill`, `programs` | `/workspace/ban/<slug>/`, `/workspace/dao-tao/` |
| Sơ duyệt nhân sự & đánh giá | Sơ duyệt đơn ứng tuyển vào Ban, soạn phiếu đánh giá định kỳ | `dept.member.screen`, `BUNDLE_HR_SCREENING` | `organization.MembershipApplication`, `evaluations` | `/workspace/ban/<slug>/`, `/workspace/danh-gia/` |
| Ủy quyền cho Phó ban | Cấp gói năng lực cho Phó ban (chỉ Trưởng ban; bị chặn bởi Hard Ceiling) | `dept.permission.delegate` | `organization.PermissionGrant` | `/workspace/ban/<slug>/uy-quyen/` |

### 2.5 Ban Chủ nhiệm (`CHAIRMAN` / `VICE_CHAIRMAN`)
| Nhu cầu | Chức năng | Quyền hạn | Nguồn dữ liệu | Điểm truy cập |
|---|---|---|---|---|
| Điều hành & duyệt cấp CLB | Duyệt thành viên chính thức, duyệt sự kiện, phê duyệt đánh giá | `club.member.approve`, `club.event.approve`, `club.evaluation.finalize` | `organization`, `events`, `evaluations` | `/workspace/quan-tri/`, `/sukien/` |
| Quản lý tài chính CLB | Lập & duyệt chi Maker-Checker (`INV-03`), xem sổ quỹ | `club.finance.view_summary`, `create_transaction`, `approve_transaction` | `finance.FinancialTransaction` | `/workspace/tai-chinh/` |
| Quản trị AI & Tri thức | Kiểm duyệt tri thức `ClubKnowledge`, chỉnh prompt profile, xem eval | `is_lead` (`can_manage_confidential` cho `CONFIDENTIAL`) | `aiassist.ClubKnowledge`, `AIPromptProfile` | `/troly/huan-luyen/` |

### 2.6 Cố vấn (`ADVISOR` — Hard Read-Only `INV-04`)
| Nhu cầu | Chức năng | Quyền hạn | Nguồn dữ liệu | Điểm truy cập |
|---|---|---|---|---|
| Giám sát độc lập | Xem tổng quan Ban, nhân sự, tài chính, nhật ký vòng đời (chỉ đọc) | `club.overview.supervise`, `club.finance.view_summary` | `organization`, `finance` (Read-Only) | `/workspace/giam-sat/`, `/workspace/tai-chinh/` |

### 2.7 Quản trị viên (`ADMIN` / `is_server_admin`)
| Nhu cầu | Chức năng | Quyền hạn | Nguồn dữ liệu | Điểm truy cập |
|---|---|---|---|---|
| Quản trị hệ thống & bổ nhiệm | Bổ nhiệm/miễn nhiệm Chủ nhiệm, Phó CN, Trưởng ban, Cố vấn; quản lý tài khoản & audit log | `is_server_admin`, `is_admin_role` | `accounts.User`, `AuditLog`, `organization.Appointment` | `/workspace/quan-tri/`, `/taikhoan/danh-sach/`, `/taikhoan/nhat-ky/` |
