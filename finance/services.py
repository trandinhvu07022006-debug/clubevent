"""
Tầng Nghiệp vụ Phase 5: Quản lý Quỹ & Tài chính Bất biến (`finance.services`):

- `WF22` & `INV-03`: Maker-Checker (`created_by != approved_by`).
- Bất biến giao dịch `CONFIRMED`: mọi sai lệch phải lập bút toán `ADJUSTMENT` (`CREDIT`/`DEBIT`).
- `CM-03` Bridge: Đồng bộ `organizing.Expense` -> Sổ cái và khoá sửa/xoá khi đã `CONFIRMED`.
- `PA-06`: Trưởng/Phó ban chỉ được đề xuất chi cho phạm vi Ban mình hoặc sự kiện Ban mình.
- `SEC-01`: Kiểm tra chứng từ hoá đơn (PDF/PNG/JPG/WEBP, magic bytes, <=10MB) và lưu trong `PrivateVaultStorage`.
- `SEC-02`: Xuất CSV an toàn với `safe_csv_row` chống Formula Injection.
"""
from __future__ import annotations

import csv
import hashlib
import io
import mimetypes
import os
import uuid
from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, User
from core.security import safe_csv_row
from notifications.models import NotificationKind
from notifications.services import notify_on_commit
from organization.models import (
    Appointment,
    Department,
    PositionCode,
)
from organization.permissions import PermissionEngine
from organization.services import GovernanceError
from programs.services import _is_active_club_actor, _is_pure_advisor

from .models import (
    AdjustmentDirection,
    ContributionStatus,
    FinancialTransaction,
    FundCategory,
    FundCategoryType,
    MemberContribution,
    TransactionStatus,
    TransactionType,
)

MAX_RECEIPT_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_EXTENSIONS = frozenset({".pdf", ".png", ".jpg", ".jpeg", ".webp"})


def bootstrap_finance_categories() -> list[FundCategory]:
    """Khởi tạo idempotent các danh mục Thu / Chi / Điều chỉnh mặc định của CLB KMG."""
    defaults = [
        ("THU-QUY", "Đóng góp quỹ thành viên định kỳ", FundCategoryType.INCOME, 1, "Quỹ sinh hoạt định kỳ của thành viên các Ban"),
        ("THU-TAI-TRO", "Tài trợ & Hợp tác biểu diễn", FundCategoryType.INCOME, 2, "Nguồn thu tài trợ, cat-xe biểu diễn hợp tác"),
        ("THU-VE-CLB", "Kết chuyển doanh thu bán vé sự kiện", FundCategoryType.INCOME, 3, "Chuyển doanh thu vé thực thu từ hệ thống bán vé"),
        ("CHI-SU-KIEN", "Chi phí tổ chức sự kiện & sân khấu", FundCategoryType.EXPENSE, 4, "Âm thanh, ánh sáng, trang trí, MC, hậu cần đêm nhạc"),
        ("CHI-TAP-LUYEN", "Thuê phòng tập, nhạc cụ & đạo cụ", FundCategoryType.EXPENSE, 5, "Chi phí thuê studio, dây đàn, dùi trống, phụ kiện"),
        ("CHI-THIET-BI", "Mua sắm & bảo trì thiết bị CLB", FundCategoryType.EXPENSE, 6, "Micro, dây tín hiệu, mixer, vật tư kỹ thuật"),
        ("CHI-DAO-TAO", "Chi phí đào tạo & gắn kết nội bộ", FundCategoryType.EXPENSE, 7, "Workshop chuyên môn, tài liệu học thuật"),
        ("DIEU-CHINH", "Bút toán điều chỉnh & hoàn ứng", FundCategoryType.ADJUSTMENT, 99, "Bút toán bù trừ sai sót sổ cái sau khi đã CONFIRMED"),
    ]
    created_or_existing = []
    for code, name, tx_type, order, desc in defaults:
        cat, _ = FundCategory.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "tx_type": tx_type,
                "display_order": order,
                "description": desc,
            },
        )
        created_or_existing.append(cat)
    return created_or_existing


