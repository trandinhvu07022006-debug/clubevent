"""Unit test cho M6 - Phản hồi & thống kê."""
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType
from registrations.models import Ticket, TicketStatus

from .models import Feedback
from .services import (FeedbackError, can_submit_feedback, event_statistics,
                       submit_feedback)


class FeedbackRuleTests(TestCase):
    """F6.1 - Chỉ người đã check-in mới được gửi, mỗi người 1 lần."""

    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            name="Sự kiện đã xong", location="A1",
            starts_at=now - timezone.timedelta(days=1),
            register_deadline=now - timezone.timedelta(days=3),
            status=EventStatus.DONE)
        self.ticket_type = TicketType.objects.create(
            event=self.event, name="Vé", price=0, quota=50, sold=2)

        self.attended = User.objects.create_user(
            username="dudu", password="x", mssv="A1", role=Role.MEMBER)
        self.absent = User.objects.create_user(
            username="khongdu", password="x", mssv="A2", role=Role.MEMBER)

        # Người dự: vé đã check-in
        Ticket.objects.create(event=self.event, ticket_type=self.ticket_type,
                              user=self.attended, status=TicketStatus.CHECKED_IN,
                              checked_in_at=self.event.starts_at)
        # Người không dự: chỉ xác nhận, không check-in
        Ticket.objects.create(event=self.event, ticket_type=self.ticket_type,
                              user=self.absent, status=TicketStatus.CONFIRMED)

    def test_checked_in_user_can_submit(self):
        allowed, _ = can_submit_feedback(self.attended, self.event)
        self.assertTrue(allowed)

        feedback = submit_feedback(self.attended, self.event, 5, "Rất hay")
        self.assertEqual(feedback.rating, 5)

    def test_user_who_did_not_check_in_cannot_submit(self):
        """Không dự thì không được đánh giá."""
        allowed, reason = can_submit_feedback(self.absent, self.event)

        self.assertFalse(allowed)
        self.assertIn("check-in", reason)
        with self.assertRaises(FeedbackError):
            submit_feedback(self.absent, self.event, 5, "Hay")

    def test_cannot_submit_twice(self):
        """Mỗi người chỉ gửi 1 lần cho mỗi sự kiện."""
        submit_feedback(self.attended, self.event, 4, "Lần 1")

        allowed, reason = can_submit_feedback(self.attended, self.event)
        self.assertFalse(allowed)
        self.assertIn("đã gửi", reason)

    def test_cannot_submit_after_window_closes(self):
        """Quá 7 ngày sau sự kiện thì không gửi được nữa."""
        self.event.starts_at = timezone.now() - timezone.timedelta(days=10)
        self.event.save()

        allowed, reason = can_submit_feedback(self.attended, self.event)
        self.assertFalse(allowed)
        self.assertIn("quá thời hạn", reason.lower())


class StatisticsTests(TestCase):
    """F6.3 - Thống kê sự kiện."""

    def test_statistics_are_computed_correctly(self):
        now = timezone.now()
        event = Event.objects.create(
            name="SK", location="A1",
            starts_at=now - timezone.timedelta(days=1),
            register_deadline=now - timezone.timedelta(days=3),
            status=EventStatus.DONE)
        ticket_type = TicketType.objects.create(
            event=event, name="Vé", price=10000, quota=10, sold=4)

        # 4 vé: 2 check-in, 1 xác nhận, 1 huỷ
        statuses = [TicketStatus.CHECKED_IN, TicketStatus.CHECKED_IN,
                    TicketStatus.CONFIRMED, TicketStatus.CANCELLED]
        for index, status in enumerate(statuses):
            user = User.objects.create_user(
                username=f"u{index}", password="x", mssv=f"M{index}")
            Ticket.objects.create(event=event, ticket_type=ticket_type, user=user,
                                  price=10000, status=status,
                                  checked_in_at=now if status ==
                                  TicketStatus.CHECKED_IN else None)

        stat = event_statistics(event)

        self.assertEqual(stat["sold"], 3)          # không tính vé đã huỷ
        self.assertEqual(stat["checked_in"], 2)
        self.assertEqual(stat["checkin_rate"], 67)  # 2/3
        self.assertEqual(stat["cancelled"], 1)
        self.assertEqual(stat["revenue"], 30000)    # 3 vé có hiệu lực x 10000
