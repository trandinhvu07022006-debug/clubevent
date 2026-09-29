"""
Unit test cho M4 + M5, viết theo bảng test case trong báo cáo.

Chạy:  python manage.py test

Phương pháp: phân hoạch tương đương (equivalence partitioning) và giá trị
biên (boundary value). Mã test TC07-x khớp với bảng test case trong tài liệu
để điền RTM (ma trận truy vết yêu cầu).
"""
from django.conf import settings
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType

from .models import Ticket, TicketStatus
from .services import (CHECKIN_INVALID, CHECKIN_OK, CHECKIN_USED, BookingError,
                       book_tickets, cancel_ticket, check_in, confirm_payment,
                       release_expired_tickets)


class BookingTestBase(TestCase):
    """Dữ liệu dùng chung cho các test đặt vé."""

    def setUp(self):
        now = timezone.now()
        self.member = User.objects.create_user(
            username="tv1", password="x", full_name="Thành viên 1",
            mssv="AT001", role=Role.MEMBER)
        self.staff = User.objects.create_user(
            username="btc1", password="x", full_name="BTC 1",
            mssv="AT002", role=Role.STAFF)
        self.event = Event.objects.create(
            name="Sự kiện test", location="Phòng A1",
            starts_at=now + timezone.timedelta(days=10),
            register_deadline=now + timezone.timedelta(days=8),
            capacity=100, status=EventStatus.OPEN)
        self.paid = TicketType.objects.create(
            event=self.event, name="Vé thường", price=50000, quota=10, sold=0)
        self.free = TicketType.objects.create(
            event=self.event, name="Vé miễn phí", price=0, quota=5, sold=0)


class BookTicketTests(BookingTestBase):
    """F4.1 - Đặt vé."""

    def test_tc07_1_book_two_tickets_when_seats_available(self):
        """TC07-1: đặt 2 vé khi còn 10 chỗ -> thành công, còn 8 chỗ."""
        tickets = book_tickets(self.member, self.paid.id, 2)

        self.assertEqual(len(tickets), 2)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.sold, 2)
        self.assertEqual(self.paid.remaining, 8)

    def test_tc07_2_book_exactly_the_limit(self):
        """TC07-2: đặt đúng 4 vé (giá trị biên trên) -> thành công."""
        limit = settings.MAX_TICKETS_PER_USER_PER_EVENT
        tickets = book_tickets(self.member, self.paid.id, limit)
        self.assertEqual(len(tickets), limit)

    def test_tc07_3_book_over_the_limit_is_rejected(self):
        """TC07-3: đặt 5 vé (vượt biên) -> báo lỗi, không tạo vé nào."""
        limit = settings.MAX_TICKETS_PER_USER_PER_EVENT
        with self.assertRaises(BookingError) as ctx:
            book_tickets(self.member, self.paid.id, limit + 1)

        self.assertIn("tối đa", str(ctx.exception))
        self.assertEqual(Ticket.objects.count(), 0)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.sold, 0)   # rollback đúng, không trừ chỗ

    def test_tc07_3b_limit_counts_tickets_across_several_bookings(self):
        """Giới hạn 4 vé tính tổng nhiều lần đặt, không phải mỗi lần 4 vé."""
        book_tickets(self.member, self.paid.id, 3)
        with self.assertRaises(BookingError):
            book_tickets(self.member, self.paid.id, 2)   # 3 + 2 = 5 > 4

    def test_tc07_4_book_the_last_seat(self):
        """TC07-4: đặt 1 vé khi còn đúng 1 chỗ -> thành công và hết chỗ."""
        self.paid.sold = self.paid.quota - 1
        self.paid.save()

        book_tickets(self.member, self.paid.id, 1)

        self.paid.refresh_from_db()
        self.assertEqual(self.paid.remaining, 0)
        self.assertTrue(self.paid.is_sold_out)

    def test_tc07_5_book_when_sold_out(self):
        """TC07-5: đặt khi đã hết chỗ -> báo hết chỗ."""
        self.paid.sold = self.paid.quota
        self.paid.save()

        with self.assertRaises(BookingError) as ctx:
            book_tickets(self.member, self.paid.id, 1)
        self.assertIn("hết chỗ", str(ctx.exception))

    def test_tc07_8_free_ticket_is_confirmed_immediately(self):
        """Vé miễn phí -> Đã xác nhận ngay, không cần chờ thanh toán."""
        tickets = book_tickets(self.member, self.free.id, 1)
        self.assertEqual(tickets[0].status, TicketStatus.CONFIRMED)

    def test_tc07_9_paid_ticket_waits_for_payment(self):
        """Vé có phí -> Chờ thanh toán."""
        tickets = book_tickets(self.member, self.paid.id, 1)
        self.assertEqual(tickets[0].status, TicketStatus.PENDING)

    def test_tc07_10_cannot_book_when_event_not_open(self):
        """Sự kiện không ở trạng thái Mở đăng ký -> bị chặn."""
        for status in (EventStatus.DRAFT, EventStatus.CLOSED,
                       EventStatus.CANCELLED, EventStatus.DONE):
            self.event.status = status
            self.event.save()
            with self.assertRaises(BookingError):
                book_tickets(self.member, self.paid.id, 1)

    def test_tc07_11_cannot_book_after_deadline(self):
        """Quá hạn đăng ký -> bị chặn dù sự kiện vẫn đang Mở."""
        self.event.register_deadline = timezone.now() - timezone.timedelta(hours=1)
        self.event.save()

        with self.assertRaises(BookingError) as ctx:
            book_tickets(self.member, self.paid.id, 1)
        self.assertIn("quá hạn", str(ctx.exception).lower())

    def test_ticket_codes_are_unique_and_unguessable(self):
        """Mã vé phải khác nhau và không phải số tăng dần."""
        tickets = book_tickets(self.member, self.paid.id, 4)
        codes = [t.code for t in Ticket.objects.all()]

        self.assertEqual(len(set(codes)), len(codes))     # không trùng
        self.assertTrue(all(len(c) == 12 for c in codes))
        self.assertFalse(any(c.isdigit() for c in codes))  # không phải ID


