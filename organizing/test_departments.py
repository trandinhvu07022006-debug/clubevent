"""
Test cho các Ban (đơn vị tổ chức), giao việc cho cả Ban, tự nhận việc,
quyền giao việc của Trưởng ban và lệnh nhắc hạn công việc.
"""
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus
from notifications.models import Notification, NotificationKind

from .models import Department, Task, TaskStatus
from .services import (claim_task, departments_with_stats, save_task,
                       send_task_reminders)


class Base(TestCase):
    def setUp(self):
        cache.clear()   # badge sidebar cache 60s, tránh lẫn giữa các test
        self.now = timezone.now()
        mk = User.objects.create_user
        self.lead = mk(username="lead", password="x", full_name="Trưởng BTC",
                       role=Role.LEAD, email="lead@x.vn")
        self.head = mk(username="head", password="x", full_name="Trưởng ban TT",
                       role=Role.STAFF, email="head@x.vn")
        self.s1 = mk(username="s1", password="x", full_name="BTC Một",
                     role=Role.STAFF, email="s1@x.vn")
        self.outsider = mk(username="s2", password="x", full_name="BTC Ngoài",
                           role=Role.STAFF, email="s2@x.vn")
        self.member = mk(username="tv", password="x", role=Role.MEMBER)
        self.dept = Department.objects.create(name="Ban Truyền thông",
                                              slug="truyen-thong", lead=self.head)
        self.dept.members.set([self.head, self.s1])

    def make_event(self, **kw):
        data = dict(name="Đêm nhạc", location="A2",
                    starts_at=self.now + timezone.timedelta(days=5),
                    register_deadline=self.now + timezone.timedelta(days=4),
                    status=EventStatus.OPEN, created_by=self.lead)
        data.update(kw)
        return Event.objects.create(**data)

    def dept_task(self, **kw):
        data = dict(title="Đăng bài teaser", department=self.dept,
                    created_by=self.lead,
                    deadline=self.now + timezone.timedelta(days=2))
        data.update(kw)
        return Task.objects.create(**data)


class DepartmentPermissionTests(Base):
    def test_guest_cannot_see_departments(self):
        guest = User.objects.create_user(username="khach", password="x", role=Role.GUEST)
        self.client.force_login(guest)
        r = self.client.get(reverse("organizing:department_list"))
        self.assertEqual(r.status_code, 403)

    def test_official_member_sees_departments_but_cannot_claim(self):
        self.dept.members.add(self.member)
        t = self.dept_task()
        self.client.force_login(self.member)
        r = self.client.get(self.dept.get_absolute_url())
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Nhận việc</button>")
        self.assertFalse(claim_task(self.member, t))

    def test_member_in_department_not_notified_of_tasks(self):
        self.dept.members.add(self.member)
        with self.captureOnCommitCallbacks(execute=True):
            save_task(self.lead, Task(title="Việc Ban", department=self.dept))
        self.assertFalse(Notification.objects.filter(user=self.member).exists())

    def test_staff_sees_list_and_detail(self):
        self.client.force_login(self.outsider)
        r = self.client.get(reverse("organizing:department_list"))
        self.assertContains(r, "Ban Truyền thông")
        r = self.client.get(self.dept.get_absolute_url())
        self.assertEqual(r.status_code, 200)

    def test_only_lead_can_create_department(self):
        self.client.force_login(self.head)   # Trưởng ban, không phải Trưởng BTC
        r = self.client.get(reverse("organizing:department_create"))
        self.assertEqual(r.status_code, 403)

    def test_create_department_autoslug_keeps_d(self):
        self.client.force_login(self.lead)
        r = self.client.post(reverse("organizing:department_create"), {
            "name": "Ban Đối ngoại", "slug": "", "icon": "bi-briefcase",
            "description": "", "lead": self.s1.pk, "members": [self.s1.pk],
            "order": 1})
        dept = Department.objects.get(name="Ban Đối ngoại")
        self.assertEqual(dept.slug, "ban-doi-ngoai")
        self.assertRedirects(r, dept.get_absolute_url())

    def test_icon_rejects_injection(self):
        self.client.force_login(self.lead)
        r = self.client.post(reverse("organizing:department_create"), {
            "name": "Ban X", "icon": 'bi-x" onmouseover="alert(1)', "order": 0})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Department.objects.filter(name="Ban X").exists())

    def test_delete_keeps_tasks(self):
        t = self.dept_task()
        self.client.force_login(self.lead)
        self.client.post(reverse("organizing:department_delete", args=[self.dept.slug]))
        t.refresh_from_db()
        self.assertIsNone(t.department_id)


