"""
Người ngoài Học viện (sinh viên trường khác, không phải sinh viên) cũng tạo
tài khoản và đặt vé được; MSSV chỉ bắt buộc với sinh viên Học viện.
"""
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from organizing.models import Department
from recruitment.models import Application, RecruitmentRound
from recruitment.services import KMA_ONLY_REASON, eligibility

from .models import Affiliation, Role, User

PW = "Matkhau!2026x"


def form(**kw):
    data = {"affiliation": "KMA", "username": "moi", "full_name": "Người Mới",
            "email": "moi@x.vn", "mssv": "", "school": "", "phone": "",
            "password1": PW, "password2": PW}
    data.update(kw)
    return data


class RegisterAffiliationTests(TestCase):
    def post(self, **kw):
        return self.client.post(reverse("accounts:register"), form(**kw))

    def test_public_registers_without_mssv(self):
        r = self.post(affiliation="PUBLIC")
        # Khách mới đăng ký được chuyển sang nhập mã OTP xác minh email (F1.7)
        self.assertRedirects(r, reverse("accounts:verify_email"))
        u = User.objects.get(username="moi")
        self.assertEqual((u.affiliation, u.mssv, u.role), ("PUBLIC", None, Role.GUEST))

    def test_two_people_without_mssv_do_not_collide(self):
        """MSSV trống lưu NULL: cột unique cho nhiều NULL, nhưng chỉ một chuỗi rỗng."""
        self.post(affiliation="PUBLIC")
        self.client.logout()
        self.post(affiliation="OTHER", username="moi2", email="moi2@x.vn",
                  school="ĐH Bách khoa")
        self.assertEqual(User.objects.filter(mssv__isnull=True).count(), 2)
        self.assertEqual(User.objects.get(username="moi2").school, "ĐH Bách khoa")

    def test_kma_student_must_give_mssv(self):
        r = self.post(affiliation="KMA")
        self.assertContains(r, "Sinh viên Học viện vui lòng nhập MSSV.")
        self.assertFalse(User.objects.filter(username="moi").exists())

    def test_kma_student_with_mssv(self):
        self.post(affiliation="KMA", mssv="at210099")
        self.assertEqual(User.objects.get(username="moi").mssv, "AT210099")

    def test_outsider_mssv_is_not_stored(self):
        """Người ngoài gõ mã SV trường họ -> không lưu, khỏi chiếm MSSV của SV Học viện."""
        self.post(affiliation="OTHER", mssv="AT210099")
        self.assertIsNone(User.objects.get(username="moi").mssv)

    def test_phone_and_school_optional(self):
        r = self.post(affiliation="OTHER")
        self.assertEqual(r.status_code, 302)

    def test_register_page_shows_three_choices(self):
        r = self.client.get(reverse("accounts:register"))
        for label in Affiliation.labels:
            self.assertContains(r, label)
        self.assertContains(r, "(không bắt buộc)")


class ProfileAffiliationTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="x", password="x", full_name="X",
                                          affiliation="PUBLIC")
        self.client.force_login(self.u)

    def test_switch_to_kma_requires_mssv(self):
        r = self.client.post(reverse("accounts:profile"),
                             {"full_name": "X", "affiliation": "KMA", "mssv": "", "school": "", "phone": ""})
        self.assertContains(r, "vui lòng nhập MSSV")
        self.client.post(reverse("accounts:profile"),
                         {"full_name": "X", "affiliation": "KMA", "mssv": "AT1", "school": "", "phone": ""})
        self.u.refresh_from_db()
        self.assertEqual((self.u.affiliation, self.u.mssv), ("KMA", "AT1"))

    def test_keep_own_mssv_is_not_duplicate(self):
        self.u.affiliation, self.u.mssv = "KMA", "AT5"
        self.u.save()
        r = self.client.post(reverse("accounts:profile"),
                             {"full_name": "Y", "affiliation": "KMA", "mssv": "AT5", "school": "", "phone": ""})
        self.assertEqual(r.status_code, 302)


class RecruitmentForOutsidersTests(TestCase):
    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.round = RecruitmentRound.objects.create(
            name="Đợt 1", opens_at=now - timezone.timedelta(days=1),
            closes_at=now + timezone.timedelta(days=3))
        self.dept = Department.objects.create(name="Ban Chuyên môn", slug="chuyen-mon")

    def test_outsider_cannot_apply_but_kma_can(self):
        outsider = User.objects.create_user(username="o", password="x", role=Role.GUEST,
                                            affiliation="OTHER")
        kma = User.objects.create_user(username="k", password="x", role=Role.GUEST, mssv="AT9")
        self.assertEqual(eligibility(outsider, self.round), KMA_ONLY_REASON)
        self.assertEqual(eligibility(kma, self.round), "")
        self.client.force_login(outsider)
        self.client.post(reverse("recruitment:apply"), {
            "department": self.dept.pk, "strengths": "Guitar", "level": "BASIC",
            "portfolio_url": "", "motivation": "x"})
        self.assertFalse(Application.objects.exists())

    def test_kma_without_mssv_is_asked_to_update_profile(self):
        u = User.objects.create_user(username="k2", password="x", role=Role.GUEST)
        self.assertEqual(eligibility(u, self.round), KMA_ONLY_REASON)
        self.client.force_login(u)
        r = self.client.get(reverse("recruitment:home"))
        self.assertContains(r, "Cập nhật hồ sơ")

    @override_settings(RECRUIT_KMA_ONLY=False)
    def test_setting_opens_recruitment_to_everyone(self):
        outsider = User.objects.create_user(username="o", password="x", role=Role.GUEST,
                                            affiliation="PUBLIC")
        self.assertEqual(eligibility(outsider, self.round), "")

    def test_outsider_dashboard_explains(self):
        outsider = User.objects.create_user(username="o", password="x", role=Role.GUEST,
                                            affiliation="PUBLIC")
        self.client.force_login(outsider)
        r = self.client.get(reverse("pages:dashboard"))
        self.assertContains(r, "dành cho sinh viên Học viện")
