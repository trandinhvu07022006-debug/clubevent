from django.contrib import admin

from .models import Feedback, FeedbackSummary


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "rating", "created_at")
    list_filter = ("rating", "event")
    search_fields = ("user__full_name", "content")


@admin.register(FeedbackSummary)
class FeedbackSummaryAdmin(admin.ModelAdmin):
    list_display = ("event", "feedback_count", "generated_at")
