from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("username", "full_name", "mssv", "affiliation", "role", "is_locked")
    list_filter = ("role", "affiliation", "is_locked")
    search_fields = ("username", "full_name", "mssv", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("Thông tin CLB", {"fields": ("affiliation", "mssv", "school", "full_name", "phone",
                                      "role", "avatar", "is_locked")}),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "target")
    list_filter = ("action",)
    search_fields = ("target", "note")
