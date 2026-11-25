"""
Giao diện Web Phase 5 — Đánh giá 7 Tiêu chí, Vinh danh & Phân tích Báo cáo.

- Thành viên: xem phiếu đánh giá cá nhân đã chốt, gửi phản hồi xây dựng (`BE-06`).
- Cán bộ Ban: lập nháp đánh giá 7 tiêu chí theo số liệu tự động, chốt đánh giá (Trưởng ban).
- Ban Chủ nhiệm / Cố vấn: trung tâm phân tích vận hành toàn CLB & theo từng Ban, xuất CSV.
"""
from __future__ import annotations

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from accounts.models import User
from organization.models import Department, DepartmentMembership, DeptMembershipStatus
from organization.permissions import PermissionEngine, club_member_required
from organization.services import GovernanceError
from programs.services import _is_pure_advisor

from .analytics import (
    accessible_departments_for_analytics,
    build_department_analytics,
    build_executive_analytics,
    can_view_club_analytics,
    export_analytics_csv,
)
from .models import (
    EvaluationCriterion,
    EvaluationCriterionScore,
    EvaluationCycle,
    EvaluationStatus,
    MemberEvaluation,
    MemberRecognition,
    OverallRating,
    RatingLevel,
    RecognitionScope,
    RecognitionStatus,
)
from .services import (
    can_draft_in_department,
    can_finalize_in_department,
    can_view_evaluation,
    create_cycle,
    create_or_update_evaluation_draft,
    ensure_cycle,
    finalize_evaluation,
    get_current_cycle,
    nominate_recognition,
    reviewable_departments,
    submit_evaluation_response,
    verify_recognition,
)


@club_member_required
def evaluation_hub(request):
    actor = request.user
    is_advisor = _is_pure_advisor(actor)
    current_cycle = get_current_cycle()
    if not current_cycle:
        current_cycle = ensure_cycle(
            actor,
            code="2026-HK1",
            name="Đánh giá Học kỳ 1 / 2026",
            starts_on=parse_date("2026-01-01"),
            ends_on=parse_date("2026-06-30"),
            response_deadline=parse_date("2026-07-15"),
        )

    my_evaluations = list(
        MemberEvaluation.objects.select_related("cycle", "department", "finalized_by")
        .filter(member=actor, status=EvaluationStatus.CONFIRMED)
        .order_by("-cycle__starts_on", "-id")
    )

    review_depts = reviewable_departments(actor)
    can_review = bool(review_depts) and not is_advisor
    can_finalize_club = PermissionEngine.authorize(actor, "club.evaluation.finalize") and not is_advisor

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
        action = request.POST.get("action", "")
        try:
            if action == "nominate_recognition":
                recipient = get_object_or_404(User, pk=request.POST.get("recipient_id"))
                dept_id = (request.POST.get("department_id") or "").strip()
                dept = (
                    Department.objects.filter(pk=dept_id, is_active=True).first()
                    if dept_id.isdigit()
                    else None
                )
                scope = request.POST.get("scope", RecognitionScope.DEPARTMENT)
                rec = nominate_recognition(
                    actor,
                    recipient=recipient,
                    title=request.POST.get("title", ""),
                    citation=request.POST.get("citation", ""),
                    scope=scope,
                    department=dept,
                    cycle=current_cycle,
                    is_public=request.POST.get("is_public") == "1",
                )
                messages.success(request, f"Đã gửi đề cử vinh danh '{rec.title}' cho {recipient.public_name}.")
            elif action == "verify_recognition":
                rec = get_object_or_404(MemberRecognition, pk=request.POST.get("recognition_id"))
                decision = request.POST.get("decision", "")
                is_pub = request.POST.get("is_public") == "1" if "is_public" in request.POST else None
                verify_recognition(actor, rec, approve=(decision == "approve"), is_public=is_pub)
                messages.success(request, "Đã cập nhật trạng thái vinh danh.")
            return redirect("evaluations:hub")
        except (GovernanceError, PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))

    evaluations_to_review = []
    managed_members = []
    if can_review:
        evaluations_to_review = list(
            MemberEvaluation.objects.select_related("cycle", "member", "department")
            .filter(department__in=review_depts, cycle=current_cycle)
            .order_by("department__display_order", "member__full_name")
        )
        active_dms = DepartmentMembership.objects.select_related("user", "department").filter(
            department__in=review_depts, status=DeptMembershipStatus.ACTIVE
        ).exclude(user=actor)
        managed_members = [dm for dm in active_dms]

    recognitions = list(
        MemberRecognition.objects.select_related("recipient", "department", "proposed_by")
        .order_by("-created_at")[:20]
    )

    return render(
        request,
        "evaluations/hub.html",
        {
            "is_advisor": is_advisor,
            "current_cycle": current_cycle,
            "my_evaluations": my_evaluations,
            "can_review": can_review,
            "can_finalize_club": can_finalize_club,
            "review_depts": review_depts,
            "evaluations_to_review": evaluations_to_review,
            "managed_members": managed_members,
            "recognitions": recognitions,
            "scopes": RecognitionScope.choices,
        },
    )


