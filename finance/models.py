"""
Mô hình dữ liệu Phase 5: Quản lý Quỹ & Tài chính CLB Bất biến (`finance`):

Tuân thủ:
- `WF22` & `INV-03`: Quy trình Maker-Checker (`created_by != approved_by`).
- Bất biến sổ cái (`CONFIRMED` ledger immutability): khi `status == CONFIRMED`, chặn
  mọi chỉnh sửa trường tài chính hoặc `.delete()` ở cả ORM và tầng Service; mọi sai sót
  bắt buộc lập bút toán bù trừ `ADJUSTMENT` nối về giao dịch gốc (`adjusted_from`).
- `CM-03` Bridge: kết nối `legacy_expense` với `organizing.Expense` và khoá sửa/xoá
  khoản chi sự kiện cũ sau khi đã xác nhận vào sổ cái.
- `SEC-01`: Chứng từ hoá đơn lưu trên `PrivateVaultStorage` ngoài `/media/`.
"""
from __future__ import annotations

import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from core.storage import private_vault_storage
from organization.models import Department


class FundCategoryType(models.TextChoices):
    INCOME = "INCOME", "Khoản thu"
    EXPENSE = "EXPENSE", "Khoản chi"
    ADJUSTMENT = "ADJUSTMENT", "Bút toán điều chỉnh"