def _generate_tx_code() -> str:
    return f"TX-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def validate_receipt_file(uploaded_file) -> dict:
    """
    Xác thực tệp chứng từ hoá đơn (`SEC-01`, `WF20`):
    - Chỉ chấp nhận `.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`, tối đa 10 MB.
    - Kiểm tra chữ ký byte đầu tệp (magic bytes) để chặn giả mạo HTML/SVG/PHP/EXE.
    """
    if uploaded_file is None:
        raise GovernanceError("Vui lòng chọn tệp chứng từ hoá đơn hợp lệ.")

    raw_name = os.path.basename(getattr(uploaded_file, "name", "") or "").strip()
    if not raw_name:
        raise GovernanceError("Tên tệp chứng từ không hợp lệ.")
    _, ext = os.path.splitext(raw_name)
    ext = ext.lower()
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        raise GovernanceError(
            f"Định dạng '{ext}' không được hỗ trợ cho chứng từ tài chính. Chỉ nhận PDF, PNG, JPG, JPEG, WEBP."
        )

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > MAX_RECEIPT_BYTES:
        raise GovernanceError("Dung lượng chứng từ vượt quá 10 MB.")

    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    data = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    if not data:
        raise GovernanceError("Tệp chứng từ rỗng (0 bytes).")
    if len(data) > MAX_RECEIPT_BYTES:
        raise GovernanceError("Dung lượng chứng từ vượt quá 10 MB.")

    head = data[:512]
    head_l = head.lstrip().lower()
    if head.startswith(b"MZ") or head.startswith(b"\x7fELF") or any(
        sig in head_l for sig in (b"<script", b"<html", b"<!doctype html", b"<svg", b"<?php", b"#!")
    ):
        raise GovernanceError("Phát hiện mã độc hoặc script giả mạo chứng từ, đã chặn tải lên.")

    # Kiểm tra magic bytes theo từng định dạng cho phép
    if ext == ".pdf" and not head.lstrip().startswith(b"%PDF-"):
        raise GovernanceError("Tệp .pdf không đúng cấu trúc PDF chuẩn.")
    elif ext == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise GovernanceError("Tệp .png không đúng cấu trúc PNG chuẩn.")
    elif ext in (".jpg", ".jpeg") and not data.startswith(b"\xff\xd8\xff"):
        raise GovernanceError("Tệp ảnh JPEG không đúng cấu trúc chuẩn.")
    elif ext == ".webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise GovernanceError("Tệp .webp không đúng cấu trúc WEBP chuẩn.")

    checksum = hashlib.sha256(data).hexdigest()
    guessed_ct, _ = mimetypes.guess_type(raw_name)
    content_type = (
        getattr(uploaded_file, "content_type", "") or guessed_ct or "application/octet-stream"
    )[:120]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    return {
        "original_name": raw_name[:255],
        "content_type": content_type,
        "checksum_sha256": checksum,
        "content_file": ContentFile(data, name=safe_name),
    }


def can_view_club_finance(actor: User) -> bool:
    """Kiểm tra actor có quyền xem sổ cái quỹ cấp toàn CLB (kể cả Cố vấn đọc giám sát `INV-04`)."""
    if not actor or not getattr(actor, "is_authenticated", False) or not actor.pk:
        return False
    return any(
        PermissionEngine.authorize(actor, code)
        for code in (
            "club.finance.view_summary",
            "club.finance.create_transaction",
            "club.finance.approve_transaction",
        )
    )


def can_propose_dept_expense(actor: User, department: Department | None) -> bool:
    """Kiểm tra Trưởng/Phó ban có quyền đề xuất khoản chi cho đúng Ban của mình (`PA-06`)."""
    if department is None or _is_pure_advisor(actor) or not _is_active_club_actor(actor):
        return False
    return PermissionEngine.authorize(
        actor, "dept.event.manage_internal", department=department
    ) or PermissionEngine.authorize(
        actor, "dept.proposal.submit_to_bcn", department=department
    )


def can_view_transaction(actor: User, tx: FinancialTransaction) -> bool:
    """Quyền xem chi tiết một phiếu thu/chi và tải chứng từ bảo mật (`SEC-01`, `PA-06`)."""
    if can_view_club_finance(actor):
        return True
    if not actor or not getattr(actor, "is_authenticated", False) or not actor.pk:
        return False
    if tx.created_by_id == actor.pk:
        return True
    if tx.department_id and can_propose_dept_expense(actor, tx.department):
        return True
    return False


