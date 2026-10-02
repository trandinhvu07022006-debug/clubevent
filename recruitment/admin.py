from django.contrib import admin

from .models import Application, RecruitmentRound


@admin.register(RecruitmentRound)
class RecruitmentRoundAdmin(admin.ModelAdmin):
    list_display = ("name", "opens_at", "closes_at")
    filter_horizontal = ("departments",)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("user", "round", "department", "status", "created_at")
    list_filter = ("round", "department", "status")
    search_fields = ("user__full_name", "user__mssv", "strengths")
