"""View cho trợ lý tra cứu và Trung tâm Đánh giá & Tối ưu AI (LLMOps Studio)."""
import io
import json
import logging
import time

from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import CommandError, call_command
from django.db.models import Q
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.security import is_rate_limited
from organization.permissions import PermissionEngine

from .chatbot import PRIVATE_INTENTS, SUGGESTIONS, answer, stream_answer
from .egress import DataClassification, normalize_classification
from .eval_data import to_jsonl
from .management.commands.export_finetune_dataset import build_finetune_records
from .models import (AIInteractionLog, AIPromptProfile, AITaskKey,
                     ClubKnowledge, FeedbackRating, KnowledgeCategory,
                     KnowledgeVisibility)
from .privacy import known_names, redact
from .services import visible_knowledge_levels

logger = logging.getLogger(__name__)

# Rate limit: tối đa 30 request/phút mỗi IP (SEC-06: lưu trong Cache, bỏ cookie vẫn bị chặn).
RATE_LIMIT = 30
RATE_WINDOW = 60  # giây

# Tối đa 10 lượt vào nhánh AI mỗi 10 phút/IP, tính cả lỗi và ngắt kết nối.
# Đây là ngân sách request chat, chưa phải ngân sách token hoặc số lần retry.
AI_LIMIT = 10
AI_WINDOW = 600   # giây
CHAT_HISTORY_POLICY_VERSION = 3

# Token đánh giá: chỉ người nhận câu trả lời mới có, hết hạn sau 24 giờ.
FEEDBACK_SALT = "aiassist.feedback"
FEEDBACK_MAX_AGE = 24 * 3600   # giây


def _has_studio_access(user) -> bool:
    """
    Chỉ Chủ nhiệm / Server Admin / Phó CN có quyền `club.document.manage_confidential`
    hoặc `club.event.approve` mới được truy cập AI Studio; chặn Cố vấn thuần túy và Guest.
    """
    if not user or not getattr(user, "is_authenticated", False) or getattr(user, "is_locked", False):
        return False
    return bool(
        PermissionEngine.authorize(user, "club.document.manage_confidential")
        or PermissionEngine.authorize(user, "club.event.approve")
    )


def _studio_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _has_studio_access(request.user):
            raise PermissionDenied("Bạn không có quyền quản trị AI Studio.")
        return view_func(request, *args, **kwargs)
    return wrapper


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


def _reserve_ai_attempt(request):
    """Kiểm tra và ghi nhận cùng một thao tác nguyên tử, trước khi gọi AI."""
    return not is_rate_limited(
        request,
        scope="aiassist_llm_budget",
        limit=AI_LIMIT,
        window_seconds=AI_WINDOW,
        record=True,
    )


def _load_chat_history(request):
    """
    Nạp và re-check quyền cho session chat_history qua mỗi lượt (AUD-006):
    - Vô hiệu hóa lịch sử cũ thiếu version mới hoặc đổi người dùng.
    - Đối chiếu trực tiếp `visible_knowledge_levels(request.user)` để cắt bỏ mọi
      ngữ cảnh INTERNAL/CONFIDENTIAL nếu user bị hạ/thu hồi quyền giữa chừng.
    """
    uid = request.user.pk if getattr(request.user, "is_authenticated", False) else "anon"
    if (
        request.session.get("chat_history_policy") != CHAT_HISTORY_POLICY_VERSION
        or request.session.get("chat_history_uid") != uid
    ):
        request.session["chat_history"] = []
        request.session["chat_history_policy"] = CHAT_HISTORY_POLICY_VERSION
        request.session["chat_history_uid"] = uid
        return []
    raw_history = request.session.get("chat_history", [])
    if not isinstance(raw_history, list):
        return []
    allowed = set(visible_knowledge_levels(request.user))
    filtered = [
        item for item in raw_history
        if isinstance(item, dict) and item.get("classification") in allowed
    ]
    if len(filtered) != len(raw_history):
        request.session["chat_history"] = filtered
        request.session.modified = True
    return filtered