def _notify_finance_approvers(actor: User, tx: FinancialTransaction) -> None:
    """Thông báo các Checker có quyền phê duyệt độc lập (loại trừ chính Maker `INV-03`)."""
    url = reverse("finance:transaction_detail", kwargs={"pk": tx.pk})
    approver_ids = set(
        Appointment.objects.filter(
            is_active=True,
            ended_at__isnull=True,
            position__code=PositionCode.CHAIRMAN,
        ).values_list("user_id", flat=True)
    )
    approver_ids |= set(
        Appointment.objects.filter(
            is_active=True,
            ended_at__isnull=True,
            position__code=PositionCode.VICE_CHAIRMAN,
            permission_grants__is_active=True,
            permission_grants__revoked_at__isnull=True,
            permission_grants__bundle_code="PORTFOLIO_FINANCE_DOC",
        ).values_list("user_id", flat=True)
    )
    approver_ids.discard(actor.pk)
    for recipient in User.objects.filter(id__in=approver_ids, is_locked=False):
        notify_on_commit(
            recipient,
            NotificationKind.FINANCE_TX,
            f"Phiếu tài chính chờ duyệt: {tx.tx_code}",
            f"{actor.public_name} vừa lập {tx.get_tx_type_display().lower()} \"{tx.title}\" ({tx.amount:,}đ).",
            url=url,
        )


@transaction.atomic
def create_financial_transaction(
    actor: User,
    *,
    tx_type: str,
    category: FundCategory,
    title: str,
    amount: int,
    transaction_date: date | None = None,
    department: Department | None = None,
    club_event=None,
    description: str = "",
    receipt_file=None,
) -> FinancialTransaction:
    """
    Lập phiếu Thu hoặc Chi mới ở trạng thái `PENDING_APPROVAL` (Maker-Checker `INV-03`).
    - Cố vấn bị chặn (`INV-04`).
    - Trưởng/Phó ban không có quyền tài chính toàn CLB chỉ được đề xuất phiếu CHI cho đúng Ban mình (`PA-06`).
    """
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04), không thể lập phiếu tài chính.")
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Tài khoản không có quyền hoạt động trong Không gian CLB.")

    if tx_type not in (TransactionType.INCOME, TransactionType.EXPENSE):
        raise GovernanceError("Chỉ hỗ trợ lập mới phiếu THU (INCOME) hoặc CHI (EXPENSE).")

    has_club_maker = PermissionEngine.authorize(actor, "club.finance.create_transaction")
    if not has_club_maker:
        if tx_type != TransactionType.EXPENSE or department is None:
            raise PermissionDenied(
                "Bạn không có quyền lập phiếu tài chính toàn CLB. Cán bộ Ban chỉ được đề xuất phiếu chi thuộc Ban mình."
            )
        if not can_propose_dept_expense(actor, department):
            raise PermissionDenied(
                f"Bạn không có quyền đề xuất chi tiêu cho {department.name} (PA-06)."
            )

    if club_event is not None and department is not None:
        if (
            getattr(club_event, "lead_department_id", None)
            and club_event.lead_department_id != department.id
            and not has_club_maker
        ):
            raise PermissionDenied(
                "Sự kiện được chọn không thuộc phạm vi Ban của bạn (PA-06)."
            )

    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Vui lòng nhập nội dung phiếu thu / chi.")
    try:
        amount_val = int(amount)
    except (TypeError, ValueError) as exc:
        raise GovernanceError("Số tiền giao dịch không hợp lệ.") from exc
    if amount_val <= 0:
        raise GovernanceError("Số tiền giao dịch phải lớn hơn 0 VND.")

    if category.tx_type != tx_type:
        raise GovernanceError(
            f"Danh mục '{category.name}' ({category.get_tx_type_display()}) không khớp loại phiếu."
        )

    receipt_meta = validate_receipt_file(receipt_file) if receipt_file is not None else None

    tx = FinancialTransaction(
        tx_code=_generate_tx_code(),
        tx_type=tx_type,
        status=TransactionStatus.PENDING_APPROVAL,
        category=category,
        department=department,
        club_event=club_event,
        title=clean_title[:200],
        description=(description or "").strip(),
        amount=amount_val,
        transaction_date=transaction_date or timezone.localdate(),
        created_by=actor,
    )
    if receipt_meta:
        tx.receipt = receipt_meta["content_file"]
        tx.receipt_original_name = receipt_meta["original_name"]
        tx.receipt_content_type = receipt_meta["content_type"]
        tx.receipt_checksum_sha256 = receipt_meta["checksum_sha256"]
    tx.save()

    AuditLog.write(
        actor,
        "Lập phiếu tài chính (Maker)",
        tx.tx_code,
        f"{tx.get_tx_type_display()} · {tx.title} · {tx.amount:,}đ",
    )
    _notify_finance_approvers(actor, tx)
    return tx