class ClaimTests(Base):
    def test_member_of_department_claims_task(self):
        t = self.dept_task()
        self.client.force_login(self.s1)
        self.client.post(reverse("organizing:claim", args=[t.pk]))
        t.refresh_from_db()
        self.assertEqual(t.assignee, self.s1)

    def test_outsider_cannot_claim(self):
        t = self.dept_task()
        self.client.force_login(self.outsider)
        self.client.post(reverse("organizing:claim", args=[t.pk]))
        t.refresh_from_db()
        self.assertIsNone(t.assignee_id)

    def test_second_claim_fails(self):
        t = self.dept_task()
        self.assertTrue(claim_task(self.s1, t))
        self.assertFalse(claim_task(self.head, t))
        t.refresh_from_db()
        self.assertEqual(t.assignee, self.s1)

    def test_claim_requires_post(self):
        t = self.dept_task()
        self.client.force_login(self.s1)
        r = self.client.get(reverse("organizing:claim", args=[t.pk]))
        self.assertEqual(r.status_code, 405)

    def test_my_tasks_lists_claimable(self):
        self.dept_task(title="Việc chờ nhận ABC")
        self.client.force_login(self.s1)
        r = self.client.get(reverse("organizing:my_tasks"))
        self.assertContains(r, "Việc chờ nhận ABC")
        self.assertContains(r, "Nhận việc")


