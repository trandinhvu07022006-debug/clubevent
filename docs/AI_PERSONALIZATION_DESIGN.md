# KMG AI — Thiết kế Cá nhân hóa (AI Personalization Design)

## 1. Tái sử dụng & Mở rộng Model
- **Tái sử dụng trực tiếp:** `organization.UserSkill` (kỹ năng đã ghi nhận & trạng thái xác minh CLB), `programs.TrainingCourse` / `TrainingEnrollment` (khóa đào tạo CLB).
- **Bổ sung tối thiểu (`aiassist/models.py`):**
  - `MusicLearningProfile`: `user` (OneToOne), `personalization_enabled`, `instrument`, `level` (`NEWBIE`/`BASIC`/`INTERMEDIATE`/`ADVANCED`), `goal`, `favorite_genres`, `daily_minutes`, `current_challenges`, `active_plan`, `mentor_notes`.
  - `MusicPracticeLog`: `profile`, `practiced_at`, `duration_minutes`, `focus_topic`, `completed_exercise`, `self_rating` (1–5), `notes`.

## 2. Lộ trình Thích ứng & Quyền kiểm soát dữ liệu
- **Lộ trình 7 ngày / 30 ngày:** Điều chỉnh theo `daily_minutes`, `level`, `goal`, và `UserSkill`; không bắt đầu bằng kỹ thuật nâng cao cho người mới; gợi ý giảm tải khi người dùng bận thi.
- **Tiến độ thực tế:** Tính từ số buổi, tổng phút tập và bài tập hoàn thành trong `MusicPracticeLog` — **không tự sinh phần trăm tiến độ giả**.
- **Quyền người dùng (`/troly/ho-so-nhac/`):** Cho phép xem (`GET`), chỉnh sửa hoặc bật/tắt `personalization_enabled` (`POST`), và xóa toàn bộ hồ sơ (`DELETE`).
