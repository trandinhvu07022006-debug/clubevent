"""
Test trang công khai và Tổng quan theo vai trò.

Trọng tâm: ĐIỀU HƯỚNG đúng người - khách thấy website, người đăng nhập thấy
không gian của mình, và quyền vẫn được kiểm ở server (thành viên gõ
?space=org không vào được không gian tổ chức).
"""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Role, User
from events.models import Event, EventStatus, TicketType
from organizing.models import Department, Task
from registrations.models import Ticket, TicketStatus


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.now = timezone.now()
        mk = User.objects.create_user
        self.member = mk(username="tv", password="x", full_name="Hoàng Mai")
        self.staff = mk(username="btc", password="x", full_name="Lê Hương", role=Role.STAFF)
        self.lead = mk(username="lead", password="x", full_name="Trần Vũ", role=Role.LEAD)
        self.admin = mk(username="ad", password="x", full_name="Admin", role=Role.ADMIN)

    def make_event(self, hours=48, **kw):
        data = dict(name="Acoustic Night", location="Hội trường A2",
                    starts_at=self.now + timezone.timedelta(hours=hours),
                    register_deadline=self.now + timezone.timedelta(hours=hours - 1),
                    status=EventStatus.OPEN, created_by=self.lead)
        data.update(kw)
        return Event.objects.create(**data)


class PublicPagesTests(Base):
    def test_guest_sees_landing_with_two_paths(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse("pages:for_members"))
        self.assertContains(r, reverse("pages:for_organizers"))
        self.assertContains(r, 'class="site-nav')            # menu công khai
        self.assertNotContains(r, 'id="appSidebar"')          # không có sidebar app

    def test_landing_shows_real_upcoming_events_only(self):
        self.make_event(name="Sự kiện mở")
        self.make_event(name="Bản nháp bí mật", status=EventStatus.DRAFT)
        self.make_event(name="Đã qua", hours=-48)
        r = self.client.get("/")
        self.assertContains(r, "Sự kiện mở")
        self.assertNotContains(r, "Bản nháp bí mật")
        self.assertNotContains(r, "Đã qua")

    def test_numbers_hidden_when_empty(self):
        r = self.client.get("/")
        self.assertNotContains(r, "lượt check-in")

    def test_logged_in_home_redirects_to_dashboard(self):
        self.client.force_login(self.member)
        r = self.client.get("/")
        self.assertRedirects(r, reverse("pages:dashboard"))
        # Vẫn xem lại được trang giới thiệu khi muốn
        self.assertEqual(self.client.get("/?xem=1").status_code, 200)

    def test_audience_pages_render(self):
        Department.objects.create(name="Ban Hậu cần", slug="hau-can")
        for name in ("for_members", "for_organizers", "about"):
            r = self.client.get(reverse(f"pages:{name}"))
            self.assertEqual(r.status_code, 200, name)
        r = self.client.get(reverse("pages:for_organizers"))
        self.assertContains(r, "Ban Hậu cần")
        self.assertContains(r, 'id="vai-tro"')

    def test_about_shows_real_board_and_achievements(self):
        r = self.client.get(reverse("pages:about"))
        # Ban Quản trị 2026 - 2027 nạp sẵn bằng migration
        for name in ("Trần Nhật Hoàng", "Trần Đình Vũ", "Lưu Nhật Linh", "Phan Tiến Đạt"):
            self.assertContains(r, name)
        self.assertContains(r, "Trưởng ban Chuyên môn")
        self.assertContains(r, "The House Voice")
        self.assertContains(r, "Sing To Learn")
        self.assertContains(r, "CLB Guitar Học viện Kỹ thuật Mật mã")

    def test_home_shows_board_and_recruit_path(self):
        r = self.client.get("/")
        self.assertContains(r, "Ban Quản trị")
        self.assertContains(r, reverse("recruitment:home"))

    def test_event_list_moved_but_reachable(self):
        self.assertEqual(reverse("events:list"), "/sukien/")
        self.assertEqual(self.client.get("/sukien/").status_code, 200)

    def test_meta_tags_present(self):
        r = self.client.get("/")
        self.assertContains(r, 'property="og:title"')
        self.assertContains(r, 'name="description"')


class LoginRedirectTests(Base):
    def test_login_goes_to_dashboard(self):
        r = self.client.post(reverse("accounts:login"),
                             {"username": "tv", "password": "x"})
        self.assertRedirects(r, reverse("pages:dashboard"))

    def test_logout_goes_home(self):
        self.client.force_login(self.member)
        r = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(r, reverse("pages:home"))


