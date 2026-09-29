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

from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventStatus

from .services import AIError, _clean_tasks, _parse_json, suggest_tasks


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
