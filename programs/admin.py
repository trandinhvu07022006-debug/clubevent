from django.contrib import admin

from .models import (
    ConfidentialDocument,
    DepartmentProposal,
    DepartmentShowcaseItem,
    DocumentACLEntry,
    DocumentAccessLog,
    DocumentCategory,
    DocumentVersion,
    PracticeParticipant,
    PracticeSession,
    ProposalComment,
    ProposalReview,
    TrainingCourse,
    TrainingEnrollment,
)


@admin.register(DocumentCategory)
class DocumentCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "department", "display_order", "is_active")
    list_filter = ("department", "is_active")


@admin.register(ConfidentialDocument)
class ConfidentialDocumentAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "department", "classification", "owner", "is_archived", "updated_at")
    list_filter = ("classification", "department", "is_archived")
    search_fields = ("code", "title")


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "original_filename", "file_size", "is_current", "created_at")
    list_filter = ("is_current",)


@admin.register(DocumentACLEntry)
class DocumentACLEntryAdmin(admin.ModelAdmin):
    list_display = (
        "document",
        "subject_type",
        "user",
        "position",
        "department",
        "permission_level",
        "is_break_glass",
        "is_active",
        "expires_at",
    )
    list_filter = ("subject_type", "permission_level", "is_break_glass", "is_active")


@admin.register(DocumentAccessLog)
class DocumentAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "document", "actor", "action", "ip_address", "reason")
    list_filter = ("action",)
    readonly_fields = ("document", "version", "actor", "action", "ip_address", "user_agent", "reason", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DepartmentProposal)
class DepartmentProposalAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "proposal_type", "scope", "department", "proposer", "status", "is_escalated_to_bcn")
    list_filter = ("status", "scope", "proposal_type", "department", "is_escalated_to_bcn")
    search_fields = ("code", "title")


@admin.register(ProposalReview)
class ProposalReviewAdmin(admin.ModelAdmin):
    list_display = ("proposal", "stage", "decision", "reviewer", "created_at")
    readonly_fields = ("proposal", "reviewer", "stage", "decision", "feedback", "created_at")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProposalComment)
class ProposalCommentAdmin(admin.ModelAdmin):
    list_display = ("proposal", "author", "created_at")


@admin.register(TrainingCourse)
class TrainingCourseAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "instructor", "starts_at", "capacity", "status")
    list_filter = ("department", "status")


@admin.register(TrainingEnrollment)
class TrainingEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("course", "user", "status", "attendance_count", "enrolled_at")
    list_filter = ("status",)


@admin.register(PracticeSession)
class PracticeSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "club_event", "starts_at", "status")
    list_filter = ("department", "status")


@admin.register(PracticeParticipant)
class PracticeParticipantAdmin(admin.ModelAdmin):
    list_display = ("session", "user", "assigned_role", "response_status")
    list_filter = ("response_status",)


@admin.register(DepartmentShowcaseItem)
class DepartmentShowcaseItemAdmin(admin.ModelAdmin):
    list_display = ("title", "department", "category_label", "item_type", "is_pinned", "created_at")
    list_filter = ("department", "item_type", "is_pinned")
