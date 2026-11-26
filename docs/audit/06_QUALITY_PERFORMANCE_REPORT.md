# PHASE 6 — BÁO CÁO CHẤT LƯỢNG & HIỆU NĂNG (QUALITY & PERFORMANCE REPORT)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/kmg-system-stabilization`  

---

## 1. Tăng cường kiểm thử tự động & Độ bao phủ mã nguồn (`P6.1`)

Đã bổ sung bộ kiểm thử mới cho các vùng có coverage thấp trước đây:
- `accounts/test_phase6_coverage.py` — kiểm thử `accounts.sms` (console/webhook/error handling) và `accounts.services` (OTP SMS/Email, lockout, session device tracking, revoke, post-login routing).
- `finance/test_phase6_coverage.py` — kiểm thử `finance.views` (hub, detail, approve/adjust, chứng từ bảo mật, CSV, chặn Cố vấn `INV-04`) và `finance.api_views`.
- `organization/test_phase6_api_coverage.py` — kiểm thử `organization.api_views` (`auth_register`, `auth_otp_send/verify`, `auth_me`, `auth_sessions`, `auth_session_revoke`, `departments_list`, đồng thời vá lỗi thiếu mặc định `affiliation="KMA"` trên JSON API đăng ký).
- `registrations/test_phase6_perf.py` — kiểm thử đa mức tải 50 / 200 người dùng và giới hạn N+1 SQL query.

### So sánh Coverage trước & sau Phase 6 (`coverage report`, bỏ `migrations` & `test*.py`)

| Module trọng tâm | Baseline Phase 0 | Sau Phase 6 | Trạng thái |
|---|---|---|---|
| `accounts/sms.py` | 28% | **98%** | **VERIFIED** |
| `finance/views.py` | 37% | **88%** *(đã vá lỗi KeyError `dept_txs` cho Cố vấn)* | **VERIFIED** |
| `finance/api_views.py` | 58% | **89%** | **VERIFIED** |
| `accounts/services.py` | 43% | **79%** | **VERIFIED** |
| `organization/api_views.py` | 38% | **54%** *(đã vá lỗi `affiliation` ở `/api/v1/auth/register/`)* | **VERIFIED** |
| `events/models.py`, `events/services.py` | 99% / 98% | **99% / 98%** | **VERIFIED** |
| `registrations/services.py` | 95% | **95%** | **VERIFIED** |
| `aiassist/providers.py`, `chatbot.py`, `services.py` | 91% / 90% / 89% | **91% / 91% / 89%** | **VERIFIED** |
| **Tổng hợp 11 app (`14,532` stmts + `63` file 100%)** | 77% (7 app) | **77%** (mở rộng ra cả 11 app gồm `operations`, `programs`, `social`, `evaluations`) | **VERIFIED** |

---

## 2. Tối ưu CSDL & Kiểm thử đa mức tải (`P6.2` & `P6.3`)

- **Kiểm soát truy vấn (`QueryOptimizationTests`):** Trang `/sukien/` (`events:list`) với 12 sự kiện công khai và loại vé tiêu tốn đúng **4 truy vấn SQL** (`assertNumQueries(4)`), không có N+1 query.
- **Kết quả đo hiệu năng (chạy trong suite toàn cục dưới `coverage` trên SQLite `IMMEDIATE`, phân tách IP theo người dùng):**

| Kịch bản | Quy mô | Kết quả đúng đắn | P95 đo được (ms) | Ghi chú phân biệt |
|---|---|---|---|---|
| `LOAD-50-BOOK` | 50 luồng tranh 30 vé | `30/30` vé, **0 oversell** | `782.0ms` | Service `book_tickets()` qua lock hàng SQLite |
| `PILOT-BOOK-100` | 100 luồng tranh 60 vé | `60/60` vé, `40` bị từ chối | `443.3ms` | Service-level concurrency + `coverage` |
| `PILOT-CHECKIN-100` | 10 luồng quét trùng + 100 vé | `1 OK / 9 USED`, `100/100` | `8.3ms` | Service `check_in()` |
| `LOAD-200-CHECKIN` | 200 vé check-in liên tiếp | `200/200` vé | `10.3ms` | Service `check_in()` |
| `PILOT-CHAT-100` | 100 request `/troly/hoi/` | `100/100` HTTP 200 | `17.3ms` | Tầng luật nội bộ, không tính độ trễ LLM ngoài |
| `LOAD-200-CHAT` | 200 request `/troly/hoi/` | `200/200` HTTP 200 | `13.9ms` | Tầng luật nội bộ, không tính độ trễ LLM ngoài |

> **Phân biệt môi trường:** Số liệu trên chạy qua Django `TestCase` / `TransactionTestCase` trên SQLite + `LocMemCache`; độ trễ HTTP thực tế qua Gunicorn + Nginx + MySQL 8.4 + Redis 7 trên tải 200–500 người dùng đồng thời cần xác nhận lại trên CI / staging khi có Docker và mạng thật.
