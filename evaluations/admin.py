from django.contrib import admin

from .models import (
    EvaluationCriterionScore,
    EvaluationCycle,
    EvaluationResponse,
    MemberEvaluation,
    MemberRecognition,
)


@admin.register(EvaluationCycle)
class EvaluationCycleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "starts_on", "ends_on", "status")


class CriterionInline(admin.TabularInline):
    model = EvaluationCriterionScore
    extra = 0


@admin.register(MemberEvaluation)
class MemberEvaluationAdmin(admin.ModelAdmin):
    list_display = ("cycle", "member", "department", "status", "overall_rating", "finalized_by")
    list_filter = ("cycle", "department", "status")
    inlines = [CriterionInline]


@admin.register(EvaluationResponse)
class EvaluationResponseAdmin(admin.ModelAdmin):
    list_display = ("evaluation", "author", "is_member_response", "created_at")


@admin.register(MemberRecognition)
class MemberRecognitionAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "scope", "department", "status", "is_public")
    list_filter = ("status", "scope", "is_public")
