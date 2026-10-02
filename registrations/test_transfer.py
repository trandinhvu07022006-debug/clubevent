"""F5.5 - Vé ghi danh (đối chiếu giấy tờ) và F4.10 - Chuyển nhượng vé."""
import json

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Role, User
from events.models import Event, EventStatus, TicketType

from .models import Ticket, TicketStatus, TicketTransfer
from .services import (CHECKIN_INVALID, CHECKIN_OK, CHECKIN_VERIFY, BookingError,
                       check_in, reject_id_check, transfer_ticket)


class Base(TestCase):
    def setUp(self):
        self.now = timezone.now()
        mk = User.objects.create_user
        self.staff = mk(username="btc", password="x", full_name="BTC", role=Role.STAFF)
        self.owner = mk(username="an", password="x", full_name="Nguyễn An",
                        email="an@x.vn", email_verified_at=self.now)
        self.friend = mk(username="binh", password="x", full_name="Trần Bình",
                         email="binh.tran@gmail.com", email_verified_at=self.now)
        self.event = self.make_event()
        self.tt = TicketType.objects.create(event=self.event, name="Thường",
                                            price=50000, quota=50, sold=1)
        self.ticket = self.make_ticket(self.owner)

    def make_event(self, days=5, **kw):
        return Event.objects.create(
            name="Đêm nhạc", location="Hội trường",
            starts_at=self.now + timezone.timedelta(days=days),
            register_deadline=self.now + timezone.timedelta(days=days - 1),
            capacity=100, status=EventStatus.OPEN, **kw)

    def make_ticket(self, user, status=TicketStatus.CONFIRMED, event=None):
        event = event or self.event
        tt = self.tt if event == self.event else TicketType.objects.create(
            event=event, name="Thường", price=0, quota=50)
        return Ticket.objects.create(event=event, ticket_type=tt, user=user,
                                     price=tt.price, status=status)


class IdCheckTests(Base):
    def setUp(self):
        super().setUp()
        self.event.require_id_check = True
        self.event.save()

    def test_valid_ticket_waits_for_id_check(self):
        result, ticket, _ = check_in(self.staff, self.ticket.code, event=self.event)
        self.assertEqual(result, CHECKIN_VERIFY)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.CONFIRMED)

    def test_confirm_checks_in(self):
        result, _, _ = check_in(self.staff, self.ticket.code, event=self.event,
                                id_confirmed=True)
        self.assertEqual(result, CHECKIN_OK)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.CHECKED_IN)
        self.assertTrue(AuditLog.objects.filter(
            action="Check-in", note__contains="đối chiếu giấy tờ").exists())

    def test_reject_logs_and_keeps_ticket(self):
        result, note = reject_id_check(self.staff, self.ticket.code, self.event)
        self.assertEqual(result, CHECKIN_INVALID)
        self.assertIn("Nguyễn An", note)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.CONFIRMED)
        self.assertTrue(AuditLog.objects.filter(action="Từ chối check-in").exists())

    def test_invalid_ticket_is_rejected_before_id_check(self):
        self.ticket.status = TicketStatus.PENDING
        self.ticket.save()
        result, _, _ = check_in(self.staff, self.ticket.code, event=self.event)
        self.assertEqual(result, CHECKIN_INVALID)

    def test_event_without_flag_checks_in_directly(self):
        ev = self.make_event()
        t = self.make_ticket(self.owner, event=ev)
        self.assertEqual(check_in(self.staff, t.code, event=ev)[0], CHECKIN_OK)

    def test_scan_api_two_steps(self):
        self.client.force_login(self.staff)
        url = reverse("registrations:checkin_scan", args=[self.event.pk])
        post = lambda body: self.client.post(url, json.dumps(body),
                                             content_type="application/json").json()
        data = post({"code": self.ticket.code})
        self.assertEqual(data["result"], "VERIFY")
        self.assertEqual(data["ticket"]["user_name"], "Nguyễn An")
        self.assertIn("affiliation", data["ticket"])
        self.assertEqual(post({"code": self.ticket.code, "decision": "confirm"})["result"], "OK")

    def test_checkin_page_shows_decision_buttons(self):
        self.client.force_login(self.staff)
        url = reverse("registrations:checkin", args=[self.event.pk])
        r = self.client.post(url, {"code": self.ticket.code})
        self.assertContains(r, "ĐỐI CHIẾU GIẤY TỜ")
        self.assertContains(r, 'value="confirm"')
        r = self.client.post(url, {"code": self.ticket.code, "decision": "reject"})
        self.assertContains(r, "Đã từ chối")


