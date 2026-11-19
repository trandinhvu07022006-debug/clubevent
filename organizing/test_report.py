"""Unit test cho chức năng Báo cáo Tổng kết Sự kiện Tự động (Post-Mortem Executive Report)."""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType
from organizing.models import EventPostMortem, Expense, ExpenseCategory, Task, TaskStatus
from registrations.models import Ticket, TicketStatus
from feedback.models import Feedback

from aiassist.services import generate_event_postmortem, build_postmortem_markdown


class EventPostMortemTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.lead = User.objects.create_user(
            username="lead_user", password="password123", mssv="BCN01", role=Role.LEAD, full_name="Trưởng Ban"
        )
        self.staff = User.objects.create_user(
            username="staff_user", password="password123", mssv="STAFF01", role=Role.STAFF, full_name="Thành viên BTC"
        )
        self.guest = User.objects.create_user(
            username="guest_user", password="password123", mssv="GUEST01", role=Role.GUEST, full_name="Khách Vãng Lai"
        )

        self.event = Event.objects.create(
            name="Đêm Nhạc Acoustic Mùa Thu",
            category="MUSIC",
            location="Hội trường Trịnh Công Sơn",
            capacity=200,
            starts_at=now + timezone.timedelta(days=2),
            register_deadline=now + timezone.timedelta(days=1),
            status=EventStatus.OPEN,
            created_by=self.lead,
        )

        self.ticket_type = TicketType.objects.create(
            event=self.event, name="Vé VIP", price=50000, quota=50
        )

        # Tạo vé và check-in
        self.ticket1 = Ticket.objects.create(
            event=self.event, ticket_type=self.ticket_type, user=self.guest,
            code="TCK000000001", status=TicketStatus.CHECKED_IN,
            price=50000, checked_in_at=now
        )
        self.ticket2 = Ticket.objects.create(
            event=self.event, ticket_type=self.ticket_type, user=self.staff,
            code="TCK000000002", status=TicketStatus.CONFIRMED,
            price=50000
        )

        # Tạo công việc
        self.task1 = Task.objects.create(
            event=self.event, title="Setup âm thanh", status=TaskStatus.DONE, assignee=self.staff
        )
        self.task2 = Task.objects.create(
            event=self.event, title="Check-in đón khách", status=TaskStatus.DOING, assignee=self.staff
        )

        # Tạo khoản chi
        self.expense = Expense.objects.create(
            event=self.event, title="Thuê dàn loa", amount=30000,
            category=ExpenseCategory.EQUIPMENT, paid_by=self.staff, created_by=self.lead
        )

        # Tạo phản hồi
        self.feedback = Feedback.objects.create(
            event=self.event, user=self.guest, rating=5, content="Âm thanh rất hay, chương trình tuyệt vời!"
        )

    def test_generate_event_postmortem_fallback(self):
        """Khi AI ném lỗi hoặc mock, hệ thống tự động sinh báo cáo chuẩn từ số liệu thực tế."""
        data, stats, md, used_ai, err = generate_event_postmortem(self.event)
        self.assertFalse(used_ai)
        self.assertIn("Đêm Nhạc Acoustic Mùa Thu", data["executive_summary"])
        self.assertTrue(len(data["highlights"]) >= 2)
        self.assertTrue(len(data["lessons_learned"]) >= 2)
        self.assertTrue(len(data["action_items"]) >= 2)

        # Kiểm tra 4 nguồn dữ liệu
        self.assertEqual(stats["total_registered"], 2)
        self.assertEqual(stats["checked_in_count"], 1)
        self.assertEqual(stats["attendance_rate"], 50)
        self.assertEqual(stats["income"], 100000)
        self.assertEqual(stats["spent"], 30000)
        self.assertEqual(stats["balance"], 70000)
        self.assertEqual(stats["total_tasks"], 2)
        self.assertEqual(stats["done_tasks"], 1)
        self.assertEqual(stats["task_rate"], 50)
        self.assertEqual(stats["avg_rating"], 5.0)

        # Markdown chứa tiêu đề và bảng
        self.assertIn("# BÁO CÁO TỔNG KẾT SỰ KIỆN", md)
        self.assertIn("Bảng Chỉ số Hoạt động Cốt lõi", md)

    @patch("aiassist.services._ask_ai")
    def test_generate_event_postmortem_with_ai(self, mock_ai):
        """Khi AI thành công, kết quả được phân tích và trích xuất đúng định dạng."""
        mock_ai.return_value = {
            "executive_summary": "Sự kiện diễn ra thành công vượt mong đợi.",
            "highlights": ["Âm thanh đạt chuẩn chuyên nghiệp", "Khán giả tham dự đúng giờ"],
            "financial_analysis": "Ngân sách cân đối thặng dư 70.000đ.",
            "feedback_analysis": "Đánh giá tuyệt đối 5/5 sao từ người tham gia.",
            "lessons_learned": ["Cần mở thêm bàn check-in lúc cao điểm"],
            "action_items": ["Lên kế hoạch tổ chức đêm nhạc số 2 vào tháng sau"],
        }
        data, stats, md, used_ai, err = generate_event_postmortem(self.event)
        self.assertTrue(used_ai)
        self.assertEqual(data["executive_summary"], "Sự kiện diễn ra thành công vượt mong đợi.")
        self.assertEqual(len(data["highlights"]), 2)
        self.assertIn("Sự kiện diễn ra thành công vượt mong đợi.", md)

    def test_event_report_view_permissions(self):
        """Chỉ Trưởng BTC (Role.LEAD trở lên) mới được xem báo cáo điều hành."""
        url = reverse("organizing:report", args=[self.event.pk])

        # Guest -> 403 Forbidden
        self.client.force_login(self.guest)
        resp_guest = self.client.get(url)
        self.assertEqual(resp_guest.status_code, 403)

        # Lead -> 200 OK
        self.client.force_login(self.lead)
        resp_lead = self.client.get(url)
        self.assertEqual(resp_lead.status_code, 200)
        self.assertContains(resp_lead, "Báo cáo Tổng kết Sự kiện")
        self.assertContains(resp_lead, "Tỷ lệ Tham dự")

    def test_event_report_generate_view(self):
        """POST lên action report_generate lưu dữ liệu vào EventPostMortem."""
        url = reverse("organizing:report_generate", args=[self.event.pk])
        self.client.force_login(self.lead)

        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("organizing:report", args=[self.event.pk]))

        # Kiểm tra CSDL
        self.assertTrue(EventPostMortem.objects.filter(event=self.event).exists())
        pm = EventPostMortem.objects.get(event=self.event)
        self.assertTrue(len(pm.executive_summary) > 0)
        self.assertEqual(pm.generated_by, self.lead)
        self.assertEqual(pm.stats_snapshot["income"], 100000)

    def test_event_report_markdown_download(self):
        """Tải về file markdown đính kèm thành công."""
        url = reverse("organizing:report_markdown", args=[self.event.pk])
        self.client.force_login(self.lead)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp["Content-Type"])
        self.assertIn('attachment; filename="Bao-cao-tong-ket-', resp["Content-Disposition"])
        content = resp.content.decode("utf-8")
        self.assertIn("# BÁO CÁO TỔNG KẾT SỰ KIỆN: ĐÊM NHẠC ACOUSTIC MÙA THU", content)