class FundCategory(models.Model):
    """Danh mục thu / chi / điều chỉnh chuẩn của CLB KMG."""

    code = models.CharField("Mã danh mục", max_length=32, unique=True)
    name = models.CharField("Tên danh mục", max_length=120)
    tx_type = models.CharField(
        "Loại giao dịch", max_length=16, choices=FundCategoryType.choices
    )
    description = models.CharField("Mô tả", max_length=255, blank=True)
    is_active = models.BooleanField("Đang sử dụng", default=True)
    display_order = models.PositiveSmallIntegerField("Thứ tự", default=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Danh mục quỹ CLB"
        verbose_name_plural = "Danh mục quỹ CLB"
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return f"[{self.get_tx_type_display()}] {self.name}"


class TransactionType(models.TextChoices):
    INCOME = "INCOME", "Phiếu thu quỹ"
    EXPENSE = "EXPENSE", "Phiếu chi quỹ"
    ADJUSTMENT = "ADJUSTMENT", "Bút toán điều chỉnh / bù trừ"


class TransactionStatus(models.TextChoices):
    PENDING_APPROVAL = "PENDING_APPROVAL", "Chờ duyệt độc lập"
    CONFIRMED = "CONFIRMED", "Đã duyệt ghi sổ (Bất biến)"
    REJECTED = "REJECTED", "Từ chối"


class AdjustmentDirection(models.TextChoices):
    CREDIT = "CREDIT", "Bù tăng quỹ (+)"
    DEBIT = "DEBIT", "Giảm trừ quỹ (-)"


def finance_receipt_upload_to(instance, filename: str) -> str:
    _, ext = os.path.splitext(os.path.basename(filename or ""))
    safe_ext = ext.lower() if ext else ".bin"
    return f"finance/receipts/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{safe_ext}"


LEDGER_IMMUTABLE_MESSAGE = (
    "Giao dịch CONFIRMED là bất biến; hãy lập bút toán ADJUSTMENT bù trừ."
)


class FinancialTransactionQuerySet(models.QuerySet):
    """Không cho bulk write bỏ qua kiểm tra model và quy trình duyệt."""

    def update(self, **kwargs):
        raise ValidationError("Sổ quỹ không hỗ trợ update hàng loạt; hãy dùng dịch vụ nghiệp vụ.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Sổ quỹ không hỗ trợ bulk_update; hãy dùng dịch vụ nghiệp vụ.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Sổ quỹ không hỗ trợ bulk_create; hãy dùng dịch vụ nghiệp vụ.")

    def delete(self):
        with transaction.atomic(using=self.db):
            rows = list(self.select_for_update().order_by("pk").values_list("pk", "status"))
            if any(status == TransactionStatus.CONFIRMED for _, status in rows):
                raise ValidationError(LEDGER_IMMUTABLE_MESSAGE)
            # Chỉ xoá tập đã khóa, tránh quét thêm bản ghi vừa được tạo đồng thời.
            locked = self.filter(pk__in=[pk for pk, _ in rows])
            return super(FinancialTransactionQuerySet, locked).delete()


class FinancialTransaction(models.Model):
    """
    Sổ cái Giao dịch Tài chính Bất biến (`WF22`, `INV-03`, `CM-03`, `SEC-01`).

    Khi `status == TransactionStatus.CONFIRMED`:
    - Không được chỉnh sửa các trường tài chính qua `.save()`.
    - Không được gọi `.delete()`.
    - Mọi điều chỉnh số liệu phải tạo bản ghi `ADJUSTMENT` tham chiếu `adjusted_from`.
    """

    objects = FinancialTransactionQuerySet.as_manager()

    IMMUTABLE_FINANCIAL_FIELDS = (
        "tx_code",
        "tx_type",
        "status",
        "category_id",
        "department_id",
        "club_event_id",
        "legacy_expense_id",
        "title",
        "description",
        "amount",
        "adjustment_direction",
        "adjusted_from_id",
        "transaction_date",
        "created_by_id",
        "approved_by_id",
        "approved_at",
    )

    tx_code = models.CharField("Mã phiếu", max_length=32, unique=True)
    tx_type = models.CharField(
        "Loại phiếu", max_length=16, choices=TransactionType.choices
    )
    status = models.CharField(
        "Trạng thái",
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING_APPROVAL,
    )
    category = models.ForeignKey(
        FundCategory,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="Danh mục",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finance_transactions",
        verbose_name="Ban liên quan",
    )
    club_event = models.ForeignKey(
        "operations.ClubEventProfile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="finance_transactions",
        verbose_name="Sự kiện CLB",
    )
    legacy_expense = models.OneToOneField(
        "organizing.Expense",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_transaction",
        verbose_name="Khoản chi sự kiện cũ (CM-03)",
    )
    title = models.CharField("Nội dung giao dịch", max_length=200)
    description = models.TextField("Diễn giải chi tiết", blank=True)
    amount = models.PositiveBigIntegerField("Số tiền (VND)")
    adjustment_direction = models.CharField(
        "Chiều điều chỉnh",
        max_length=10,
        choices=AdjustmentDirection.choices,
        blank=True,
    )
    adjusted_from = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="adjustments",
        verbose_name="Điều chỉnh cho phiếu gốc",
    )
    transaction_date = models.DateField("Ngày phát sinh", default=timezone.localdate)
    receipt = models.FileField(
        "Chứng từ / Hóa đơn bảo mật",
        upload_to=finance_receipt_upload_to,
        storage=private_vault_storage,
        blank=True,
    )
    receipt_original_name = models.CharField(max_length=255, blank=True)
    receipt_content_type = models.CharField(max_length=120, blank=True)
    receipt_checksum_sha256 = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_finance_transactions",
        verbose_name="Người lập phiếu (Maker)",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_finance_transactions",
        verbose_name="Người phê duyệt (Checker)",
    )
    approved_at = models.DateTimeField("Thời điểm duyệt", null=True, blank=True)
    rejection_reason = models.CharField("Lý do từ chối", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Giao dịch Quỹ CLB"
        verbose_name_plural = "Sổ cái Quỹ CLB"
        ordering = ["-transaction_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=TransactionStatus.CONFIRMED)
                    | (
                        models.Q(approved_by__isnull=False, approved_at__isnull=False)
                        & ~models.Q(approved_by=models.F("created_by"))
                    )
                ),
                name="fin_confirmed_independent_checker",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "tx_type"]),
            models.Index(fields=["department", "status"]),
            models.Index(fields=["transaction_date"]),
            models.Index(fields=["status", "transaction_date", "id"], name="fin_status_date_id_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.tx_code} — {self.title} ({self.amount:,}đ)"

    @property
    def signed_amount(self) -> int:
        if self.tx_type == TransactionType.INCOME:
            return int(self.amount)
        if self.tx_type == TransactionType.EXPENSE:
            return -int(self.amount)
        if self.adjustment_direction == AdjustmentDirection.CREDIT:
            return int(self.amount)
        return -int(self.amount)

    @property
    def is_immutable(self) -> bool:
        return self.status == TransactionStatus.CONFIRMED

    def clean(self):
        super().clean()
        if not self.amount or self.amount <= 0:
            raise ValidationError("Số tiền giao dịch phải lớn hơn 0 VND.")
        if self.status == TransactionStatus.CONFIRMED and (
            not self.approved_by_id
            or self.approved_by_id == self.created_by_id
            or self.approved_at is None
        ):
            raise ValidationError("Ghi sổ cần người duyệt độc lập và thời điểm duyệt (INV-03).")
        if self.tx_type == TransactionType.ADJUSTMENT:
            if not self.adjusted_from_id:
                raise ValidationError("Bút toán điều chỉnh bắt buộc phải tham chiếu giao dịch gốc.")
            if self.adjustment_direction not in AdjustmentDirection.values:
                raise ValidationError("Bút toán điều chỉnh phải chỉ định chiều CREDIT hoặc DEBIT.")

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            # Cùng thứ tự khóa với Expense: khoản chi trước, phiếu sổ quỹ sau.
            # Kể cả khi kết chuyển lần đầu, giữ khóa khoản chi đến hết transaction.
            from organizing.models import Expense
            old_expense_id = None
            if self.pk:
                old_expense_id = type(self).objects.using(using).filter(pk=self.pk).values_list(
                    "legacy_expense_id", flat=True
                ).first()
            expense_ids = {pk for pk in (old_expense_id, self.legacy_expense_id) if pk}
            if expense_ids:
                list(Expense.objects.using(using).select_for_update().filter(
                    pk__in=expense_ids
                ).order_by("pk").values_list("pk", flat=True))
            if self.pk:
                existing_status = type(self).objects.using(using).select_for_update().filter(
                    pk=self.pk
                ).values_list("status", flat=True).first()
                if existing_status == TransactionStatus.CONFIRMED:
                    raise ValidationError(LEDGER_IMMUTABLE_MESSAGE)
            if self.status == TransactionStatus.CONFIRMED and self.legacy_expense_id:
                source = Expense.objects.using(using).get(pk=self.legacy_expense_id)
                if source.amount != self.amount or source.spent_on != self.transaction_date:
                    raise ValidationError("Khoản chi nguồn đã thay đổi; cần đối soát trước khi ghi sổ (CM-03).")
            self.clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=using):
            _protect_confirmed_transaction(type(self), self, using=using)
            return super().delete(*args, **kwargs)


