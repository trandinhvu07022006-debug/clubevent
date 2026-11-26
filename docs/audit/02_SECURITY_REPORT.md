# PHASE 2 — BÁO CÁO KIỂM TOÁN & GIA CỐ BẢO MẬT (SECURITY REPORT)

**Ngày thực hiện:** 2026-11-26  
**Nhánh làm việc:** `feature/kmg-system-stabilization`  

---

## 1. Kết quả kiểm toán bảo mật toàn hệ thống

### P2.1. Bảo mật tài khoản (`accounts`)
- **Mật khẩu & băm:** Ưu tiên `Argon2PasswordHasher` (`PASSWORD_HASHERS` trong `config/settings.py`), fallback `BCryptSHA256` / `PBKDF2`.
- **Chống dò mật khẩu (`accounts/throttle.py`):** Bảo vệ 2 lớp theo IP (`20 lần/300s`) và theo định danh tài khoản gộp username/email/SĐT (`10 lần/900s`), áp dụng cho cả đăng nhập web và `/admin/login/` (`config/urls.py:16`), tự reset bộ đếm khi đăng nhập thành công.
- **Thu hồi phiên & khóa tài khoản tức thời (`accounts/middleware.py` - INV-06):** `LockedUserMiddleware` kiểm tra `is_locked` / `AccountStatus.LOCKED`, `UserSession.revoked_at`, và hạn chế phạm vi thành viên `ClubMembershipStatus.SUSPENDED` trên cả Web (`/workspace/`) và REST API (`/api/v1/`).
- **OTP & Reset mật khẩu (`accounts/services.py`, `accounts/models.py`):** OTP 6 số lưu dạng `salted_hmac` (không lưu plaintext), giới hạn gửi lại `60s`, tối đa `5 mã/giờ`, tối đa `5 lần thử`, `PASSWORD_RESET_TIMEOUT = 2 giờ`, khóa dòng `select_for_update()` khi kiểm chứng OTP.
- **MFA cho Admin / BCN:** Hệ thống hiện hỗ trợ OTP qua Email cho tài khoản Khách và phiên thiết bị có thu hồi từ xa; **chưa có TOTP MFA (authenticator app)** cho Admin / Chủ nhiệm — ghi nhận ở mục kiến nghị nâng cấp giai đoạn sau (không nằm trong blocker v1.0 nhưng nên bật cho môi trường công khai).

### P2.2. Kiểm toán phân quyền (`accounts/permissions.py`, `organization/permissions.py`, `finance`, `operations`, `programs`, `social`)
- **Động cơ RBAC + DBAC + ABAC + Delegation + ACL (`organization/permissions.py`):** Thực thi kiểm tra tại Backend cho đủ nhóm vai trò: Khách, Thành viên, Phó ban (Baseline + 4 Gói ủy quyền + Trần cứng `DEPUTY_HEAD_FORBIDDEN_PERMISSIONS`), Trưởng ban, Phó chủ nhiệm (4 Mảng phụ trách), Chủ nhiệm, Cố vấn (`_is_pure_advisor` → **Hard Read-Only INV-04** trả HTTP 403 trên mọi mutation), Admin Server (`server.leadership.manage`), và BTC sự kiện (`staff_required` / `lead_required`).
- **Tách nhiệm vụ & Anti-Self-Approval (`INV-03`):**
  - `operations`: chặn tự nghiệm thu nhiệm vụ bản thân được giao; chặn người ra quyết định ban đầu tự xét khiếu nại (`WF24`).
  - `finance`: chặn Maker tự duyệt (`created_by != approved_by`) trên cả Web lẫn API (`/api/v1/finance/...`); sổ cái `CONFIRMED` bất biến, sửa sai qua `ADJUSTMENT`.
  - `accounts`: chặn Admin tự đổi role chính mình (`core/test_quality.py`).

