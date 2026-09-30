"""
Test hồi quy cho các lỗi tìm ra khi rà soát chất lượng code cũ.
Mỗi test ứng với một lỗi đã sửa — chạy lại để lỗi không quay lại.
"""
import json

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType
from feedback.models import Feedback
from organizing.models import Task, TaskStatus
from registrations.models import Ticket, TicketStatus


class Base(TestCase):
    def setUp(self):
        mk = User.objects.create_user
        self.admin = mk(username="admin", password="x", role=Role.ADMIN)
        self.lead = mk(username="lead", password="x", role=Role.LEAD)
        self.staff = mk(username="btc", password="x", role=Role.STAFF)
        self.member = mk(username="tv", password="x", mssv="AT190001")
        now = timezone.now()
        self.ev = Event.objects.create(
            name="Sự kiện", location="A", capacity=100, status=EventStatus.OPEN,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4))
        self.tt = TicketType.objects.create(event=self.ev, name="Thường", price=50000, quota=50)


class DashboardNumbersTests(Base):
    """Thống kê tổng hợp: JOIN nhiều bảng cùng lúc từng làm số liệu bị nhân lên."""

    def test_counts_not_multiplied_by_feedback_and_tasks(self):
        from feedback.services import semester_overview
        users = [User.objects.create_user(username=f"u{i}", password="x") for i in range(3)]
        for u in users:
            Ticket.objects.create(event=self.ev, ticket_type=self.tt, user=u, price=50000,
                                  status=TicketStatus.CHECKED_IN)
            Feedback.objects.create(event=self.ev, user=u, rating=4)
        for i in range(4):
            Task.objects.create(event=self.ev, title=f"T{i}", status=TaskStatus.DONE,
                                deadline=timezone.now(), done_at=timezone.now())
        row = next(r for r in semester_overview() if r["event"] == self.ev)
        self.assertEqual(row["sold"], 3)                 # trước đây: 3 × 3 × 4 = 36
        self.assertEqual(row["checked_in"], 3)
        self.assertEqual(row["revenue"], 150000)         # trước đây bị nhân 12 lần
        self.assertEqual(row["rating_count"], 3)
        self.assertEqual(row["task_total"], 4)
        self.assertEqual(row["task_done"], 4)
        self.assertEqual(row["rating_avg"], 4.0)

    def test_dashboard_matches_event_statistics(self):
        from feedback.services import event_statistics, semester_overview
        Ticket.objects.create(event=self.ev, ticket_type=self.tt, user=self.member,
                              price=50000, status=TicketStatus.CONFIRMED)
        Feedback.objects.create(event=self.ev, user=self.member, rating=5)
        Task.objects.create(event=self.ev, title="A")
        Task.objects.create(event=self.ev, title="B")
        row = next(r for r in semester_overview() if r["event"] == self.ev)
        stat = event_statistics(self.ev)
        for key in ("sold", "checked_in", "revenue", "rating_count", "task_total"):
            self.assertEqual(row[key], stat[key], key)


class LockedUserTests(Base):
    def test_locked_member_is_logged_out_on_next_request(self):
        self.client.force_login(self.member)
        self.member.is_locked = True
        self.member.save()
        r = self.client.get(reverse("registrations:my_tickets"))
        self.assertRedirects(r, reverse("accounts:login"), fetch_redirect_response=False)
        # Phiên đã bị huỷ, không đặt vé được nữa
        r = self.client.post(reverse("registrations:book", args=[self.ev.pk]),
                             {"ticket_type": self.tt.pk, "quantity": 1})
        self.assertFalse(Ticket.objects.exists())


