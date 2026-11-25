"""View cho trợ lý tra cứu và Trung tâm Huấn luyện AI (LLMOps Studio)."""
import io
import json

from django.contrib import messages
from django.core.management import call_command
from django.db.models import Q
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import lead_required
from core.security import is_rate_limited, record_rate_event

from .chatbot import SUGGESTIONS, answer, stream_answer
from .management.commands.export_finetune_dataset import build_finetune_records
from .models import (AIInteractionLog, AIPromptProfile, AITaskKey,
                     ClubKnowledge, FeedbackRating, KnowledgeCategory)

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


@lead_required
def ai_studio(request):
    """Trung tâm Huấn luyện & Tối ưu AI (LLMOps Studio) dành cho Ban Chủ nhiệm."""
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "add_kb":
            title = request.POST.get("title", "").strip()[:160]
            content = request.POST.get("content", "").strip()
            category = request.POST.get("category", KnowledgeCategory.GENERAL)
            keywords = request.POST.get("keywords", "").strip()[:255]
            try:
                priority = max(1, min(int(request.POST.get("priority", 10)), 999))
            except (TypeError, ValueError):
                priority = 10
            if category not in KnowledgeCategory.values:
                category = KnowledgeCategory.GENERAL
            if title and content:
                ClubKnowledge.objects.create(
                    title=title, category=category, keywords=keywords,
                    content=content, priority=priority,
                )
                messages.success(request, f"Đã thêm tri thức RAG: '{title}'.")
            else:
                messages.error(request, "Vui lòng nhập đầy đủ tiêu đề và nội dung tri thức.")

        elif action == "toggle_kb":
            kb = get_object_or_404(ClubKnowledge, pk=request.POST.get("kb_id"))
            kb.is_active = not kb.is_active
            kb.save(update_fields=["is_active", "updated_at"])
            messages.success(request, f"Đã {'bật' if kb.is_active else 'tắt'} mục '{kb.title}'.")

        elif action == "delete_kb":
            kb = get_object_or_404(ClubKnowledge, pk=request.POST.get("kb_id"))
            title = kb.title
            kb.delete()
            messages.success(request, f"Đã xoá mục tri thức '{title}'.")

        elif action == "save_profile":
            task_key = request.POST.get("task_key", "")
            if task_key in AITaskKey.values:
                brand_voice = request.POST.get("brand_voice", "").strip()
                extra_instructions = request.POST.get("extra_instructions", "").strip()
                raw_few_shot = request.POST.get("few_shot_json", "").strip()
                is_active = request.POST.get("is_active") == "on"
                few_shot = []
                if raw_few_shot:
                    try:
                        parsed = json.loads(raw_few_shot)
                        if isinstance(parsed, list):
                            few_shot = [x for x in parsed if isinstance(x, dict)]
                    except ValueError:
                        messages.warning(request, "JSON ví dụ Few-Shot không hợp lệ — giữ nguyên danh sách cũ.")
                        existing = AIPromptProfile.objects.filter(task_key=task_key).first()
                        few_shot = existing.few_shot_examples if existing else []
                AIPromptProfile.objects.update_or_create(
                    task_key=task_key,
                    defaults={
                        "brand_voice": brand_voice,
                        "extra_instructions": extra_instructions,
                        "few_shot_examples": few_shot,
                        "is_active": is_active,
                    },
                )
                messages.success(request, f"Đã cập nhật cấu hình huấn luyện cho modun '{dict(AITaskKey.choices).get(task_key)}'.")

        elif action == "mark_log_up":
            log = get_object_or_404(AIInteractionLog, pk=request.POST.get("log_id"))
            log.feedback = FeedbackRating.UP
            log.save(update_fields=["feedback"])
            messages.success(request, "Đã đưa câu hỏi này vào tập mẫu chuẩn (👍).")

        return redirect("aiassist:studio")

    total_logs = AIInteractionLog.objects.count()
    up_count = AIInteractionLog.objects.filter(feedback=FeedbackRating.UP).count()
    down_count = AIInteractionLog.objects.filter(feedback=FeedbackRating.DOWN).count()
    rated_total = up_count + down_count
    satisfaction_rate = (up_count * 100 // rated_total) if rated_total else 100

    need_review_logs = AIInteractionLog.objects.filter(
        Q(feedback=FeedbackRating.DOWN) | Q(intent="unknown")
    ).order_by("-created_at")[:15]

    knowledge_items = ClubKnowledge.objects.all()
    profiles_map = {p.task_key: p for p in AIPromptProfile.objects.all()}
    profiles_list = []
    for key, label in AITaskKey.choices:
        prof = profiles_map.get(key)
        profiles_list.append({
            "task_key": key,
            "label": label,
            "brand_voice": prof.brand_voice if prof else "",
            "extra_instructions": prof.extra_instructions if prof else "",
            "few_shot_json": json.dumps(prof.few_shot_examples, ensure_ascii=False, indent=2) if (prof and prof.few_shot_examples) else "[]",
            "is_active": prof.is_active if prof else True,
            "configured": prof is not None,
        })

    return render(request, "aiassist/studio.html", {
        "total_logs": total_logs,
        "up_count": up_count,
        "down_count": down_count,
        "satisfaction_rate": satisfaction_rate,
        "knowledge_items": knowledge_items,
        "active_kb_count": knowledge_items.filter(is_active=True).count(),
        "profiles_list": profiles_list,
        "need_review_logs": need_review_logs,
        "categories": KnowledgeCategory.choices,
    })


@require_POST
@lead_required
def ai_studio_eval(request):
    """Chạy bộ kiểm định tự động evaluate_ai ngay từ giao diện web."""
    buf = io.StringIO()
    call_command("evaluate_ai", stdout=buf)
    output = buf.getvalue().strip()
    summary_line = output.splitlines()[-1] if output else "Đã hoàn tất kiểm định."
    if "100%" in summary_line:
        messages.success(request, f"Kết quả Eval Suite: {summary_line}")
    else:
        messages.warning(request, f"Kết quả Eval Suite:\n{output}")
    return redirect("aiassist:studio")


@lead_required
def ai_studio_export(request):
    """Xuất file .jsonl huấn luyện Fine-Tuning cho Gemini hoặc OpenAI."""
    fmt = request.GET.get("format", "gemini")
    if fmt not in ("gemini", "openai"):
        fmt = "gemini"
    module = request.GET.get("module", "all")
    if module not in ("all", "chatbot", "marketing", "postmortem"):
        module = "all"
    include_unrated = request.GET.get("include_unrated") == "1"

    records = build_finetune_records(fmt=fmt, module=module, include_unrated=include_unrated)
    content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else "")
    resp = HttpResponse(content, content_type="application/jsonl; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="kmg-finetune-{fmt}-{module}.jsonl"'
    return resp
