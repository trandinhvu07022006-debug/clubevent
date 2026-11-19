from django.contrib import admin

from .models import ContactSubmission


@admin.register(ContactSubmission)
class ContactSubmissionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "full_name", "email", "topic", "status")
    list_filter = ("topic", "status")
    search_fields = ("full_name", "email", "message")
