from django.contrib import admin

from .models import Ticket, WaitlistEntry


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("code", "booking_ref", "event", "user", "ticket_type", "status", "price", "created_at")
    list_filter = ("status", "event")
    search_fields = ("code", "booking_ref", "user__full_name", "user__mssv")
    readonly_fields = ("code",)
    date_hierarchy = "created_at"


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "ticket_type", "status", "created_at", "resolved_at")
    list_filter = ("status", "ticket_type__event")
    search_fields = ("user__full_name", "user__mssv")