class CancelTicketTests(BookingTestBase):
    """F4.3 - Huỷ vé."""

    def test_cancel_returns_the_seat(self):
        """Huỷ vé -> trả lại chỗ cho người khác."""
        tickets = book_tickets(self.member, self.paid.id, 1)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.sold, 1)

        cancel_ticket(self.member, tickets[0].id)

        self.paid.refresh_from_db()
        self.assertEqual(self.paid.sold, 0)
        self.assertEqual(Ticket.objects.get(pk=tickets[0].id).status,
                         TicketStatus.CANCELLED)

    def test_cannot_cancel_within_24h_of_event(self):
        """Còn dưới 24h tới giờ diễn ra -> không huỷ được."""
        tickets = book_tickets(self.member, self.paid.id, 1)
        self.event.starts_at = timezone.now() + timezone.timedelta(hours=5)
        self.event.save()

        with self.assertRaises(BookingError):
            cancel_ticket(self.member, tickets[0].id)

    def test_cannot_cancel_someone_elses_ticket(self):
        """Không huỷ được vé của người khác."""
        tickets = book_tickets(self.member, self.paid.id, 1)
        other = User.objects.create_user(username="tv2", password="x",
                                         mssv="AT099", role=Role.MEMBER)
        with self.assertRaises(BookingError):
            cancel_ticket(other, tickets[0].id)


class CheckInTests(BookingTestBase):
    """F5.1 - Check-in, 3 kết quả theo đặc tả UC10."""

    def _confirmed_ticket(self):
        ticket = book_tickets(self.member, self.paid.id, 1)[0]
        return confirm_payment(self.staff, ticket.id)

    def test_tc10_1_valid_ticket(self):
        """TC10-1: vé đã xác nhận -> HỢP LỆ."""
        ticket = self._confirmed_ticket()

        result, got, note = check_in(self.staff, ticket.code, event=self.event)

        self.assertEqual(result, CHECKIN_OK)
        self.assertEqual(got.status, TicketStatus.CHECKED_IN)
        self.assertIsNotNone(got.checked_in_at)
        self.assertEqual(got.checked_in_by, self.staff)

    def test_tc10_2_second_scan_reports_used(self):
        """TC10-2: quét lại lần 2 -> ĐÃ SỬ DỤNG. Đây là bước demo quan trọng."""
        ticket = self._confirmed_ticket()
        check_in(self.staff, ticket.code, event=self.event)

        result, _, note = check_in(self.staff, ticket.code, event=self.event)

        self.assertEqual(result, CHECKIN_USED)
        self.assertIn("đã được check-in", note.lower())

    def test_tc10_3_unknown_code(self):
        """TC10-3: mã không tồn tại -> KHÔNG HỢP LỆ."""
        result, got, _ = check_in(self.staff, "KHONGCOMA123", event=self.event)
        self.assertEqual(result, CHECKIN_INVALID)
        self.assertIsNone(got)

    def test_tc10_4_unpaid_ticket_rejected(self):
        """TC10-4: vé chưa thanh toán -> KHÔNG HỢP LỆ."""
        ticket = book_tickets(self.member, self.paid.id, 1)[0]

        result, _, note = check_in(self.staff, ticket.code, event=self.event)

        self.assertEqual(result, CHECKIN_INVALID)
        self.assertIn("chưa được xác nhận", note)

    def test_tc10_5_cancelled_ticket_rejected(self):
        """TC10-5: vé đã huỷ -> KHÔNG HỢP LỆ."""
        ticket = self._confirmed_ticket()
        ticket.status = TicketStatus.CANCELLED
        ticket.save()

        result, _, note = check_in(self.staff, ticket.code, event=self.event)

        self.assertEqual(result, CHECKIN_INVALID)
        self.assertIn("huỷ", note)

    def test_tc10_6_ticket_of_another_event_rejected(self):
        """TC10-6: vé của sự kiện khác -> KHÔNG HỢP LỆ."""
        ticket = self._confirmed_ticket()
        other_event = Event.objects.create(
            name="Sự kiện khác", location="B2",
            starts_at=timezone.now() + timezone.timedelta(days=5),
            register_deadline=timezone.now() + timezone.timedelta(days=3),
            status=EventStatus.OPEN)

        result, _, note = check_in(self.staff, ticket.code, event=other_event)

        self.assertEqual(result, CHECKIN_INVALID)
        self.assertIn("thuộc sự kiện", note)

    def test_code_is_case_insensitive_and_trimmed(self):
        """Nhập mã chữ thường hoặc lỡ thừa dấu cách vẫn check-in được."""
        ticket = self._confirmed_ticket()

        result, _, _ = check_in(self.staff, f"  {ticket.code.lower()}  ",
                                event=self.event)
        self.assertEqual(result, CHECKIN_OK)