class TransferTests(Base):
    def test_transfer_changes_owner_and_code(self):
        old = self.ticket.code
        with self.captureOnCommitCallbacks(execute=True):
            t = transfer_ticket(self.owner, self.ticket.pk, "binh")
        self.assertEqual(t.user, self.friend)
        self.assertNotEqual(t.code, old)
        self.assertTrue(TicketTransfer.objects.filter(old_code=old, to_user=self.friend).exists())
        self.assertEqual(mail.outbox[-1].to, ["binh.tran@gmail.com"])
        self.assertIn(t.code, mail.outbox[-1].body)

    def test_old_code_rejected_at_door_with_reason(self):
        old = self.ticket.code
        transfer_ticket(self.owner, self.ticket.pk, "binh")
        result, _, note = check_in(self.staff, old, event=self.event)
        self.assertEqual(result, CHECKIN_INVALID)
        self.assertIn("chuyển nhượng", note)

    def test_find_recipient_by_email_alias(self):
        t = transfer_ticket(self.owner, self.ticket.pk, "BinhTran+ve@gmail.com")
        self.assertEqual(t.user, self.friend)

    def test_only_one_transfer_per_ticket(self):
        transfer_ticket(self.owner, self.ticket.pk, "binh")
        with self.assertRaisesMessage(BookingError, "đã được chuyển nhượng"):
            transfer_ticket(self.friend, self.ticket.pk, "an")

    def test_pending_ticket_cannot_transfer(self):
        t = self.make_ticket(self.owner, status=TicketStatus.PENDING)
        with self.assertRaisesMessage(BookingError, "đã xác nhận"):
            transfer_ticket(self.owner, t.pk, "binh")

    def test_too_close_to_event(self):
        ev = self.make_event(days=0)
        ev.starts_at = self.now + timezone.timedelta(hours=2)
        ev.save()
        t = self.make_ticket(self.owner, event=ev)
        with self.assertRaisesMessage(BookingError, "trước giờ diễn ra"):
            transfer_ticket(self.owner, t.pk, "binh")

    def test_not_owner(self):
        with self.assertRaises(BookingError):
            transfer_ticket(self.friend, self.ticket.pk, "binh")

    def test_bad_recipients(self):
        User.objects.create_user(username="moi", password="x", email="moi@x.vn")
        locked = User.objects.create_user(username="khoa", password="x",
                                          email_verified_at=self.now, is_locked=True)
        for who, msg in [("an", "chính mình"), ("khongco", "Không tìm thấy"),
                         ("moi", "chưa xác minh"), (locked.username, "bị khoá")]:
            with self.assertRaisesMessage(BookingError, msg):
                transfer_ticket(self.owner, self.ticket.pk, who)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.user, self.owner)

    @override_settings(MAX_TICKETS_PER_USER_PER_EVENT=1)
    def test_recipient_ticket_limit(self):
        self.make_ticket(self.friend)
        with self.assertRaisesMessage(BookingError, "đã có đủ"):
            transfer_ticket(self.owner, self.ticket.pk, "binh")

    def test_view_flow(self):
        self.client.force_login(self.owner)
        r = self.client.get(reverse("registrations:my_tickets"))
        url = reverse("registrations:transfer", args=[self.ticket.pk])
        self.assertContains(r, url)
        self.assertContains(self.client.get(url), "Chuyển vé")
        r = self.client.post(url, {"recipient": "binh"})
        self.assertRedirects(r, reverse("registrations:my_tickets"))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.user, self.friend)
        # Vé không còn của mình -> 404
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_view_shows_error(self):
        self.client.force_login(self.owner)
        r = self.client.post(reverse("registrations:transfer", args=[self.ticket.pk]),
                             {"recipient": "khongco"})
        self.assertContains(r, "Không tìm thấy tài khoản")
