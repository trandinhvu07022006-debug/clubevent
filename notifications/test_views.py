"""F7.3 - Chuông thông báo (T7.3.x) + kiểm tra khói: mọi trang chính render được."""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType
from registrations.models import Ticket, TicketStatus

from .models import Notification, NotificationKind


class BellTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user(username="u", password="x")
        self.other = User.objects.create_user(username="o", password="x")
        for i in range(12):
            Notification.objects.create(user=self.u, kind=NotificationKind.TASK_ASSIGNED,
                                        title=f"TB {i}", message="m", url="/ve/cua-toi/")
        self.client.force_login(self.u)

    def test_t7_3_1_badge_count(self):
        r = self.client.get(reverse("notifications:list"))
        self.assertEqual(r.context["unread_count"], 12)
        self.assertContains(r, "9+")

    def test_t7_3_2_open_other_users_notification_404(self):
        n = Notification.objects.create(user=self.other, kind="TASK", title="x", message="y")
        r = self.client.post(reverse("notifications:open", args=[n.pk]))
        self.assertEqual(r.status_code, 404)
        n.refresh_from_db()
        self.assertFalse(n.is_read)

    def test_t7_3_3_no_open_redirect(self):
        n = Notification.objects.create(user=self.u, kind="TASK", title="x", message="y",
                                        url="https://evil.com/phish")
        r = self.client.post(reverse("notifications:open", args=[n.pk]))
        self.assertRedirects(r, reverse("notifications:list"), fetch_redirect_response=False)

    def test_open_marks_read_and_redirects(self):
        n = self.u.notifications.first()
        r = self.client.post(reverse("notifications:open", args=[n.pk]))
        self.assertRedirects(r, "/ve/cua-toi/", fetch_redirect_response=False)
        n.refresh_from_db()
        self.assertTrue(n.is_read)

    def test_open_requires_post(self):
        n = self.u.notifications.first()
        self.assertEqual(self.client.get(reverse("notifications:open", args=[n.pk])).status_code, 405)

    def test_read_all(self):
        self.client.post(reverse("notifications:read_all"))
        self.assertFalse(self.u.notifications.filter(is_read=False).exists())

    def test_t7_3_4_guest_home_no_notification_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.logout()
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("events:list"))
        self.assertFalse([q for q in ctx.captured_queries if "notification" in q["sql"]])


class SmokeTests(TestCase):
    """Mọi trang chính trả 200 với đúng vai trò — bắt lỗi template sớm."""

    def setUp(self):
        now = timezone.now()
        self.lead = User.objects.create_user(username="lead", password="x", role=Role.LEAD,
                                             full_name="Lead")
        self.ev = Event.objects.create(name="Ev", location="L", status=EventStatus.OPEN,
                                       starts_at=now + timezone.timedelta(days=3),
                                       register_deadline=now + timezone.timedelta(days=2),
                                       created_by=self.lead)
        tt = TicketType.objects.create(event=self.ev, name="T", price=20000, quota=1)
        self.t = Ticket.objects.create(event=self.ev, ticket_type=tt, user=self.lead,
                                       status=TicketStatus.PENDING, price=20000,
                                       booking_ref="ABCD2345")
        tt.sold = 1
        tt.save()
        self.client.force_login(self.lead)

    def test_pages(self):
        pk = self.ev.pk
        urls = [
            reverse("events:list"), reverse("events:detail", args=[pk]),
            reverse("events:calendar"), reverse("events:create"),
            reverse("events:update", args=[pk]), reverse("events:dashboard"),
            reverse("registrations:my_tickets"), reverse("registrations:my_tickets") + "?tab=history",
            reverse("registrations:print", args=[self.t.pk]),
            reverse("registrations:payment_list"), reverse("registrations:payment_list") + "?q=KMG+ABCD2345",
            reverse("registrations:participants", args=[pk]),
            reverse("registrations:participants", args=[pk]) + "?view=waitlist",
            reverse("registrations:checkin", args=[pk]),
            reverse("organizing:board", args=[pk]), reverse("organizing:budget", args=[pk]),
            reverse("organizing:expense_create", args=[pk]),
            reverse("notifications:list"), reverse("accounts:profile"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
