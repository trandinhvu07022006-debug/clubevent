"""F1.7 - Xác minh email bằng OTP trước khi Khách được đặt vé."""
import re

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventStatus, TicketType
from registrations.models import Ticket
from registrations.services import EmailNotVerified, book_tickets, join_waitlist

from .models import EmailOTP, Role, User, canonical_email
from .services import OTPError, send_email_otp, verify_email_otp


def code_in_last_mail():
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def wrong(code):
    return f"{(int(code) + 1) % 10 ** 6:06d}"


class OTPBase(TestCase):
    def setUp(self):
        now = timezone.now()
        self.guest = User.objects.create_user(
            username="khach", password="x", full_name="Khách", email="khach@x.vn",
            role=Role.GUEST, affiliation="PUBLIC")
        self.event = Event.objects.create(
            name="Đêm nhạc", location="Hội trường",
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4),
            capacity=100, status=EventStatus.OPEN)
        self.tt = TicketType.objects.create(event=self.event, name="Thường",
                                            price=0, quota=10)

    def age_otps(self, seconds):
        """Lùi giờ gửi của các mã để giả lập thời gian trôi qua."""
        EmailOTP.objects.update(
            created_at=timezone.now() - timezone.timedelta(seconds=seconds))


class BookingGateTests(OTPBase):
    def test_unverified_guest_cannot_book(self):
        with self.assertRaises(EmailNotVerified):
            book_tickets(self.guest, self.tt.pk, 1)
        self.tt.refresh_from_db()
        self.assertEqual(self.tt.sold, 0)

    def test_unverified_guest_cannot_join_waitlist(self):
        self.tt.sold = self.tt.quota
        self.tt.save()
        with self.assertRaises(EmailNotVerified):
            join_waitlist(self.guest, self.tt.pk)

    def test_member_needs_no_verification(self):
        member = User.objects.create_user(username="tv", password="x", role=Role.MEMBER)
        self.assertEqual(len(book_tickets(member, self.tt.pk, 1)), 1)

    def test_verified_guest_can_book(self):
        self.guest.email_verified_at = timezone.now()
        self.guest.save()
        self.assertEqual(len(book_tickets(self.guest, self.tt.pk, 1)), 1)

    @override_settings(REQUIRE_EMAIL_OTP=False)
    def test_setting_off_skips_verification(self):
        self.assertEqual(len(book_tickets(self.guest, self.tt.pk, 1)), 1)


class VerifyServiceTests(OTPBase):
    def test_code_is_hashed_and_correct_code_verifies(self):
        otp = send_email_otp(self.guest)
        code = code_in_last_mail()
        self.assertNotIn(code, otp.code_hash)
        verify_email_otp(self.guest, code)
        self.guest.refresh_from_db()
        self.assertIsNotNone(self.guest.email_verified_at)
        self.assertFalse(self.guest.needs_email_verification)

    def test_code_cannot_be_reused(self):
        send_email_otp(self.guest)
        code = code_in_last_mail()
        verify_email_otp(self.guest, code)
        self.guest.email_verified_at = None
        self.guest.save()
        with self.assertRaises(OTPError):
            verify_email_otp(self.guest, code)

    def test_wrong_code_counts_attempts_then_burns(self):
        send_email_otp(self.guest)
        code = code_in_last_mail()
        for _ in range(5):
            with self.assertRaises(OTPError):
                verify_email_otp(self.guest, wrong(code))
        # Đã sai 5 lần: mã đúng cũng không còn dùng được
        with self.assertRaises(OTPError):
            verify_email_otp(self.guest, code)
        self.guest.refresh_from_db()
        self.assertIsNone(self.guest.email_verified_at)

    def test_expired_code_rejected(self):
        send_email_otp(self.guest)
        code = code_in_last_mail()
        self.age_otps(11 * 60)
        with self.assertRaises(OTPError):
            verify_email_otp(self.guest, code)

    def test_new_code_invalidates_old_one(self):
        send_email_otp(self.guest)
        old = code_in_last_mail()
        self.age_otps(61)
        send_email_otp(self.guest)
        new = code_in_last_mail()
        if old != new:
            with self.assertRaises(OTPError):
                verify_email_otp(self.guest, old)
        verify_email_otp(self.guest, new)

    def test_resend_cooldown(self):
        send_email_otp(self.guest)
        with self.assertRaisesMessage(OTPError, "chờ"):
            send_email_otp(self.guest)
        self.assertEqual(len(mail.outbox), 1)

    def test_hourly_cap(self):
        for _ in range(5):
            send_email_otp(self.guest)
            self.age_otps(61)
        with self.assertRaisesMessage(OTPError, "quá nhiều"):
            send_email_otp(self.guest)

    def test_smtp_failure_does_not_consume_quota(self):
        with override_settings(EMAIL_BACKEND="no.such.Backend"):
            with self.assertRaises(OTPError):
                send_email_otp(self.guest)
        self.assertFalse(EmailOTP.objects.exists())
        send_email_otp(self.guest)          # thử lại ngay được, không bị bắt chờ


