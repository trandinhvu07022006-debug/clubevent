from django.contrib import admin

from .models import (
    Appointment,
    ClubMembership,
    Department,
    DepartmentMembership,
    MemberLifecycleEvent,
    MembershipApplication,
    Permission,
    PermissionGrant,
    PolicyVersion,
    Position,
    ResourceAccessRule,
    Skill,
    SkillCategory,
    UserSkill,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "slug", "is_demo", "is_active", "display_order")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ClubMembership)
class ClubMembershipAdmin(admin.ModelAdmin):
    list_display = ("member_code", "user", "status", "joined_at", "is_featured")
    list_filter = ("status", "is_featured")
    search_fields = ("member_code", "user__username", "user__full_name")


@admin.register(DepartmentMembership)
class DepartmentMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "department", "status", "joined_at")
    list_filter = ("department", "status")


@admin.register(MembershipApplication)
class MembershipApplicationAdmin(admin.ModelAdmin):
    list_display = ("user", "primary_department", "status", "created_at")
    list_filter = ("status", "primary_department")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "scope_type", "is_singleton", "is_read_only", "rank_order")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "position",
        "department",
        "term_label",
        "is_active",
        "started_at",
        "ended_at",
    )
    list_filter = ("position", "is_active", "department")


@admin.register(MemberLifecycleEvent)
class MemberLifecycleEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "event_type", "department", "title", "actor")
    list_filter = ("event_type", "department")
    readonly_fields = (
        "user",
        "event_type",
        "department",
        "actor",
        "title",
        "note",
        "metadata",
        "created_at",
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "department", "display_order")


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "is_active")
    list_filter = ("category", "is_active")


@admin.register(UserSkill)
class UserSkillAdmin(admin.ModelAdmin):
    list_display = ("user", "skill", "proficiency", "verification_status", "verified_by")
    list_filter = ("verification_status", "proficiency")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "module", "scope_type", "is_mutation")
    list_filter = ("module", "scope_type", "is_mutation")


@admin.register(PermissionGrant)
class PermissionGrantAdmin(admin.ModelAdmin):
    list_display = ("grantee", "bundle_code", "department", "is_active", "expires_at")
    list_filter = ("bundle_code", "is_active")


@admin.register(ResourceAccessRule)
class ResourceAccessRuleAdmin(admin.ModelAdmin):
    list_display = ("title", "resource_code", "department", "classification", "recommended_skill")
    list_filter = ("classification", "department")


@admin.register(PolicyVersion)
class PolicyVersionAdmin(admin.ModelAdmin):
    list_display = ("policy_key", "version_number", "title", "is_current", "effective_from")
