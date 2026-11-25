"""Chống dò mật khẩu ở /admin/login/ và trang đăng nhập của web."""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import User

PASSWORD = "Mat-khau-Dung-2026!"


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()   # bộ đếm nằm trong cache, không tự xoá giữa các test
        self.boss = User.objects.create_superuser(
            username="boss", email="boss@kmg.vn", password=PASSWORD,
            phone="0901234567")
        self.other = User.objects.create_user(
            username="other", email="other@kmg.vn", password=PASSWORD)

    def _try(self, url, username="boss", password="sai", ip="10.0.0.1"):
        return self.client.post(
            url, {"username": username, "password": password}, REMOTE_ADDR=ip)

    def _admin(self, **kwargs):
        return self._try("/admin/login/", **kwargs)

    def _web(self, **kwargs):
        return self._try(reverse("accounts:login"), **kwargs)

    def assertNotLoggedIn(self):
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_login_is_blocked_after_repeated_failures(self):
        for _ in range(10):
            self.assertEqual(self._admin().status_code, 200)
        self.assertEqual(self._admin().status_code, 429)
        # Đã bị khoá thì mật khẩu đúng cũng không vào được
        self.assertEqual(self._admin(password=PASSWORD).status_code, 429)
        self.assertNotLoggedIn()

    def test_changing_ip_does_not_bypass_account_limit(self):
        for i in range(10):
            self.assertEqual(self._web(ip=f"10.0.1.{i}").status_code, 200)
        blocked = self._web(ip="10.0.2.1", password=PASSWORD)
        self.assertEqual(blocked.status_code, 429)
        self.assertNotLoggedIn()

    def test_admin_and_web_share_one_account_budget(self):
        for _ in range(5):
            self._web()
            self._admin()
        self.assertEqual(self._web().status_code, 429)
        self.assertEqual(self._admin().status_code, 429)

    def test_every_way_of_naming_the_account_counts_together(self):
        names = ["boss", "BOSS", "boss@kmg.vn", "0901234567", "+84 901 234 567",
                 " boss ", "ｂｏｓｓ", "Boss@KMG.vn", "84901234567", "boss"]
        for name in names:
            self.assertEqual(self._web(username=name).status_code, 200, name)
        self.assertEqual(self._web(username="boss@kmg.vn").status_code, 429)

    def test_successful_login_resets_the_account_budget(self):
        for _ in range(9):
            self._web()
        self.assertEqual(self._web(password=PASSWORD).status_code, 302)
        self.client.logout()
        for _ in range(9):
            self.assertEqual(self._web(ip="10.0.3.1").status_code, 200)

    def test_one_locked_account_does_not_lock_others(self):
        for _ in range(11):
            self._web()
        response = self._web(username="other", password=PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_admin_login_has_ip_limit_across_accounts(self):
        for i in range(20):
            self.assertEqual(self._admin(username=f"ma{i}").status_code, 200)
        self.assertEqual(self._admin(username="ma-cuoi").status_code, 429)

    def test_viewing_the_admin_form_is_never_limited(self):
        for _ in range(25):
            self._admin()
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)

    def test_normal_admin_login_still_works(self):
        response = self._admin(password=PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