@transaction.atomic
def review_financial_transaction(
    actor: User,
    tx: FinancialTransaction,
    *,
    approve: bool,
    rejection_reason: str = "",
) -> FinancialTransaction:
    """
    Phê duyệt hoặc từ chối phiếu tài chính bởi Checker độc lập (`INV-03`).
    - Bắt buộc có quyền `club.finance.approve_transaction` và `actor != tx.created_by`.
    - Sau khi chuyển sang `CONFIRMED`, giao dịch trở thành BẤT BIẾN toàn phần.
    """
    # Giữ cùng thứ tự khóa với model Expense/FinancialTransaction để tránh
    # vừa sửa khoản chi vừa duyệt sổ quỹ hoặc deadlock giữa hai thao tác.
    from organizing.models import Expense
    expense_id = FinancialTransaction.objects.filter(pk=tx.pk).values_list("legacy_expense_id", flat=True).get()
    legacy_expense = None
    if expense_id:
        legacy_expense = Expense.objects.select_for_update().get(pk=expense_id)
    locked_tx = FinancialTransaction.objects.select_for_update().select_related(
        "created_by", "category", "department"
    ).get(pk=tx.pk)

    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04), không thể phê duyệt giao dịch tài chính.")
    PermissionEngine.require(
        actor,
        "club.finance.approve_transaction",
        target_user=locked_tx.created_by,
    )

    if locked_tx.status != TransactionStatus.PENDING_APPROVAL:
        raise GovernanceError(
            f"Phiếu {locked_tx.tx_code} đã ở trạng thái '{locked_tx.get_status_display()}', không thể duyệt lại."
        )

    now = timezone.now()
    if approve:
        if legacy_expense is not None and (
            legacy_expense.amount != locked_tx.amount
            or legacy_expense.spent_on != locked_tx.transaction_date
        ):
            raise GovernanceError(
                "Khoản chi nguồn đã thay đổi sau khi kết chuyển. Hãy đối soát lại phiếu trước khi duyệt."
            )
        locked_tx.status = TransactionStatus.CONFIRMED
        locked_tx.approved_by = actor
        locked_tx.approved_at = now
        locked_tx.rejection_reason = ""
        locked_tx.save()

        # Tự động xác nhận khoản đóng góp thành viên liên kết (nếu có)
        contrib = getattr(locked_tx, "member_contribution", None)
        if contrib is not None:
            contrib.status = ContributionStatus.CONFIRMED
            if not contrib.paid_on:
                contrib.paid_on = locked_tx.transaction_date
            contrib.save(update_fields=["status", "paid_on"])

        AuditLog.write(
            actor,
            "Duyệt ghi sổ quỹ CLB (Checker)",
            locked_tx.tx_code,
            f"CONFIRMED · {locked_tx.amount:,}đ (Maker: {locked_tx.created_by.username})",
        )
        notify_on_commit(
            locked_tx.created_by,
            NotificationKind.FINANCE_TX,
            f"Phiếu {locked_tx.tx_code} đã được duyệt ghi sổ",
            f"{actor.public_name} đã xác nhận ghi sổ khoản '{locked_tx.title}' ({locked_tx.amount:,}đ).",
            url=reverse("finance:transaction_detail", kwargs={"pk": locked_tx.pk}),
        )
    else:
        clean_reason = (rejection_reason or "").strip()
        if not clean_reason:
            raise GovernanceError("Vui lòng nêu rõ lý do khi từ chối phiếu tài chính.")
        locked_tx.status = TransactionStatus.REJECTED
        locked_tx.approved_by = actor
        locked_tx.approved_at = now
        locked_tx.rejection_reason = clean_reason[:300]
        locked_tx.save()

        contrib = getattr(locked_tx, "member_contribution", None)
        if contrib is not None:
            contrib.status = ContributionStatus.CANCELLED
            contrib.save(update_fields=["status"])

        AuditLog.write(
            actor,
            "Từ chối phiếu tài chính (Checker)",
            locked_tx.tx_code,
            f"REJECTED: {clean_reason}",
        )
        notify_on_commit(
            locked_tx.created_by,
            NotificationKind.FINANCE_TX,
            f"Phiếu {locked_tx.tx_code} bị từ chối",
            f"{actor.public_name} đã từ chối '{locked_tx.title}': {clean_reason}",
            url=reverse("finance:transaction_detail", kwargs={"pk": locked_tx.pk}),
        )
    return locked_tx