class DepartmentHeadAssignTests(Base):
    def assign(self, user, **data):
        self.client.force_login(user)
        payload = {"title": "Việc mới", "priority": "NORMAL", "event": "",
                   "deadline": "", "description": "", "assignee": "",
                   "department": ""}
        payload.update({k: v for k, v in data.items()})
        return self.client.post(reverse("organizing:assign"), payload)

    def test_plain_staff_cannot_assign(self):
        self.client.force_login(self.outsider)
        r = self.client.get(reverse("organizing:assign"))
        self.assertEqual(r.status_code, 403)

    def test_head_assigns_within_department(self):
        self.assign(self.head, department=self.dept.pk, assignee=self.s1.pk)
        t = Task.objects.get(title="Việc mới")
        self.assertEqual((t.assignee, t.department), (self.s1, self.dept))

    def test_head_cannot_assign_outside_department(self):
        r = self.assign(self.head, department=self.dept.pk, assignee=self.outsider.pk)
        self.assertEqual(r.status_code, 200)        # form báo lỗi, không lưu
        self.assertFalse(Task.objects.filter(title="Việc mới").exists())

    def test_head_cannot_pick_other_department(self):
        other = Department.objects.create(name="Ban Hậu cần", slug="hau-can")
        r = self.assign(self.head, department=other.pk)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Task.objects.filter(title="Việc mới").exists())

    def test_needs_person_or_department(self):
        r = self.assign(self.lead)
        self.assertContains(r, "Chọn người nhận")

    def test_assign_to_department_notifies_members_not_actor(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.assign(self.lead, department=self.dept.pk)
        notified = set(Notification.objects.values_list("user__username", flat=True))
        self.assertEqual(notified, {"head", "s1"})

    def test_head_sees_assign_in_sidebar(self):
        self.client.force_login(self.head)
        r = self.client.get(reverse("organizing:my_tasks"))
        self.assertContains(r, reverse("organizing:assign"))
        self.client.force_login(self.outsider)
        cache.clear()
        r = self.client.get(reverse("organizing:my_tasks"))
        self.assertNotContains(r, 'href="%s"' % reverse("organizing:assign"))


class DepartmentHeadEditTests(Base):
    def test_head_can_update_status_of_department_task(self):
        t = self.dept_task(assignee=self.s1)
        self.client.force_login(self.head)
        self.client.post(reverse("organizing:set_status", args=[t.pk]),
                         {"status": TaskStatus.DONE})
        t.refresh_from_db()
        self.assertEqual(t.status, TaskStatus.DONE)


class StatsTests(Base):
    def test_department_stats(self):
        self.dept_task(status=TaskStatus.DONE, assignee=self.s1)
        self.dept_task(deadline=self.now - timezone.timedelta(hours=1))     # quá hạn, chờ nhận
        # Việc của sự kiện đã huỷ: không tính
        self.dept_task(event=self.make_event(status=EventStatus.CANCELLED))
        d = departments_with_stats()[0]
        self.assertEqual((d.task_total, d.task_done, d.task_unclaimed, d.task_overdue),
                         (2, 1, 1, 1))
        self.assertEqual(d.progress, 50)
        self.assertEqual(d.member_count, 2)


class TaskReminderTests(Base):
    def remind(self):
        with self.captureOnCommitCallbacks(execute=True):
            return send_task_reminders()

    def test_due_soon_reminded_once(self):
        Task.objects.create(title="In poster", assignee=self.s1, created_by=self.lead,
                            deadline=self.now + timezone.timedelta(hours=10))
        self.assertEqual(self.remind(), 1)
        self.assertEqual(self.remind(), 0)          # chạy lại không nhắc trùng
        n = Notification.objects.get(user=self.s1)
        self.assertEqual(n.kind, NotificationKind.TASK_DUE)
        self.assertEqual(len(mail.outbox), 1)

    def test_far_deadline_not_reminded(self):
        Task.objects.create(title="Xa", assignee=self.s1,
                            deadline=self.now + timezone.timedelta(days=3))
        self.assertEqual(self.remind(), 0)

    def test_overdue_notifies_assignee_and_creator(self):
        Task.objects.create(title="Trễ", assignee=self.s1, created_by=self.lead,
                            deadline=self.now - timezone.timedelta(hours=2))
        self.assertEqual(self.remind(), 1)
        users = set(Notification.objects.values_list("user__username", flat=True))
        self.assertEqual(users, {"s1", "lead"})
        self.assertEqual(self.remind(), 0)

    def test_unclaimed_department_task_reminds_whole_department(self):
        self.dept_task(deadline=self.now + timezone.timedelta(hours=5))
        self.remind()
        users = set(Notification.objects.values_list("user__username", flat=True))
        self.assertEqual(users, {"head", "s1"})

    def test_done_or_cancelled_event_skipped(self):
        Task.objects.create(title="Xong", assignee=self.s1, status=TaskStatus.DONE,
                            deadline=self.now + timezone.timedelta(hours=3))
        Task.objects.create(title="Huỷ", assignee=self.s1,
                            event=self.make_event(status=EventStatus.CANCELLED),
                            deadline=self.now + timezone.timedelta(hours=3))
        self.assertEqual(self.remind(), 0)

    def test_changing_deadline_rearms_reminder(self):
        t = Task.objects.create(title="Đổi hạn", assignee=self.s1,
                                deadline=self.now + timezone.timedelta(hours=3))
        self.remind()
        old = t.deadline
        t.refresh_from_db()
        t.deadline = self.now + timezone.timedelta(hours=6)
        save_task(self.lead, t, old_assignee_id=self.s1.pk, old_deadline=old)
        self.assertEqual(self.remind(), 1)

    def test_run_periodic_includes_task_step(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("run_periodic", stdout=out, stderr=StringIO())
        self.assertIn("công việc", out.getvalue())
