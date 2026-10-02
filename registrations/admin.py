from django.contrib import admin

from .models import Ticket, TicketTransfer, WaitlistEntry


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


@admin.register(TicketTransfer)
class TicketTransferAdmin(admin.ModelAdmin):
    list_display = ("created_at", "ticket", "old_code", "from_user", "to_user")
    search_fields = ("old_code", "ticket__code", "from_user__full_name", "to_user__full_name")
