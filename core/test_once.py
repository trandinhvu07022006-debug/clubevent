"""
Chống gửi trùng form (core/once.py).

Lỗi thật tìm được khi chạy thử bằng trình duyệt với mạng chậm: bấm đúp nút
"Đăng ký" gửi 2 request -> tài khoản bị đặt 2 vé, màn hình chỉ báo 1 vé.
Ở đây mô phỏng đúng cú bấm đúp: 2 lần POST cùng một mã của form.
"""
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType
from organizing.models import Department, Expense, Task
from recruitment.models import Application, RecruitmentRound
from registrations.models import Ticket

TOKEN = "a" * 32


class Base(TestCase):
    def setUp(self):
        cache.clear()
        now = timezone.now()
        self.lead = User.objects.create_user(username="lead", password="x", role=Role.LEAD)
        self.member = User.objects.create_user(username="tv", password="x", role=Role.MEMBER)
        self.event = Event.objects.create(
            name="Đêm nhạc", location="A2", status=EventStatus.OPEN, created_by=self.lead,
            starts_at=now + timezone.timedelta(days=5),
            register_deadline=now + timezone.timedelta(days=4))
        self.tt = TicketType.objects.create(event=self.event, name="Thường", price=0, quota=50)

    def double_post(self, url, data):
        """Bấm đúp: 2 POST cùng mã _once."""
        payload = {**data, "_once": TOKEN}
        r1 = self.client.post(url, payload)
        r2 = self.client.post(url, payload)
        return r1, r2


class BookingDoubleClickTests(Base):
    def test_double_click_books_only_once(self):
        self.client.force_login(self.member)
        url = reverse("registrations:book", args=[self.event.pk])
        _, r2 = self.double_post(url, {"ticket_type": self.tt.pk, "quantity": 1})
        self.assertEqual(Ticket.objects.filter(user=self.member).count(), 1)
        self.assertRedirects(r2, reverse("registrations:my_tickets"))

    def test_two_separate_bookings_still_allowed(self):
        """Hai lần mở form (2 mã khác nhau) là 2 lần đặt thật -> vẫn cho."""
        self.client.force_login(self.member)
        url = reverse("registrations:book", args=[self.event.pk])
        for token in ("1" * 32, "2" * 32):
            self.client.post(url, {"ticket_type": self.tt.pk, "quantity": 1, "_once": token})
        self.assertEqual(Ticket.objects.filter(user=self.member).count(), 2)

    def test_token_is_per_user(self):
        other = User.objects.create_user(username="tv2", password="x", role=Role.MEMBER)
        url = reverse("registrations:book", args=[self.event.pk])
        for user in (self.member, other):
            self.client.force_login(user)
            self.client.post(url, {"ticket_type": self.tt.pk, "quantity": 1, "_once": TOKEN})
        self.assertEqual(Ticket.objects.count(), 2)

    def test_detail_page_renders_token(self):
        self.client.force_login(self.member)
        r = self.client.get(self.event.get_absolute_url())
        self.assertContains(r, 'name="_once"')


class OtherFormsDoubleClickTests(Base):
    def test_assign_task_once(self):
        self.client.force_login(self.lead)
        self.double_post(reverse("organizing:assign"), {
            "title": "In standee", "assignee": self.lead.pk, "priority": "NORMAL",
            "event": "", "department": "", "deadline": "", "description": ""})
        self.assertEqual(Task.objects.filter(title="In standee").count(), 1)

    def test_expense_once(self):
        self.client.force_login(self.lead)
        self.double_post(reverse("organizing:expense_create", args=[self.event.pk]), {
            "title": "Thuê loa", "category": Expense._meta.get_field("category").choices[0][0],
            "amount": 500000, "spent_on": "2026-10-01", "note": ""})
        self.assertEqual(Expense.objects.filter(title="Thuê loa").count(), 1)

    def test_apply_once_and_no_500(self):
        guest = User.objects.create_user(username="khach", password="x", role=Role.GUEST, mssv="AT77")
        dept = Department.objects.create(name="Ban Chuyên môn", slug="chuyen-mon")
        now = timezone.now()
        RecruitmentRound.objects.create(name="Đợt 1", opens_at=now - timezone.timedelta(days=1),
                                        closes_at=now + timezone.timedelta(days=3))
        self.client.force_login(guest)
        r1, r2 = self.double_post(reverse("recruitment:apply"), {
            "department": dept.pk, "strengths": "Guitar", "level": "BASIC",
            "portfolio_url": "", "motivation": "Thích nhạc"})
        self.assertEqual(Application.objects.filter(user=guest).count(), 1)
        self.assertEqual(r2.status_code, 302)
