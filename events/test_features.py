"""
Test cho chức năng Sprint 4-5 gắn với sự kiện: nhắc lịch (F7.2), file .ics
(F7.4), danh mục (F2.5), chứng nhận (F8.1-F8.2), ngân sách, lịch tháng.
"""
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from notifications.models import Notification, NotificationKind
from organizing.models import Expense
from registrations.models import Ticket, TicketStatus

from .models import Event, EventCategory, EventStatus, TicketType
from .services import (cert_token, event_ics, mask_mssv, send_event_reminders,
                       verify_certificate)


class Base(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.lead = User.objects.create_user(username="lead", password="x",
                                             full_name="Trưởng BTC", role=Role.LEAD)
        self.member = User.objects.create_user(
            username="tv", password="x", full_name="Nguyễn Văn A",
            mssv="2021123456", email="tv@x.vn", phone="0909000111")

    def make_event(self, hours=48, **kw):
        data = dict(name="Sự kiện", location="Phòng A",
                    starts_at=self.now + timezone.timedelta(hours=hours),
                    register_deadline=self.now + timezone.timedelta(hours=hours - 1),
                    status=EventStatus.OPEN, created_by=self.lead)
        data.update(kw)
        return Event.objects.create(**data)

    def ticket(self, event, user=None, status=TicketStatus.CONFIRMED, **kw):
        tt, _ = TicketType.objects.get_or_create(event=event, name="Thường",
                                                 defaults={"price": 0, "quota": 50})
        return Ticket.objects.create(event=event, ticket_type=tt, user=user or self.member,
                                     status=status, **kw)


# ---------------------------------------------------------------------------
# F7.2 - Nhắc lịch
# ---------------------------------------------------------------------------
class ReminderTests(Base):
    def run_reminders(self):
        with self.captureOnCommitCallbacks(execute=True):
            return send_event_reminders()

    def test_t7_2_1_event_in_20h_is_reminded(self):
        ev = self.make_event(20)
        self.ticket(ev)
        self.assertEqual(self.run_reminders(), 1)
        self.assertEqual(len(mail.outbox), 1)
        ev.refresh_from_db()
        self.assertIsNotNone(ev.reminder_sent_at)

    def test_t7_2_2_event_in_30h_not_yet(self):
        self.ticket(self.make_event(30))
        self.assertEqual(self.run_reminders(), 0)

    def test_t7_2_3_run_twice_sends_once(self):
        self.ticket(self.make_event(20))
        self.run_reminders()
        self.run_reminders()
        self.assertEqual(len(mail.outbox), 1)

    def test_t7_2_4_pending_ticket_not_reminded(self):
        self.ticket(self.make_event(20), status=TicketStatus.PENDING)
        self.run_reminders()
        self.assertEqual(len(mail.outbox), 0)

    def test_t7_2_5_three_tickets_one_mail(self):
        ev = self.make_event(20)
        for _ in range(3):
            self.ticket(ev)
        self.run_reminders()
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Notification.objects.filter(
            kind=NotificationKind.EVENT_REMINDER).count(), 1)

    def test_run_periodic_command(self):
        self.ticket(self.make_event(20))
        out = StringIO()
        call_command("run_periodic", stdout=out, stderr=out)
        self.assertNotIn("LỖI", out.getvalue())
        self.assertEqual(Event.objects.filter(reminder_sent_at__isnull=False).count(), 1)


# ---------------------------------------------------------------------------
# F7.4 - File lịch .ics
# ---------------------------------------------------------------------------
class IcsTests(Base):
    def test_t7_4_1_crlf(self):
        ics = event_ics(self.make_event())
        self.assertIn("\r\n", ics)
        self.assertNotIn("\n", ics.replace("\r\n", ""))

    def test_t7_4_2_escape_comma_semicolon(self):
        ev = self.make_event(name="Đêm nhạc, acoustic; số 5")
        self.assertIn("SUMMARY:Đêm nhạc\\, acoustic\\; số 5", event_ics(ev).replace("\r\n ", ""))

    def test_t7_4_3_lines_max_75_bytes_and_utf8(self):
        ev = self.make_event(name="Sự kiện có tên rất dài tiếng Việt " * 6,
                             description="Mô tả dài có dấu tiếng Việt. " * 40)
        raw = event_ics(ev).encode("utf-8")
        for line in raw.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)
        raw.decode("utf-8")   # không cắt giữa ký tự nhiều byte

    def test_t7_4_4_draft_hidden_from_guest(self):
        ev = self.make_event(status=EventStatus.DRAFT)
        r = self.client.get(reverse("events:ics", args=[ev.pk]))
        self.assertEqual(r.status_code, 404)

    def test_download_headers_and_utc(self):
        ev = self.make_event(status=EventStatus.CANCELLED)
        r = self.client.get(reverse("events:ics", args=[ev.pk]))
        self.assertEqual(r["Content-Type"], "text/calendar; charset=utf-8")
        self.assertIn(f'su-kien-{ev.pk}.ics', r["Content-Disposition"])
        body = r.content.decode()
        self.assertIn("STATUS:CANCELLED", body)
        self.assertRegex(body, r"DTSTART:\d{8}T\d{6}Z")

    def test_default_end_two_hours(self):
        ev = self.make_event()
        self.assertEqual(ev.effective_ends_at - ev.starts_at, timezone.timedelta(hours=2))


