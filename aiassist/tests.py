"""
Unit test cho phần tích hợp AI.

Nguyên tắc: KHÔNG test nội dung AI sinh ra (mỗi lần một khác, không ổn
định). Chỉ test phần tích hợp:
  - JSON sai định dạng thì xử lý thế nào
  - API lỗi thì có fallback không
  - Dữ liệu AI trả về có được làm sạch trước khi lưu không

Dùng mock (giả lập API) để kết quả test ổn định và không tốn quota.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User
from events.models import Event, EventStatus
from feedback.models import Feedback, FeedbackSummary

from .services import (AIError, _ask_ai, _clean_tasks, _parse_json, suggest_tasks,
                       summarize_feedback)


class ParseJsonTests(TestCase):
    """Test bước làm sạch output của model."""

    def test_parse_plain_json(self):
        data = _parse_json('{"tasks": [{"title": "Thuê địa điểm"}]}')
        self.assertEqual(data["tasks"][0]["title"], "Thuê địa điểm")

    def test_parse_json_wrapped_in_code_fence(self):
        """Model hay bọc kết quả trong ```json ... ```."""
        raw = '```json\n{"tasks": [{"title": "In poster"}]}\n```'
        data = _parse_json(raw)
        self.assertEqual(data["tasks"][0]["title"], "In poster")

    def test_parse_json_with_leading_text(self):
        """Model hay thêm câu dẫn trước JSON."""
        raw = 'Đây là kết quả:\n{"tasks": [{"title": "Chốt tiết mục"}]}'
        data = _parse_json(raw)
        self.assertEqual(data["tasks"][0]["title"], "Chốt tiết mục")

    def test_invalid_json_raises_ai_error(self):
        """JSON hỏng -> AIError, không để exception lạ lọt ra ngoài."""
        with self.assertRaises(AIError):
            _parse_json("xin chào, tôi không trả JSON")


class CleanTasksTests(TestCase):
    """Không tin dữ liệu từ bên ngoài, phải lọc trước khi dùng."""

    def test_drops_items_without_title(self):
        tasks = _clean_tasks([{"title": ""}, {"note": "thiếu title"},
                              {"title": "Hợp lệ"}], days_left=10)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Hợp lệ")

    def test_clamps_days_before_into_valid_range(self):
        """days_before vượt số ngày còn lại thì kẹp lại, không để deadline âm."""
        tasks = _clean_tasks([{"title": "A", "days_before": 999},
                              {"title": "B", "days_before": -5}], days_left=10)
        self.assertEqual(tasks[0]["days_before"], 10)
        self.assertEqual(tasks[1]["days_before"], 0)

    def test_handles_non_numeric_days_before(self):
        """AI trả chữ thay vì số -> không crash."""
        tasks = _clean_tasks([{"title": "A", "days_before": "hai tuần"}],
                             days_left=10)
        self.assertEqual(tasks[0]["days_before"], 0)

    def test_ignores_garbage_items(self):
        tasks = _clean_tasks(["chuỗi", 123, None, {"title": "OK"}], days_left=5)
        self.assertEqual(len(tasks), 1)


class SuggestTasksFallbackTests(TestCase):
    """Kiểm tra fault tolerance: AI lỗi thì hệ thống vẫn chạy."""

    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            name="Minishow test", location="Quán cà phê",
            starts_at=now + timezone.timedelta(days=20),
            register_deadline=now + timezone.timedelta(days=15),
            capacity=100, status=EventStatus.OPEN)

    @patch("aiassist.services._ask_ai")
    def test_returns_ai_tasks_when_api_works(self, mock_ask):
        """API chạy được -> dùng kết quả AI, cờ used_ai = True."""
        mock_ask.return_value = {"tasks": [
            {"title": "Chốt địa điểm", "days_before": 14, "note": "Gọi quán"},
            {"title": "In poster", "days_before": 7, "note": ""},
        ]}

        tasks, used_ai, error = suggest_tasks(self.event)

        self.assertTrue(used_ai)
        self.assertEqual(error, "")
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["title"], "Chốt địa điểm")

    @patch("aiassist.services._ask_ai", side_effect=AIError("Hết quota"))
    def test_falls_back_when_api_fails(self, mock_ask):
        """
        API lỗi -> KHÔNG crash, trả danh sách mặc định và cờ used_ai = False.

        Đây chính là fault tolerance (lập trình thứ lỗi): một thành phần
        phụ chết thì hệ thống chính vẫn hoạt động.
        """
        tasks, used_ai, error = suggest_tasks(self.event)

        self.assertFalse(used_ai)
        self.assertIn("Hết quota", error)
        self.assertGreater(len(tasks), 0, "Fallback phải có danh sách mặc định")
        self.assertTrue(all(t["title"] for t in tasks))

    @patch("aiassist.services._ask_ai", return_value={"tasks": []})
    def test_falls_back_when_ai_returns_nothing_usable(self, mock_ask):
        """AI trả danh sách rỗng -> cũng phải fallback."""
        tasks, used_ai, _ = suggest_tasks(self.event)

        self.assertFalse(used_ai)
        self.assertGreater(len(tasks), 0)


class SummarizeFeedbackTests(TestCase):
    """
    Tóm tắt phản hồi bằng AI - test phần tích hợp và yêu cầu quyền riêng tư.

    Không test nội dung tóm tắt (AI mỗi lần một khác), chỉ test:
      - AI chạy được thì lưu FeedbackSummary vào DB, đếm đúng số phản hồi.
      - AI lỗi thì KHÔNG crash, trả (None, thông báo lỗi) để view hiện fallback.
      - Sự kiện chưa có phản hồi thì không gọi AI.
      - QUYỀN RIÊNG TƯ: prompt gửi sang AI chỉ có số sao và nội dung góp ý,
        TUYỆT ĐỐI không kèm họ tên hay MSSV người đánh giá.
    """

    def setUp(self):
        now = timezone.now()
        self.event = Event.objects.create(
            name="Đêm nhạc đã xong", location="Hội trường B",
            starts_at=now - timezone.timedelta(days=2),
            register_deadline=now - timezone.timedelta(days=5),
            capacity=200, status=EventStatus.DONE)

        # Người đánh giá có họ tên và MSSV rất dễ nhận ra, để test quyền riêng
        # tư: hai chuỗi này KHÔNG được xuất hiện trong prompt gửi sang AI.
        self.u1 = User.objects.create_user(
            username="nguoi1", password="x", mssv="SV0000001",
            full_name="Nguyễn Văn Bí Mật", role=Role.MEMBER)
        self.u2 = User.objects.create_user(
            username="nguoi2", password="x", mssv="SV0000002",
            full_name="Trần Thị Kín Đáo", role=Role.MEMBER)
        Feedback.objects.create(event=self.event, user=self.u1, rating=5,
                                content="Chương trình rất hay, âm thanh tốt.")
        Feedback.objects.create(event=self.event, user=self.u2, rating=2,
                                content="Chỗ ngồi hơi chật, cần cải thiện.")

    @patch("aiassist.services._ask_ai")
    def test_creates_summary_when_ai_works(self, mock_ask):
        """AI chạy được -> lưu FeedbackSummary, đếm đúng số phản hồi."""
        mock_ask.return_value = {
            "positive": "Nội dung hay, âm thanh tốt.",
            "negative": "Chỗ ngồi chật.",
            "suggestion": "Thuê hội trường rộng hơn.",
        }

        summary, error = summarize_feedback(self.event)

        self.assertEqual(error, "")
        self.assertIsNotNone(summary)
        self.assertEqual(summary.feedback_count, 2)
        self.assertEqual(summary.positive, "Nội dung hay, âm thanh tốt.")

        # Gọi lại lần nữa chỉ cập nhật, không đẻ thêm bản ghi (event là OneToOne)
        summarize_feedback(self.event)
        self.assertEqual(
            FeedbackSummary.objects.filter(event=self.event).count(), 1)

    @patch("aiassist.services._ask_ai", side_effect=AIError("Hết quota"))
    def test_returns_error_when_ai_fails(self, mock_ask):
        """AI lỗi -> KHÔNG crash, trả (None, thông báo), không lưu gì."""
        summary, error = summarize_feedback(self.event)

        self.assertIsNone(summary)
        self.assertIn("Hết quota", error)
        self.assertFalse(
            FeedbackSummary.objects.filter(event=self.event).exists())

    @patch("aiassist.services._ask_ai")
    def test_no_feedback_does_not_call_ai(self, mock_ask):
        """Sự kiện chưa có phản hồi thì không gọi AI, chỉ trả thông báo."""
        empty = Event.objects.create(
            name="Sự kiện chưa có phản hồi", location="C1",
            starts_at=timezone.now() - timezone.timedelta(days=1),
            register_deadline=timezone.now() - timezone.timedelta(days=3),
            status=EventStatus.DONE)

        summary, error = summarize_feedback(empty)

        self.assertIsNone(summary)
        self.assertIn("chưa có phản hồi", error)
        mock_ask.assert_not_called()

    @patch("aiassist.services._ask_ai")
    def test_does_not_send_name_or_mssv_to_ai(self, mock_ask):
        """
        QUYỀN RIÊNG TƯ (yêu cầu phi chức năng): chỉ gửi số sao + nội dung góp
        ý sang dịch vụ bên thứ ba, không gửi họ tên hay MSSV.
        """
        mock_ask.return_value = {"positive": "a", "negative": "b",
                                 "suggestion": "c"}

        summarize_feedback(self.event)

        prompt = mock_ask.call_args.args[0]
        self.assertNotIn("Nguyễn Văn Bí Mật", prompt)
        self.assertNotIn("Trần Thị Kín Đáo", prompt)
        self.assertNotIn("SV0000001", prompt)
        # Nội dung góp ý thì phải có, nếu không thì bản tóm tắt vô nghĩa
        self.assertIn("âm thanh tốt", prompt)


def _http_error(code):
    """Tạo lỗi HTTP giả giống urllib ném ra khi API trả mã lỗi."""
    import urllib.error
    return urllib.error.HTTPError("https://ai.test", code, "err", {}, None)


@override_settings(AI_PROVIDER="gemini", AI_API_KEY="test-key")
@patch("aiassist.services.time.sleep")          # không chờ thật khi test
class RetryTests(TestCase):
    """
    Lỗi TẠM THỜI (429, 5xx) được thử lại; lỗi CẤU HÌNH (401, 404) báo ngay.

    Bối cảnh: khi cấu hình AI thật, Gemini trả 503 ở lần gọi đầu rồi lần sau
    lại thành công - không có thử lại thì người dùng thấy lỗi dù mọi thứ đúng.
    """

    @patch("aiassist.services._call_gemini",
           side_effect=[_http_error(503), '{"ok": true}'])
    def test_503_then_success(self, mock_call, mock_sleep):
        self.assertEqual(_ask_ai("x"), {"ok": True})
        self.assertEqual(mock_call.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("aiassist.services._call_gemini",
           side_effect=[_http_error(503), _http_error(503), _http_error(503)])
    def test_503_gives_up_after_3_attempts(self, mock_call, mock_sleep):
        with self.assertRaises(AIError) as ctx:
            _ask_ai("x")
        self.assertEqual(mock_call.call_count, 3)
        self.assertIn("quá tải", str(ctx.exception))

    @patch("aiassist.services._call_gemini", side_effect=[_http_error(401)])
    def test_401_not_retried_and_blames_key(self, mock_call, mock_sleep):
        with self.assertRaises(AIError) as ctx:
            _ask_ai("x")
        self.assertEqual(mock_call.call_count, 1)
        mock_sleep.assert_not_called()
        self.assertIn("AI_API_KEY", str(ctx.exception))

    @patch("aiassist.services._call_gemini", side_effect=[_http_error(404)])
    def test_404_not_retried_and_names_the_model(self, mock_call, mock_sleep):
        with self.assertRaises(AIError) as ctx:
            _ask_ai("x", model="model-da-bi-go")
        self.assertEqual(mock_call.call_count, 1)
        self.assertIn("model-da-bi-go", str(ctx.exception))

    @patch("aiassist.services._call_gemini",
           side_effect=[_http_error(429), '{"ok": true}'])
    def test_429_is_retried(self, mock_call, mock_sleep):
        """429 THEO PHÚT: chờ chút rồi thử lại là được."""
        self.assertEqual(_ask_ai("x"), {"ok": True})
        self.assertEqual(mock_call.call_count, 2)

    def test_429_daily_quota_not_retried(self, mock_sleep):
        """
        429 THEO NGÀY (gói miễn phí ~20 lượt/ngày/model): thử lại vô ích, chỉ
        bắt người dùng chờ thêm - báo ngay và nói rõ là hết lượt trong ngày.
        """
        import io
        import urllib.error
        body = b'{"error": {"details": [{"violations": [{"quotaId": ' \
               b'"GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}'
        err = urllib.error.HTTPError("https://ai.test", 429, "err", {}, io.BytesIO(body))
        with patch("aiassist.services._call_gemini", side_effect=[err]) as mock_call:
            with self.assertRaises(AIError) as ctx:
                _ask_ai("x")
        self.assertEqual(mock_call.call_count, 1)
        mock_sleep.assert_not_called()
        self.assertIn("trong ngày", str(ctx.exception))

    @override_settings(AI_ASSISTANT_MODEL="model-rieng-cho-tro-ly")
    def test_assistant_uses_its_own_model(self, mock_sleep):
        """Trợ lý chat gọi model riêng, không ăn lượt của model chính."""
        from .services import ask_assistant
        with patch("aiassist.services._call_gemini",
                   return_value='{"answer": "ok", "event_ids": []}') as mock_call:
            ask_assistant("chỗ gửi xe ở đâu")
        self.assertEqual(mock_call.call_args[0][1], "model-rieng-cho-tro-ly")

    def test_other_features_use_main_model(self, mock_sleep):
        with patch("aiassist.services._call_gemini",
                   return_value='{"ok": true}') as mock_call:
            _ask_ai("x")
        from django.conf import settings
        self.assertEqual(mock_call.call_args[0][1], settings.AI_MODEL)
