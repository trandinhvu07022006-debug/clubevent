"""Phase 6 QA coverage tests for accounts.sms and accounts.services (OTP, sessions, post-login routing)."""
from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts import sms
from accounts.models import AccountStatus, OtpChannel, Role, UserSession
from accounts.services import (
    OtpVerificationError,
    _describe_device,
    issue_otp_challenge,
    record_login_session,
    resolve_post_login_url,
    revoke_all_other_sessions,
    revoke_user_session,
    select_default_otp_channel,
    verify_otp_challenge,
)

User = get_user_model()


class SmsGatewayTests(TestCase):
    @override_settings(SMS_PROVIDER="console", SMS_SENDER_ID="KMG-TEST")
    def test_console_sms_outbox_and_clear(self):
        self.assertFalse(sms.send_sms_otp("", "123456"))
        ok = sms.send_sms_otp("+84 901 234 567", "654321")
        self.assertTrue(ok)
        self.assertEqual(len(sms.SMS_OUTBOX), 1)
        self.assertEqual(sms.SMS_OUTBOX[0]["to"], "0901234567")
        self.assertEqual(sms.SMS_OUTBOX[0]["code"], "654321")
        sms.clear_sms_outbox()
        self.assertEqual(sms.SMS_OUTBOX, [])

    @override_settings(SMS_PROVIDER="unknown")
    def test_unsupported_sms_provider_returns_false(self):
        self.assertFalse(sms.send_sms_otp("0901234567", "111111"))

    @override_settings(SMS_PROVIDER="webhook", SMS_WEBHOOK_URL="", SMS_API_KEY="k")
    def test_webhook_missing_url_returns_false(self):
        self.assertFalse(sms.send_sms_otp("0901234567", "111111"))

    @override_settings(SMS_PROVIDER="webhook", SMS_WEBHOOK_URL="https://sms.example/send", SMS_API_KEY="sec")
    def test_webhook_success_and_network_failure(self):
        captured = {}

        class _OkResp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_open(req, timeout=8):
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _OkResp()

        with patch("accounts.sms.urllib.request.urlopen", side_effect=fake_open):
            self.assertTrue(sms.send_sms_otp("0901234567", "222333"))
        self.assertEqual(captured["headers"]["Authorization"], "Bearer sec")
        self.assertEqual(captured["body"]["otp"], "222333")

        with patch("accounts.sms.urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            self.assertFalse(sms.send_sms_otp("0901234567", "222333"))


class AccountOtpAndSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="p6_acc",
            email="p6_acc@kma.edu.vn",
            phone="0912345678",
            password="x",
            role=Role.GUEST,
            account_status=AccountStatus.UNVERIFIED,
        )

    @override_settings(SMS_PROVIDER="console")
    def test_otp_channel_selection_sms_verify_and_lockout(self):
        no_contact = User.objects.create_user("nocontact", password="x")
        with self.assertRaises(OtpVerificationError):
            select_default_otp_channel(no_contact)

        with override_settings(OTP_MAX_ATTEMPTS=2):
            with patch("accounts.services.secrets.randbelow", return_value=123456):
                ch, _ = issue_otp_challenge(self.user, channel=OtpChannel.SMS)
            self.assertEqual(ch.channel, OtpChannel.SMS)

            with self.assertRaises(OtpVerificationError):
                verify_otp_challenge(self.user, "000000", channel=OtpChannel.SMS)
            with self.assertRaises(OtpVerificationError) as ctx:
                verify_otp_challenge(self.user, "000000", channel=OtpChannel.SMS)
            self.assertEqual(ctx.exception.code, "OTP_LOCKED")

        # Re-issue and verify cleanly activates account
        with patch("accounts.services.secrets.randbelow", return_value=654321):
            issue_otp_challenge(self.user, channel=OtpChannel.EMAIL)
        verified = verify_otp_challenge(self.user, "654321", channel=OtpChannel.EMAIL)
        self.assertEqual(verified.channel, OtpChannel.EMAIL)
        self.user.refresh_from_db()
        self.assertEqual(self.user.account_status, AccountStatus.ACTIVE)

    def test_device_description_session_recording_and_revocation(self):
        self.assertEqual(_describe_device(""), "Trình duyệt Web")
        self.assertEqual(_describe_device("Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"), "Chrome trên Windows")
        self.assertEqual(_describe_device("Mozilla/5.0 (Linux; Android 14) Edg/120.0"), "Edge trên Android")
        self.assertEqual(_describe_device("Mozilla/5.0 (iPhone) Safari/605.1"), "Safari trên iOS")
        self.assertEqual(_describe_device("Mozilla/5.0 (Macintosh) Firefox/122.0"), "Firefox trên macOS")

        self.client.force_login(self.user)
        req1 = RequestFactory().get("/", HTTP_USER_AGENT="Mozilla/5.0 Chrome/120.0 Windows")
        req1.session = self.client.session
        s1 = record_login_session(req1, self.user)
        self.assertIsNotNone(s1)

        s2 = UserSession.objects.create(
            user=self.user, session_key="other_sess_key", device_label="Other", ip_address="127.0.0.1"
        )
        revoked_count = revoke_all_other_sessions(self.user, s1.session_key)
        self.assertEqual(revoked_count, 1)
        s2.refresh_from_db()
        self.assertIsNotNone(s2.revoked_at)

        revoke_user_session(self.user, s1, reason="Test revoke")
        s1.refresh_from_db()
        self.assertIsNotNone(s1.revoked_at)

    def test_resolve_post_login_url_admin_and_default(self):
        admin = User.objects.create_user("p6_admin", password="x", role=Role.ADMIN, account_status=AccountStatus.ACTIVE)
        self.assertEqual(resolve_post_login_url(admin), reverse("accounts:user_list"))
        self.assertTrue(resolve_post_login_url(self.user).startswith("/"))