@transaction.atomic
def create_adjustment_transaction(
    actor: User,
    original_tx: FinancialTransaction,
    *,
    direction: str,
    amount: int,
    reason: str,
    receipt_file=None,
) -> FinancialTransaction:
    """
    Lập bút toán điều chỉnh / bù trừ (`ADJUSTMENT`) nối về giao dịch đã `CONFIRMED`.
    Bút toán điều chỉnh cũng đi qua quy trình Maker-Checker `PENDING_APPROVAL -> CONFIRMED`.
    """
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
    PermissionEngine.require(actor, "club.finance.create_transaction")

    if original_tx.status != TransactionStatus.CONFIRMED:
        raise GovernanceError(
            "Chỉ lập bút toán ADJUSTMENT cho giao dịch đã được duyệt ghi sổ (CONFIRMED)."
        )
    if direction not in AdjustmentDirection.values:
        raise GovernanceError("Chiều điều chỉnh phải là CREDIT (cộng) hoặc DEBIT (trừ).")
    try:
        amount_val = int(amount)
    except (TypeError, ValueError) as exc:
        raise GovernanceError("Số tiền điều chỉnh không hợp lệ.") from exc
    if amount_val <= 0:
        raise GovernanceError("Số tiền điều chỉnh phải lớn hơn 0 VND.")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise GovernanceError("Bắt buộc nhập lý do kế toán cho bút toán điều chỉnh.")

    bootstrap_finance_categories()
    adj_cat = FundCategory.objects.get(code="DIEU-CHINH")
    receipt_meta = validate_receipt_file(receipt_file) if receipt_file is not None else None

    adj_tx = FinancialTransaction(
        tx_code=_generate_tx_code(),
        tx_type=TransactionType.ADJUSTMENT,
        status=TransactionStatus.PENDING_APPROVAL,
        category=adj_cat,
        department=original_tx.department,
        club_event=original_tx.club_event,
        title=f"Điều chỉnh {original_tx.tx_code}: {clean_reason[:130]}",
        description=f"Điều chỉnh cho phiếu gốc {original_tx.tx_code} ({original_tx.amount:,}đ). Lý do: {clean_reason}",
        amount=amount_val,
        adjustment_direction=direction,
        adjusted_from=original_tx,
        transaction_date=timezone.localdate(),
        created_by=actor,
    )
    if receipt_meta:
        adj_tx.receipt = receipt_meta["content_file"]
        adj_tx.receipt_original_name = receipt_meta["original_name"]
        adj_tx.receipt_content_type = receipt_meta["content_type"]
        adj_tx.receipt_checksum_sha256 = receipt_meta["checksum_sha256"]
    adj_tx.save()

    AuditLog.write(
        actor,
        "Lập bút toán điều chỉnh (ADJUSTMENT)",
        adj_tx.tx_code,
        f"{direction} {amount_val:,}đ <- {original_tx.tx_code}",
    )
    _notify_finance_approvers(actor, adj_tx)
    return adj_tx


