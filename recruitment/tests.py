"""
Test tuyển thành viên theo đợt.

Trọng tâm: tạo tài khoản online CHỈ là Khách (không làm loãng danh sách
thành viên); lên Thành viên phải qua đơn được duyệt; Trưởng ban chỉ duyệt
đơn vào Ban mình; mọi quyết định đều báo cho ứng viên.
"""
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from notifications.models import Notification, NotificationKind
from organizing.models import Department

from .models import Application, ApplicationStatus, RecruitmentRound
from .services import RecruitmentError, review_application


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        mk = User.objects.create_user
        self.lead = mk(username="lead", password="x", role=Role.LEAD, full_name="Phó CN")
        self.head_cm = mk(username="linh", password="x", role=Role.STAFF, full_name="Trưởng CM")
        self.staff = mk(username="btc", password="x", role=Role.STAFF)
        self.guest = mk(username="khach", password="x", role=Role.GUEST,
                        full_name="Phan Gia Huy", email="khach@x.vn", mssv="AT2")
        self.member = mk(username="tv", password="x", role=Role.MEMBER)
        self.cm = Department.objects.create(name="Ban Chuyên môn", slug="chuyen-mon",
                                            lead=self.head_cm)
        self.tt = Department.objects.create(name="Ban Truyền thông & Sự kiện",
                                            slug="truyen-thong-su-kien")
        self.round = RecruitmentRound.objects.create(
            name="Đợt HK1", opens_at=self.now - timezone.timedelta(days=1),
            closes_at=self.now + timezone.timedelta(days=5))

    def application(self, user=None, dept=None, **kw):
        return Application.objects.create(
            round=self.round, user=user or self.guest, department=dept or self.cm,
            strengths="Guitar", motivation="Thích chơi nhạc", **kw)

    def form_data(self, dept=None):
        return {"department": (dept or self.cm).pk, "strengths": "Guitar đệm hát",
                "level": "BASIC", "portfolio_url": "", "motivation": "Mê guitar"}


class RegisterIsGuestTests(Base):
    def test_online_signup_creates_guest_not_member(self):
        self.client.post(reverse("accounts:register"), {
            "affiliation": "KMA", "username": "moi", "full_name": "Người Mới", "mssv": "AT9",
            "email": "moi@x.vn", "password1": "Matkhau!2026x", "password2": "Matkhau!2026x"})
        user = User.objects.get(username="moi")
        self.assertEqual(user.role, Role.GUEST)
        self.assertFalse(user.is_club_member)

    def test_guest_can_still_open_event_list_and_tickets(self):
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse("events:list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("registrations:my_tickets")).status_code, 200)


class ApplyTests(Base):
    def test_public_page_shows_open_round(self):
        r = self.client.get(reverse("recruitment:home"))
        self.assertContains(r, "Đợt HK1")
        self.assertContains(r, "Ban Chuyên môn")

    def test_guest_applies(self):
        self.client.force_login(self.guest)
        r = self.client.post(reverse("recruitment:apply"), self.form_data())
        self.assertRedirects(r, reverse("recruitment:my_application"))
        app = Application.objects.get(user=self.guest)
        self.assertEqual((app.round, app.department, app.status),
                         (self.round, self.cm, ApplicationStatus.PENDING))

    def test_cannot_apply_twice_in_same_round(self):
        self.application()
        self.client.force_login(self.guest)
        self.client.post(reverse("recruitment:apply"), self.form_data(self.tt))
        self.assertEqual(Application.objects.filter(user=self.guest).count(), 1)

    def test_member_cannot_apply(self):
        self.client.force_login(self.member)
        self.client.post(reverse("recruitment:apply"), self.form_data())
        self.assertFalse(Application.objects.exists())

    def test_closed_round_rejects(self):
        self.round.closes_at = self.now - timezone.timedelta(minutes=1)
        self.round.save()
        self.client.force_login(self.guest)
        self.client.post(reverse("recruitment:apply"), self.form_data())
        self.assertFalse(Application.objects.exists())

    def test_department_must_be_open_in_round(self):
        self.round.departments.set([self.tt])
        self.client.force_login(self.guest)
        r = self.client.post(reverse("recruitment:apply"), self.form_data(self.cm))
        self.assertEqual(r.status_code, 200)       # lỗi form: Ban không có trong danh sách
        self.assertFalse(Application.objects.exists())

    def test_withdraw(self):
        app = self.application()
        self.client.force_login(self.guest)
        self.client.post(reverse("recruitment:withdraw", args=[app.pk]))
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.WITHDRAWN)

    def test_cannot_withdraw_others(self):
        app = self.application()
        self.client.force_login(self.staff)
        r = self.client.post(reverse("recruitment:withdraw", args=[app.pk]))
        self.assertEqual(r.status_code, 404)


