from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib.auth.tokens import default_token_generator
from accounts.models import User, Role, AuditLog

class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tv", password="matkhau123", email="tv@kmgclub.local", mssv="A1", role=Role.MEMBER
        )

    def test_t141_email_exists(self):
        # T1.4.1
        response = self.client.post(reverse("accounts:password_reset"), {"email": "tv@kmgclub.local"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/taikhoan/datlai/", mail.outbox[0].body)

    def test_t142_email_not_exists(self):
        # T1.4.2
        response = self.client.post(reverse("accounts:password_reset"), {"email": "notfound@kmgclub.local"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_t143_locked_account(self):
        # T1.4.3
        self.user.is_locked = True
        self.user.save()
        response = self.client.post(reverse("accounts:password_reset"), {"email": "tv@kmgclub.local"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_t144_reset_password(self):
        # T1.4.4
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token})
        
        # Django redirects to set-password
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        redirect_url = response.url
        
        response = self.client.post(redirect_url, {"new_password1": "matkhaumoi", "new_password2": "matkhaumoi"})
        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        
        # Check login works
        self.assertTrue(self.client.login(username="tv", password="matkhaumoi"))
        
        # Check audit log
        self.assertTrue(AuditLog.objects.filter(user=self.user, action="Đặt lại mật khẩu").exists())

    def test_t145_reuse_token(self):
        # T1.4.5
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        url = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uidb64, "token": token})
        
        response = self.client.get(url)
        redirect_url = response.url
        
        # Reset once
        self.client.post(redirect_url, {"new_password1": "matkhaumoi", "new_password2": "matkhaumoi"})
        
        # Try again using original URL
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200) # Invalid token page
        self.assertIn("không hợp lệ", response.content.decode('utf-8'))

    def test_t146_rate_limit(self):
        # T1.4.6
        for _ in range(6):
            self.client.post(reverse("accounts:password_reset"), {"email": "tv@kmgclub.local"})
        self.assertEqual(len(mail.outbox), 5)

    def test_t147_case_insensitive_email(self):
        # T1.4.7
        response = self.client.post(reverse("accounts:password_reset"), {"email": "TV@KMGCLUB.LOCAL"})
        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
