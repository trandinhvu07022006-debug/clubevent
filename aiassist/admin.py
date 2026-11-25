import json

from django.contrib import admin
from django.http import HttpResponse

from .models import AIInteractionLog, AIPromptProfile, ClubKnowledge


@admin.register(ClubKnowledge)
class ClubKnowledgeAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "priority", "is_active", "updated_at")
    list_filter = ("category", "is_active")
    search_fields = ("title", "keywords", "content")
    list_editable = ("priority", "is_active")


@admin.register(AIPromptProfile)
class AIPromptProfileAdmin(admin.ModelAdmin):
    list_display = ("task_key", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("task_key", "brand_voice", "extra_instructions")


@admin.action(description="Xuất các mẫu đã chọn sang JSONL (Gemini Fine-Tuning)")
def export_gemini_jsonl(modeladmin, request, queryset):
    lines = []
    for log in queryset:
        if not log.answer_preview:
            continue
        record = {
            "contents": [
                {"role": "user", "parts": [{"text": log.question}]},
                {"role": "model", "parts": [{"text": log.answer_preview}]},
            ]
        }
        lines.append(json.dumps(record, ensure_ascii=False))
    response = HttpResponse("\n".join(lines), content_type="application/jsonl; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="kmg-ai-finetune-gemini.jsonl"'
    return response


@admin.register(AIInteractionLog)
class AIInteractionLogAdmin(admin.ModelAdmin):
    list_display = ("question_short", "intent", "source", "feedback", "created_at")
    list_filter = ("feedback", "source", "intent")
    search_fields = ("question", "answer_preview", "feedback_note")
    readonly_fields = ("question", "intent", "source", "answer_preview", "created_at")
    actions = [export_gemini_jsonl]

    @admin.display(description="Câu hỏi")
    def question_short(self, obj):
        return obj.question[:80]
