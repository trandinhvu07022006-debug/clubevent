from django.contrib import admin
from django.http import HttpResponse

from .eval_data import to_jsonl
from .models import AIInteractionLog, AIPromptProfile, ClubKnowledge


@admin.register(ClubKnowledge)
class ClubKnowledgeAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "visibility", "priority", "is_active", "updated_at")
    list_filter = ("category", "visibility", "is_active")
    search_fields = ("title", "keywords", "content")
    list_editable = ("priority", "is_active")


@admin.register(AIPromptProfile)
class AIPromptProfileAdmin(admin.ModelAdmin):
    list_display = ("task_key", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("task_key", "brand_voice", "extra_instructions")


@admin.action(description="Xuất các mẫu đã chọn sang JSONL (dữ liệu đánh giá)")
def export_eval_jsonl(modeladmin, request, queryset):
    response = HttpResponse(to_jsonl(queryset),
                            content_type="application/jsonl; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="kmg-ai-eval.jsonl"'
    return response


@admin.register(AIInteractionLog)
class AIInteractionLogAdmin(admin.ModelAdmin):
    list_display = ("question_short", "intent", "source", "feedback", "latency_ms",
                    "prompt_version", "created_at")
    list_filter = ("feedback", "source", "intent", "prompt_version")
    search_fields = ("question", "answer_preview", "feedback_note")
    readonly_fields = ("question", "intent", "source", "answer_preview", "latency_ms",
                       "model_name", "prompt_version", "created_at")
    actions = [export_eval_jsonl]

    @admin.display(description="Câu hỏi")
    def question_short(self, obj):
        return obj.question[:80]