class GetMustNotChangeDataTests(Base):
    """Thao tác đổi dữ liệu phải bắt buộc POST: GET qua một đường link thì bị từ chối."""

    def test_cancel_ticket_get_405(self):
        t = Ticket.objects.create(event=self.ev, ticket_type=self.tt, user=self.member,
                                  status=TicketStatus.CONFIRMED)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("registrations:cancel", args=[t.pk])).status_code, 405)
        t.refresh_from_db()
        self.assertEqual(t.status, TicketStatus.CONFIRMED)

    def test_other_mutations_get_405(self):
        t = Ticket.objects.create(event=self.ev, ticket_type=self.tt, user=self.member,
                                  status=TicketStatus.PENDING)
        task = Task.objects.create(event=self.ev, title="A", assignee=self.lead)
        empty_tt = TicketType.objects.create(event=self.ev, name="Trống", quota=1)
        self.client.force_login(self.lead)
        urls = [reverse("registrations:payment_confirm", args=[t.pk]),
                reverse("organizing:set_status", args=[task.pk]),
                reverse("feedback:ai_summarize", args=[self.ev.pk]),
                reverse("events:tt_delete", args=[empty_tt.pk])]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(TicketType.objects.filter(pk=empty_tt.pk).exists())


class AccountRulesTests(Base):
    def test_admin_cannot_change_own_role(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:user_role", args=[self.admin.pk]), {"role": Role.MEMBER})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Role.ADMIN)

    def test_mssv_duplicate_case_insensitive(self):
        from accounts.forms import RegisterForm
        f = RegisterForm(data={"username": "moi", "full_name": "Mới", "mssv": "at190001",
                               "email": "moi@x.vn", "password1": "Kmg#2026abc",
                               "password2": "Kmg#2026abc"})
        self.assertFalse(f.is_valid())
        self.assertIn("mssv", f.errors)

    def test_avatar_over_2mb_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from accounts.forms import ProfileForm
        big = SimpleUploadedFile("a.png", b"x" * (2 * 1024 * 1024 + 1), content_type="image/png")
        f = ProfileForm(data={"full_name": "A"}, files={"avatar": big}, instance=self.member)
        self.assertFalse(f.is_valid())
        self.assertIn("avatar", f.errors)


class EventRulesTests(Base):
    def test_capacity_below_ticket_quota_rejected(self):
        from events.forms import EventForm
        fmt = "%Y-%m-%dT%H:%M"
        f = EventForm(instance=self.ev, data={
            "name": self.ev.name, "category": "OTHER", "location": "A", "budget": 0,
            "capacity": 10,                                      # loại vé đang chiếm 50
            "starts_at": timezone.localtime(self.ev.starts_at).strftime(fmt),
            "register_deadline": timezone.localtime(self.ev.register_deadline).strftime(fmt)})
        self.assertFalse(f.is_valid())
        self.assertIn("capacity", f.errors)

    def test_cannot_add_ticket_type_to_done_event(self):
        self.ev.status = EventStatus.DONE
        self.ev.save()
        self.client.force_login(self.lead)
        self.client.post(reverse("events:tt_create", args=[self.ev.pk]),
                         {"name": "Mới", "price": 0, "quota": 1})
        self.assertFalse(TicketType.objects.filter(name="Mới").exists())


class ChatApiTests(TestCase):
    def test_non_object_json_is_400(self):
        for body in ("[1,2]", '"chuoi"', "42"):
            with self.subTest(body=body):
                r = self.client.post(reverse("aiassist:chat_api"), body,
                                     content_type="application/json")
                self.assertEqual(r.status_code, 400)
                self.assertIn("error", json.loads(r.content))


class FeedbackFlowTests(Base):
    """Luồng người dùng thật của M6 qua HTTP (trước đây chỉ test ở tầng service)."""

    def setUp(self):
        super().setUp()
        self.ev.status = EventStatus.DONE
        self.ev.starts_at = timezone.now() - timezone.timedelta(days=1)
        self.ev.save()
        Ticket.objects.create(event=self.ev, ticket_type=self.tt, user=self.member,
                              status=TicketStatus.CHECKED_IN, price=50000)
        self.url = reverse("feedback:send", args=[self.ev.pk])

    def test_member_submits_feedback_once(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        r = self.client.post(self.url, {"rating": "5", "content": "Rất hay"})
        self.assertRedirects(r, reverse("events:detail", args=[self.ev.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(Feedback.objects.get().rating, 5)
        r = self.client.get(self.url, follow=True)          # lần 2 bị chặn
        self.assertContains(r, "đã gửi đánh giá")
        self.assertEqual(Feedback.objects.count(), 1)

    def test_invalid_rating_rejected(self):
        self.client.force_login(self.member)
        self.client.post(self.url, {"rating": "9"})
        self.assertFalse(Feedback.objects.exists())

    def test_not_checked_in_is_redirected(self):
        self.client.force_login(self.staff)
        r = self.client.get(self.url, follow=True)
        self.assertContains(r, "Chỉ người đã check-in")

    def test_lead_sees_feedback_list_and_ai_fallback(self):
        Feedback.objects.create(event=self.ev, user=self.member, rating=4, content="Ổn")
        self.client.force_login(self.lead)
        r = self.client.get(reverse("feedback:list", args=[self.ev.pk]))
        self.assertContains(r, "Ổn")
        # Không có khoá AI khi chạy test -> vẫn quay về trang, có cảnh báo, không lỗi
        r = self.client.post(reverse("feedback:ai_summarize", args=[self.ev.pk]), follow=True)
        self.assertEqual(r.status_code, 200)

    def test_member_cannot_see_feedback_list(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("feedback:list", args=[self.ev.pk])).status_code, 403)


class CommandTests(Base):
    """Các lệnh quản trị chạy được và in kết quả (trước đây chưa có test)."""

    def test_release_expired_and_send_reminders(self):
        from io import StringIO

        from django.core.management import call_command
        Ticket.objects.create(event=self.ev, ticket_type=self.tt, user=self.member,
                              status=TicketStatus.PENDING, price=50000)
        Ticket.objects.update(created_at=timezone.now() - timezone.timedelta(hours=30))
        self.tt.sold = 1
        self.tt.save()
        out = StringIO()
        call_command("release_expired", stdout=out)
        self.assertIn("1 vé", out.getvalue())
        self.tt.refresh_from_db()
        self.assertEqual(self.tt.sold, 0)
        out = StringIO()
        call_command("send_reminders", stdout=out)
        self.assertIn("0 sự kiện", out.getvalue())


class ShrinkImageTests(TestCase):
    """Ảnh tải lên được thu nhỏ, xoá EXIF (có GPS); file không phải ảnh giữ nguyên."""

    def make_upload(self, size=(4000, 3000), fmt="JPEG", name="bia.jpg"):
        import io

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = io.BytesIO()
        img = Image.new("RGB", size, (200, 120, 40))
        exif = Image.Exif()
        exif[0x010F] = "DienThoai"                         # thẻ EXIF hãng máy
        img.save(buf, fmt, exif=exif) if fmt == "JPEG" else img.save(buf, fmt)
        return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")

    def test_large_photo_is_shrunk_and_exif_removed(self):
        from PIL import Image

        from core.images import shrink_image
        up = self.make_upload()
        out = shrink_image(up, 1600)
        im = Image.open(out)
        self.assertEqual(max(im.size), 1600)
        self.assertLess(out.size, up.size)
        self.assertEqual(len(im.getexif()), 0)

    def test_non_image_returned_unchanged(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.images import shrink_image
        up = SimpleUploadedFile("x.jpg", b"khong phai anh")
        self.assertIs(shrink_image(up, 1600), up)

    def test_event_form_shrinks_cover(self):
        from PIL import Image

        from events.forms import EventForm
        now = timezone.localtime()
        fmt = "%Y-%m-%dT%H:%M"
        f = EventForm(data={"name": "A", "category": "OTHER", "location": "B", "capacity": 10,
                            "budget": 0,
                            "starts_at": (now + timezone.timedelta(days=3)).strftime(fmt),
                            "register_deadline": (now + timezone.timedelta(days=1)).strftime(fmt)},
                      files={"cover": self.make_upload()})
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(max(Image.open(f.cleaned_data["cover"]).size), 1600)
