from django.contrib import admin

from .models import Event, TicketType


class TicketTypeInline(admin.TabularInline):
    """Hiện các loại vé ngay trong trang chi tiết sự kiện."""
    model = TicketType
    extra = 1


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "status", "starts_at", "capacity", "created_by")
    list_filter = ("status", "category")
    search_fields = ("name", "location")
    date_hierarchy = "starts_at"
    inlines = [TicketTypeInline]


@admin.register(TicketType)
class TicketTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "event", "price", "quota", "sold")
    list_filter = ("event",)