### P2.3 & P2.4. Gia cố Production & Bảo mật Dữ liệu
- **Quét bí mật Git (`git grep`):** Không phát hiện API key Gemini/OpenAI, token GitHub hay private key lọt vào các file được Git theo dõi.
- **Quét sink nguy hiểm (`git grep`):**
  - `@csrf_exempt`: Chỉ có 1 điểm duy nhất tại `registrations/views.py:274` (`sepay_webhook`), xác thực bằng `hmac.compare_digest` với `SEPAY_API_KEY`.
  - `|safe`: Chỉ dùng ở 3 template tài khoản (`password_change.html`, `password_reset_confirm.html`, `register.html`) cho `field.help_text` sinh nội bộ từ `AUTH_PASSWORD_VALIDATORS`, không dùng trên dữ liệu người dùng.
  - `.raw()`, `.extra()`, `shell=True`: **0** kết quả.

---

## 2. Lỗ hổng / Điểm yếu phát hiện & đã vá trong Phase 2

| ID | Mức | Vấn đề phát hiện | Bản vá thực tế & File | Kiểm thử xác minh |
|---|---|---|---|---|
| **SEC-P2-01** | **High** | `operations/services.py::submit_task_deliverable` nhận trực tiếp `attachment` từ `request.FILES` mà chưa qua bộ kiểm tra đuôi cấm/magic bytes/dung lượng (cho phép tải `.html`, `.svg`, `.exe`, tệp rỗng). | Gọi `programs.services.validate_and_prepare_vault_file(attachment)` (chặn `.html/.svg/.exe/.php/.js`, kiểm tra magic bytes, `<=20MB`, tên UUID) trong `operations/services.py:527-530`. | `core.test_security_phase2.OperationsUploadAndDownloadSecurityTests.test_submit_task_deliverable_rejects_dangerous_uploads` (**VERIFIED**) |
| **SEC-P2-02** | **Medium** | `operations/views.py::download_task_submission_file` trả `FileResponse` thiếu `X-Content-Type-Options: nosniff` và `Cache-Control: private, no-store`. | Bổ sung 2 header an toàn trong `operations/views.py:428-436`. | `core.test_security_phase2.OperationsUploadAndDownloadSecurityTests.test_download_submission_sets_nosniff_and_private_no_store` (**VERIFIED**) |
| **SEC-P2-03** | **Medium** | `social/views.py` (`chat_attachment_download`, `social_attachment_download`) cho phép hiển thị `inline` với mọi `content_type` bắt đầu bằng `image/`, có thể bị lạm dụng nếu dữ liệu cũ gắn `image/svg+xml`. | Siết whitelist chỉ phục vụ inline với ảnh raster an toàn (`image/png`, `image/jpeg`, `image/webp`, `image/gif`), còn lại ép `as_attachment=True`. | `core.test_security_phase2.SocialAttachmentDispositionTests` (**VERIFIED**) |
| **SEC-P2-04** | **High** | `USE_X_FORWARDED_HOST=True` bật theo `TRUST_PROXY_HEADERS` trong khi `deployment/nginx.conf.template` chưa ghi đè `X-Forwarded-Host`; `ALLOW_DEMO_SEED` mặc định `True` khi `DEBUG=False`; thiếu header `CSP` và `Referrer-Policy` trên Nginx. | Đã sửa tại `config/settings.py`, `deployment/nginx.conf.template` (thêm `X-Forwarded-Host $http_host`, `Referrer-Policy`, `Content-Security-Policy` chặn `object-src 'none'`, `frame-ancestors 'none'`). | `core.test_secret_guard.SecretGuardTests` & `core.test_security_phase2.NginxConfigSecurityTests` (**VERIFIED**) |

---

## 3. Bằng chứng kiểm thử Phase 2
- `python manage.py test core.test_security_phase2 --settings=config.settings_test`: **4/4 OK** (`2.203s`).
- `python manage.py test core.test_security_phase2 operations.test_phase2_operations social.test_phase4_social finance.test_phase5_finance --settings=config.settings_test`: các test trong `operations`, `social`, `finance` (50/50) đạt trước khi chỉnh test import và `core.test_security_phase2` (4/4) đạt sau khi chỉnh xong.