class DashboardTests(Base):
    def get(self, user, space=None):
        self.client.force_login(user)
        url = reverse("pages:dashboard") + (f"?space={space}" if space else "")
        return self.client.get(url)

    def test_requires_login(self):
        r = self.client.get(reverse("pages:dashboard"))
        self.assertEqual(r.status_code, 302)

    def test_member_gets_personal_space_only(self):
        r = self.get(self.member)
        self.assertEqual(r.context["space"], "me")
        self.assertNotContains(r, "Chọn không gian")
        # Gõ thẳng ?space=org vẫn chỉ thấy cá nhân - quyền kiểm ở server
        r = self.get(self.member, "org")
        self.assertEqual(r.context["space"], "me")
        self.assertNotIn("task_counts", r.context)

    def test_staff_defaults_to_org_and_can_switch(self):
        r = self.get(self.staff)
        self.assertEqual(r.context["space"], "org")
        self.assertContains(r, "Việc của tôi")
        r = self.get(self.staff, "me")
        self.assertEqual(r.context["space"], "me")

    def test_staff_does_not_see_lead_or_admin_blocks(self):
        r = self.get(self.staff)
        self.assertNotIn("active_events", r.context)
        self.assertNotIn("role_rows", r.context)

    def test_lead_sees_active_events(self):
        self.make_event(name="Đang chuẩn bị", status=EventStatus.DRAFT)
        r = self.get(self.lead)
        self.assertContains(r, "Đang chuẩn bị")
        self.assertNotIn("role_rows", r.context)

    def test_admin_sees_accounts_and_logs(self):
        AuditLog.write(self.admin, "Gán vai trò", "tv")
        AuditLog.write(None, "Tự huỷ vé quá hạn", "vé X")   # log của hệ thống, user=None
        r = self.get(self.admin)
        self.assertContains(r, "Hệ thống")
        self.assertIn("role_rows", r.context)
        self.assertContains(r, "Hoạt động gần đây")

    def test_member_todo_pending_payment_and_feedback(self):
        paid = self.make_event(name="Có phí")
        tt = TicketType.objects.create(event=paid, name="Thường", price=50000, quota=10)
        Ticket.objects.create(event=paid, ticket_type=tt, user=self.member,
                              status=TicketStatus.PENDING, booking_ref="ABCD2345",
                              price=50000)
        past = self.make_event(name="Vừa diễn ra", hours=-24)
        tt2 = TicketType.objects.create(event=past, name="Thường", price=0, quota=10)
        Ticket.objects.create(event=past, ticket_type=tt2, user=self.member,
                              status=TicketStatus.CHECKED_IN)
        r = self.get(self.member)
        self.assertContains(r, "ABCD2345")
        self.assertContains(r, reverse("feedback:send", args=[past.pk]))

    def test_onboarding_tracks_profile(self):
        r = self.get(self.member)
        self.assertLess(r.context["steps_done"], r.context["steps_total"])

    def test_department_progress_on_org_space(self):
        d = Department.objects.create(name="Ban Truyền thông", slug="tt", lead=self.staff)
        Task.objects.create(title="Chờ nhận", department=d)
        r = self.get(self.staff)
        self.assertContains(r, "Ban Truyền thông")
        self.assertEqual(r.context["claimable_count"], 1)
        self.assertContains(r, "Trưởng Ban Truyền thông")


class SidebarNavigationTests(Base):
    """Mỗi vai trò chỉ thấy đúng nhóm menu của mình."""

    def nav(self, user):
        self.client.force_login(user)
        return self.client.get(reverse("events:list")).content.decode()

    def test_member_has_no_org_or_admin_menu(self):
        html = self.nav(self.member)
        self.assertIn("Cá nhân", html)
        self.assertNotIn(reverse("organizing:my_tasks"), html)
        self.assertNotIn(reverse("accounts:user_list"), html)

    def test_staff_has_org_menu_without_admin(self):
        html = self.nav(self.staff)
        self.assertIn(reverse("organizing:department_list"), html)
        self.assertNotIn(reverse("events:dashboard"), html)

    def test_admin_has_everything(self):
        html = self.nav(self.admin)
        for name in ("organizing:department_list", "events:dashboard",
                     "accounts:user_list", "accounts:audit_log"):
            self.assertIn(reverse(name), html)
