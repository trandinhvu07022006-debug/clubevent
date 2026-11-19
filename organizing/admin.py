from django.contrib import admin

from finance.admin import LedgerReadOnlyAdmin

from .models import Department, EventPostMortem, Expense, Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "event", "department", "assignee", "priority", "status",
                    "deadline", "created_by", "created_by_ai")
    list_filter = ("status", "priority", "department", "event", "created_by_ai")
    search_fields = ("title", "assignee__full_name")


@admin.register(Expense)
class ExpenseAdmin(LedgerReadOnlyAdmin):
    list_display = ("title", "event", "category", "amount", "paid_by", "spent_on")
    list_filter = ("category", "event")
    search_fields = ("title", "note")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "lead", "order")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("members",)
    search_fields = ("name",)


@admin.register(EventPostMortem)
class EventPostMortemAdmin(admin.ModelAdmin):
    list_display = ("event", "generated_by", "generated_at")
    search_fields = ("event__name", "executive_summary")
    readonly_fields = ("generated_at",)