# ---------------------------------------------------------------------------
# F2.5 - Danh mục + lọc
# ---------------------------------------------------------------------------
class CategoryFilterTests(Base):
    def setUp(self):
        super().setUp()
        self.music = self.make_event(name="Nhạc hội", category=EventCategory.MUSIC)
        self.sport = self.make_event(name="Bóng đá", category=EventCategory.SPORT)
        self.old = self.make_event(name="Nhạc cũ", category=EventCategory.MUSIC,
                                   status=EventStatus.DONE, hours=-48)

    def names(self, **params):
        r = self.client.get(reverse("events:list"), params)
        self.assertEqual(r.status_code, 200)
        return {e.name for e in r.context["events"]}

    def test_filter_category(self):
        self.assertEqual(self.names(category="MUSIC"), {"Nhạc hội", "Nhạc cũ"})

    def test_combine_three_params(self):
        self.assertEqual(self.names(category="MUSIC", status="OPEN", q="hội"), {"Nhạc hội"})

    def test_when_upcoming_and_past(self):
        self.assertEqual(self.names(when="past"), {"Nhạc cũ"})
        self.assertNotIn("Nhạc cũ", self.names(when="upcoming"))

    def test_unknown_params_ignored(self):
        self.assertEqual(len(self.names(category="XYZ", status="???", when="abc")), 3)

    def test_ends_before_start_rejected(self):
        from .forms import EventForm
        f = EventForm(data={
            "name": "x", "category": "OTHER", "location": "y", "capacity": 10, "budget": 0,
            "starts_at": (self.now + timezone.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "ends_at": (self.now + timezone.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
            "register_deadline": (self.now + timezone.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"),
        })
        self.assertFalse(f.is_valid())
        self.assertIn("ends_at", f.errors)

    def test_draft_detail_hidden_from_member(self):
        ev = self.make_event(status=EventStatus.DRAFT)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(ev.get_absolute_url()).status_code, 404)

    def test_calendar_page(self):
        r = self.client.get(reverse("events:calendar"),
                            {"y": self.music.starts_at.year, "m": self.music.starts_at.month})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Nhạc hội")
        self.assertEqual(self.client.get(reverse("events:calendar"), {"m": "13"}).status_code, 200)


# ---------------------------------------------------------------------------
# F8.1 + F8.2 - Lịch sử tham gia & chứng nhận
# ---------------------------------------------------------------------------
class CertificateTests(Base):
    def setUp(self):
        super().setUp()
        self.done = self.make_event(hours=-48, status=EventStatus.DONE, name="Minishow")
        self.t = self.ticket(self.done, status=TicketStatus.CHECKED_IN,
                             checked_in_at=self.now - timezone.timedelta(hours=47))
        self.client.force_login(self.member)

    def test_t8_2_1_not_checked_in_404(self):
        other = User.objects.create_user(username="o", password="x")
        self.ticket(self.done, user=other)          # CONFIRMED, chưa check-in
        self.client.force_login(other)
        r = self.client.get(reverse("events:certificate", args=[self.done.pk]))
        self.assertEqual(r.status_code, 404)

    def test_t8_2_2_event_not_done_404(self):
        ev = self.make_event()
        self.ticket(ev, status=TicketStatus.CHECKED_IN)
        r = self.client.get(reverse("events:certificate", args=[ev.pk]))
        self.assertEqual(r.status_code, 404)

    def test_certificate_page(self):
        r = self.client.get(reverse("events:certificate", args=[self.done.pk]))
        self.assertContains(r, "GIẤY CHỨNG NHẬN")
        self.assertContains(r, "Nguyễn Văn A")
        self.assertContains(r, "Trưởng BTC")
        # Có in đường dẫn xác thực bằng chữ, không chỉ mỗi QR
        self.assertContains(r, f"/chungnhan/xacthuc/{self.t.code}/{cert_token(self.t)}/")

    def test_t8_2_3_valid_token(self):
        self.assertEqual(verify_certificate(self.t.code, cert_token(self.t)), self.t)

    def test_t8_2_4_tampered_token(self):
        token = cert_token(self.t)
        bad = ("A" if token[0] != "A" else "B") + token[1:]
        self.assertIsNone(verify_certificate(self.t.code, bad))
        self.client.logout()
        r = self.client.get(reverse("events:cert_verify", args=[self.t.code, bad]))
        self.assertContains(r, "Không xác thực được")

    def test_t8_2_5_public_page_minimal_data(self):
        self.client.logout()
        r = self.client.get(reverse("events:cert_verify", args=[self.t.code, cert_token(self.t)]))
        self.assertContains(r, "Chứng nhận hợp lệ")
        self.assertContains(r, "2021****56")
        self.assertNotContains(r, "2021123456")
        self.assertNotContains(r, "tv@x.vn")
        self.assertNotContains(r, "0909000111")

    def test_mask_mssv(self):
        self.assertEqual(mask_mssv("2021123456"), "2021****56")
        self.assertEqual(mask_mssv(""), "")

    def test_t8_1_profile_history(self):
        self.ticket(self.done, status=TicketStatus.CHECKED_IN)   # vé thứ 2 cùng sự kiện
        r = self.client.get(reverse("accounts:profile"))
        self.assertEqual(len(r.context["attended"]), 1)
        self.assertContains(r, "Minishow")
        self.assertEqual(r.context["stats"]["attended"], 1)


# ---------------------------------------------------------------------------
# Ngân sách
# ---------------------------------------------------------------------------
class BudgetTests(Base):
    def setUp(self):
        super().setUp()
        self.ev = self.make_event(budget=1_000_000)
        tt = TicketType.objects.create(event=self.ev, name="VIP", price=100000, quota=10)
        for status in (TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN, TicketStatus.PENDING):
            Ticket.objects.create(event=self.ev, ticket_type=tt, user=self.member,
                                  status=status, price=100000)
        Expense.objects.create(event=self.ev, title="Thuê loa", amount=300000, category="EQUIP")

    def test_summary(self):
        from .services import budget_summary
        s = budget_summary(self.ev)
        self.assertEqual((s["income"], s["pending_income"], s["spent"], s["balance"]),
                         (200000, 100000, 300000, -100000))
        self.assertEqual(s["budget_percent"], 30)

    def test_member_forbidden(self):
        self.client.force_login(self.member)
        r = self.client.get(reverse("organizing:budget", args=[self.ev.pk]))
        self.assertEqual(r.status_code, 403)

    def test_lead_crud_and_csv(self):
        self.client.force_login(self.lead)
        r = self.client.get(reverse("organizing:budget", args=[self.ev.pk]))
        self.assertContains(r, "Thuê loa")
        r = self.client.post(reverse("organizing:expense_create", args=[self.ev.pk]), {
            "title": "In poster", "category": "PRINT", "amount": 50000,
            "spent_on": timezone.localdate().isoformat(), "note": ""})
        self.assertEqual(r.status_code, 302)
        exp = Expense.objects.get(title="In poster")
        self.client.post(reverse("organizing:expense_delete", args=[exp.pk]))
        self.assertFalse(Expense.objects.filter(pk=exp.pk).exists())
        r = self.client.get(reverse("organizing:budget_csv", args=[self.ev.pk]))
        self.assertIn("Thuê loa", r.content.decode("utf-8-sig"))


class TaskAssignNotificationTests(Base):
    def test_notify_only_when_assignee_changes_and_not_self(self):
        from organizing.models import Task
        from organizing.services import save_task
        staff = User.objects.create_user(username="s", password="x", role=Role.STAFF)
        ev = self.make_event()
        t = Task(event=ev, title="Thuê loa", assignee=staff)
        with self.captureOnCommitCallbacks(execute=True):
            save_task(self.lead, t)
        self.assertEqual(Notification.objects.filter(user=staff).count(), 1)
        # Sửa mô tả, không đổi người -> không báo thêm
        t.description = "mới"
        with self.captureOnCommitCallbacks(execute=True):
            save_task(self.lead, t, old_assignee_id=staff.pk)
        self.assertEqual(Notification.objects.filter(user=staff).count(), 1)
        # Tự giao cho chính mình -> không báo
        t2 = Task(event=ev, title="Việc 2", assignee=self.lead)
        with self.captureOnCommitCallbacks(execute=True):
            save_task(self.lead, t2)
        self.assertFalse(Notification.objects.filter(user=self.lead).exists())


class CalendarBoundaryTests(Base):
    def test_month_uses_local_time(self):
        """00:30 ngày 1/11 giờ VN (= 17:30 ngày 31/10 UTC) phải thuộc tháng 11."""
        from datetime import datetime

        from .services import events_for_calendar
        tz = timezone.get_current_timezone()
        ev = self.make_event(name="Nửa đêm")
        Event.objects.filter(pk=ev.pk).update(starts_at=datetime(2030, 11, 1, 0, 30, tzinfo=tz))
        self.assertEqual([e.name for e in events_for_calendar(self.lead, 2030, 11)], ["Nửa đêm"])
        self.assertEqual(list(events_for_calendar(self.lead, 2030, 10)), [])
        self.assertEqual(list(events_for_calendar(self.lead, 2030, 12)), [])
