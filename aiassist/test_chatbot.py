"""
Unit test cho trợ lý tra cứu.

Đây là lợi thế lớn nhất của cách làm rule-based so với chatbot dùng LLM:
kết quả xác định nên test được từng ý định, điền thẳng vào bảng test case.
Chatbot LLM thì mỗi lần trả lời một khác, gần như không test được.
"""
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus, TicketType
from organizing.models import Task, TaskStatus
from registrations.models import Ticket, TicketStatus

from .chatbot import answer, detect_intent, normalize
from .services import AIError, build_assistant_context


class NormalizeTests(TestCase):
    """Chuẩn hoá tiếng Việt: hạ chữ thường và bỏ dấu."""

    def test_removes_vietnamese_diacritics(self):
        self.assertEqual(normalize("Còn vé không"), "con ve khong")
        self.assertEqual(normalize("Sự kiện sắp tới"), "su kien sap toi")

    def test_handles_letter_d_with_stroke(self):
        """Chữ 'đ' không tách dấu được như các chữ khác, phải thay riêng."""
        self.assertEqual(normalize("Đăng ký"), "dang ky")
        self.assertEqual(normalize("đặt vé"), "dat ve")

    def test_handles_empty_input(self):
        self.assertEqual(normalize(""), "")
        self.assertEqual(normalize(None), "")


class IntentTests(TestCase):
    """Nhận diện ý định."""

    def test_detects_intent_with_diacritics(self):
        self.assertEqual(detect_intent("Còn vé không?")["code"], "seats_left")
        self.assertEqual(detect_intent("Sắp tới có sự kiện gì?")["code"],
                         "upcoming_events")

    def test_detects_intent_without_diacritics(self):
        """Người dùng gõ không dấu vẫn phải hiểu được."""
        self.assertEqual(detect_intent("con ve khong")["code"], "seats_left")
        self.assertEqual(detect_intent("ve cua toi")["code"], "my_tickets")

    def test_unknown_question_returns_none(self):
        self.assertIsNone(detect_intent("hôm nay trời mưa không"))
        self.assertIsNone(detect_intent(""))

    def test_keyword_must_be_whole_word(self):
        """
        Lỗi cũ: từ khoá chào hỏi "hi" khớp vào giữa "phí", "thi", "chỉ" (sau
        khi bỏ dấu) nên các câu này bị hiểu nhầm là lời chào.
        """
        for q in ["Phí gửi xe bao nhiêu", "Có thi cử gì không",
                  "Chỉ đường tới quán"]:
            intent = detect_intent(q)
            self.assertNotEqual(intent and intent["code"], "greeting", q)
        # Lời chào thật vẫn phải nhận ra
        self.assertEqual(detect_intent("hi bạn")["code"], "greeting")
        self.assertEqual(detect_intent("Xin chào")["code"], "greeting")