def _log_interaction(question: str, result: dict, user=None,
                     classification: str = DataClassification.INTERNAL.value,
                     **telemetry) -> int | None:
    """
    Lưu log phục vụ đánh giá. Không gắn user/IP; câu hỏi được che PII theo mẫu;
    câu trả lời của ý định cá nhân (vé, công việc, lời chào có tên) thì KHÔNG lưu.
    """
    names = known_names(user)
    q_clean = redact((question or "").strip(), names)[:500]
    if not q_clean:
        return None
    intent = str(result.get("intent", ""))[:64]
    if intent in PRIVATE_INTENTS:
        cls_norm = DataClassification.PRIVATE_PII.value
        answer_text = ""
    else:
        cls_norm = normalize_classification(classification)
        answer_text = redact(result.get("text", ""), names)[:1000]
    try:
        log = AIInteractionLog.objects.create(
            question=q_clean,
            intent=intent,
            source=str(result.get("source", "rules"))[:16],
            answer_preview=answer_text,
            classification=cls_norm,
            **telemetry,
        )
        return log.pk
    except Exception:
        logger.warning("Không ghi được nhật ký AI", exc_info=True)
        return None


def _attach_feedback_token(question, result, user, started) -> str:
    """
    Ghi log (kèm độ trễ, model, phiên bản prompt, classification) rồi gắn token
    đã ký vào kết quả trả cho trình duyệt.
    """
    meta = dict(result.pop("meta", {}) or {})
    turn_cls = normalize_classification(
        meta.pop("classification", DataClassification.INTERNAL.value)
    )
    latency_ms = int((time.monotonic() - started) * 1000)
    log_id = _log_interaction(
        question, result, user, classification=turn_cls, latency_ms=latency_ms, **meta
    )
    if log_id:
        result["feedback_token"] = signing.dumps(log_id, salt=FEEDBACK_SALT)
    return turn_cls


def _remember(chat_history, question, result, user,
              classification: str = DataClassification.INTERNAL.value):
    """
    Thêm một lượt vào lịch sử hội thoại. Trả về True nếu có thêm.

    Lịch sử được gửi kèm cho AI ở câu sau, nên lượt hỏi đáp cá nhân / PRIVATE_PII bị bỏ hẳn.
    """
    answer_text = result.get("text", "")
    cls_norm = normalize_classification(classification)
    if (
        not answer_text
        or result.get("intent") in PRIVATE_INTENTS
        or cls_norm == DataClassification.PRIVATE_PII.value
    ):
        return False
    names = known_names(user)
    chat_history.append({
        "role": "user",
        "text": redact(question, names),
        "classification": cls_norm,
    })
    chat_history.append({
        "role": "assistant",
        "text": redact(answer_text, names),
        "classification": cls_norm,
    })
    return True


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

    chat_history = _load_chat_history(request)
    started = time.monotonic()
    result = answer(question, user=request.user,
                    allow_ai=lambda: _reserve_ai_attempt(request),
                    history=list(chat_history))

    turn_cls = _attach_feedback_token(question, result, request.user, started)

    # Cập nhật ngữ cảnh hội thoại đa lượt (tối đa 6 tin nhắn gần nhất)
    if _remember(chat_history, question, result, request.user, classification=turn_cls):
        request.session["chat_history"] = chat_history[-6:]
        request.session.modified = True
    return JsonResponse(result)


