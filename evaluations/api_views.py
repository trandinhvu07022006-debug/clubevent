"""
REST API `/api/v1/evaluations/...`, `/api/v1/recognitions/...`, `/api/v1/analytics/...`.
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

from .analytics import (
    accessible_departments_for_analytics,
    build_department_analytics,
    build_executive_analytics,
    can_view_club_analytics,
    export_analytics_csv,
)
from .models import (
    EvaluationCycle,
    EvaluationStatus,
    MemberEvaluation,
    MemberRecognition,
    RecognitionScope,
)
from .services import (
    can_draft_in_department,
    can_view_evaluation,
    create_or_update_evaluation_draft,
    finalize_evaluation,
    get_current_cycle,
    nominate_recognition,
    submit_evaluation_response,
    verify_recognition,
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


def evaluation_to_json(ev: MemberEvaluation) -> dict:
    return {
        "id": ev.id,
        "cycle_code": ev.cycle.code,
        "member_id": ev.member_id,
        "member_name": ev.member.public_name,
        "department_id": ev.department_id,
        "department_name": ev.department.name,
        "status": ev.status,
        "overall_rating": ev.overall_rating or None,
        "strengths": ev.strengths,
        "growth_areas": ev.growth_areas,
        "development_plan": ev.development_plan,
        "telemetry_snapshot": ev.telemetry_snapshot,
        "criterion_scores": [
            {
                "criterion": s.criterion,
                "rating_level": s.rating_level,
                "auto_evidence": s.auto_evidence,
                "comment": s.comment,
            }
            for s in ev.criterion_scores.all()
        ],
        "finalized_at": ev.finalized_at.isoformat() if ev.finalized_at else None,
    }


def recognition_to_json(r: MemberRecognition) -> dict:
    return {
        "id": r.id,
        "title": r.title,
        "citation": r.citation,
        "scope": r.scope,
        "recipient_id": r.recipient_id,
        "recipient_name": r.recipient.public_name,
        "department_id": r.department_id,
        "department_name": r.department.name if r.department else None,
        "status": r.status,
        "is_public": r.is_public,
        "verified_at": r.verified_at.isoformat() if r.verified_at else None,
    }


@require_GET
@api_login_required
@_api_guard
def api_evaluations_my(request):
    """Thành viên (kể cả SUSPENDED) xem các phiếu đánh giá của chính mình đã chốt."""
    evals = MemberEvaluation.objects.select_related("cycle", "department").prefetch_related(
        "criterion_scores"
    ).filter(member=request.user, status=EvaluationStatus.CONFIRMED)
    return api_ok([evaluation_to_json(e) for e in evals])


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_evaluations_list(request):
    actor = request.user
    if request.method == "GET":
        dept_id = request.GET.get("department_id")
        if not dept_id:
            raise GovernanceError("Vui lòng truyền department_id để lọc phiếu đánh giá theo Ban.")
        dept = get_object_or_404(Department, pk=dept_id)
        if not can_draft_in_department(actor, dept):
            raise PermissionDenied("Bạn không có quyền xem danh sách đánh giá của Ban này.")
        evals = MemberEvaluation.objects.select_related("cycle", "department", "member").prefetch_related(
            "criterion_scores"
        ).filter(department=dept)
        return api_ok([evaluation_to_json(e) for e in evals])

    payload = _parse_json_body(request)
    member = get_object_or_404(User, pk=payload.get("member_id"))
    dept = get_object_or_404(Department, pk=payload.get("department_id"), is_active=True)
    cycle = get_current_cycle()
    if not cycle:
        raise GovernanceError("Không có kỳ đánh giá nào đang mở.")

    ev = create_or_update_evaluation_draft(
        actor,
        cycle=cycle,
        member=member,
        department=dept,
        criteria=payload.get("criteria"),
        comments=payload.get("comments"),
        overall_rating=payload.get("overall_rating", ""),
        strengths=payload.get("strengths", ""),
        growth_areas=payload.get("growth_areas", ""),
        development_plan=payload.get("development_plan", ""),
    )
    return api_ok(evaluation_to_json(ev), status=201)


@require_GET
@api_login_required
@_api_guard
def api_evaluation_detail(request, pk: int):
    ev = get_object_or_404(
        MemberEvaluation.objects.select_related("cycle", "department", "member").prefetch_related(
            "criterion_scores"
        ),
        pk=pk,
    )
    if not can_view_evaluation(request.user, ev):
        raise PermissionDenied("Bạn không có quyền xem phiếu đánh giá này.")
    return api_ok(evaluation_to_json(ev))


@require_POST
@api_login_required
@_api_guard
def api_evaluation_finalize(request, pk: int):
    ev = get_object_or_404(MemberEvaluation, pk=pk)
    ev = finalize_evaluation(request.user, ev)
    return api_ok(evaluation_to_json(ev))


@require_POST
@api_login_required
@_api_guard
def api_evaluation_response(request, pk: int):
    ev = get_object_or_404(MemberEvaluation, pk=pk)
    payload = _parse_json_body(request)
    resp = submit_evaluation_response(request.user, ev, payload.get("message", ""))
    return api_ok(
        {
            "id": resp.id,
            "author_id": resp.author_id,
            "is_member_response": resp.is_member_response,
            "message": resp.message,
            "created_at": resp.created_at.isoformat(),
        },
        status=201,
    )


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_recognitions(request):
    actor = request.user
    if request.method == "GET":
        qs = MemberRecognition.objects.select_related("recipient", "department")
        if request.GET.get("public_only") == "1":
            qs = qs.filter(status="VERIFIED", is_public=True)
        return api_ok([recognition_to_json(r) for r in qs[:100]])

    payload = _parse_json_body(request)
    recipient = get_object_or_404(User, pk=payload.get("recipient_id"))
    dept = None
    if payload.get("department_id"):
        dept = get_object_or_404(Department, pk=payload.get("department_id"))
    rec = nominate_recognition(
        actor,
        recipient=recipient,
        title=payload.get("title", ""),
        citation=payload.get("citation", ""),
        scope=payload.get("scope", RecognitionScope.DEPARTMENT),
        department=dept,
        is_public=bool(payload.get("is_public", False)),
    )
    return api_ok(recognition_to_json(rec), status=201)


@require_POST
@api_login_required
@_api_guard
def api_recognition_verify(request, pk: int):
    rec = get_object_or_404(MemberRecognition, pk=pk)
    payload = _parse_json_body(request)
    decision = (payload.get("decision") or "").upper()
    is_pub = payload.get("is_public")
    rec = verify_recognition(
        request.user, rec, approve=(decision == "APPROVE"), is_public=is_pub
    )
    return api_ok(recognition_to_json(rec))


@require_GET
@api_login_required
@_api_guard
def api_analytics_summary(request):
    actor = request.user
    dept_id = request.GET.get("department_id")
    if dept_id:
        dept = get_object_or_404(Department, pk=dept_id)
        data = build_department_analytics(actor, dept)
        return api_ok(
            {
                "department": {"id": dept.id, "name": dept.name},
                "active_members_count": data["active_members_count"],
                "tasks": data["tasks"],
                "events": data["events"],
                "training": data["training"],
                "proposals": data["proposals"],
                "documents_count": data["documents_count"],
                "evaluations": {
                    "total": data["evaluations"]["total"],
                    "confirmed": data["evaluations"]["confirmed"],
                    "draft": data["evaluations"]["draft"],
                    "distribution": data["evaluations"]["distribution"],
                },
                "recognitions_count": data["recognitions_count"],
            }
        )

    if can_view_club_analytics(actor):
        data = build_executive_analytics(actor)
        return api_ok(
            {
                "is_advisor": data["is_advisor"],
                "club_kpis": data["club_kpis"],
                "departments": [
                    {
                        "id": d["department"].id,
                        "name": d["department"].name,
                        "members": d["active_members_count"],
                        "task_rate": d["tasks"]["rate"],
                        "attendance_rate": d["events"]["attendance_rate"],
                        "evals_confirmed": d["evaluations"]["confirmed"],
                    }
                    for d in data["dept_summaries"]
                ],
                "recent_recognitions": data["recent_recognitions"],
            }
        )
    raise PermissionDenied("Bạn không có quyền truy cập tổng quan toàn CLB.")


@require_GET
@api_login_required
@_api_guard
def api_analytics_export_csv(request):
    content = export_analytics_csv(request.user)
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="bao-cao-phan-tich-kmg.csv"'
    resp["Cache-Control"] = "private, no-store"
    return resp