@club_member_required
def evaluation_detail(request, pk: int):
    actor = request.user
    ev = get_object_or_404(
        MemberEvaluation.objects.select_related(
            "cycle", "member", "department", "drafted_by", "finalized_by"
        ),
        pk=pk,
    )
    if not can_view_evaluation(actor, ev):
        raise PermissionDenied("Bạn không có quyền xem phiếu đánh giá này.")

    is_advisor = _is_pure_advisor(actor)
    is_member = ev.member_id == actor.pk
    can_draft = can_draft_in_department(actor, ev.department) and not is_advisor
    can_finalize = can_finalize_in_department(actor, ev.department, target_user=ev.member) and not is_advisor

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")
        action = request.POST.get("action", "")
        try:
            if action == "save_draft" and can_draft and ev.status == EvaluationStatus.DRAFT:
                criteria_data = {}
                comments_data = {}
                for c in EvaluationCriterion.values:
                    score_val = request.POST.get(f"criterion_{c}")
                    if score_val:
                        criteria_data[c] = score_val
                    comments_data[c] = request.POST.get(f"comment_{c}", "")
                create_or_update_evaluation_draft(
                    actor,
                    cycle=ev.cycle,
                    member=ev.member,
                    department=ev.department,
                    criteria=criteria_data,
                    comments=comments_data,
                    overall_rating=request.POST.get("overall_rating", ""),
                    strengths=request.POST.get("strengths", ""),
                    growth_areas=request.POST.get("growth_areas", ""),
                    development_plan=request.POST.get("development_plan", ""),
                )
                messages.success(request, "Đã lưu bản nháp đánh giá.")
                return redirect("evaluations:detail", pk=ev.pk)

            elif action == "finalize" and can_finalize and ev.status == EvaluationStatus.DRAFT:
                finalize_evaluation(actor, ev)
                messages.success(request, "Đã chốt phiếu đánh giá và gửi kết quả cho thành viên.")
                return redirect("evaluations:detail", pk=ev.pk)

            elif action == "submit_response":
                msg = request.POST.get("message", "")
                submit_evaluation_response(actor, ev, msg)
                messages.success(request, "Đã gửi phản hồi trao đổi hai chiều.")
                return redirect("evaluations:detail", pk=ev.pk)

            else:
                messages.error(request, "Thao tác không hợp lệ.")
        except (GovernanceError, PermissionDenied, ValidationError) as exc:
            messages.error(request, "; ".join(getattr(exc, "messages", [str(exc)])))

    scores = list(ev.criterion_scores.all().order_by("id"))
    responses = list(ev.responses.select_related("author").order_by("created_at"))

    return render(
        request,
        "evaluations/detail.html",
        {
            "ev": ev,
            "scores": scores,
            "responses": responses,
            "is_advisor": is_advisor,
            "is_member": is_member,
            "can_draft": can_draft,
            "can_finalize": can_finalize,
            "criteria_choices": EvaluationCriterion.choices,
            "rating_levels": RatingLevel.choices,
            "overall_ratings": OverallRating.choices,
        },
    )


