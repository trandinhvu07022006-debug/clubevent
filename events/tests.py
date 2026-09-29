"""Unit test cho M2 - Sự kiện, tập trung vào máy trạng thái."""
from django.test import TestCase
from django.utils import timezone

from .models import ALLOWED_TRANSITIONS, Event, EventStatus, TicketType


class EventStateMachineTests(TestCase):
    """F2.4 - Chuyển trạng thái phải đúng bảng ALLOWED_TRANSITIONS."""

    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            name="SK", location="A1",
            starts_at=now + timezone.timedelta(days=10),
            register_deadline=now + timezone.timedelta(days=8),
            capacity=100, status=EventStatus.DRAFT)

    def test_valid_transitions(self):
        """Đang chuẩn bị -> Mở đăng ký là hợp lệ."""
        self.assertTrue(self.event.can_change_to(EventStatus.OPEN))
        self.assertTrue(self.event.can_change_to(EventStatus.CANCELLED))

    def test_invalid_transitions_are_rejected(self):
        """Đang chuẩn bị KHÔNG được nhảy thẳng sang Đã diễn ra."""
        self.assertFalse(self.event.can_change_to(EventStatus.DONE))
        self.assertFalse(self.event.can_change_to(EventStatus.CLOSED))

    def test_cancelled_is_a_final_state(self):
        """Đã huỷ là trạng thái cuối, không quay lại được."""
        self.event.status = EventStatus.CANCELLED
        for status in EventStatus.values:
            self.assertFalse(self.event.can_change_to(status))

    def test_done_is_a_final_state(self):
        self.event.status = EventStatus.DONE
        self.assertEqual(ALLOWED_TRANSITIONS[EventStatus.DONE], [])

    def test_is_registerable_only_when_open_and_before_deadline(self):
        """Chỉ đăng ký được khi Mở đăng ký VÀ chưa quá hạn."""
        self.event.status = EventStatus.OPEN
        self.assertTrue(self.event.is_registerable)

        # Quá hạn đăng ký
        self.event.register_deadline = timezone.now() - timezone.timedelta(hours=1)
        self.assertFalse(self.event.is_registerable)

        # Chưa mở đăng ký
        self.event.register_deadline = timezone.now() + timezone.timedelta(days=5)
        self.event.status = EventStatus.DRAFT
        self.assertFalse(self.event.is_registerable)


class SeatCountTests(TestCase):
    """Kiểm tra tính số chỗ còn lại."""

    def test_seats_left_sums_all_ticket_types(self):
        now = timezone.now()
        event = Event.objects.create(
            name="SK", location="A1",
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=3),
            capacity=100, status=EventStatus.OPEN)
        TicketType.objects.create(event=event, name="Loại 1", quota=30, sold=10)
        TicketType.objects.create(event=event, name="Loại 2", quota=20, sold=20)

        self.assertEqual(event.total_quota, 50)
        self.assertEqual(event.total_sold, 30)
        self.assertEqual(event.seats_left, 20)
