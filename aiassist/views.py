"""View cho trợ lý tra cứu."""
import json

from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from core.security import is_rate_limited, record_rate_event

from .chatbot import SUGGESTIONS, answer, stream_answer
from .models import AIInteractionLog, FeedbackRating

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


def _log_interaction(question: str, result: dict) -> int | None:
    """Lưu log ẩn danh (Zero PII) phục vụ đánh giá & tạo tập dữ liệu huấn luyện."""
    q_clean = (question or "").strip()[:500]
    if not q_clean:
        return None
    try:
        log = AIInteractionLog.objects.create(
            question=q_clean,
            intent=str(result.get("intent", ""))[:64],
            source=str(result.get("source", "rules"))[:16],
            answer_preview=str(result.get("text", ""))[:1000],
        )
        return log.pk
    except Exception:
        return None


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

    log_id = _log_interaction(question, result)
    if log_id:
        result["log_id"] = log_id

    # Cập nhật ngữ cảnh hội thoại đa lượt (tối đa 6 tin nhắn gần nhất)
    answer_text = result.get("text", "")
    if answer_text:
        chat_history.append({"role": "user", "text": question})
        chat_history.append({"role": "assistant", "text": answer_text})
        request.session["chat_history"] = chat_history[-6:]
        request.session.modified = True
    return JsonResponse(result)


@require_POST
def chat_stream_api(request):
    """
    Endpoint SSE trả token thời gian thực (Real-time Streaming via Server-Sent Events).
    Cho phép hiển thị câu trả lời dạng máy gõ (typewriter) giảm độ trễ cảm nhận.
    """
    if _is_rate_limited(request):
        return JsonResponse(
            {"error": "Bạn gửi quá nhanh, vui lòng chờ một chút."},
            status=429)

    try:
        payload = json.loads(request.body.decode("utf-8"))
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

    allow_ai = _ai_allowed(request)
    chat_history = list(request.session.get("chat_history", []))

    # Đảm bảo session key tồn tại trước khi mở stream để Set-Cookie được gửi đúng
    if not request.session.session_key:
        request.session.save()

    def sse_event_stream():
        final_result = None
        for chunk in stream_answer(question, user=request.user, allow_ai=allow_ai, history=chat_history):
            if chunk.get("done"):
                final_result = chunk
                log_id = _log_interaction(question, chunk)
                if log_id:
                    chunk["log_id"] = log_id
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        if final_result:
            if final_result.get("source") == "ai":
                _record_ai_use(request)
            answer_text = final_result.get("text", "")
            if answer_text:
                chat_history.append({"role": "user", "text": question})
                chat_history.append({"role": "assistant", "text": answer_text})
                request.session["chat_history"] = chat_history[-6:]
                request.session.modified = True
                request.session.save()

    response = StreamingHttpResponse(sse_event_stream(), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@require_POST
def chat_feedback_api(request):
    """Nhận đánh giá 👍/👎 của người dùng cho câu trả lời trợ lý (RLHF-lite)."""
    if is_rate_limited(request, scope="aiassist_feedback", limit=RATE_LIMIT, window_seconds=RATE_WINDOW):
        return JsonResponse({"error": "Bạn gửi đánh giá quá nhanh."}, status=429)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        log_id = int(payload.get("log_id"))
        rating = str(payload.get("rating", "")).upper()
        if rating not in (FeedbackRating.UP, FeedbackRating.DOWN):
            raise ValueError
        note = str(payload.get("note", "")).strip()[:255]
    except (ValueError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": "Dữ liệu đánh giá không hợp lệ."}, status=400)

    updated = AIInteractionLog.objects.filter(pk=log_id).update(
        feedback=rating,
        feedback_note=note,
    )
    if not updated:
        return JsonResponse({"error": "Không tìm thấy nhật ký tương tác."}, status=404)
    return JsonResponse({"status": "ok", "rating": rating})
