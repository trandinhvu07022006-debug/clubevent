"""
Tích hợp AI — 2 chức năng:
  1. suggest_tasks()      : gợi ý danh sách công việc chuẩn bị sự kiện
  2. summarize_feedback() : tóm tắt phản hồi sau sự kiện

Nguyên tắc thiết kế:
  - API key đọc từ biến môi trường, KHÔNG hard-code (settings.AI_API_KEY).
  - Luôn có FALLBACK: AI lỗi, hết quota hay timeout thì hệ thống vẫn chạy,
    chỉ hiện thông báo để người dùng tự nhập tay. Đây là fault tolerance
    (lập trình thứ lỗi) — một tiêu chí của phần mềm tốt.
  - Bắt AI trả JSON để parse được, kèm bước làm sạch vì model hay bọc kết
    quả trong khối ```json.
  - Không gửi kèm tên hay MSSV sang dịch vụ bên thứ ba (yêu cầu phi chức
    năng về quyền riêng tư).
"""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings


class AIError(Exception):
    """AI không trả được kết quả dùng được. View bắt lỗi này và hiện fallback."""


# ---------------------------------------------------------------------------
# Gọi API
# ---------------------------------------------------------------------------
def _call_gemini(prompt):
    """Gọi Google Gemini API. Trả về chuỗi text mà model sinh ra."""
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{settings.AI_MODEL}:generateContent?key={settings.AI_API_KEY}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_openai(prompt):
    """Gọi OpenAI API. Dùng nếu nhóm chọn OpenAI thay vì Gemini."""
    body = json.dumps({
        "model": settings.AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {settings.AI_API_KEY}"})
    with urllib.request.urlopen(req, timeout=settings.AI_TIMEOUT_SECONDS) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _ask_ai(prompt):
    """
    Gửi prompt tới AI, trả về dict đã parse từ JSON.

    Mọi lỗi (mạng, quota, JSON sai định dạng) đều gom về AIError để view chỉ
    cần bắt một loại lỗi.
    """
    if settings.AI_PROVIDER == "mock":
        raise AIError("Đang ở chế độ mock, không gọi API thật.")
    if not settings.AI_API_KEY:
        raise AIError("Chưa cấu hình AI_API_KEY trong file .env.")

    try:
        raw = (_call_openai(prompt) if settings.AI_PROVIDER == "openai"
               else _call_gemini(prompt))
    except urllib.error.HTTPError as e:
        raise AIError(f"Dịch vụ AI trả lỗi {e.code}. Có thể hết quota hoặc sai API key.")
    except urllib.error.URLError as e:
        raise AIError(f"Không kết nối được dịch vụ AI: {e.reason}")
    except (KeyError, IndexError):
        raise AIError("Dịch vụ AI trả về dữ liệu không đúng định dạng mong đợi.")
    except Exception as e:  # timeout và các lỗi còn lại
        raise AIError(f"Lỗi khi gọi AI: {e}")

    return _parse_json(raw)


def _parse_json(raw):
    """
    Làm sạch và parse JSON từ output của model.

    Model hay bọc kết quả trong ```json ... ``` hoặc thêm câu dẫn, nên phải
    cắt lấy phần JSON trước khi parse.
    """
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise AIError("AI trả về JSON không hợp lệ, không parse được.")


# ---------------------------------------------------------------------------
# Chức năng 1: gợi ý công việc chuẩn bị sự kiện
# ---------------------------------------------------------------------------
SUGGEST_PROMPT = """Bạn là người có kinh nghiệm tổ chức sự kiện cho câu lạc bộ sinh viên Việt Nam.

Thông tin sự kiện:
- Tên: {name}
- Địa điểm: {location}
- Số người dự kiến: {capacity}
- Mô tả: {description}
- Số ngày còn lại tới ngày diễn ra: {days_left}

Hãy đề xuất {count} công việc cần chuẩn bị, sắp theo thứ tự thời gian thực hiện.
Mỗi công việc gồm:
- "title": tên công việc, ngắn gọn dưới 12 từ, bằng tiếng Việt
- "days_before": số ngày trước sự kiện phải hoàn thành (số nguyên, từ 0 đến {days_left})
- "note": một câu ngắn giải thích cần làm gì

Chỉ trả về JSON đúng định dạng sau, không thêm lời dẫn:
{{"tasks": [{{"title": "...", "days_before": 14, "note": "..."}}]}}"""


# Danh sách dự phòng khi AI không dùng được. Nhờ vậy nút "Gợi ý công việc"
# luôn có kết quả, chỉ khác là chung chung hơn.
FALLBACK_TASKS = [
    {"title": "Chốt ý tưởng và nội dung chương trình", "days_before": 21,
     "note": "Họp BTC thống nhất chủ đề, nội dung và thông điệp."},
    {"title": "Lập dự toán kinh phí", "days_before": 18,
     "note": "Liệt kê các khoản chi và nguồn thu dự kiến."},
    {"title": "Liên hệ và chốt địa điểm", "days_before": 14,
     "note": "Xác nhận thời gian, sức chứa và chi phí thuê."},
    {"title": "Thiết kế poster và ấn phẩm truyền thông", "days_before": 12,
     "note": "Poster, ảnh bìa sự kiện, nội dung bài đăng."},
    {"title": "Mở đăng ký và truyền thông", "days_before": 10,
     "note": "Đăng bài lên fanpage, mở form đăng ký trên hệ thống."},
    {"title": "Chuẩn bị âm thanh, ánh sáng, nhạc cụ", "days_before": 7,
     "note": "Kiểm tra thiết bị, thuê thêm nếu thiếu."},
    {"title": "Chốt danh sách tiết mục và chạy thử", "days_before": 5,
     "note": "Tổng duyệt, chốt thứ tự tiết mục."},
    {"title": "Phân công nhân sự ngày diễn ra", "days_before": 3,
     "note": "Ai đón khách, ai check-in, ai hỗ trợ sân khấu."},
    {"title": "Setup địa điểm và kiểm tra lần cuối", "days_before": 1,
     "note": "Bàn ghế, trang trí, thiết bị, bảng chỉ dẫn."},
    {"title": "Thu dọn và tổng kết", "days_before": 0,
     "note": "Dọn dẹp, trả thiết bị, họp rút kinh nghiệm."},
]


def suggest_tasks(event, count=8):
    """
    Gợi ý danh sách công việc cho sự kiện.

    Trả về (danh_sách_task, đã_dùng_ai, thông_báo_lỗi).
    View dùng cờ `đã_dùng_ai` để hiện nhãn "AI gợi ý" hay "danh sách mặc định".
    """
    from django.utils import timezone

    days_left = max((event.starts_at - timezone.now()).days, 0)
    prompt = SUGGEST_PROMPT.format(
        name=event.name, location=event.location, capacity=event.capacity,
        description=(event.description or "Không có mô tả")[:500],
        days_left=days_left or 30, count=count,
    )

    try:
        data = _ask_ai(prompt)
        tasks = data.get("tasks") if isinstance(data, dict) else data
        cleaned = _clean_tasks(tasks, days_left)
        if not cleaned:
            raise AIError("AI không trả về công việc nào hợp lệ.")
        return cleaned, True, ""
    except AIError as e:
        # FALLBACK: hệ thống vẫn chạy, chỉ báo cho người dùng biết
        return _clean_tasks(FALLBACK_TASKS[:count], days_left), False, str(e)


def _clean_tasks(tasks, days_left):
    """Lọc và chuẩn hoá dữ liệu AI trả về — không tin dữ liệu bên ngoài."""
    result = []
    for item in (tasks or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()[:200]
        if not title:
            continue
        try:
            days_before = int(item.get("days_before", 0))
        except (TypeError, ValueError):
            days_before = 0
        # Kẹp days_before vào khoảng hợp lý
        days_before = max(0, min(days_before, max(days_left, 0)))
        result.append({
            "title": title,
            "days_before": days_before,
            "note": str(item.get("note", "")).strip()[:255],
        })
    return result


# ---------------------------------------------------------------------------
# Chức năng 2: tóm tắt phản hồi sau sự kiện
# ---------------------------------------------------------------------------
SUMMARY_PROMPT = """Dưới đây là các phản hồi của người tham gia một sự kiện câu lạc bộ sinh viên.
Mỗi dòng có dạng: [số sao]/5 - nội dung góp ý.

{feedbacks}

Hãy đọc và tổng hợp. Chỉ trả về JSON đúng định dạng sau, không thêm lời dẫn:
{{"positive": "những điểm được khen nhiều nhất, 2-3 câu",
  "negative": "những điểm bị góp ý nhiều nhất, 2-3 câu",
  "suggestion": "3 đề xuất cụ thể để lần sau tổ chức tốt hơn"}}"""


def summarize_feedback(event):
    """
    Tóm tắt phản hồi của sự kiện bằng AI, lưu kết quả vào DB.

    Lưu ý quyền riêng tư: chỉ gửi số sao và nội dung góp ý, KHÔNG gửi tên
    hay MSSV của người đánh giá.

    Trả về (đối_tượng_FeedbackSummary hoặc None, thông_báo_lỗi).
    """
    from feedback.models import Feedback, FeedbackSummary

    items = Feedback.objects.filter(event=event).order_by("-created_at")[:100]
    if not items:
        return None, "Sự kiện chưa có phản hồi nào để tóm tắt."

    lines = "\n".join(
        f"- {f.rating}/5 - {(f.content or 'không ghi góp ý')[:300]}" for f in items)

    try:
        data = _ask_ai(SUMMARY_PROMPT.format(feedbacks=lines))
    except AIError as e:
        return None, str(e)

    summary, _ = FeedbackSummary.objects.update_or_create(
        event=event,
        defaults={
            "positive": str(data.get("positive", ""))[:2000],
            "negative": str(data.get("negative", ""))[:2000],
            "suggestion": str(data.get("suggestion", ""))[:2000],
            "feedback_count": len(items),
        },
    )
    return summary, ""
