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


@require_POST
def chat_api(request):
    """
    Nhận câu hỏi, trả câu trả lời dạng JSON.

    Chỉ nhận POST vì đây là hành động gửi dữ liệu, và POST thì Django bắt
    buộc kiểm tra CSRF token — chặn được việc trang web khác gọi thay bạn.
    Có rate limit để chặn spam.
    """
    if _is_rate_limited(request):
        return JsonResponse(
            {"error": "Bạn gửi quá nhanh, vui lòng chờ một chút."},
            status=429)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        question = str(payload.get("question", ""))[:500]
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Dữ liệu gửi lên không hợp lệ."},
                            status=400)

    return JsonResponse(answer(question, user=request.user))
