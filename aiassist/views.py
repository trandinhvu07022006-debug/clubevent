"""View cho trợ lý tra cứu."""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.security import is_rate_limited, record_rate_event

from .chatbot import SUGGESTIONS, answer

# Rate limit: tối đa 30 request/phút mỗi IP (SEC-06: lưu trong Cache, bỏ cookie vẫn bị chặn).
RATE_LIMIT = 30
RATE_WINDOW = 60  # giây

# Giới hạn RIÊNG cho nhánh AI (tốn quota, chậm): tối đa 10 câu trả lời AI mỗi
# 10 phút mỗi IP. Hết lượt thì trợ lý vẫn trả lời bằng luật như bình thường.
AI_LIMIT = 10
AI_WINDOW = 600   # giây


def chat_page(request):
    """Trang chat đầy đủ, ai cũng vào được."""
    return render(request, "aiassist/chat.html", {"suggestions": SUGGESTIONS})


def _is_rate_limited(request):
    """Kiểm tra rate limit dựa trên Cache + IP (SEC-06)."""
    return is_rate_limited(
        request,
        scope="aiassist_chat",
        limit=RATE_LIMIT,
        window_seconds=RATE_WINDOW,
    )


def _ai_allowed(request):
    """Kiểm tra hạn mức nhánh LLM mà chưa ghi nhận tiêu thụ."""
    return not is_rate_limited(
        request,
        scope="aiassist_llm_budget",
        limit=AI_LIMIT,
        window_seconds=AI_WINDOW,
        record=False,
    )


def _record_ai_use(request):
    """Chỉ tính lượt khi AI THẬT SỰ trả lời - câu hỏi đi nhánh luật không tốn lượt."""
    record_rate_event(
        request,
        scope="aiassist_llm_budget",
        window_seconds=AI_WINDOW,
    )


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
        if payload.get("action") == "clear":
            request.session["chat_history"] = []
            request.session.modified = True
            return JsonResponse({"status": "cleared"})
        question = str(payload.get("question", ""))[:500]
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Dữ liệu gửi lên không hợp lệ."},
                            status=400)

    chat_history = request.session.get("chat_history", [])
    result = answer(question, user=request.user, allow_ai=_ai_allowed(request),
                    history=chat_history)
    if result.get("source") == "ai":
        _record_ai_use(request)

    # Cập nhật ngữ cảnh hội thoại đa lượt (tối đa 6 tin nhắn gần nhất)
    answer_text = result.get("text", "")
    if answer_text:
        chat_history.append({"role": "user", "text": question})
        chat_history.append({"role": "assistant", "text": answer_text})
        request.session["chat_history"] = chat_history[-6:]
        request.session.modified = True
    return JsonResponse(result)