@transaction.atomic
def record_member_contribution(
    actor: User,
    *,
    member: User,
    period_label: str,
    title: str,
    amount: int,
    department: Department | None = None,
    paid_on: date | None = None,
    note: str = "",
    receipt_file=None,
) -> MemberContribution:
    """Ghi nhận đóng góp quỹ thành viên và đồng bộ tạo phiếu thu `PENDING_APPROVAL` trên sổ cái."""
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
    PermissionEngine.require(actor, "club.finance.create_transaction")

    bootstrap_finance_categories()
    cat_dues = FundCategory.objects.get(code="THU-QUY")
    clean_period = (period_label or "").strip() or f"{timezone.localdate():%Y}-Q{(timezone.localdate().month - 1)//3 + 1}"
    clean_title = (title or "").strip() or f"Đóng góp quỹ {clean_period} — {member.public_name}"

    tx = create_financial_transaction(
        actor,
        tx_type=TransactionType.INCOME,
        category=cat_dues,
        title=f"{clean_title} ({member.public_name})",
        amount=amount,
        transaction_date=paid_on or timezone.localdate(),
        department=department,
        description=note,
        receipt_file=receipt_file,
    )
    contrib = MemberContribution.objects.create(
        member=member,
        department=department,
        period_label=clean_period[:60],
        title=clean_title[:200],
        amount=tx.amount,
        status=ContributionStatus.PENDING,
        ledger_transaction=tx,
        paid_on=paid_on or timezone.localdate(),
        note=(note or "")[:255],
        recorded_by=actor,
    )
    AuditLog.write(
        actor,
        "Ghi nhận đóng góp quỹ thành viên",
        member,
        f"{clean_period} · {tx.amount:,}đ · {tx.tx_code}",
    )
    return contrib


@transaction.atomic
def sync_legacy_expense_to_ledger(
    actor: User,
    legacy_expense,
    *,
    department: Department | None = None,
) -> FinancialTransaction:
    """
    Cầu nối tương thích ngược `CM-03`: kết chuyển một `organizing.Expense` lên sổ cái chính thức.
    Sau khi phiếu này được Checker duyệt (`CONFIRMED`), khoản chi legacy bị khoá sửa/xoá hoàn toàn.
    """
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")

    has_club_maker = PermissionEngine.authorize(actor, "club.finance.create_transaction")
    if not has_club_maker:
        if not can_propose_dept_expense(actor, department):
            raise PermissionDenied("Bạn không có quyền kết chuyển khoản chi này lên sổ cái quỹ.")

    from organizing.models import Expense
    legacy_expense = Expense.objects.select_for_update().select_related("event").get(pk=legacy_expense.pk)
    linked_tx = FinancialTransaction.objects.filter(legacy_expense_id=legacy_expense.pk).first()
    if linked_tx is not None:
        raise GovernanceError(
            f"Khoản chi '{legacy_expense.title}' đã được liên kết với phiếu {linked_tx.tx_code}."
        )

    bootstrap_finance_categories()
    cat_event_exp = FundCategory.objects.get(code="CHI-SU-KIEN")
    tx = FinancialTransaction.objects.create(
        tx_code=_generate_tx_code(),
        tx_type=TransactionType.EXPENSE,
        status=TransactionStatus.PENDING_APPROVAL,
        category=cat_event_exp,
        department=department,
        title=f"[Quyết toán SK: {legacy_expense.event.name}] {legacy_expense.title}"[:200],
        description=legacy_expense.note or f"Đồng bộ từ ngân sách sự kiện {legacy_expense.event.name}",
        amount=int(legacy_expense.amount),
        transaction_date=legacy_expense.spent_on,
        legacy_expense=legacy_expense,
        created_by=actor,
    )
    AuditLog.write(
        actor,
        "Kết chuyển Expense sự kiện -> Sổ cái Quỹ (CM-03)",
        tx.tx_code,
        f"Expense#{legacy_expense.pk} · {legacy_expense.amount:,}đ",
    )
    _notify_finance_approvers(actor, tx)
    return tx


