"""
Giao diện Web Phase 5 — Quỹ & Tài chính CLB (`/workspace/tai-chinh/`).

- Thành viên: xem đóng góp quỹ cá nhân.
- Trưởng/Phó ban: đề xuất phiếu chi thuộc Ban mình (`PA-06`).
- BCN mảng Tài chính: lập phiếu (Maker), duyệt độc lập (Checker — `INV-03`), bút toán điều chỉnh.
- Cố vấn: chỉ đọc báo cáo tổng hợp (`INV-04`), không có form thao tác.
"""
from __future__ import annotations

import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from accounts.models import User
from operations.models import ClubEventProfile
from organization.models import ClubMembershipStatus, Department
from organization.permissions import PermissionEngine, club_member_required
from organization.services import GovernanceError
from programs.services import _is_pure_advisor

from .models import (
    AdjustmentDirection,
    FinancialTransaction,
    FundCategory,
    MemberContribution,
    TransactionStatus,
    TransactionType,
)
from .services import (
    bootstrap_finance_categories,
    can_propose_dept_expense,
    can_view_club_finance,
    can_view_transaction,
    compute_club_fund_summary,
    create_adjustment_transaction,
    create_financial_transaction,
    export_ledger_csv,
    record_member_contribution,
    review_financial_transaction,
)


def _int_or_none(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


@club_member_required
def finance_hub(request):
    actor = request.user
    bootstrap_finance_categories()
    is_advisor = _is_pure_advisor(actor)
    can_view_club = can_view_club_finance(actor)
    can_make = PermissionEngine.authorize(actor, "club.finance.create_transaction")
    can_approve = PermissionEngine.authorize(actor, "club.finance.approve_transaction")
    proposable_depts = [
        d for d in Department.objects.filter(is_active=True) if can_propose_dept_expense(actor, d)
    ]

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
        action = request.POST.get("action", "")
        try:
            if action == "create_transaction":
                category = get_object_or_404(FundCategory, pk=request.POST.get("category_id"))
                dept_id = _int_or_none(request.POST.get("department_id"))
                dept = Department.objects.filter(pk=dept_id, is_active=True).first() if dept_id else None
                ev_id = _int_or_none(request.POST.get("club_event_id"))
                club_event = ClubEventProfile.objects.filter(pk=ev_id).first() if ev_id else None
                tx = create_financial_transaction(
                    actor,
                    tx_type=request.POST.get("tx_type", ""),
                    category=category,
                    title=request.POST.get("title", ""),
                    amount=request.POST.get("amount", ""),
                    transaction_date=parse_date(request.POST.get("transaction_date") or ""),
                    department=dept,
                    club_event=club_event,
                    description=request.POST.get("description", ""),
                    receipt_file=request.FILES.get("receipt"),
                )
                messages.success(request, f"Đã lập phiếu {tx.tx_code} — chờ Checker độc lập duyệt.")
            elif action == "record_contribution":
                member = get_object_or_404(User, pk=request.POST.get("member_id"))
                dept_id = _int_or_none(request.POST.get("department_id"))
                dept = Department.objects.filter(pk=dept_id).first() if dept_id else None
                contrib = record_member_contribution(
                    actor,
                    member=member,
                    period_label=request.POST.get("period_label", ""),
                    title=request.POST.get("title", ""),
                    amount=request.POST.get("amount", ""),
                    department=dept,
                    paid_on=parse_date(request.POST.get("paid_on") or ""),
                    note=request.POST.get("note", ""),
                    receipt_file=request.FILES.get("receipt"),
                )
                messages.success(
                    request,
                    f"Đã ghi nhận đóng góp của {member.public_name} (phiếu {contrib.ledger_transaction.tx_code}).",
                )
            else:
                messages.error(request, "Thao tác không hợp lệ.")
            return redirect("finance:hub")
        except (GovernanceError, PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))

    my_contributions = list(
        MemberContribution.objects.select_related("ledger_transaction", "department").filter(
            member=actor
        )[:20]
    )
    ctx = {
        "is_advisor": is_advisor,
        "can_view_club": can_view_club,
        "can_make": can_make and not is_advisor,
        "can_approve": can_approve and not is_advisor,
        "can_export": can_view_club or PermissionEngine.authorize(actor, "club.report.export"),
        "proposable_depts": proposable_depts,
        "my_contributions": my_contributions,
        "categories": list(FundCategory.objects.filter(is_active=True).exclude(tx_type="ADJUSTMENT")),
        "tx_types": [(TransactionType.INCOME, "Phiếu thu"), (TransactionType.EXPENSE, "Phiếu chi")],
    }
    if can_view_club:
        ctx["summary"] = compute_club_fund_summary()
        ctx["pending_txs"] = list(
            FinancialTransaction.objects.select_related("category", "department", "created_by")
            .filter(status=TransactionStatus.PENDING_APPROVAL)
            .order_by("transaction_date", "id")[:30]
        )
        ctx["recent_txs"] = list(
            FinancialTransaction.objects.select_related(
                "category", "department", "created_by", "approved_by"
            )[:40]
        )
        if can_make and not is_advisor:
            ctx["active_members"] = list(
                User.objects.filter(club_membership__status=ClubMembershipStatus.ACTIVE)
                .order_by("full_name")[:300]
            )
            ctx["departments"] = list(Department.objects.filter(is_active=True))
    elif proposable_depts:
        ctx["dept_txs"] = list(
            FinancialTransaction.objects.select_related("category", "department", "created_by")
            .filter(department__in=proposable_depts)[:40]
        )
        ctx["club_events"] = list(
            ClubEventProfile.objects.select_related("event", "lead_department")
            .filter(lead_department__in=proposable_depts)[:30]
        )
    return render(request, "finance/hub.html", ctx)