class AnswerTests(TestCase):
    """Nội dung câu trả lời, có truy vấn dữ liệu thật."""

    def setUp(self):
        now = timezone.now()
        self.member = User.objects.create_user(
            username="tv", password="x", full_name="Nguyễn Văn A",
            mssv="A1", role=Role.MEMBER)
        self.staff = User.objects.create_user(
            username="btc", password="x", full_name="Trần Thị B",
            mssv="A2", role=Role.STAFF)
        self.event = Event.objects.create(
            name="Đêm nhạc thử nghiệm", location="Hội trường A2",
            starts_at=now + timezone.timedelta(days=7),
            register_deadline=now + timezone.timedelta(days=5),
            capacity=100, status=EventStatus.OPEN)
        self.ticket_type = TicketType.objects.create(
            event=self.event, name="Vé thường", price=50000, quota=10, sold=7)

    def test_upcoming_events_lists_open_events(self):
        result = answer("Sắp tới có sự kiện gì?")
        self.assertEqual(result["intent"], "upcoming_events")
        self.assertIn("Đêm nhạc thử nghiệm", result["text"])
        self.assertIn("Hội trường A2", result["text"])

    def test_upcoming_events_hides_draft_events(self):
        """Sự kiện đang chuẩn bị chưa công khai thì không được lộ ra."""
        Event.objects.create(
            name="Sự kiện bí mật", location="X",
            starts_at=timezone.now() + timezone.timedelta(days=3),
            register_deadline=timezone.now() + timezone.timedelta(days=1),
            status=EventStatus.DRAFT)
        result = answer("Sắp tới có sự kiện gì?")
        self.assertNotIn("Sự kiện bí mật", result["text"])

    def test_seats_left_reports_real_number(self):
        result = answer("Còn vé không?")
        self.assertEqual(result["intent"], "seats_left")
        self.assertIn("3 chỗ", result["text"])   # quota 10 - sold 7

    def test_seats_left_says_sold_out(self):
        self.ticket_type.sold = self.ticket_type.quota
        self.ticket_type.save()
        result = answer("Còn chỗ không?")
        self.assertIn("hết chỗ", result["text"])

    def test_personal_question_requires_login(self):
        """Hỏi thông tin cá nhân mà chưa đăng nhập thì phải yêu cầu đăng nhập."""
        from django.contrib.auth.models import AnonymousUser

        result = answer("Vé của tôi thế nào?", user=AnonymousUser())
        self.assertIn("đăng nhập", result["text"].lower())

    def test_my_tickets_lists_user_tickets(self):
        ticket = Ticket.objects.create(
            event=self.event, ticket_type=self.ticket_type, user=self.member,
            price=50000, status=TicketStatus.CONFIRMED)
        result = answer("Vé của tôi", user=self.member)
        self.assertIn(ticket.code, result["text"])
        self.assertIn("Đêm nhạc thử nghiệm", result["text"])

    def test_my_tickets_does_not_leak_other_users_tickets(self):
        """Quan trọng: không được lộ vé của người khác."""
        other = User.objects.create_user(username="khac", password="x", mssv="A9")
        secret = Ticket.objects.create(
            event=self.event, ticket_type=self.ticket_type, user=other,
            price=50000, status=TicketStatus.CONFIRMED)

        result = answer("Vé của tôi", user=self.member)

        self.assertNotIn(secret.code, result["text"])
        self.assertIn("chưa đăng ký", result["text"])

    def test_my_tasks_for_staff(self):
        Task.objects.create(event=self.event, title="In poster",
                            assignee=self.staff,
                            deadline=timezone.now() + timezone.timedelta(days=2))
        result = answer("Việc của tôi có gì?", user=self.staff)
        self.assertIn("In poster", result["text"])

    def test_my_tasks_marks_overdue(self):
        Task.objects.create(event=self.event, title="Việc trễ",
                            assignee=self.staff,
                            deadline=timezone.now() - timezone.timedelta(days=1))
        result = answer("deadline của tôi", user=self.staff)
        self.assertIn("QUÁ HẠN", result["text"])

    def test_my_tasks_blocked_for_plain_member(self):
        """Thành viên thường không có việc BTC, phải báo rõ thay vì trả rỗng."""
        result = answer("Việc của tôi", user=self.member)
        self.assertIn("ban tổ chức", result["text"].lower())

    def test_how_to_register_mentions_the_limit(self):
        result = answer("Đăng ký thế nào?")
        self.assertEqual(result["intent"], "how_to_register")
        self.assertIn("4 vé", result["text"])

    def test_unknown_question_suggests_topics(self):
        result = answer("bạn tên gì")
        self.assertEqual(result["intent"], "unknown")
        self.assertIn("chưa hiểu", result["text"].lower())


