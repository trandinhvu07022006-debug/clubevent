"""
Kiểm thử bảo mật tự động Giai đoạn 1 (Phase 1 Security Hardening):
- SEC-01: Private Vault Storage cho chứng từ tài chính (`Expense.receipt`) ngoài `MEDIA_ROOT`.
- SEC-02: Chống CSV Formula Injection trên `safe_csv_cell`, `budget_csv` và `participant_csv`.
- SEC-06: Giới hạn tần suất (Rate-limit) theo Cache + IP chống tấn công bỏ cookie `sessionid`.
- SEC-07 & Argon2id: Tách khóa ký chứng nhận `CERT_SIGNING_KEY` khỏi `SECRET_KEY`; băm mật khẩu Argon2id.
"""
from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth.hashers import BCryptSHA256PasswordHasher, make_password
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from core.security import safe_csv_cell
from events.models import Event, EventCategory, EventStatus
from events.services import cert_token, verify_cert_token
from organizing.models import Expense, ExpenseCategory
from registrations.models import Ticket, TicketStatus, TicketType

# Ảnh PNG 1x1 tối giản hợp lệ cho ImageField
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class Phase1SecurityHardeningTests(TestCase):
    def setUp(self):
        self.tmp_vault = Path(tempfile.mkdtemp(prefix="kmg_vault_test_"))
        self.tmp_media = Path(tempfile.mkdtemp(prefix="kmg_media_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp_vault, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(self.tmp_media, ignore_errors=True))

        now = timezone.now()
        self.lead = User.objects.create_user(
            username="sec_lead",
            password="Password@123",
            full_name="Trưởng BTC",
            role=Role.LEAD,
            email="sec_lead@kmg.vn",
        )
        self.staff = User.objects.create_user(
            username="sec_staff",
            password="Password@123",
            full_name="TV BTC",
            role=Role.STAFF,
            email="sec_staff@kmg.vn",
        )
        self.member = User.objects.create_user(
            username="sec_member",
            password="Password@123",
            full_name="=CMD|' /C calc'!A0",
            mssv="+84909998877",
            phone="+84909998877",
            role=Role.MEMBER,
            email="sec_member@kmg.vn",
        )
        self.event = Event.objects.create(
            name="Liveshow Bảo mật KMG",
            location="Hội trường A",
            category=EventCategory.MUSIC,
            starts_at=now + timedelta(days=5),
            register_deadline=now + timedelta(days=4),
            capacity=100,
            budget=5_000_000,
            status=EventStatus.OPEN,
            created_by=self.lead,
        )

    def test_sec01_expense_receipt_stored_in_private_vault_and_protected(self):
        """SEC-01: Hóa đơn lưu ngoài MEDIA_ROOT và chỉ Trưởng BTC/Admin mới tải được."""
        with override_settings(
            PRIVATE_VAULT_ROOT=self.tmp_vault,
            MEDIA_ROOT=self.tmp_media,
        ):
            upload = SimpleUploadedFile(
                "hoadon_amthanh.png", TINY_PNG, content_type="image/png"
            )
            expense = Expense.objects.create(
                event=self.event,
                category=ExpenseCategory.EQUIPMENT,
                title="Thuê loa FOH",
                amount=1_500_000,
                receipt=upload,
                created_by=self.lead,
            )

            receipt_path = Path(expense.receipt.path).resolve()
            self.assertTrue(receipt_path.is_relative_to(self.tmp_vault.resolve()))
            self.assertFalse(receipt_path.is_relative_to(self.tmp_media.resolve()))

            url = reverse("organizing:expense_receipt", args=[expense.pk])

            # 1. Khách chưa đăng nhập -> 302 redirect sang login
            anon_resp = Client().get(url)
            self.assertEqual(anon_resp.status_code, 302)

            # 2. Thành viên thường & TV BTC thường -> 403 Forbidden
            member_client = Client()
            member_client.force_login(self.member)
            self.assertEqual(member_client.get(url).status_code, 403)

            staff_client = Client()
            staff_client.force_login(self.staff)
            self.assertEqual(staff_client.get(url).status_code, 403)

            # 3. Trưởng BTC -> 200 OK kèm header chống MIME sniffing & đúng nội dung tệp
            lead_client = Client()
            lead_client.force_login(self.lead)
            ok_resp = lead_client.get(url)
            self.assertEqual(ok_resp.status_code, 200)
            self.assertEqual(ok_resp["X-Content-Type-Options"], "nosniff")
            self.assertEqual(b"".join(ok_resp.streaming_content), TINY_PNG)
            if getattr(ok_resp, "file_to_stream", None):
                ok_resp.file_to_stream.close()

            # 4. Chống Path Traversal qua private_vault_receipt
            traversal_url = reverse(
                "organizing:private_vault_receipt", args=["../manage.py"]
            )
            self.assertEqual(lead_client.get(traversal_url).status_code, 404)

    def test_sec02_csv_formula_injection_neutralized_while_preserving_numbers(self):
        """SEC-02: Chuỗi mở đầu bằng =, +, -, @, tab bị khóa bằng dấu nháy đơn; số âm giữ nguyên."""
        self.assertEqual(safe_csv_cell("=1+1"), "'=1+1")
        self.assertEqual(safe_csv_cell("+8490123456"), "'+8490123456")
        self.assertEqual(safe_csv_cell("-2+3+cmd"), "'-2+3+cmd")
        self.assertEqual(safe_csv_cell("@SUM(A1:A5)"), "'@SUM(A1:A5)")
        self.assertEqual(safe_csv_cell("\t=1+1"), "'\t=1+1")
        self.assertEqual(safe_csv_cell("  =HYPERLINK()"), "'  =HYPERLINK()")
        # Kiểu số âm (ví dụ chênh lệch ngân sách -100000) phải giữ nguyên kiểu số
        self.assertEqual(safe_csv_cell(-100000), -100000)

        # Kiểm tra thực tế trên endpoint xuất CSV ngân sách & danh sách người tham gia
        Expense.objects.create(
            event=self.event,
            category=ExpenseCategory.OTHER,
            title="=HYPERLINK(\"http://evil.tld\",\"Click\")",
            amount=100_000,
            note="@SUM(1,2)",
            created_by=self.lead,
        )
        tt = TicketType.objects.create(
            event=self.event, name="Vé Thường", price=0, quota=50, sold=1
        )
        Ticket.objects.create(
            event=self.event,
            ticket_type=tt,
            user=self.member,
            status=TicketStatus.CONFIRMED,
            price=0,
        )

        lead_client = Client()
        lead_client.force_login(self.lead)

        budget_resp = lead_client.get(
            reverse("organizing:budget_csv", args=[self.event.pk])
        )
        self.assertEqual(budget_resp.status_code, 200)
        budget_text = budget_resp.content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK(", budget_text)
        self.assertIn("'@SUM(1,2)", budget_text)
        # Thu 0 - Chi 100000 = -100000 giữ nguyên số âm không bị gắn dấu nháy
        self.assertIn(",-100000", budget_text)

        part_resp = lead_client.get(
            reverse("registrations:participants_csv", args=[self.event.pk])
        )
        self.assertEqual(part_resp.status_code, 200)
        part_text = part_resp.content.decode("utf-8-sig")
        self.assertIn("'=CMD|", part_text)
        self.assertIn("'+84909998877", part_text)

    def test_sec06_ip_cache_rate_limit_blocks_sessionless_cookie_dropping_attack(self):
        """SEC-06: Dùng 6 Client mới tinh (không giữ cookie session) vẫn bị chặn gửi email ở lần thứ 6."""
        mail.outbox.clear()
        reset_url = reverse("accounts:password_reset")
        for attempt in range(5):
            fresh_client = Client()  # Mô phỏng kẻ tấn công vứt bỏ cookie mỗi request
            resp = fresh_client.post(reset_url, {"email": "sec_member@kmg.vn"})
            self.assertEqual(
                resp.status_code,
                302,
                f"Lượt hợp lệ #{attempt + 1} phải redirect sang trang thông báo.",
            )
        self.assertEqual(len(mail.outbox), 5)

        # Lượt thứ 6 từ một Client mới hoàn toàn cùng IP: vẫn trả 302 chống dò email nhưng KHÔNG gửi email thứ 6!
        sixth_client = Client()
        blocked_resp = sixth_client.post(reset_url, {"email": "sec_member@kmg.vn"})
        self.assertEqual(blocked_resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 5)

        # Kiểm tra tương tự với API AI Chat: vượt ngưỡng 30 tin/phút trên các Client mới không cookie -> 429
        ai_url = reverse("aiassist:chat_api")
        for _ in range(30):
            c = Client()
            r = c.post(
                ai_url,
                data=json.dumps({"question": "Sự kiện nào đang mở?"}),
                content_type="application/json",
            )
            self.assertEqual(r.status_code, 200)
        blocked_ai = Client().post(
            ai_url,
            data=json.dumps({"question": "Spam không cookie"}),
            content_type="application/json",
        )
        self.assertEqual(blocked_ai.status_code, 429)

    def test_sec07_cert_signing_key_separation_and_argon2id_primary_hasher(self):
        """SEC-07: Đổi SECRET_KEY không làm hỏng chữ ký chứng nhận khi giữ CERT_SIGNING_KEY."""
        tt = TicketType.objects.create(
            event=self.event, name="Vé Checkin", price=0, quota=10, sold=1
        )
        ticket = Ticket.objects.create(
            event=self.event,
            ticket_type=tt,
            user=self.member,
            status=TicketStatus.CHECKED_IN,
            price=0,
        )

        with override_settings(
            SECRET_KEY="old-django-session-secret-key-aaa",
            CERT_SIGNING_KEY="dedicated-kmg-cert-key-2026-permanent",
        ):
            token = cert_token(ticket)
            self.assertTrue(verify_cert_token(ticket.code, token))

        # Xoay vòng SECRET_KEY sang khóa hoàn toàn mới -> Chứng nhận A4 đã in vẫn xác thực thành công!
        with override_settings(
            SECRET_KEY="brand-new-rotated-django-secret-key-bbb",
            CERT_SIGNING_KEY="dedicated-kmg-cert-key-2026-permanent",
        ):
            self.assertTrue(verify_cert_token(ticket.code, token))

        # Kiểm tra Argon2id là thuật toán băm mặc định và tương thích ngược với bcrypt cũ
        self.assertTrue(self.member.password.startswith("argon2$argon2id$"))
        legacy_user = User.objects.create(
            username="legacy_bcrypt_user",
            password=make_password(
                "LegacyPass123", hasher=BCryptSHA256PasswordHasher()
            ),
        )
        self.assertTrue(legacy_user.password.startswith("bcrypt_sha256$"))
        self.assertTrue(
            Client().login(username="legacy_bcrypt_user", password="LegacyPass123")
        )
        legacy_user.refresh_from_db()
        # Sau khi đăng nhập thành công, Django tự động nâng cấp hash lên Argon2id!
        self.assertTrue(legacy_user.password.startswith("argon2$argon2id$"))