class VerifyViewTests(OTPBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.guest)
        self.url = reverse("accounts:verify_email")

    def test_book_redirects_to_verify_and_sends_code(self):
        r = self.client.post(reverse("registrations:book", args=[self.event.pk]),
                             {"ticket_type": self.tt.pk, "quantity": 1})
        self.assertTrue(r.url.startswith(self.url))
        self.assertEqual(len(mail.outbox), 1)
        self.assertFalse(Ticket.objects.exists())

        # Nhập mã xong quay về trang sự kiện, đặt vé được
        r = self.client.post(self.url, {"action": "verify", "code": code_in_last_mail(),
                                        "next": self.event.get_absolute_url()})
        self.assertRedirects(r, self.event.get_absolute_url(), fetch_redirect_response=False)
        self.client.post(reverse("registrations:book", args=[self.event.pk]),
                         {"ticket_type": self.tt.pk, "quantity": 1})
        self.assertEqual(Ticket.objects.filter(user=self.guest).count(), 1)

    def test_open_redirect_blocked(self):
        send_email_otp(self.guest)
        r = self.client.post(self.url, {"action": "verify", "code": code_in_last_mail(),
                                        "next": "https://evil.example/"})
        self.assertEqual(r.url, reverse("pages:dashboard"))

    def test_already_verified_says_so(self):
        self.guest.email_verified_at = timezone.now()
        self.guest.save()
        r = self.client.post(self.url, {"action": "send"}, follow=True)
        self.assertContains(r, "đã được xác minh")
        self.assertEqual(len(mail.outbox), 0)

    def test_page_renders(self):
        self.assertContains(self.client.get(self.url), "Gửi mã")
        send_email_otp(self.guest)
        self.assertContains(self.client.get(self.url), "one-time-code")

    def test_register_sends_code(self):
        self.client.logout()
        r = self.client.post(reverse("accounts:register"), {
            "affiliation": "PUBLIC", "full_name": "Người mới", "username": "moi",
            "email": "moi@x.vn", "password1": "MatKhau@2026x", "password2": "MatKhau@2026x"})
        self.assertRedirects(r, self.url, fetch_redirect_response=False)
        self.assertEqual(mail.outbox[-1].to, ["moi@x.vn"])
        self.assertTrue(User.objects.get(username="moi").needs_email_verification)


class CanonicalEmailTests(TestCase):
    """Chặn một hộp thư tạo nhiều tài khoản bằng dấu chấm / dấu + (Gmail)."""

    def test_normalisation(self):
        cases = {
            "Abc@Gmail.com": "abc@gmail.com",
            "a.b.c+ve1@gmail.com": "abc@gmail.com",
            "abc@googlemail.com": "abc@gmail.com",
            "an.nguyen+x@kma.edu.vn": "an.nguyen@kma.edu.vn",  # chỉ Gmail mới bỏ dấu chấm
            "": "",
        }
        for raw, expected in cases.items():
            self.assertEqual(canonical_email(raw), expected, raw)

    def test_saved_automatically(self):
        u = User.objects.create_user(username="u", password="x", email="A.B+1@gmail.com")
        self.assertEqual(u.email_canonical, "ab@gmail.com")
        u.email = "c@x.vn"
        u.save(update_fields=["email"])
        u.refresh_from_db()
        self.assertEqual(u.email_canonical, "c@x.vn")

    def test_register_rejects_alias_of_existing_mailbox(self):
        User.objects.create_user(username="goc", password="x", email="vecho@gmail.com")
        for alias in ("ve.cho@gmail.com", "vecho+2@gmail.com", "VeCho@googlemail.com"):
            r = self.client.post(reverse("accounts:register"), {
                "affiliation": "PUBLIC", "full_name": "Phe vé", "username": "phe",
                "email": alias, "password1": "MatKhau@2026x", "password2": "MatKhau@2026x"})
            self.assertEqual(r.status_code, 200, alias)
            self.assertContains(r, "Hộp thư này đã có tài khoản")
        self.assertFalse(User.objects.filter(username="phe").exists())
