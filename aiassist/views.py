"""View cho trợ lý tra cứu."""
import json
import time

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .chatbot import SUGGESTIONS, answer

# Rate limit: tối đa 30 request/phút mỗi session.
# Không cần thư viện ngoài, dùng session Django có sẵn.
RATE_LIMIT = 30
RATE_WINDOW = 60  # giây

# Giới hạn RIÊNG cho nhánh AI (tốn quota, chậm): tối đa 10 câu trả lời AI mỗi
# 10 phút mỗi session. Hết lượt thì trợ lý vẫn trả lời bằng luật như bình
# thường, chỉ là câu hỏi lạ nhận lời gợi ý thay vì câu trả lời AI.
AI_LIMIT = 10
AI_WINDOW = 600   # giây


def chat_page(request):
    """Trang chat đầy đủ, ai cũng vào được."""
    return render(request, "aiassist/chat.html", {"suggestions": SUGGESTIONS})


def _is_rate_limited(request):
    """
    Kiểm tra rate limit dựa trên session.

    Lưu danh sách timestamp của các request gần đây. Nếu vượt quá RATE_LIMIT
    trong RATE_WINDOW giây thì trả True.
    """
    now = time.time()
    key = "chat_timestamps"
    timestamps = request.session.get(key, [])
    # Chỉ giữ lại các timestamp trong cửa sổ thời gian
    timestamps = [t for t in timestamps if now - t < RATE_WINDOW]
    if len(timestamps) >= RATE_LIMIT:
        return True
    timestamps.append(now)
    request.session[key] = timestamps
    return False


def _ai_timestamps(request):
    """Các lần dùng AI còn nằm trong cửa sổ thời gian của session này."""
    now = time.time()
    return [t for t in request.session.get("chat_ai_timestamps", [])
            if now - t < AI_WINDOW]


def _ai_allowed(request):
    return len(_ai_timestamps(request)) < AI_LIMIT


def _record_ai_use(request):
    """Chỉ tính lượt khi AI THẬT SỰ trả lời - câu hỏi đi nhánh luật không tốn lượt."""
    stamps = _ai_timestamps(request)
    stamps.append(time.time())
    request.session["chat_ai_timestamps"] = stamps


@require_POST
def chat_api(request):
    """
    Nhận câu hỏi, trả câu trả lời dạng JSON.

    Chỉ nhận POST vì đây là hành động gửi dữ liệu, và POST thì Django bắt
    buộc kiểm tra CSRF token - chặn được việc trang web khác gọi thay bạn.
    Có rate limit để chặn spam.
    """
    if _is_rate_limited(request):
        return JsonResponse(
            {"error": "Bạn gửi quá nhanh, vui lòng chờ một chút."},
            status=429)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        # Body là JSON hợp lệ nhưng không phải object (vd "[1,2]") thì
        # payload.get sẽ ném AttributeError -> lỗi 500. Chặn ở đây.
        if not isinstance(payload, dict):
            raise ValueError
        question = str(payload.get("question", ""))[:500]
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Dữ liệu gửi lên không hợp lệ."},
                            status=400)

    result = answer(question, user=request.user, allow_ai=_ai_allowed(request))
    if result.get("source") == "ai":
        _record_ai_use(request)
    return JsonResponse(result)
