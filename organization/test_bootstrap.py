"""Khởi tạo pilot không được ghi đè dữ liệu người dùng hoặc đưa tài khoản mẫu vào."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import User
from events.models import Event
from organization.models import Department, Position


class PilotBootstrapTests(TestCase):
    def test_bootstrap_preserves_accounts_and_department_customization(self):
        user = User.objects.create_user(username="admin", password="A-real-pilot-password-72")
        old_password = user.password
        call_command("bootstrap_kmg", stdout=StringIO())
        dept = Department.objects.get(code="TECHNICAL")
        dept.name = "Ban Kỹ thuật đã xác nhận"
        dept.is_demo = False
        dept.save()
        call_command("bootstrap_kmg", stdout=StringIO())
        user.refresh_from_db()
        dept.refresh_from_db()
        self.assertEqual(user.password, old_password)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Department.objects.count(), 3)
        self.assertEqual(Position.objects.count(), 6)
        self.assertFalse(Event.objects.exists())
        self.assertEqual(dept.name, "Ban Kỹ thuật đã xác nhận")
        self.assertFalse(dept.is_demo)

    @override_settings(ALLOW_DEMO_SEED=False)
    def test_demo_commands_refused_before_any_writes(self):
        for command in ("seed_demo", "seed_kmg"):
            with self.subTest(command=command), self.assertRaises(CommandError):
                call_command(command, stdout=StringIO())
        self.assertFalse(User.objects.exists())
        self.assertFalse(Department.objects.exists())
        self.assertFalse(Event.objects.exists())

    @override_settings(ALLOW_DEMO_SEED=True)
    def test_kmg_demo_refuses_existing_real_account_and_rolls_back(self):
        user = User.objects.create_user(username="admin", password="Real-password-938")
        old_password = user.password
        with self.assertRaisesMessage(CommandError, "đã có mật khẩu khác"):
            call_command("seed_kmg", stdout=StringIO())
        user.refresh_from_db()
        self.assertEqual(user.password, old_password)
        self.assertFalse(user.is_superuser)
        self.assertFalse(Department.objects.exists())
