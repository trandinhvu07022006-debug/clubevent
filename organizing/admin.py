from django.contrib import admin

from .models import Expense, Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "event", "assignee", "priority", "status", "deadline",
                    "created_by", "created_by_ai")
    list_filter = ("status", "priority", "event", "created_by_ai")
    search_fields = ("title", "assignee__full_name")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "event", "category", "amount", "paid_by", "spent_on")
    list_filter = ("category", "event")
    search_fields = ("title", "note")
