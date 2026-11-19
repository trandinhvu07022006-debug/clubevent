"""
View cho Module 01 — Public Website KMG (`/`) & API Liên hệ Công khai (`/api/v1/public/contact/`).

Tuân thủ nghiêm ngặt:
- `INT-01`: Chỉ truy vấn sự kiện `visibility=EventVisibility.PUBLIC` và đã duyệt mở/đã diễn ra;
  tuyệt đối không để lọt sự kiện `DRAFT` hay `INTERNAL`.
- `Data Privacy`: Chỉ hiển thị tên hiển thị, chức danh, Ban và kỹ năng đã xác minh của thành viên tiêu biểu;
  tuyệt đối không lộ SĐT, Email riêng tư hay Ngày sinh ra trang công khai.
"""
from __future__ import annotations

import hashlib
import json

from django.contrib import messages
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.security import get_client_ip, is_rate_limited
from events.models import Event, EventStatus, EventVisibility
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DeptMembershipStatus,
    PositionCode,
    UserSkill,
)

from .forms import PublicContactForm
from .models import ContactSubmission, ContactTopic


def _hash_ip(request) -> str:
    ip = get_client_ip(request)
    return hashlib.sha256(f"kmg-contact:{ip}".encode("utf-8")).hexdigest()[:32]


def home(request):
    """Trang chủ thương hiệu công khai KMG Editorial Stage (`/`)."""
    contact_form = PublicContactForm(request.POST or None)
    if request.method == "POST":
        if is_rate_limited(
            request,
            scope="public_contact",
            limit=5,
            window_seconds=600,
        ):
            messages.error(
                request,
                "Bạn đã gửi nhiều liên hệ liên tiếp. Vui lòng thử lại sau ít phút.",
            )
            return redirect(reverse("public_portal:home") + "#lien-he")
        if contact_form.is_valid():
            submission = contact_form.save(commit=False)
            submission.ip_hash = _hash_ip(request)
            submission.save()
            messages.success(
                request,
                "Cảm ơn bạn đã liên hệ CLB Âm nhạc KMG! Ban Truyền thông sự kiện sẽ phản hồi sớm nhất.",
            )
            return redirect(reverse("public_portal:home") + "#lien-he")

    now = timezone.now()
    departments = list(
        Department.objects.filter(is_active=True).annotate(
            active_members_count=Count(
                "memberships",
                filter=Q(memberships__status=DeptMembershipStatus.ACTIVE),
            )
        )
    )

    # Ban điều hành & Cố vấn đương nhiệm hiển thị minh bạch trên trang giới thiệu tổ chức
    leadership = list(
        Appointment.objects.select_related("user", "position", "department")
        .filter(
            is_active=True,
            ended_at__isnull=True,
            position__code__in=[
                PositionCode.CHAIRMAN,
                PositionCode.VICE_CHAIRMAN,
                PositionCode.ADVISOR,
                PositionCode.DEPT_HEAD,
            ],
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .order_by("position__rank_order", "department__display_order")
    )

    # Sự kiện CÔNG KHAI sắp tới (hoặc gần đây nếu chưa có sự kiện sắp mở)
    public_upcoming = list(
        Event.objects.filter(
            visibility=EventVisibility.PUBLIC,
            status__in=[EventStatus.OPEN, EventStatus.CLOSED],
            starts_at__gte=now,
        )
        .prefetch_related("ticket_types")
        .order_by("starts_at")[:6]
    )
    public_past = []
    if len(public_upcoming) < 3:
        public_past = list(
            Event.objects.filter(
                visibility=EventVisibility.PUBLIC,
                status=EventStatus.DONE,
            )
            .order_by("-starts_at")[: 3 - len(public_upcoming)]
        )

    # Thành viên tiêu biểu được vinh danh (không lộ PII nhạy cảm)
    featured_members = list(
        ClubMembership.objects.select_related("user", "user__profile")
        .prefetch_related(
            "user__department_memberships__department",
            "user__user_skills__skill",
        )
        .filter(status=ClubMembershipStatus.ACTIVE, is_featured=True)
        .order_by("member_code")[:6]
    )
    featured_cards = []
    for cm in featured_members:
        depts = [
            dm.department.name
            for dm in cm.user.department_memberships.all()
            if dm.status == DeptMembershipStatus.ACTIVE
        ]
        skills = [
            us.skill.name
            for us in cm.user.user_skills.all()
            if us.verification_status == "VERIFIED"
        ][:4]
        featured_cards.append(
            {
                "user": cm.user,
                "stage_name": getattr(getattr(cm.user, "profile", None), "stage_name", ""),
                "featured_title": cm.featured_title or "Thành viên tiêu biểu KMG",
                "departments": depts,
                "skills": skills,
            }
        )

    # Vinh danh thành viên công khai từ Phase 5 (tách biệt điểm số)
    from evaluations.services import public_recognitions

    public_honors = public_recognitions(limit=6)

    hero_stats = {
        "members": ClubMembership.objects.filter(
            status=ClubMembershipStatus.ACTIVE
        ).count(),
        "departments": len(departments) or 3,
        "verified_skills": UserSkill.objects.filter(
            verification_status="VERIFIED"
        ).count(),
        "public_events": Event.objects.filter(
            visibility=EventVisibility.PUBLIC
        )
        .exclude(status__in=[EventStatus.DRAFT, EventStatus.CANCELLED])
        .count(),
    }

    return render(
        request,
        "public_portal/home.html",
        {
            "departments": departments,
            "leadership": leadership,
            "public_upcoming": public_upcoming,
            "public_past": public_past,
            "featured_cards": featured_cards,
            "public_honors": public_honors,
            "hero_stats": hero_stats,
            "contact_form": contact_form,
        },
    )


@require_POST
def api_public_contact(request):
    """`POST /api/v1/public/contact/` — Gửi liên hệ công khai qua JSON API."""
    if is_rate_limited(
        request,
        scope="public_contact",
        limit=5,
        window_seconds=600,
    ):
        return JsonResponse(
            {
                "ok": False,
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Bạn gửi liên hệ quá nhanh. Vui lòng thử lại sau.",
                    "details": {},
                },
            },
            status=429,
        )
    try:
        payload = json.loads(request.body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return JsonResponse(
            {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Dữ liệu JSON không hợp lệ.",
                    "details": {},
                },
            },
            status=400,
        )

    if payload.get("website"):
        return JsonResponse(
            {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Yêu cầu không hợp lệ.",
                    "details": {},
                },
            },
            status=400,
        )

    form = PublicContactForm(
        data={
            "full_name": payload.get("full_name", ""),
            "email": payload.get("email", ""),
            "phone": payload.get("phone", ""),
            "topic": payload.get("topic", ContactTopic.GENERAL),
            "message": payload.get("message", ""),
            "website": "",
        }
    )
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Vui lòng kiểm tra lại thông tin liên hệ.",
                    "details": form.errors,
                },
            },
            status=400,
        )
    sub = form.save(commit=False)
    sub.ip_hash = _hash_ip(request)
    sub.save()
    return JsonResponse(
        {
            "ok": True,
            "data": {"id": sub.id, "status": sub.status},
            "meta": {"timestamp": timezone.localtime().isoformat()},
        },
        status=201,
    )
