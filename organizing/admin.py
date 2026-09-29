from django.contrib import admin

from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "event", "assignee", "status", "deadline", "created_by_ai")
    list_filter = ("status", "event", "created_by_ai")
    search_fields = ("title", "assignee__full_name")
