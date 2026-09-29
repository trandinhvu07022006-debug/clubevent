from django.contrib import admin

from .models import Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("code", "event", "user", "ticket_type", "status", "price", "created_at")
    list_filter = ("status", "event")
    search_fields = ("code", "user__full_name", "user__mssv")
    readonly_fields = ("code",)
    date_hierarchy = "created_at"