@club_member_required
def evaluation_draft_new(request):
    """Bắt đầu soạn phiếu đánh giá mới cho một thành viên trong Ban."""
    actor = request.user
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ chỉ đọc (INV-04).")

    cycle = get_current_cycle()
    if not cycle:
        messages.error(request, "Chưa có kỳ đánh giá nào đang mở.")
        return redirect("evaluations:hub")

    member_id = request.GET.get("member_id") or request.POST.get("member_id")
    dept_id = request.GET.get("dept_id") or request.POST.get("dept_id")
    member = get_object_or_404(User, pk=member_id)
    dept = get_object_or_404(Department, pk=dept_id, is_active=True)

    ev = create_or_update_evaluation_draft(
        actor,
        cycle=cycle,
        member=member,
        department=dept,
    )
    return redirect("evaluations:detail", pk=ev.pk)


@club_member_required
def analytics_dashboard(request):
    """Trung tâm Phân tích Vận hành & Đánh giá (Cấp CLB / Cấp Ban)."""
    actor = request.user
    is_advisor = _is_pure_advisor(actor)
    can_club = can_view_club_analytics(actor)
    depts = accessible_departments_for_analytics(actor)

    if not can_club and not depts:
        raise PermissionDenied("Bạn không có quyền xem trang phân tích.")

    selected_dept_id = request.GET.get("dept")
    selected_dept = None
    if selected_dept_id and selected_dept_id.isdigit():
        selected_dept = Department.objects.filter(pk=selected_dept_id, is_active=True).first()

    ctx = {
        "is_advisor": is_advisor,
        "can_club": can_club,
        "can_export": can_club or PermissionEngine.authorize(actor, "club.report.export"),
        "accessible_departments": depts,
        "selected_dept": selected_dept,
    }

    if can_club and not selected_dept:
        ctx["executive_data"] = build_executive_analytics(actor)
    elif selected_dept:
        ctx["dept_data"] = build_department_analytics(actor, selected_dept)
    elif depts:
        ctx["dept_data"] = build_department_analytics(actor, depts[0])
        ctx["selected_dept"] = depts[0]

    if request.GET.get("ai") == "1":
        from aiassist.services import analyze_club_operations
        from core.security import is_rate_limited
        if not is_rate_limited(request, scope="kmg_ai_assist", limit=20, window_seconds=300):
            if "executive_data" in ctx:
                ed = ctx["executive_data"]
                metrics = {
                    "club_kpis": ed.get("club_kpis", {}),
                    "departments": [
                        {
                            "name": ds["department"].name,
                            "members": ds["active_members_count"],
                            "task_rate": ds["tasks"]["rate"],
                            "attendance_rate": ds["events"]["attendance_rate"],
                        }
                        for ds in ed.get("dept_summaries", [])[:8]
                    ],
                }
                scope_label = "Toàn CLB"
            else:
                dd = ctx["dept_data"]
                metrics = {
                    "members": dd.get("active_members_count", 0),
                    "tasks": dd.get("tasks", {}),
                    "events": dd.get("events", {}),
                    "evaluations_confirmed": dd.get("evaluations", {}).get("confirmed", 0),
                }
                scope_label = ctx["selected_dept"].name if ctx.get("selected_dept") else "Ban chuyên môn"
            insight, used_ai, _ = analyze_club_operations(metrics, scope_label=scope_label)
            ctx["ai_insight"] = insight
            ctx["ai_used"] = used_ai

    return render(request, "evaluations/analytics.html", ctx)


@club_member_required
def analytics_csv(request):
    content = export_analytics_csv(request.user)
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="bao-cao-phan-tich-kmg.csv"'
    resp["Cache-Control"] = "private, no-store"
    return resp
