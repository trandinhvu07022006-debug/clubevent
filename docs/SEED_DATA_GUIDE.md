# HƯỚNG DẪN DỮ LIỆU SEED & STAGING — KMG PLATFORM

## 1. Phân biệt các lệnh Seed
| Lệnh | Mục đích | Tài khoản mẫu | Bị chặn trên Production? |
|---|---|---|---|
| `bootstrap_kmg` | Khởi tạo danh mục chuẩn (3 Ban, 6 chức vụ, quyền, kỹ năng, policy) | **Không tạo user** | An toàn chạy trên mọi môi trường |
| `seed_demo` / `seed_kmg` | Demo nhỏ / Kịch bản 7 persona D04 | Có (chỉ nội bộ demo) | **Có** (`assert_non_production_seed_allowed`) |
| `seed_staging` | Dữ liệu mô phỏng đầy đủ quy mô staging/load test | Có (`@staging.example.invalid`, `@guest.example.invalid`) | **Có** (Chặn cứng nếu `KMG_ENV=prod`, `ALLOW_DEMO_SEED=False`, hoặc `DEBUG=False` không có `KMG_ALLOW_STAGING_SEED=1`) |

## 2. Quy mô dựng sẵn của `seed_staging`
- `--scale smoke`: ~3% quy mô, chạy < 3 giây để kiểm tra logic.
- `--scale medium`: ~25% quy mô (`40` thành viên, `150` khách, `4.000` tin nhắn, `10.000` logs).
- `--scale full` *(mặc định đề xuất Staging)*:
  - `120` thành viên CLB (đủ `ACTIVE`, `SUSPENDED`, `ALUMNI`, `LEFT`, đa Ban)
  - `500` khách (`ACTIVE`, `UNVERIFIED`, `LOCKED`)
  - `200` hồ sơ ứng tuyển (`MembershipApplication` + `recruitment.Application`)
  - `40` sự kiện (`DRAFT`, `OPEN`, `CLOSED`, `DONE`, `CANCELLED`, công khai + nội bộ)
  - `2.500` vé (`CONFIRMED`, `CHECKED_IN`, `PENDING`, `CANCELLED`)
  - `800` công việc (đầy đủ 10 trạng thái, gồm quá hạn và cần giao lại)
  - `3.000` bản ghi điểm danh RSVP
  - `300` giao dịch tài chính (`CONFIRMED` thu/chi, `PENDING_APPROVAL`, `REJECTED`, `ADJUSTMENT`)
  - `150` tài liệu phân quyền
  - `500` bài đăng mạng xã hội + `2.000` bình luận (kèm tiếng Việt có dấu + emoji `utf8mb4`)
  - `20.000` tin nhắn mã hóa AES-256-GCM thực
  - `10.000` thông báo
  - `50.000` nhật ký (`AuditLog` + `AIInteractionLog` không PII thật)

## 3. Lệnh chạy mẫu
```powershell
.\venv\Scripts\python.exe manage.py seed_staging --seed 2026 --scale full
```
Có thể ghi đè từng con số bằng `--members`, `--guests`, `--events`, `--tickets`, `--tasks`, `--messages`, `--notifications`, `--logs`.