class ExpiredTicketTests(BookingTestBase):
    """F4.5 - Tự huỷ vé quá hạn thanh toán."""

    def test_expired_pending_ticket_is_released(self):
        """Vé chờ thanh toán quá 24h -> tự huỷ, trả lại chỗ."""
        ticket = book_tickets(self.member, self.paid.id, 1)[0]
        # Lùi thời điểm đặt về 25h trước (auto_now_add nên phải update trực tiếp)
        old = timezone.now() - timezone.timedelta(hours=25)
        Ticket.objects.filter(pk=ticket.pk).update(created_at=old)

        count = release_expired_tickets()

        self.assertEqual(count, 1)
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.sold, 0)
        self.assertEqual(Ticket.objects.get(pk=ticket.pk).status,
                         TicketStatus.CANCELLED)

    def test_confirmed_ticket_is_not_released(self):
        """Vé đã xác nhận thì không bị huỷ dù đặt lâu rồi."""
        ticket = book_tickets(self.member, self.paid.id, 1)[0]
        confirm_payment(self.staff, ticket.id)
        old = timezone.now() - timezone.timedelta(days=5)
        Ticket.objects.filter(pk=ticket.pk).update(created_at=old)

        self.assertEqual(release_expired_tickets(), 0)


class RaceConditionTests(TransactionTestCase):
    """
    TC07-7: hai người cùng đặt chỗ CUỐI CÙNG -> chỉ 1 người thành công.

    Dùng TransactionTestCase (không phải TestCase) vì cần transaction thật
    commit được để 2 thread nhìn thấy dữ liệu của nhau. TestCase bọc mỗi test
    trong 1 transaction rồi rollback nên không mô phỏng được tình huống này.

    LƯU Ý: test này chỉ chặn thật trên MySQL/PostgreSQL vì chúng hỗ trợ
    SELECT ... FOR UPDATE. SQLite khoá toàn bộ file DB nên vẫn pass nhưng
    bằng cơ chế khác. Khi demo nhớ chạy trên MySQL.
    """

    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            name="Sự kiện 1 chỗ", location="B301",
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=3),
            capacity=20, status=EventStatus.OPEN)
        # Chỉ còn ĐÚNG 1 chỗ
        self.ticket_type = TicketType.objects.create(
            event=self.event, name="Vé workshop", price=30000,
            quota=20, sold=19)
        self.user_a = User.objects.create_user(
            username="userA", password="x", mssv="A1", role=Role.MEMBER)
        self.user_b = User.objects.create_user(
            username="userB", password="x", mssv="B1", role=Role.MEMBER)

    def test_only_one_of_two_concurrent_bookings_succeeds(self):
        """Hai thread cùng đặt chỗ cuối: đúng 1 thành công, 1 báo hết chỗ."""
        import threading

        from django.db import connections

        results = {}

        def try_book(key, user):
            try:
                book_tickets(user, self.ticket_type.id, 1)
                results[key] = "OK"
            except BookingError as e:
                results[key] = f"FAIL: {e}"
            finally:
                # Mỗi thread có connection riêng, phải đóng để không rò rỉ
                connections.close_all()

        t1 = threading.Thread(target=try_book, args=("A", self.user_a))
        t2 = threading.Thread(target=try_book, args=("B", self.user_b))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        successes = [k for k, v in results.items() if v == "OK"]

        # Điều quan trọng nhất: KHÔNG bán vượt số chỗ
        self.ticket_type.refresh_from_db()
        self.assertLessEqual(self.ticket_type.sold, self.ticket_type.quota,
                             "Đã bán vượt số chỗ -> race condition chưa được xử lý!")
        self.assertEqual(len(successes), 1,
                         f"Phải có đúng 1 người đặt được. Kết quả: {results}")
        self.assertEqual(Ticket.objects.count(), 1)
