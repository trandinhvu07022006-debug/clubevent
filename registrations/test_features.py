"""
Test cho các chức năng Sprint 3-4 của M4: mã giao dịch nhóm + VietQR (F4.7),
thông báo nghiệp vụ (F7.1), danh sách chờ (F4.8), hạn thanh toán (B2).

Mã test khớp bảng trong docs/ke-hoach-chuc-nang.md (T4.7.x, T4.8.x, T7.1.x).
"""
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType
from notifications.models import Notification, NotificationKind

from .models import Ticket, TicketStatus, WaitlistEntry, WaitlistStatus
from .services import (BookingError, book_tickets, cancel_ticket,
                       confirm_booking, confirm_payment, expire_waitlists,
                       join_waitlist, leave_waitlist, pending_bookings,
                       release_expired_tickets)
from .vietqr import crc16_ccitt, payment_info, tlv, vietqr_payload

BANK = dict(BANK_BIN="970436", BANK_NAME="Vietcombank",
            BANK_ACCOUNT="0123456789", BANK_ACCOUNT_NAME="KMG CLUB")


def assert_sold_consistent(testcase, ticket_type):
    """T4.8.11 - Bất biến: sold luôn bằng số vé còn hiệu lực thật."""
    ticket_type.refresh_from_db()
    real = Ticket.objects.filter(
        ticket_type=ticket_type,
        status__in=[TicketStatus.PENDING, TicketStatus.CONFIRMED,
                    TicketStatus.CHECKED_IN]).count()
    testcase.assertEqual(ticket_type.sold, real)


class Base(TestCase):
    def setUp(self):
        now = timezone.now()
        mk = User.objects.create_user
        self.staff = mk(username="btc", password="x", full_name="BTC",
                        email="btc@x.vn", role=Role.STAFF)
        self.a = mk(username="a", password="x", full_name="An", email="a@x.vn", mssv="A1")
        self.b = mk(username="b", password="x", full_name="Bình", email="b@x.vn", mssv="B1")
        self.c = mk(username="c", password="x", full_name="Chi", email="c@x.vn", mssv="C1")
        self.d = mk(username="d", password="x", full_name="Dũng", email="d@x.vn", mssv="D1")
        self.event = Event.objects.create(
            name="Đêm nhạc", location="Hội trường",
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4),
            capacity=100, status=EventStatus.OPEN)
        self.paid = TicketType.objects.create(event=self.event, name="Thường",
                                              price=50000, quota=10)
        self.tiny = TicketType.objects.create(event=self.event, name="VIP",
                                              price=0, quota=1)

    def book(self, user, tt, qty=1):
        with self.captureOnCommitCallbacks(execute=True):
            return book_tickets(user, tt.pk, qty)


# ---------------------------------------------------------------------------
# F4.7 - Mã giao dịch nhóm + VietQR
# ---------------------------------------------------------------------------
class VietQRTests(TestCase):
    def test_t4_7_1_crc_check_value(self):
        self.assertEqual(crc16_ccitt("123456789"), "29B1")

    def test_t4_7_2_tlv(self):
        self.assertEqual(tlv("00", "01"), "000201")

    def test_payload_structure(self):
        p = vietqr_payload("970436", "0123456789", 150000, "KMG ABCD2345")
        self.assertTrue(p.startswith("000201010212"))
        self.assertIn("0006970436", p)
        self.assertIn("5406150000", p)
        self.assertIn("0812KMG ABCD2345", p)
        # 4 ký tự cuối là CRC của mọi thứ phía trước
        self.assertEqual(p[-4:], crc16_ccitt(p[:-4]))

    @override_settings(BANK_BIN="", BANK_ACCOUNT="", BANK_ACCOUNT_NAME="")
    def test_t4_7_7a_missing_bank_config_returns_none(self):
        self.assertIsNone(payment_info("ABCD2345", 50000))

    @override_settings(**BANK)
    def test_payment_info_with_config(self):
        info = payment_info("ABCD2345", 50000)
        self.assertEqual(info["content"], "KMG ABCD2345")
        self.assertEqual(info["amount"], 50000)