@club_member_required
def transaction_detail(request, pk: int):
    actor = request.user
    tx = get_object_or_404(
        FinancialTransaction.objects.select_related(
            "category", "department", "created_by", "approved_by", "adjusted_from", "legacy_expense"
        ),
        pk=pk,
    )
    if not can_view_transaction(actor, tx):
        raise PermissionDenied("Bạn không có quyền xem phiếu tài chính này.")
    is_advisor = _is_pure_advisor(actor)

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
        action = request.POST.get("action", "")
        try:
            if action in ("approve", "reject"):
                review_financial_transaction(
                    actor,
                    tx,
                    approve=(action == "approve"),
                    rejection_reason=request.POST.get("rejection_reason", ""),
                )
                messages.success(
                    request,
                    "Đã duyệt ghi sổ (CONFIRMED)." if action == "approve" else "Đã từ chối phiếu.",
                )
            elif action == "adjust":
                adj = create_adjustment_transaction(
                    actor,
                    tx,
                    direction=request.POST.get("direction", ""),
                    amount=request.POST.get("amount", ""),
                    reason=request.POST.get("reason", ""),
                    receipt_file=request.FILES.get("receipt"),
                )
                messages.success(request, f"Đã lập bút toán điều chỉnh {adj.tx_code}.")
                return redirect("finance:transaction_detail", pk=adj.pk)
            else:
                messages.error(request, "Thao tác không hợp lệ.")
            return redirect("finance:transaction_detail", pk=tx.pk)
        except (GovernanceError, PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))

    can_review = (
        not is_advisor
        and tx.status == TransactionStatus.PENDING_APPROVAL
        and PermissionEngine.authorize(
            actor, "club.finance.approve_transaction", target_user=tx.created_by
        )
    )
    can_adjust = (
        not is_advisor
        and tx.status == TransactionStatus.CONFIRMED
        and PermissionEngine.authorize(actor, "club.finance.create_transaction")
    )
    return render(
        request,
        "finance/transaction_detail.html",
        {
            "tx": tx,
            "can_review": can_review,
            "is_self_maker": tx.created_by_id == actor.pk,
            "can_adjust": can_adjust,
            "adjustments": list(tx.adjustments.select_related("created_by")),
            "directions": AdjustmentDirection.choices,
        },
    )


@club_member_required
def transaction_receipt(request, pk: int):
    tx = get_object_or_404(FinancialTransaction, pk=pk)
    if not can_view_transaction(request.user, tx):
        raise PermissionDenied("Bạn không có quyền xem chứng từ này (SEC-01).")
    if not tx.receipt:
        raise Http404("Phiếu này không có chứng từ đính kèm.")
    try:
        fh = tx.receipt.open("rb")
    except FileNotFoundError as exc:
        raise Http404("Không tìm thấy tệp chứng từ.") from exc
    ctype = tx.receipt_content_type or mimetypes.guess_type(tx.receipt.name)[0] or "application/octet-stream"
    resp = FileResponse(fh, content_type=ctype)
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    resp["Content-Disposition"] = f'inline; filename="{tx.tx_code}"'
    return resp


@club_member_required
def ledger_csv(request):
    content = export_ledger_csv(request.user)
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="so-cai-quy-kmg.csv"'
    resp["Cache-Control"] = "private, no-store"
    return resp