class ChatApiTests(TestCase):
    """API của trợ lý."""

    def test_api_returns_json(self):
        response = self.client.post(
            reverse("aiassist:chat_api"),
            data='{"question": "Đăng ký thế nào?"}',
            content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "how_to_register")

    def test_api_rejects_get(self):
        """Chỉ nhận POST, để Django bắt buộc kiểm tra CSRF token."""
        self.assertEqual(
            self.client.get(reverse("aiassist:chat_api")).status_code, 405)

    def test_api_handles_broken_json(self):
        response = self.client.post(reverse("aiassist:chat_api"),
                                    data="không phải json",
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_chat_page_open_to_guests(self):
        self.assertEqual(
            self.client.get(reverse("aiassist:chat")).status_code, 200)


class HybridAITests(TestCase):
    """
    Tầng AI của trợ lý (chỉ chạy khi tầng luật không nhận ra ý định).

    Không test NỘI DUNG AI viết (mỗi lần một khác) - chỉ test phần tích hợp:
    khi nào gọi AI, lỗi thì fallback ra sao, dữ liệu gửi đi có an toàn không,
    link có bị AI bịa không. AI luôn được mock, không gọi API thật.
    """

    def setUp(self):
        now = timezone.now()
        self.user = User.objects.create_user(
            username="riengtu", password="x", full_name="Người Bí Mật",
            mssv="MSSV-BI-MAT-99", email="bimat@example.com", role=Role.MEMBER)
        self.event = Event.objects.create(
            name="Đêm nhạc công khai", location="Hội trường A2",
            starts_at=now + timezone.timedelta(days=7),
            register_deadline=now + timezone.timedelta(days=5),
            capacity=100, status=EventStatus.OPEN)
        TicketType.objects.create(event=self.event, name="Vé thường",
                                  price=50000, quota=10, sold=7)
        self.draft = Event.objects.create(
            name="Sự kiện nháp bí mật", location="Phòng kín",
            starts_at=now + timezone.timedelta(days=9),
            register_deadline=now + timezone.timedelta(days=8),
            capacity=10, status=EventStatus.DRAFT)
        Ticket.objects.create(event=self.event,
                              ticket_type=self.event.ticket_types.first(),
                              user=self.user, status=TicketStatus.CONFIRMED)

    @patch("aiassist.services._ask_ai")
    def test_unknown_question_goes_to_ai(self, mock_ai):
        mock_ai.return_value = {"answer": "Đêm nhạc tổ chức ở Hội trường A2.",
                                "event_ids": [self.event.pk]}
        result = answer("Đêm nhạc tổ chức ở chỗ nào vậy bạn")
        self.assertEqual(result["source"], "ai")
        self.assertEqual(result["intent"], "ai")
        self.assertIn("Hội trường A2", result["text"])
        self.assertEqual(result["links"][0]["url"],
                         reverse("events:detail", args=[self.event.pk]))

    @patch("aiassist.services._ask_ai")
    def test_known_intent_never_calls_ai(self, mock_ai):
        """8 ý định có sẵn LUÔN đi tầng luật - chính xác, không tốn quota."""
        result = answer("Còn vé không?")
        self.assertEqual(result["source"], "rules")
        mock_ai.assert_not_called()

    @patch("aiassist.services._ask_ai", side_effect=AIError("Quá tải"))
    def test_ai_error_falls_back_to_rules_message(self, mock_ai):
        result = answer("bạn tên gì")
        self.assertEqual(result["intent"], "unknown")
        self.assertIn("chưa hiểu", result["text"].lower())

    @patch("aiassist.services._ask_ai")
    def test_allow_ai_false_skips_ai(self, mock_ai):
        """Hết lượt AI (view truyền allow_ai=False) thì không gọi AI."""
        result = answer("bạn tên gì", allow_ai=False)
        self.assertEqual(result["intent"], "unknown")
        mock_ai.assert_not_called()

    def test_without_api_key_behaves_like_before(self):
        """Không có key (như khi chạy test): y như bản chỉ có luật."""
        result = answer("bạn tên gì")
        self.assertEqual(result["intent"], "unknown")

    @patch("aiassist.services._ask_ai")
    def test_fake_or_hidden_event_ids_get_no_link(self, mock_ai):
        """AI trả mã không tồn tại, mã bản nháp, hay rác -> không tạo link."""
        mock_ai.return_value = {
            "answer": "Có vài sự kiện.",
            "event_ids": [99999, self.draft.pk, "abc", None, self.event.pk,
                          self.event.pk]}
        result = answer("kể cho mình vài sự kiện hay ho đi")
        urls = [l["url"] for l in result["links"]]
        self.assertEqual(urls, [reverse("events:detail", args=[self.event.pk])])

    @patch("aiassist.services._ask_ai")
    def test_ai_bad_structure_falls_back(self, mock_ai):
        mock_ai.return_value = ["không", "phải", "object"]
        self.assertEqual(answer("bạn tên gì")["intent"], "unknown")
        mock_ai.return_value = {"answer": "   ", "event_ids": []}
        self.assertEqual(answer("bạn tên gì")["intent"], "unknown")

    @patch("aiassist.services._ask_ai")
    def test_prompt_contains_no_personal_data_and_no_drafts(self, mock_ai):
        """Chỉ dữ liệu CÔNG KHAI được gửi sang AI."""
        mock_ai.return_value = {"answer": "ok", "event_ids": []}
        question = "chỗ gửi xe ở đâu"
        # Câu hỏi phải KHÔNG khớp ý định nào, nếu không nó đi tầng luật và
        # test này không kiểm tra được gì (chứa chữ "sự kiện" là khớp ngay).
        self.assertIsNone(detect_intent(question))
        answer(question, user=self.user)
        prompt = mock_ai.call_args[0][0]
        self.assertIn("Đêm nhạc công khai", prompt)
        for secret in ["Người Bí Mật", "MSSV-BI-MAT-99", "bimat@example.com",
                       "Sự kiện nháp bí mật", "Phòng kín"]:
            self.assertNotIn(secret, prompt)

    def test_context_lists_price_and_seats(self):
        text, ids = build_assistant_context()
        self.assertIn("50.000đ", text)
        self.assertIn("còn 3/10 chỗ", text)
        self.assertEqual(ids, {self.event.pk})

    @patch("aiassist.services._ask_ai")
    def test_long_answer_is_trimmed(self, mock_ai):
        mock_ai.return_value = {"answer": "chữ " * 1000, "event_ids": []}
        self.assertLessEqual(len(answer("bạn tên gì")["text"]), 801)

    @patch("aiassist.services._ask_ai")
    def test_api_ai_budget_per_session(self, mock_ai):
        """Tối đa AI_LIMIT câu trả lời AI mỗi cửa sổ - hết lượt thì về luật."""
        from .views import AI_LIMIT
        mock_ai.return_value = {"answer": "trả lời AI", "event_ids": []}
        url = reverse("aiassist:chat_api")
        body = '{"question": "bạn tên gì"}'
        sources = [self.client.post(url, data=body, content_type="application/json")
                   .json()["source"] for _ in range(AI_LIMIT + 1)]
        self.assertEqual(sources[:AI_LIMIT], ["ai"] * AI_LIMIT)
        self.assertEqual(sources[-1], "rules")
        self.assertEqual(mock_ai.call_count, AI_LIMIT)
