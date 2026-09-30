"""
Unit test cho M1 - Tài khoản & phân quyền.

Phần quan trọng nhất: F0.1 - gõ thẳng URL không thuộc quyền mình phải bị
chặn 403, không chỉ ẩn nút trên giao diện.
"""
from django.test import TestCase
from django.urls import reverse

from .models import Role, User


class RolePropertyTests(TestCase):
    """Kiểm tra quan hệ kế thừa quyền: Admin > Trưởng BTC > TV BTC > Thành viên."""

    def test_permission_hierarchy(self):
        member = User(role=Role.MEMBER)
        staff = User(role=Role.STAFF)
        lead = User(role=Role.LEAD)
        admin = User(role=Role.ADMIN)

        # is_staff_btc: TV BTC trở lên
        self.assertFalse(member.is_staff_btc)
        self.assertTrue(staff.is_staff_btc)
        self.assertTrue(lead.is_staff_btc)
        self.assertTrue(admin.is_staff_btc)

        # is_lead: Trưởng BTC trở lên
        self.assertFalse(staff.is_lead)
        self.assertTrue(lead.is_lead)
        self.assertTrue(admin.is_lead)

        # is_admin_role: chỉ Admin
        self.assertFalse(lead.is_admin_role)
        self.assertTrue(admin.is_admin_role)


class UrlPermissionTests(TestCase):
    """F0.1 - Phân quyền kiểm tra ở server."""

    def setUp(self):
        self.member = User.objects.create_user(
            username="tv", password="matkhau123", mssv="A1", role=Role.MEMBER)
        self.staff = User.objects.create_user(
            username="btc", password="matkhau123", mssv="A2", role=Role.STAFF)
        self.lead = User.objects.create_user(
            username="truong", password="matkhau123", mssv="A3", role=Role.LEAD)
        self.admin = User.objects.create_user(
            username="ad", password="matkhau123", mssv="A4", role=Role.ADMIN)

    def test_anonymous_is_redirected_to_login(self):
        """Chưa đăng nhập -> chuyển về trang login, không phải 403."""
        response = self.client.get(reverse("events:create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("dangnhap", response.url)

    def test_member_cannot_open_lead_pages(self):
        """Thành viên gõ URL tạo sự kiện -> 403 Forbidden."""
        self.client.login(username="tv", password="matkhau123")

        for url in (reverse("events:create"), reverse("events:dashboard")):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403,
                             f"URL {url} phải bị chặn với Thành viên")

    def test_staff_cannot_open_lead_pages(self):
        """TV BTC không được tạo sự kiện (đó là quyền Trưởng BTC)."""
        self.client.login(username="btc", password="matkhau123")
        response = self.client.get(reverse("events:create"))
        self.assertEqual(response.status_code, 403)

    def test_staff_can_open_payment_page(self):
        """TV BTC được vào trang xác nhận thanh toán."""
        self.client.login(username="btc", password="matkhau123")
        response = self.client.get(reverse("registrations:payment_list"))
        self.assertEqual(response.status_code, 200)

    def test_lead_can_open_lead_pages(self):
        self.client.login(username="truong", password="matkhau123")
        response = self.client.get(reverse("events:create"))
        self.assertEqual(response.status_code, 200)

    def test_only_admin_can_manage_accounts(self):
        """Trang quản lý tài khoản chỉ Admin vào được."""
        self.client.login(username="truong", password="matkhau123")
        self.assertEqual(
            self.client.get(reverse("accounts:user_list")).status_code, 403)

        self.client.login(username="ad", password="matkhau123")
        self.assertEqual(
            self.client.get(reverse("accounts:user_list")).status_code, 200)

    def test_locked_account_is_blocked(self):
        """
        Tài khoản bị khoá -> không vào được dù đúng role.

        LockedUserMiddleware đăng xuất ngay và chuyển về trang đăng nhập (chặt
        hơn 403: phiên bị huỷ nên mọi trang khác cũng không dùng được nữa).
        """
        self.lead.is_locked = True
        self.lead.save()

        self.client.force_login(self.lead)
        response = self.client.get(reverse("events:create"))
        self.assertRedirects(response, reverse("accounts:login"),
                             fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)


class PasswordHashTests(TestCase):
    """Mật khẩu phải được băm, không lưu thô."""

    def test_password_is_hashed(self):
        user = User.objects.create_user(username="x", password="matkhau123",
                                        mssv="A9")
        self.assertNotEqual(user.password, "matkhau123")
        # Băm chậm có salt: bcrypt hoặc pbkdf2, KHÔNG phải md5/sha1
        self.assertTrue(user.password.startswith(("bcrypt", "pbkdf2")))
        self.assertTrue(user.check_password("matkhau123"))
