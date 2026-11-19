from django.contrib import admin

from .models import FinancialTransaction, FundCategory, MemberContribution


class LedgerReadOnlyAdmin(admin.ModelAdmin):
    """Admin là màn hình tra cứu; mọi thay đổi đi qua workflow có kiểm tra quyền."""

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FundCategory)
class FundCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "tx_type", "is_active", "display_order")
    list_filter = ("tx_type", "is_active")
    search_fields = ("code", "name")


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(LedgerReadOnlyAdmin):
    list_display = (
        "tx_code",
        "tx_type",
        "title",
        "amount",
        "status",
        "department",
        "transaction_date",
        "created_by",
        "approved_by",
    )
    list_filter = ("status", "tx_type", "department", "transaction_date")
    search_fields = ("tx_code", "title", "created_by__username")

@admin.register(MemberContribution)
class MemberContributionAdmin(LedgerReadOnlyAdmin):
    list_display = ("member", "period_label", "title", "amount", "status", "paid_on")
    list_filter = ("status", "period_label", "department")
    search_fields = ("member__username", "member__full_name", "title")
