"""Unit test cho M3 - Phân công công việc BTC."""
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus

from .models import Task, TaskStatus


class TaskTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            name="SK", location="A1",
            starts_at=now + timezone.timedelta(days=10),
            register_deadline=now + timezone.timedelta(days=8),
            status=EventStatus.OPEN)
        self.staff = User.objects.create_user(
            username="btc1", password="x", mssv="A1", role=Role.STAFF)
        self.other_staff = User.objects.create_user(
            username="btc2", password="x", mssv="A2", role=Role.STAFF)
        self.lead = User.objects.create_user(
            username="truong", password="x", mssv="A3", role=Role.LEAD)

    def test_overdue_detection(self):
        """F3.3 - task quá deadline mà chưa xong thì tính là quá hạn."""
        past = timezone.now() - timezone.timedelta(days=1)
        task = Task.objects.create(event=self.event, title="Việc trễ",
                                   assignee=self.staff, deadline=past)
        self.assertTrue(task.is_overdue)

        # Xong rồi thì không còn tính quá hạn
        task.mark(TaskStatus.DONE)
        self.assertFalse(task.is_overdue)

    def test_task_without_deadline_is_never_overdue(self):
        task = Task.objects.create(event=self.event, title="Không deadline")
        self.assertFalse(task.is_overdue)

    def test_done_at_is_set_and_cleared(self):
        """Đánh dấu Xong thì ghi thời điểm, lùi lại thì xoá."""
        task = Task.objects.create(event=self.event, title="V",
                                   deadline=timezone.now())
        task.mark(TaskStatus.DONE)
        self.assertIsNotNone(task.done_at)

        task.mark(TaskStatus.DOING)
        self.assertIsNone(task.done_at)

    def test_on_time_completion(self):
        """Dùng cho thống kê tỉ lệ hoàn thành đúng hạn."""
        future = timezone.now() + timezone.timedelta(days=2)
        task = Task.objects.create(event=self.event, title="Đúng hạn",
                                   deadline=future)
        task.mark(TaskStatus.DONE)
        self.assertTrue(task.is_done_on_time)

        past = timezone.now() - timezone.timedelta(days=2)
        late = Task.objects.create(event=self.event, title="Muộn", deadline=past)
        late.mark(TaskStatus.DONE)
        self.assertFalse(late.is_done_on_time)

    def test_only_assignee_or_lead_can_update(self):
        """F3.4 - người khác không được sửa tiến độ việc không phải của mình."""
        task = Task.objects.create(event=self.event, title="V",
                                   assignee=self.staff)

        self.assertTrue(task.can_be_edited_by(self.staff))       # người phụ trách
        self.assertTrue(task.can_be_edited_by(self.lead))        # Trưởng BTC
        self.assertFalse(task.can_be_edited_by(self.other_staff))  # BTC khác

    def test_event_task_progress(self):
        """F3.5 - % tiến độ = số task Xong / tổng số task."""
        for index in range(4):
            Task.objects.create(event=self.event, title=f"V{index}")
        self.assertEqual(self.event.task_progress, 0)

        first = self.event.tasks.first()
        first.mark(TaskStatus.DONE)
        self.assertEqual(self.event.task_progress, 25)
