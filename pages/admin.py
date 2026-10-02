from django.contrib import admin

from .models import ClubOfficer


@admin.register(ClubOfficer)
class ClubOfficerAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "department", "term", "order", "is_current")
    list_editable = ("order", "is_current")
    list_filter = ("term", "is_current")
    autocomplete_fields = ("user",)