def compute_club_fund_summary() -> dict:
    """Tổng hợp số liệu Sổ cái Quỹ CLB (CONFIRMED) + Thống kê đối chiếu hệ thống vé/ngân sách sự kiện cũ (chỉ đọc)."""
    confirmed = FinancialTransaction.objects.filter(status=TransactionStatus.CONFIRMED)
    income_filter = Q(tx_type=TransactionType.INCOME) | Q(
        tx_type=TransactionType.ADJUSTMENT, adjustment_direction=AdjustmentDirection.CREDIT
    )
    expense_filter = Q(tx_type=TransactionType.EXPENSE) | Q(
        tx_type=TransactionType.ADJUSTMENT, adjustment_direction=AdjustmentDirection.DEBIT
    )
    # Một lần quét sổ cái thay vì lặp tổng hợp theo từng loại trạng thái.
    totals = FinancialTransaction.objects.aggregate(
        income=Sum("amount", filter=Q(status=TransactionStatus.CONFIRMED) & income_filter, default=0),
        expense=Sum("amount", filter=Q(status=TransactionStatus.CONFIRMED) & expense_filter, default=0),
        pending=Count("pk", filter=Q(status=TransactionStatus.PENDING_APPROVAL)),
        rejected=Count("pk", filter=Q(status=TransactionStatus.REJECTED)),
        confirmed=Count("pk", filter=Q(status=TransactionStatus.CONFIRMED)),
    )
    confirmed_income, confirmed_expense = totals["income"], totals["expense"]
    pending_count, rejected_count = totals["pending"], totals["rejected"]

    # Gom ở SQL để số truy vấn không tăng theo số danh mục/Ban hay số giao dịch.
    category_totals = {
        row["category_id"]: row
        for row in confirmed.order_by().values("category_id").annotate(count=Count("pk"), total=Sum("amount"))
    }
    by_category = [
        {"category": cat, "count": category_totals[cat.pk]["count"], "total": int(category_totals[cat.pk]["total"])}
        for cat in FundCategory.objects.filter(is_active=True)
        if cat.pk in category_totals
    ]
    department_totals = {
        row["department_id"]: row
        for row in confirmed.order_by().values("department_id").annotate(
            income=Sum("amount", filter=income_filter, default=0),
            expense=Sum("amount", filter=expense_filter, default=0),
        )
    }
    by_department = []
    for dept in Department.objects.filter(is_active=True):
        total = department_totals.get(dept.pk, {})
        inc, exp = int(total.get("income", 0)), int(total.get("expense", 0))
        by_department.append({"department": dept, "income": inc, "expense": exp, "net": inc - exp})

    # Đối chiếu chỉ đọc sang hệ thống vé & Expense sự kiện legacy
    from organizing.models import Expense
    from registrations.models import Ticket, TicketStatus

    legacy_ticket_revenue = (
        Ticket.objects.filter(
            status__in=[TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN],
            price__gt=0,
        ).aggregate(total=Sum("price"))["total"]
        or 0
    )
    legacy_expense_total = Expense.objects.aggregate(total=Sum("amount"))["total"] or 0
    legacy_expense_locked_count = Expense.objects.filter(
        ledger_transaction__status=TransactionStatus.CONFIRMED
    ).count()

    return {
        "confirmed_income": int(confirmed_income),
        "confirmed_expense": int(confirmed_expense),
        "net_club_balance": int(confirmed_income) - int(confirmed_expense),
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "confirmed_count": totals["confirmed"],
        "by_category": by_category,
        "by_department": by_department,
        "legacy_ticket_revenue": int(legacy_ticket_revenue),
        "legacy_expense_total": int(legacy_expense_total),
        "legacy_expense_locked_count": legacy_expense_locked_count,
        "member_contributions_confirmed": (
            MemberContribution.objects.filter(
                status=ContributionStatus.CONFIRMED
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        ),
    }


def export_ledger_csv(actor: User) -> str:
    """Xuất Sổ cái Tài chính CLB ra chuỗi CSV chuẩn UTF-8 BOM + chống CSV Injection (`SEC-02`)."""
    if not (
        can_view_club_finance(actor)
        or PermissionEngine.authorize(actor, "club.report.export")
    ):
        raise PermissionDenied("Bạn không có quyền xuất báo cáo tài chính CLB.")

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(
        [
            "Mã phiếu",
            "Ngày phát sinh",
            "Loại phiếu",
            "Danh mục",
            "Ban liên quan",
            "Nội dung",
            "Số tiền ký hiệu (VND)",
            "Trạng thái",
            "Người lập (Maker)",
            "Người duyệt (Checker)",
            "Phiếu gốc điều chỉnh",
        ]
    )
    txs = FinancialTransaction.objects.select_related(
        "category", "department", "created_by", "approved_by", "adjusted_from"
    ).order_by("-transaction_date", "-id")
    for tx in txs:
        writer.writerow(
            safe_csv_row(
                [
                    tx.tx_code,
                    tx.transaction_date.strftime("%d/%m/%Y"),
                    tx.get_tx_type_display(),
                    tx.category.name,
                    tx.department.name if tx.department_id else "Toàn CLB",
                    tx.title,
                    tx.signed_amount,
                    tx.get_status_display(),
                    tx.created_by.public_name if tx.created_by_id else "",
                    tx.approved_by.public_name if tx.approved_by_id else "",
                    tx.adjusted_from.tx_code if tx.adjusted_from_id else "",
                ]
            )
        )
    return buf.getvalue()