@receiver(pre_delete, sender=FinancialTransaction)
def _protect_confirmed_transaction(sender, instance, using, **kwargs):
    # Collector không gọi model.delete(); kiểm tra lại DB cũng bảo vệ instance cũ.
    status = sender.objects.using(using).select_for_update().filter(pk=instance.pk).values_list(
        "status", flat=True
    ).first()
    if status == TransactionStatus.CONFIRMED:
        raise ValidationError(LEDGER_IMMUTABLE_MESSAGE)


class ContributionStatus(models.TextChoices):
    PENDING = "PENDING", "Chờ duyệt ghi sổ"
    CONFIRMED = "CONFIRMED", "Đã xác nhận đóng góp"
    WAIVED = "WAIVED", "Miễn đóng góp"
    CANCELLED = "CANCELLED", "Huỷ / Từ chối"


class MemberContribution(models.Model):
    """Theo dõi khoản đóng góp quỹ định kỳ của từng thành viên."""

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="member_contributions",
        verbose_name="Thành viên",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member_contributions",
        verbose_name="Ban trực thuộc",
    )
    period_label = models.CharField("Kỳ quỹ", max_length=60)
    title = models.CharField("Khoản đóng góp", max_length=200)
    amount = models.PositiveBigIntegerField("Số tiền (VND)")
    status = models.CharField(
        "Trạng thái",
        max_length=16,
        choices=ContributionStatus.choices,
        default=ContributionStatus.PENDING,
    )
    ledger_transaction = models.OneToOneField(
        FinancialTransaction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="member_contribution",
        verbose_name="Phiếu thu liên kết",
    )
    paid_on = models.DateField("Ngày nộp", null=True, blank=True)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_member_contributions",
        verbose_name="Người ghi nhận",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Đóng góp Quỹ Thành viên"
        verbose_name_plural = "Đóng góp Quỹ Thành viên"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["member", "status"]),
            models.Index(fields=["period_label"]),
        ]

    def __str__(self) -> str:
        return f"{self.member} — {self.period_label} ({self.amount:,}đ)"
