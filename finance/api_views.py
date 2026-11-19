"""
REST API `/api/v1/finance/...` — Phase 5 Quỹ & Tài chính Bất biến.
"""
from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User
from organization.api_views import _parse_json_body, api_error, api_ok
from organization.models import Department
from organization.permissions import api_login_required
from organization.services import GovernanceError

from .models import FinancialTransaction, FundCategory, MemberContribution
from .services import (
    can_view_club_finance,
    can_view_transaction,
    compute_club_fund_summary,
    create_adjustment_transaction,
    create_financial_transaction,
    export_ledger_csv,
    record_member_contribution,
    review_financial_transaction,
)


def _api_guard(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except PermissionDenied as exc:
            return api_error("PERMISSION_DENIED", str(exc) or "Không đủ quyền.", status=403)
        except Http404:
            return api_error("NOT_FOUND", "Không tìm thấy tài nguyên.", status=404)
        except ValidationError as exc:
            return api_error("VALIDATION_ERROR", "; ".join(exc.messages), status=400)
        except GovernanceError as exc:
            return api_error(getattr(exc, "code", "BUSINESS_RULE"), str(exc), status=400)

    return wrapper


def tx_to_json(tx: FinancialTransaction) -> dict:
    return {
        "id": tx.id,
        "tx_code": tx.tx_code,
        "tx_type": tx.tx_type,
        "status": tx.status,
        "category": tx.category.code,
        "department_id": tx.department_id,
        "title": tx.title,
        "amount": int(tx.amount),
        "signed_amount": tx.signed_amount,
        "adjustment_direction": tx.adjustment_direction or None,
        "adjusted_from_id": tx.adjusted_from_id,
        "legacy_expense_id": tx.legacy_expense_id,
        "transaction_date": tx.transaction_date.isoformat(),
        "has_receipt": bool(tx.receipt),
        "created_by_id": tx.created_by_id,
        "approved_by_id": tx.approved_by_id,
        "approved_at": tx.approved_at.isoformat() if tx.approved_at else None,
        "rejection_reason": tx.rejection_reason,
    }


def contribution_to_json(c: MemberContribution) -> dict:
    return {
        "id": c.id,
        "period_label": c.period_label,
        "title": c.title,
        "amount": int(c.amount),
        "status": c.status,
        "paid_on": c.paid_on.isoformat() if c.paid_on else None,
        "department_id": c.department_id,
        "tx_code": c.ledger_transaction.tx_code if c.ledger_transaction_id else None,
    }


@require_GET
@api_login_required
@_api_guard
def api_finance_summary(request):
    if not can_view_club_finance(request.user):
        raise PermissionDenied("Bạn không có quyền xem báo cáo quỹ CLB.")
    s = compute_club_fund_summary()
    return api_ok(
        {
            "confirmed_income": s["confirmed_income"],
            "confirmed_expense": s["confirmed_expense"],
            "net_club_balance": s["net_club_balance"],
            "pending_count": s["pending_count"],
            "confirmed_count": s["confirmed_count"],
            "rejected_count": s["rejected_count"],
            "legacy_ticket_revenue": s["legacy_ticket_revenue"],
            "legacy_expense_total": s["legacy_expense_total"],
            "legacy_expense_locked_count": s["legacy_expense_locked_count"],
            "by_department": [
                {"department_id": r["department"].id, "income": r["income"], "expense": r["expense"], "net": r["net"]}
                for r in s["by_department"]
            ],
        }
    )


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_finance_transactions(request):
    actor = request.user
    if request.method == "GET":
        if not can_view_club_finance(actor):
            raise PermissionDenied("Bạn không có quyền xem sổ cái quỹ CLB.")
        qs = FinancialTransaction.objects.select_related("category")
        status = request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return api_ok([tx_to_json(t) for t in qs[:200]])

    payload = _parse_json_body(request)
    category = FundCategory.objects.filter(code=payload.get("category", "")).first()
    if category is None:
        raise GovernanceError("Danh mục quỹ không hợp lệ.")
    dept = None
    if payload.get("department_id"):
        dept = get_object_or_404(Department, pk=payload.get("department_id"), is_active=True)
    tx = create_financial_transaction(
        actor,
        tx_type=payload.get("tx_type", ""),
        category=category,
        title=payload.get("title", ""),
        amount=payload.get("amount"),
        transaction_date=parse_date(payload.get("transaction_date") or ""),
        department=dept,
        description=payload.get("description", ""),
    )
    return api_ok(tx_to_json(tx), status=201)


@require_GET
@api_login_required
@_api_guard
def api_finance_transaction_detail(request, pk: int):
    tx = get_object_or_404(FinancialTransaction.objects.select_related("category"), pk=pk)
    if not can_view_transaction(request.user, tx):
        raise PermissionDenied("Bạn không có quyền xem phiếu tài chính này.")
    return api_ok(tx_to_json(tx))


@require_POST
@api_login_required
@_api_guard
def api_finance_transaction_review(request, pk: int):
    tx = get_object_or_404(FinancialTransaction, pk=pk)
    payload = _parse_json_body(request)
    decision = (payload.get("decision") or "").upper()
    if decision not in ("APPROVE", "REJECT"):
        raise GovernanceError("decision phải là APPROVE hoặc REJECT.")
    tx = review_financial_transaction(
        request.user,
        tx,
        approve=(decision == "APPROVE"),
        rejection_reason=payload.get("rejection_reason", ""),
    )
    return api_ok(tx_to_json(tx))


@require_POST
@api_login_required
@_api_guard
def api_finance_transaction_adjust(request, pk: int):
    tx = get_object_or_404(FinancialTransaction, pk=pk)
    payload = _parse_json_body(request)
    adj = create_adjustment_transaction(
        request.user,
        tx,
        direction=payload.get("direction", ""),
        amount=payload.get("amount"),
        reason=payload.get("reason", ""),
    )
    return api_ok(tx_to_json(adj), status=201)


@require_http_methods(["POST"])
@api_login_required
@_api_guard
def api_finance_contributions(request):
    payload = _parse_json_body(request)
    member = get_object_or_404(User, pk=payload.get("member_id"))
    dept = None
    if payload.get("department_id"):
        dept = get_object_or_404(Department, pk=payload.get("department_id"))
    c = record_member_contribution(
        request.user,
        member=member,
        period_label=payload.get("period_label", ""),
        title=payload.get("title", ""),
        amount=payload.get("amount"),
        department=dept,
        paid_on=parse_date(payload.get("paid_on") or ""),
        note=payload.get("note", ""),
    )
    return api_ok(contribution_to_json(c), status=201)


@require_GET
@api_login_required
@_api_guard
def api_finance_my_contributions(request):
    """Chính chủ (kể cả thành viên đang SUSPENDED) xem lịch sử đóng góp quỹ của mình."""
    items = MemberContribution.objects.select_related("ledger_transaction").filter(member=request.user)
    return api_ok([contribution_to_json(c) for c in items[:100]])


@require_GET
@api_login_required
@_api_guard
def api_finance_ledger_export(request):
    content = export_ledger_csv(request.user)
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="so-cai-quy-kmg.csv"'
    resp["Cache-Control"] = "private, no-store"
    return resp