class ReviewTests(Base):
    def review(self, actor, app, status, **kw):
        with self.captureOnCommitCallbacks(execute=True):
            return review_application(actor, app, status, **kw)

    def test_accept_promotes_guest_and_adds_to_department(self):
        app = self.application()
        self.review(self.lead, app, ApplicationStatus.ACCEPTED, note="Chào mừng!")
        self.guest.refresh_from_db()
        self.assertEqual(self.guest.role, Role.MEMBER)
        self.assertTrue(self.cm.members.filter(pk=self.guest.pk).exists())
        n = Notification.objects.get(user=self.guest)
        self.assertEqual(n.kind, NotificationKind.APPLICATION)
        self.assertEqual(len(mail.outbox), 1)

    def test_accept_never_demotes(self):
        self.guest.role = Role.STAFF
        self.guest.save()
        app = self.application()
        self.review(self.lead, app, ApplicationStatus.ACCEPTED)
        self.guest.refresh_from_db()
        self.assertEqual(self.guest.role, Role.STAFF)

    def test_interview_requires_time(self):
        app = self.application()
        with self.assertRaises(RecruitmentError):
            self.review(self.lead, app, ApplicationStatus.INTERVIEW)
        self.review(self.lead, app, ApplicationStatus.INTERVIEW,
                    interview_at=self.now + timezone.timedelta(days=1))
        app.refresh_from_db()
        self.assertEqual(app.status, ApplicationStatus.INTERVIEW)

    def test_reject_keeps_guest(self):
        app = self.application()
        self.review(self.lead, app, ApplicationStatus.REJECTED)
        self.guest.refresh_from_db()
        self.assertEqual(self.guest.role, Role.GUEST)

    def test_final_status_cannot_change(self):
        app = self.application(status=ApplicationStatus.REJECTED)
        with self.assertRaises(RecruitmentError):
            self.review(self.lead, app, ApplicationStatus.ACCEPTED)

    def test_department_head_reviews_only_own_department(self):
        mine = self.application()
        other_user = User.objects.create_user(username="g2", password="x", role=Role.GUEST)
        other = self.application(user=other_user, dept=self.tt)
        self.review(self.head_cm, mine, ApplicationStatus.ACCEPTED)
        with self.assertRaises(RecruitmentError):
            self.review(self.head_cm, other, ApplicationStatus.ACCEPTED)
        self.client.force_login(self.head_cm)
        r = self.client.get(reverse("recruitment:review_list"))
        self.assertContains(r, "Phan Gia Huy")
        self.assertNotContains(r, reverse("recruitment:review_detail", args=[other.pk]))
        r = self.client.get(reverse("recruitment:review_detail", args=[other.pk]))
        self.assertEqual(r.status_code, 404)

    def test_plain_staff_cannot_review(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("recruitment:review_list")).status_code, 403)

    def test_review_via_view(self):
        app = self.application()
        self.client.force_login(self.lead)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("recruitment:review_detail", args=[app.pk]),
                             {"status": "ACCEPTED", "note": "", "interview_at": ""})
        self.guest.refresh_from_db()
        self.assertEqual(self.guest.role, Role.MEMBER)

    def test_only_lead_opens_rounds(self):
        self.client.force_login(self.head_cm)
        self.assertEqual(self.client.get(reverse("recruitment:round_create")).status_code, 403)
        self.client.force_login(self.lead)
        r = self.client.post(reverse("recruitment:round_create"), {
            "name": "Đợt 2", "opens_at": "2026-12-01T08:00", "closes_at": "2026-11-01T08:00",
            "description": ""})
        self.assertEqual(r.status_code, 200)          # hạn trước ngày mở -> lỗi
        self.assertFalse(RecruitmentRound.objects.filter(name="Đợt 2").exists())


class NavigationTests(Base):
    def test_guest_sidebar_shows_apply_with_open_badge(self):
        self.client.force_login(self.guest)
        html = self.client.get(reverse("events:list")).content.decode()
        self.assertIn("Ứng tuyển thành viên", html)
        self.assertIn(">Mở<", html)

    def test_public_nav_has_create_account_not_join_club(self):
        html = self.client.get("/").content.decode()
        self.assertIn("Tạo tài khoản", html)
        self.assertIn("Tuyển thành viên", html)
        self.assertNotIn("Tham gia CLB", html)

    def test_reviewer_sees_pending_badge(self):
        self.application()
        self.client.force_login(self.head_cm)
        html = self.client.get(reverse("events:list")).content.decode()
        self.assertIn(reverse("recruitment:review_list"), html)

    def test_guest_dashboard_shows_application_status(self):
        self.application()
        self.client.force_login(self.guest)
        r = self.client.get(reverse("pages:dashboard"))
        self.assertContains(r, "Trở thành thành viên")
        self.assertContains(r, "Chờ duyệt")
