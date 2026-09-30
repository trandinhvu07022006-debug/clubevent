"""Giao việc của Ban chủ nhiệm: việc chung CLB, giao cho Ban chủ nhiệm, 'Việc tôi đã giao'."""
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus
from notifications.models import Notification, NotificationKind

from .models import Task, TaskStatus


class AssignTests(TestCase):
    def setUp(self):
        mk = User.objects.create_user
        self.admin = mk(username="admin", password="x", full_name="Chủ nhiệm",
                        email="cn@x.vn", role=Role.ADMIN)
        self.lead = mk(username="lead", password="x", full_name="Phó chủ nhiệm",
                       email="pcn@x.vn", role=Role.LEAD)
        self.staff = mk(username="btc", password="x", full_name="BTC", role=Role.STAFF)
        self.member = mk(username="tv", password="x", role=Role.MEMBER)
        now = timezone.now()
        self.ev = Event.objects.create(name="Đêm nhạc", location="A",
                                       starts_at=now + timezone.timedelta(days=5),
                                       register_deadline=now + timezone.timedelta(days=4),
                                       status=EventStatus.OPEN)
        self.url = reverse("organizing:assign")

    def post(self, **data):
        base = {"title": "Họp Ban chủ nhiệm", "priority": "HIGH", "description": "",
                "deadline": (timezone.localtime() + timezone.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")}
        base.update(data)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, base)

    def test_admin_assigns_club_task_to_lead(self):
        """Admin giao việc chung (không thuộc sự kiện) cho thành viên Ban chủ nhiệm khác."""
        self.client.force_login(self.admin)
        r = self.post(assignee=self.lead.pk, event="")
        self.assertEqual(r.status_code, 302)
        t = Task.objects.get()
        self.assertIsNone(t.event)
        self.assertEqual((t.assignee, t.created_by), (self.lead, self.admin))
        self.assertEqual(t.scope_label, "Việc chung CLB")
        n = Notification.objects.get(user=self.lead)
        self.assertEqual(n.kind, NotificationKind.TASK_ASSIGNED)
        self.assertIn("việc chung của CLB", n.message)
        self.assertEqual(len(mail.outbox), 1)

    def test_lead_assigns_event_task_to_admin(self):
        self.client.force_login(self.lead)
        self.post(assignee=self.admin.pk, event=self.ev.pk)
        self.assertEqual(Task.objects.get().event, self.ev)
        self.assertTrue(Notification.objects.filter(user=self.admin).exists())

    def test_assignee_required_and_member_not_allowed(self):
        self.client.force_login(self.lead)
        r = self.post(assignee="", event="")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Task.objects.exists())
        r = self.post(assignee=self.member.pk, event="")      # thành viên thường không nhận việc
        self.assertFalse(Task.objects.exists())

    def test_staff_cannot_assign(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_cannot_assign_to_done_event(self):
        self.ev.status = EventStatus.DONE
        self.ev.save()
        self.client.force_login(self.lead)
        self.post(assignee=self.staff.pk, event=self.ev.pk)
        self.assertFalse(Task.objects.exists())

    def test_my_tasks_shows_club_task_and_assigned_view(self):
        t = Task.objects.create(title="Quyết toán quỹ", assignee=self.lead,
                                created_by=self.admin, priority="URGENT")
        # Việc của sự kiện đã huỷ vẫn bị ẩn, việc chung vẫn hiện
        cancelled = Event.objects.create(name="Huỷ", location="B", status=EventStatus.CANCELLED,
                                         starts_at=timezone.now(), register_deadline=timezone.now())
        Task.objects.create(title="Việc sự kiện huỷ", assignee=self.lead, event=cancelled)

        self.client.force_login(self.lead)
        r = self.client.get(reverse("organizing:my_tasks"))
        self.assertEqual([x.title for x in r.context["tasks"]], ["Quyết toán quỹ"])
        self.assertContains(r, "Việc chung CLB")
        self.assertContains(r, "Giao bởi Chủ nhiệm")
        self.assertContains(r, "Gấp")

        self.client.force_login(self.admin)
        r = self.client.get(reverse("organizing:my_tasks") + "?view=assigned")
        self.assertEqual(list(r.context["tasks"]), [t])
        self.assertContains(r, "Giao cho <strong>Phó chủ nhiệm</strong>", html=False)

    def test_staff_cannot_see_assigned_view(self):
        Task.objects.create(title="X", assignee=self.lead, created_by=self.staff)
        self.client.force_login(self.staff)
        r = self.client.get(reverse("organizing:my_tasks") + "?view=assigned")
        self.assertEqual(r.context["view"], "mine")

    def test_update_and_delete_club_task(self):
        t = Task.objects.create(title="A", assignee=self.staff, created_by=self.lead)
        self.client.force_login(self.lead)
        r = self.client.get(reverse("organizing:update", args=[t.pk]))
        self.assertContains(r, "Việc chung của CLB")
        r = self.client.post(reverse("organizing:delete", args=[t.pk]))
        self.assertRedirects(r, reverse("organizing:my_tasks") + "?view=assigned",
                             fetch_redirect_response=False)
        self.assertFalse(Task.objects.exists())

    def test_delete_requires_post(self):
        t = Task.objects.create(title="A", assignee=self.staff, event=self.ev)
        self.client.force_login(self.lead)
        self.assertEqual(self.client.get(reverse("organizing:delete", args=[t.pk])).status_code, 405)
        self.assertTrue(Task.objects.filter(pk=t.pk).exists())

    def test_set_status_blocks_open_redirect(self):
        t = Task.objects.create(title="A", assignee=self.staff)
        self.client.force_login(self.staff)
        r = self.client.post(reverse("organizing:set_status", args=[t.pk]),
                             {"status": TaskStatus.DONE, "next": "https://evil.com"})
        self.assertRedirects(r, reverse("organizing:my_tasks"), fetch_redirect_response=False)

    def test_chatbot_lists_club_task(self):
        from aiassist.chatbot import _my_tasks
        Task.objects.create(title="Họp", assignee=self.staff)
        self.assertIn("Việc chung CLB", _my_tasks(self.staff)["text"])
