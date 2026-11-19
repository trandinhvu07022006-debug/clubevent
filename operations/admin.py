from django.contrib import admin

from .models import (
    Appeal,
    ClubAnnouncement,
    ClubEventProfile,
    ClubTask,
    ClubTaskAssignee,
    DisciplineCase,
    EventAttendance,
    EventDepartmentRole,
    TaskExtensionRequest,
    TaskReview,
    TaskSubmission,
)


@admin.register(ClubTask)
class ClubTaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "department",
        "workflow_status",
        "priority",
        "deadline",
        "reassignment_needed",
    )
    list_filter = ("department", "workflow_status", "priority", "reassignment_needed")
    search_fields = ("title", "description")


@admin.register(ClubTaskAssignee)
class ClubTaskAssigneeAdmin(admin.ModelAdmin):
    list_display = ("task", "user", "role", "personal_status", "progress_percent", "is_active")
    list_filter = ("role", "personal_status", "is_active")


@admin.register(TaskSubmission)
class TaskSubmissionAdmin(admin.ModelAdmin):
    list_display = ("task", "submitted_by", "is_late", "submitted_at")
    list_filter = ("is_late",)


@admin.register(TaskExtensionRequest)
class TaskExtensionRequestAdmin(admin.ModelAdmin):
    list_display = ("task", "requested_by", "requested_deadline", "status", "reviewed_by")
    list_filter = ("status",)


@admin.register(TaskReview)
class TaskReviewAdmin(admin.ModelAdmin):
    list_display = ("task", "reviewer", "decision", "quality_score", "created_at")
    list_filter = ("decision", "quality_score")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ClubEventProfile)
class ClubEventProfileAdmin(admin.ModelAdmin):
    list_display = (
        "event",
        "event_scope",
        "approval_status",
        "lead_department",
        "require_club_rsvp",
        "rsvp_freeze_at",
    )
    list_filter = ("event_scope", "approval_status", "lead_department")


@admin.register(EventDepartmentRole)
class EventDepartmentRoleAdmin(admin.ModelAdmin):
    list_display = ("club_event", "department", "role_type")
    list_filter = ("role_type", "department")


@admin.register(EventAttendance)
class EventAttendanceAdmin(admin.ModelAdmin):
    list_display = ("club_event", "user", "rsvp_status", "checkin_status", "responded_at")
    list_filter = ("rsvp_status", "checkin_status")


@admin.register(DisciplineCase)
class DisciplineCaseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "target_user",
        "trigger_type",
        "violation_count",
        "status",
        "reviewed_by",
    )
    list_filter = ("trigger_type", "status")


@admin.register(Appeal)
class AppealAdmin(admin.ModelAdmin):
    list_display = ("id", "appellant", "target_type", "status", "original_actor", "decided_by")
    list_filter = ("target_type", "status")


@admin.register(ClubAnnouncement)
class ClubAnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "is_pinned", "recipient_count", "published_by", "created_at")
    list_filter = ("is_pinned", "department")