class BookingRefTests(Base):
    def test_t4_7_3_same_ref_in_one_booking(self):
        tickets = self.book(self.a, self.paid, 3)
        self.assertEqual(len({t.booking_ref for t in tickets}), 1)
        self.assertEqual(len(tickets[0].booking_ref), 8)

    def test_t4_7_4_different_bookings_different_refs(self):
        t1 = self.book(self.a, self.paid, 1)
        t2 = self.book(self.a, self.paid, 1)
        self.assertNotEqual(t1[0].booking_ref, t2[0].booking_ref)

    def test_t4_7_5_confirm_booking_confirms_group(self):
        tickets = self.book(self.a, self.paid, 3)
        from accounts.models import AuditLog
        before = AuditLog.objects.count()
        with self.captureOnCommitCallbacks(execute=True):
            done = confirm_booking(self.staff, tickets[0].booking_ref)
        self.assertEqual(len(done), 3)
        self.assertEqual(Ticket.objects.filter(status=TicketStatus.CONFIRMED).count(), 3)
        self.assertEqual(AuditLog.objects.count(), before + 1)

    def test_t4_7_6_confirm_booking_skips_cancelled(self):
        tickets = self.book(self.a, self.paid, 2)
        cancel_ticket(self.a, tickets[0].pk)
        done = confirm_booking(self.staff, tickets[0].booking_ref)
        self.assertEqual(len(done), 1)
        tickets[0].refresh_from_db()
        self.assertEqual(tickets[0].status, TicketStatus.CANCELLED)

    def test_confirm_booking_unknown_ref(self):
        with self.assertRaises(BookingError):
            confirm_booking(self.staff, "ZZZZZZZZ")

    def test_pending_bookings_group_and_search_by_transfer_content(self):
        t = self.book(self.a, self.paid, 2)
        self.book(self.b, self.paid, 1)
        groups = pending_bookings()
        self.assertEqual(len(groups), 2)
        found = pending_bookings(f"KMG {t[0].booking_ref}")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["total"], 100000)

    @override_settings(BANK_BIN="", BANK_ACCOUNT="", BANK_ACCOUNT_NAME="")
    def test_t4_7_7_my_tickets_renders_without_bank(self):
        self.book(self.a, self.paid, 1)
        self.client.force_login(self.a)
        r = self.client.get(reverse("registrations:my_tickets"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Cần thanh toán")
        self.assertNotContains(r, "Mã VietQR")

    @override_settings(**BANK)
    def test_my_tickets_shows_vietqr_when_configured(self):
        t = self.book(self.a, self.paid, 1)
        self.client.force_login(self.a)
        r = self.client.get(reverse("registrations:my_tickets"))
        self.assertContains(r, "Mã VietQR")
        self.assertContains(r, f"KMG {t[0].booking_ref}")

    def test_t4_7_8_data_migration_leaves_no_empty_ref(self):
        # Vé tạo qua service luôn có mã; vé "cũ" tạo tay với ref rỗng thì
        # migration 0003 sẽ điền — kiểm tra hàm điền trực tiếp.
        from importlib import import_module

        from django.apps import apps
        t = self.book(self.a, self.paid, 1)[0]
        Ticket.objects.filter(pk=t.pk).update(booking_ref="")
        mig = import_module("registrations.migrations.0003_fill_booking_ref")
        mig.fill_booking_ref(apps, None)
        self.assertFalse(Ticket.objects.filter(booking_ref="").exists())

    def test_payment_confirm_booking_view(self):
        t = self.book(self.a, self.paid, 2)
        self.client.force_login(self.staff)
        r = self.client.post(reverse("registrations:payment_confirm_booking",
                                     args=[t[0].booking_ref]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Ticket.objects.filter(status=TicketStatus.CONFIRMED).count(), 2)

    def test_member_cannot_confirm_booking(self):
        t = self.book(self.a, self.paid, 1)
        self.client.force_login(self.b)
        r = self.client.post(reverse("registrations:payment_confirm_booking",
                                     args=[t[0].booking_ref]))
        self.assertEqual(r.status_code, 403)


# ---------------------------------------------------------------------------
# F7.1 - Thông báo theo nghiệp vụ
# ---------------------------------------------------------------------------
class BusinessNotificationTests(Base):
    def test_t7_1_1_free_booking_notifies(self):
        self.book(self.a, self.tiny, 1)
        n = Notification.objects.get(user=self.a)
        self.assertEqual(n.kind, NotificationKind.TICKET_CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)

    def test_t7_1_2_paid_booking_email_has_transfer_content(self):
        with self.settings(**BANK):
            t = self.book(self.a, self.paid, 2)
        self.assertEqual(Notification.objects.get(user=self.a).kind,
                         NotificationKind.TICKET_PENDING)
        body = mail.outbox[0].body
        self.assertIn(f"KMG {t[0].booking_ref}", body)
        self.assertIn("100.000đ", body)
        self.assertIn("0123456789", body)

    def test_t7_1_3_confirm_payment_notifies_once(self):
        t = self.book(self.a, self.paid, 1)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            confirm_payment(self.staff, t[0].pk)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(Notification.objects.filter(
            user=self.a, kind=NotificationKind.TICKET_CONFIRMED).exists())

    def test_t7_1_4_expired_grouped_per_user(self):
        self.book(self.a, self.paid, 3)
        Ticket.objects.update(created_at=timezone.now() - timezone.timedelta(hours=30))
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(release_expired_tickets(), 3)
        self.assertEqual(Notification.objects.filter(
            user=self.a, kind=NotificationKind.TICKET_EXPIRED).count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_t7_1_5_cancel_event_one_mail_per_user(self):
        from events.services import cancel_event
        self.book(self.a, self.paid, 4)
        self.book(self.b, self.tiny, 1)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            cancel_event(self.staff, self.event)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(Notification.objects.filter(
            kind=NotificationKind.EVENT_CANCELLED).count(), 2)

    def test_no_notification_when_booking_rolls_back(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(BookingError):
                book_tickets(self.a, self.paid.pk, 99)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)


# ---------------------------------------------------------------------------
# F4.8 - Danh sách chờ
# ---------------------------------------------------------------------------
class WaitlistTests(Base):
    def fill_tiny(self, user=None):
        return self.book(user or self.d, self.tiny, 1)[0]

    def test_t4_8_1_cannot_wait_when_seats_left(self):
        with self.assertRaisesMessage(BookingError, "vẫn còn chỗ"):
            join_waitlist(self.a, self.paid.pk)

    def test_t4_8_2_cannot_wait_twice(self):
        self.fill_tiny()
        join_waitlist(self.a, self.tiny.pk)
        with self.assertRaises(BookingError):
            join_waitlist(self.a, self.tiny.pk)

    def test_t4_8_3_limit_counts_waiting(self):
        self.fill_tiny()
        self.book(self.a, self.paid, 3)
        # 3 vé + 0 lượt chờ + 1 = 4 -> được
        join_waitlist(self.a, self.tiny.pk)
        # thêm loại vé hết chỗ thứ hai để thử lượt chờ tiếp theo
        tt2 = TicketType.objects.create(event=self.event, name="Hết", price=0,
                                        quota=1, sold=1)
        with self.assertRaisesMessage(BookingError, "giới hạn"):
            join_waitlist(self.a, tt2.pk)   # 3 + 1 + 1 > 4

    def test_t4_8_4_first_in_line_gets_ticket(self):
        holder = self.fill_tiny()
        ea = join_waitlist(self.a, self.tiny.pk)
        eb = join_waitlist(self.b, self.tiny.pk)
        ec = join_waitlist(self.c, self.tiny.pk)
        self.assertEqual([ea.position, eb.position, ec.position], [1, 2, 3])
        with self.captureOnCommitCallbacks(execute=True):
            cancel_ticket(self.d, holder.pk)
        ea.refresh_from_db(); eb.refresh_from_db(); ec.refresh_from_db()
        self.assertEqual(ea.status, WaitlistStatus.PROMOTED)
        self.assertIsNotNone(ea.ticket)
        self.assertEqual(ea.ticket.user, self.a)
        self.assertEqual((eb.position, ec.position), (1, 2))
        self.assertTrue(Notification.objects.filter(
            user=self.a, kind=NotificationKind.WAITLIST_PROMOTED).exists())
        assert_sold_consistent(self, self.tiny)

    def test_t4_8_5_and_6_paid_promotion_then_expiry_moves_on(self):
        paid_one = TicketType.objects.create(event=self.event, name="Có phí 1 chỗ",
                                             price=30000, quota=1)
        holder = self.book(self.d, paid_one, 1)[0]
        join_waitlist(self.a, paid_one.pk)
        join_waitlist(self.b, paid_one.pk)
        with self.captureOnCommitCallbacks(execute=True):
            cancel_ticket(self.d, holder.pk)
        ta = Ticket.objects.get(user=self.a, ticket_type=paid_one)
        self.assertEqual(ta.status, TicketStatus.PENDING)
        self.assertEqual(len(ta.booking_ref), 8)
        # Vé của A quá hạn thanh toán -> B tự động được cấp
        Ticket.objects.filter(pk=ta.pk).update(
            created_at=timezone.now() - timezone.timedelta(hours=30))
        with self.captureOnCommitCallbacks(execute=True):
            release_expired_tickets()
        ta.refresh_from_db()
        self.assertEqual(ta.status, TicketStatus.CANCELLED)
        self.assertTrue(Ticket.objects.filter(
            user=self.b, ticket_type=paid_one, status=TicketStatus.PENDING).exists())
        assert_sold_consistent(self, paid_one)

    def test_t4_8_7_locked_user_skipped(self):
        holder = self.fill_tiny()
        ea = join_waitlist(self.a, self.tiny.pk)
        join_waitlist(self.b, self.tiny.pk)
        self.a.is_locked = True
        self.a.save()
        cancel_ticket(self.d, holder.pk)
        ea.refresh_from_db()
        self.assertEqual(ea.status, WaitlistStatus.SKIPPED)
        self.assertTrue(Ticket.objects.filter(user=self.b, ticket_type=self.tiny,
                                              status=TicketStatus.CONFIRMED).exists())
        assert_sold_consistent(self, self.tiny)

    def test_t4_8_8_user_with_max_tickets_skipped(self):
        holder = self.fill_tiny()
        ea = join_waitlist(self.a, self.tiny.pk)
        join_waitlist(self.b, self.tiny.pk)
        # A mua đủ 4 vé loại khác SAU khi vào hàng (lách bằng cách tạo tay)
        for _ in range(4):
            Ticket.objects.create(event=self.event, ticket_type=self.paid, user=self.a,
                                  status=TicketStatus.CONFIRMED, price=0)
        self.paid.sold = 4
        self.paid.save()
        cancel_ticket(self.d, holder.pk)
        ea.refresh_from_db()
        self.assertEqual(ea.status, WaitlistStatus.SKIPPED)
        self.assertTrue(Ticket.objects.filter(user=self.b, ticket_type=self.tiny).exists())

    def test_t4_8_9_no_promotion_after_deadline(self):
        holder = self.fill_tiny()
        ea = join_waitlist(self.a, self.tiny.pk)
        Event.objects.filter(pk=self.event.pk).update(
            register_deadline=timezone.now() - timezone.timedelta(minutes=1))
        cancel_ticket(self.d, holder.pk)
        ea.refresh_from_db()
        self.assertEqual(ea.status, WaitlistStatus.WAITING)
        assert_sold_consistent(self, self.tiny)

    def test_t4_8_10_cancel_event_cancels_waitlist(self):
        from events.services import cancel_event
        self.fill_tiny()
        ea = join_waitlist(self.a, self.tiny.pk)
        with self.captureOnCommitCallbacks(execute=True):
            cancel_event(self.staff, self.event)
        ea.refresh_from_db()
        self.assertEqual(ea.status, WaitlistStatus.CANCELLED)
        self.assertTrue(Notification.objects.filter(
            user=self.a, kind=NotificationKind.EVENT_CANCELLED).exists())

    def test_leave_waitlist(self):
        self.fill_tiny()
        e = join_waitlist(self.a, self.tiny.pk)
        with self.assertRaises(BookingError):
            leave_waitlist(self.b, e.pk)          # không phải của mình
        leave_waitlist(self.a, e.pk)
        e.refresh_from_db()
        self.assertEqual(e.status, WaitlistStatus.CANCELLED)

    def test_expire_waitlists_after_event_closed(self):
        self.fill_tiny()
        e = join_waitlist(self.a, self.tiny.pk)
        Event.objects.filter(pk=self.event.pk).update(status=EventStatus.CLOSED)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(expire_waitlists(), 1)
        e.refresh_from_db()
        self.assertEqual(e.status, WaitlistStatus.EXPIRED)
        self.assertTrue(Notification.objects.filter(
            user=self.a, kind=NotificationKind.WAITLIST_EXPIRED).exists())

    def test_join_and_leave_views(self):
        self.fill_tiny()
        self.client.force_login(self.a)
        r = self.client.post(reverse("registrations:waitlist_join", args=[self.tiny.pk]))
        self.assertEqual(r.status_code, 302)
        entry = WaitlistEntry.objects.get(user=self.a)
        r = self.client.get(reverse("events:detail", args=[self.event.pk]))
        self.assertContains(r, "vị trí thứ 1")
        r = self.client.post(reverse("registrations:waitlist_leave", args=[entry.pk]))
        entry.refresh_from_db()
        self.assertEqual(entry.status, WaitlistStatus.CANCELLED)

    def test_join_view_rejects_get(self):
        self.client.force_login(self.a)
        r = self.client.get(reverse("registrations:waitlist_join", args=[self.tiny.pk]))
        self.assertEqual(r.status_code, 405)


class PaymentDeadlineTests(Base):
    def test_b2_deadline_capped_at_event_start(self):
        Event.objects.filter(pk=self.event.pk).update(
            starts_at=timezone.now() + timezone.timedelta(hours=2))
        t = self.book(self.a, self.paid, 1)[0]
        t.refresh_from_db()
        self.assertLessEqual(t.payment_deadline, t.event.starts_at)

    def test_b2_expired_after_event_start_even_if_under_24h(self):
        t = self.book(self.a, self.paid, 1)[0]
        Event.objects.filter(pk=self.event.pk).update(
            starts_at=timezone.now() - timezone.timedelta(minutes=5))
        self.assertEqual(release_expired_tickets(), 1)
        t.refresh_from_db()
        self.assertEqual(t.status, TicketStatus.CANCELLED)


class CheckinProgressTests(Base):
    def test_t5_4_1_progress_by_type_and_recent(self):
        from .services import check_in
        tickets = self.book(self.a, self.tiny, 1)
        self.book(self.b, self.paid, 2)
        check_in(self.staff, tickets[0].code, event=self.event)
        self.client.force_login(self.staff)
        r = self.client.get(reverse("registrations:checkin_progress", args=[self.event.pk]))
        data = r.json()
        self.assertEqual((data["done"], data["total"]), (1, 3))
        self.assertEqual(len(data["by_type"]), 2)
        self.assertEqual(data["recent"][0]["name"], "An")

    def test_t5_4_2_member_blocked(self):
        self.client.force_login(self.a)
        r = self.client.get(reverse("registrations:checkin_progress", args=[self.event.pk]))
        self.assertEqual(r.status_code, 403)

    def test_checkin_page_renders(self):
        self.client.force_login(self.staff)
        r = self.client.get(reverse("registrations:checkin", args=[self.event.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "qr-scan.js")

    def test_t5_3_6_scan_non_object_json_is_400(self):
        self.client.force_login(self.staff)
        url = reverse("registrations:checkin_scan", args=[self.event.pk])
        for body in ("[1,2]", "khong-phai-json", '{"code": 5}'):
            r = self.client.post(url, body, content_type="application/json")
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["result"], "INVALID")


class CsvExportTests(Base):
    def test_csv_has_single_bom(self):
        lead = User.objects.create_user(username="lead", password="x", role=Role.LEAD)
        self.book(self.a, self.paid, 2)
        self.client.force_login(lead)
        r = self.client.get(reverse("registrations:participants_csv", args=[self.event.pk]))
        content = r.content
        self.assertTrue(content.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(content.count(b"\xef\xbb\xbf"), 1)
        self.assertIn("Mã giao dịch", content.decode("utf-8-sig"))


class MySQLBehaviourTests(Base):
    """
    MySQL không trả id sau bulk_create. Giả lập đặc tính đó trên SQLite để bắt
    lỗi "unsaved related object" khi cấp vé từ danh sách chờ.
    """

    def test_waitlist_promotion_without_bulk_insert_ids(self):
        from unittest import mock

        from django.db import connection
        with mock.patch.object(type(connection.features), "can_return_rows_from_bulk_insert", False):
            holder = self.book(self.d, self.tiny, 1)[0]
            self.assertIsNotNone(holder.pk)
            entry = join_waitlist(self.a, self.tiny.pk)
            with self.captureOnCommitCallbacks(execute=True):
                cancel_ticket(self.d, holder.pk)
        entry.refresh_from_db()
        self.assertEqual(entry.status, WaitlistStatus.PROMOTED)
        self.assertEqual(entry.ticket.user, self.a)


# ---------------------------------------------------------------------------
# Tự xác nhận khi tiền về (webhook SePay)
# ---------------------------------------------------------------------------
@override_settings(SEPAY_API_KEY="khoa-bi-mat", **BANK)
class SepayWebhookTests(Base):
    url = reverse("registrations:sepay_webhook")

    def post(self, content, amount, key="khoa-bi-mat", **extra):
        body = {"id": 1, "gateway": "MBBank", "accountNumber": "0123456789",
                "content": content, "transferType": "in",
                "transferAmount": amount, **extra}
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, body, content_type="application/json",
                                    HTTP_AUTHORIZATION=f"Apikey {key}")

    def status_of(self, tickets):
        return {Ticket.objects.get(pk=t.pk).status for t in tickets}

    def test_full_amount_confirms_whole_booking(self):
        tickets = self.book(self.a, self.paid, 2)
        ref = tickets[0].booking_ref
        r = self.post(f"MBVCB.123456.KMG{ref}.CT tu 0987", 100000)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["success"])
        self.assertTrue(r.json()["confirmed"])
        self.assertEqual(self.status_of(tickets), {TicketStatus.CONFIRMED})
        self.assertEqual(Notification.objects.filter(
            user=self.a, kind=NotificationKind.TICKET_CONFIRMED).count(), 1)

    def test_underpaid_stays_pending(self):
        tickets = self.book(self.a, self.paid, 2)
        r = self.post(f"KMG {tickets[0].booking_ref}", 50000)
        self.assertFalse(r.json()["confirmed"])
        self.assertEqual(self.status_of(tickets), {TicketStatus.PENDING})

    def test_retry_is_harmless(self):
        tickets = self.book(self.a, self.paid, 1)
        content = f"KMG {tickets[0].booking_ref}"
        self.post(content, 50000)
        r = self.post(content, 50000)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["confirmed"])
        self.assertEqual(Notification.objects.filter(
            user=self.a, kind=NotificationKind.TICKET_CONFIRMED).count(), 1)

    def test_wrong_key_rejected(self):
        tickets = self.book(self.a, self.paid, 1)
        r = self.post(f"KMG {tickets[0].booking_ref}", 50000, key="sai")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.status_of(tickets), {TicketStatus.PENDING})

    def test_outgoing_and_other_account_ignored(self):
        tickets = self.book(self.a, self.paid, 1)
        content = f"KMG {tickets[0].booking_ref}"
        self.post(content, 50000, transferType="out")
        self.post(content, 50000, accountNumber="999999")
        self.assertEqual(self.status_of(tickets), {TicketStatus.PENDING})

    @override_settings(SEPAY_API_KEY="")
    def test_disabled_without_key(self):
        self.assertEqual(self.post("KMG ABCDEFGH", 1).status_code, 404)
