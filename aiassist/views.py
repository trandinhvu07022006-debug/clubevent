"""View cho trợ lý tra cứu."""
import json

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .chatbot import SUGGESTIONS, answer


def chat_page(request):
    """Trang chat đầy đủ, ai cũng vào được."""
    return render(request, "aiassist/chat.html", {"suggestions": SUGGESTIONS})


@require_POST
def chat_api(request):
    """
    Nhận câu hỏi, trả câu trả lời dạng JSON.

    Chỉ nhận POST vì đây là hành động gửi dữ liệu, và POST thì Django bắt
    buộc kiểm tra CSRF token — chặn được việc trang web khác gọi thay bạn.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        question = str(payload.get("question", ""))[:500]
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Dữ liệu gửi lên không hợp lệ."},
                            status=400)

    return JsonResponse(answer(question, user=request.user))