@require_POST
def chat_stream_api(request):
    """
    Endpoint SSE chia nhỏ câu trả lời hoàn chỉnh để hiển thị dạng máy gõ.
    Chưa phải streaming token trực tiếp từ LLM.
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

    chat_history = _load_chat_history(request)

    # Đảm bảo session key tồn tại trước khi mở stream để Set-Cookie được gửi đúng
    if not request.session.session_key:
        request.session.save()

    def sse_event_stream():
        final_result = None
        turn_cls = DataClassification.INTERNAL.value
        started = time.monotonic()
        for chunk in stream_answer(
            question, user=request.user,
            allow_ai=lambda: _reserve_ai_attempt(request), history=list(chat_history),
        ):
            if chunk.get("done"):
                final_result = chunk
                turn_cls = _attach_feedback_token(question, chunk, request.user, started)
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        if final_result:
            if _remember(chat_history, question, final_result, request.user, classification=turn_cls):
                request.session["chat_history"] = chat_history[-6:]
                request.session.modified = True
                request.session.save()

    response = StreamingHttpResponse(sse_event_stream(), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@require_POST
def chat_feedback_api(request):
    """
    Nhận đánh giá 👍/👎. Chỉ nhận token đã ký (không nhận id thô) và mỗi câu
    trả lời chỉ đánh giá được một lần.
    """
    if is_rate_limited(request, scope="aiassist_feedback", limit=RATE_LIMIT, window_seconds=RATE_WINDOW):
        return JsonResponse({"error": "Bạn gửi đánh giá quá nhanh."}, status=429)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
        token = str(payload.get("token", ""))
        rating = str(payload.get("rating", "")).upper()
        if rating not in (FeedbackRating.UP, FeedbackRating.DOWN):
            raise ValueError
        note = str(payload.get("note", "")).strip()[:255]
    except (ValueError, TypeError, UnicodeDecodeError):
        return JsonResponse({"error": "Dữ liệu đánh giá không hợp lệ."}, status=400)

    try:
        log_id = signing.loads(token, salt=FEEDBACK_SALT, max_age=FEEDBACK_MAX_AGE)
    except signing.BadSignature:   # gồm cả token hết hạn
        return JsonResponse({"error": "Phiên đánh giá không hợp lệ hoặc đã hết hạn."},
                            status=403)

    # Điều kiện feedback=NONE nằm trong câu UPDATE nên hai request đồng thời
    # cũng chỉ có một request ghi được.
    updated = AIInteractionLog.objects.filter(
        pk=log_id, feedback=FeedbackRating.NONE,
    ).update(feedback=rating, feedback_note=redact(note, known_names(request.user))[:255])
    if not updated:
        return JsonResponse({"error": "Câu trả lời này đã được đánh giá."}, status=409)
    return JsonResponse({"status": "ok", "rating": rating})


@_studio_required
def ai_studio(request):
    """Trung tâm Huấn luyện & Tối ưu AI (LLMOps Studio) theo PermissionEngine."""
    can_manage_confidential = PermissionEngine.authorize(
        request.user, "club.document.manage_confidential"
    )
    allowed_levels = visible_knowledge_levels(request.user)
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "add_kb":
            title = request.POST.get("title", "").strip()[:160]
            content = request.POST.get("content", "").strip()
            category = request.POST.get("category", KnowledgeCategory.GENERAL)
            visibility = request.POST.get("visibility", KnowledgeVisibility.INTERNAL)
            keywords = request.POST.get("keywords", "").strip()[:255]
            try:
                priority = max(1, min(int(request.POST.get("priority", 10)), 999))
            except (TypeError, ValueError):
                priority = 10
            if category not in KnowledgeCategory.values:
                category = KnowledgeCategory.GENERAL
            if visibility not in KnowledgeVisibility.values:
                visibility = KnowledgeVisibility.INTERNAL
            if visibility == KnowledgeVisibility.CONFIDENTIAL and not can_manage_confidential:
                raise PermissionDenied("Bạn không có quyền tạo tri thức CONFIDENTIAL.")
            if title and content:
                ClubKnowledge.objects.create(
                    title=title, category=category, visibility=visibility,
                    keywords=keywords, content=content, priority=priority,
                )
                messages.success(request, f"Đã thêm tri thức RAG: '{title}'.")
            else:
                messages.error(request, "Vui lòng nhập đầy đủ tiêu đề và nội dung tri thức.")

        elif action == "toggle_kb":
            kb = get_object_or_404(ClubKnowledge, pk=request.POST.get("kb_id"))
            if kb.visibility == KnowledgeVisibility.CONFIDENTIAL and not can_manage_confidential:
                raise PermissionDenied("Bạn không có quyền sửa tri thức CONFIDENTIAL.")
            kb.is_active = not kb.is_active
            kb.save(update_fields=["is_active", "updated_at"])
            messages.success(request, f"Đã {'bật' if kb.is_active else 'tắt'} mục '{kb.title}'.")

        elif action == "delete_kb":
            kb = get_object_or_404(ClubKnowledge, pk=request.POST.get("kb_id"))
            if kb.visibility == KnowledgeVisibility.CONFIDENTIAL and not can_manage_confidential:
                raise PermissionDenied("Bạn không có quyền xoá tri thức CONFIDENTIAL.")
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
                bad_json = False
                if raw_few_shot:
                    try:
                        few_shot = json.loads(raw_few_shot)
                    except ValueError:
                        bad_json = True
                        messages.error(request, "JSON ví dụ Few-Shot không đúng cú pháp.")
                if not bad_json:
                    prof = AIPromptProfile.objects.filter(task_key=task_key).first() or AIPromptProfile(task_key=task_key)
                    prof.brand_voice = brand_voice
                    prof.extra_instructions = extra_instructions
                    prof.few_shot_examples = few_shot
                    prof.is_active = is_active
                    try:
                        prof.full_clean()
                        prof.save()
                        messages.success(request, f"Đã cập nhật cấu hình cho modun '{dict(AITaskKey.choices).get(task_key)}'.")
                    except ValidationError as exc:
                        messages.error(request, "; ".join(exc.messages))

        elif action == "mark_log_up":
            log = get_object_or_404(AIInteractionLog, pk=request.POST.get("log_id"))
            if log.classification == DataClassification.CONFIDENTIAL.value and not can_manage_confidential:
                raise PermissionDenied("Bạn không có quyền chỉnh sửa nhật ký CONFIDENTIAL.")
            log.feedback = FeedbackRating.UP
            log.save(update_fields=["feedback"])
            messages.success(request, "Đã đưa câu hỏi này vào tập mẫu chuẩn (👍).")

        return redirect("aiassist:studio")

    log_scope = AIInteractionLog.objects.filter(
        classification__in=allowed_levels
    ).exclude(intent__in=PRIVATE_INTENTS)
    total_logs = log_scope.count()
    up_count = log_scope.filter(feedback=FeedbackRating.UP).count()
    down_count = log_scope.filter(feedback=FeedbackRating.DOWN).count()
    rated_total = up_count + down_count
    satisfaction_rate = (up_count * 100 // rated_total) if rated_total else 100

    need_review_logs = log_scope.filter(
        Q(feedback=FeedbackRating.DOWN) | Q(intent="unknown")
    ).order_by("-created_at")[:15]

    knowledge_items = ClubKnowledge.objects.filter(visibility__in=allowed_levels)
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
@_studio_required
def ai_studio_eval(request):
    """Chạy bộ kiểm định tự động evaluate_ai ngay từ giao diện web."""
    buf = io.StringIO()
    try:
        call_command("evaluate_ai", stdout=buf)
        messages.success(request, f"Kết quả Eval Suite:\n{buf.getvalue().strip()}")
    except CommandError as exc:
        messages.error(request, f"{exc}\n{buf.getvalue().strip()}")
    return redirect("aiassist:studio")


@_studio_required
def ai_studio_eval_export(request):
    """Xuất nhật ký đã đánh giá (👍/👎) đã che PII ra file Eval JSONL (mặc định chỉ PUBLIC)."""
    only_down = request.GET.get("only_down") == "1"
    include_internal = (
        request.GET.get("include_internal") == "1"
        and PermissionEngine.authorize(request.user, "club.document.manage_confidential")
    )
    allowed_cls = (
        [DataClassification.PUBLIC.value, DataClassification.INTERNAL.value]
        if include_internal
        else [DataClassification.PUBLIC.value]
    )
    ratings = [FeedbackRating.DOWN] if only_down else [FeedbackRating.DOWN, FeedbackRating.UP]
    logs = list(
        AIInteractionLog.objects.filter(
            feedback__in=ratings,
            classification__in=allowed_cls,
        )
        .exclude(intent__in=PRIVATE_INTENTS)
        .order_by("-created_at")[:500]
    )
    resp = HttpResponse(to_jsonl(logs), content_type="application/jsonl; charset=utf-8")
    fname = "kmg-eval-down.jsonl" if only_down else "kmg-eval-dataset.jsonl"
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


@require_POST
@_studio_required
def ai_studio_run_pipeline(request):
    """Chạy toàn bộ quy trình LLMOps (Seed -> Post-Mortem -> Evals -> Xuất JSONL)."""
    buf = io.StringIO()
    call_command("run_training_pipeline", stdout=buf)
    lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
    summary = " | ".join(ln for ln in lines if "EVAL SUMMARY" in ln or "Đã xuất" in ln)
    messages.success(
        request,
        f"Đã thực thi xong Quy trình Huấn luyện AI! {summary}" if summary else "Đã thực thi xong Quy trình Huấn luyện AI!",
    )
    return redirect("aiassist:studio")


@_studio_required
def ai_studio_export(request):
    """Xuất file .jsonl huấn luyện Fine-Tuning (mặc định chỉ dữ liệu PUBLIC)."""
    fmt = request.GET.get("format", "gemini")
    if fmt not in ("gemini", "openai"):
        fmt = "gemini"
    module = request.GET.get("module", "all")
    if module not in ("all", "chatbot", "marketing", "tasks", "postmortem"):
        module = "all"
    include_unrated = request.GET.get("include_unrated") == "1"
    include_internal = (
        request.GET.get("include_internal") == "1"
        and PermissionEngine.authorize(request.user, "club.document.manage_confidential")
    )

    records = build_finetune_records(
        fmt=fmt,
        module=module,
        include_unrated=include_unrated,
        include_internal=include_internal,
    )
    content = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + ("\n" if records else "")
    resp = HttpResponse(content, content_type="application/jsonl; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="kmg-finetune-{fmt}-{module}.jsonl"'
    return resp
