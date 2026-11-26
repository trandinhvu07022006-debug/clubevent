"""
Trình sinh dữ liệu mô phỏng toàn diện cho Staging & Load Test KMG (`seed_staging`).

- Tái lập tuyệt đối theo `--seed` và `--scale` (`smoke | medium | full`).
- Quy mô `full`: 120 thành viên, 500 khách, 200 hồ sơ ứng tuyển, 40 sự kiện,
  2.500 vé, 800 công việc, 3.000 bản ghi điểm danh, 300 giao dịch tài chính,
  150 tài liệu, 500 bài đăng, 2.000 bình luận, 20.000 tin nhắn mã hoá,
  10.000 thông báo, 50.000 nhật ký (AuditLog + AIInteractionLog).
- Bị chặn tuyệt đối trên Production bởi `assert_non_production_seed_allowed`.
- Không dùng PII thật: mọi email dùng `.example.invalid`, SĐT giả định 099xxxxxxx.
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import os
import random
import uuid

from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.utils import timezone

from accounts.models import AccountStatus, Affiliation, AuditLog, Role, User
from aiassist.models import AIInteractionLog
from core.db_guard import assert_non_production_seed_allowed
from events.models import Event, EventCategory, EventStatus, EventVisibility, TicketType
from finance.models import (
    AdjustmentDirection,
    FinancialTransaction,
    FundCategory,
    FundCategoryType,
    TransactionStatus,
    TransactionType,
)
from notifications.models import Notification, NotificationKind
from operations.models import (
    CheckinStatus,
    ClubEventApprovalStatus,
    ClubEventProfile,
    ClubEventScope,
    ClubTask,
    ClubTaskAssignee,
    EventAttendance,
    RsvpStatus,
    TaskPriority,
    TaskWorkflowStatus,
)
from organization.models import (
    ApplicationStatus,
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
    MembershipApplication,
)
from organization.services import bootstrap_organization_catalog
from organizing.models import Department as LegacyDepartment
from organizing.models import Task as LegacyTask
from organizing.models import TaskStatus as LegacyTaskStatus
from programs.models import (
    ConfidentialDocument,
    DocumentCategory,
    DocumentClassification,
)
from recruitment.models import Application as LegacyApplication
from recruitment.models import ApplicationStatus as LegacyAppStatus
from recruitment.models import RecruitmentRound, SkillLevel
from registrations.models import Ticket, TicketStatus
from social.crypto import encrypt_message_text, generate_wrapped_dek, unwrap_dek
from social.models import (
    ChatMessage,
    Conversation,
    ConversationMember,
    ConversationMemberRole,
    ConversationType,
    SocialComment,
    SocialPost,
    SocialPostVisibility,
)

SCALE_PRESETS = {
    "smoke": {
        "members": 12,
        "guests": 30,
        "applications": 20,
        "events": 6,
        "tickets": 120,
        "tasks": 40,
        "attendances": 120,
        "finance_txs": 24,
        "documents": 15,
        "posts": 25,
        "comments": 80,
        "messages": 200,
        "notifications": 150,
        "logs": 300,
    },
    "medium": {
        "members": 40,
        "guests": 150,
        "applications": 60,
        "events": 15,
        "tickets": 600,
        "tasks": 200,
        "attendances": 750,
        "finance_txs": 80,
        "documents": 45,
        "posts": 120,
        "comments": 500,
        "messages": 4000,
        "notifications": 2000,
        "logs": 10000,
    },
    "full": {
        "members": 120,
        "guests": 500,
        "applications": 200,
        "events": 40,
        "tickets": 2500,
        "tasks": 800,
        "attendances": 3000,
        "finance_txs": 300,
        "documents": 150,
        "posts": 500,
        "comments": 2000,
        "messages": 20000,
        "notifications": 10000,
        "logs": 50000,
    },
}

_HO = ("Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Vũ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương")
_DEM = ("Minh", "Quốc", "Thu", "Đức", "Ngọc", "Gia", "Khánh", "Tuấn", "Phương", "Thanh", "Hải", "Bảo")
_TEN = ("Anh", "Linh", "Trang", "Huy", "Lan", "Long", "Kiệt", "Thảo", "Hân", "Khoa", "Tâm", "Vy", "Nam", "Bình")
_EMOJI_SAMPLES = ("🎸", "🎶", "✨", "🎤", "🔥")


def _synth_name(rng: random.Random) -> str:
    return f"{rng.choice(_HO)} {rng.choice(_DEM)} {rng.choice(_TEN)}"


def generate_staging_dataset(
    *,
    seed: int = 2026,
    scale: str = "smoke",
    overrides: dict[str, int] | None = None,
) -> dict[str, int]:
    """Tạo bộ dữ liệu staging nhất quán, tái lập được theo seed và quy mô."""
    assert_non_production_seed_allowed("seed_staging")
    if scale not in SCALE_PRESETS:
        raise ValueError(f"Quy mô không hợp lệ: {scale}")

    counts = dict(SCALE_PRESETS[scale])
    for key, val in (overrides or {}).items():
        if val is not None and key in counts:
            counts[key] = max(0, int(val))

    rng = random.Random(seed)
    now = timezone.now()
    ns = f"stg{seed}"
    hashed_pw = make_password("StagingMock!2026")

    catalog = bootstrap_organization_catalog()
    depts = [catalog["departments"]["MEDIA_EVENT"], catalog["departments"]["SPECIALTY"], catalog["departments"]["TECHNICAL"]]

    # Đảm bảo 3 Ban legacy song song để hỗ trợ RecruitmentRound / LegacyTask
    legacy_depts = []
    for d in depts:
        ld, _ = LegacyDepartment.objects.get_or_create(
            slug=d.slug,
            defaults={"name": d.name, "description": d.short_description, "icon": d.icon, "order": d.display_order},
        )
        legacy_depts.append(ld)

    # 1. Tạo thành viên CLB & Khách (dữ liệu tổng hợp an toàn, không PII thật)
    member_users: list[User] = []
    guest_users: list[User] = []

    new_users: list[User] = []
    existing_usernames = set(User.objects.values_list("username", flat=True))
    base_phone_prefix = 990000000 + (seed % 900) * 10000

    for i in range(counts["members"]):
        uname = f"{ns}_m_{i:04d}"
        if uname in existing_usernames:
            continue
        email = f"{uname}@staging.example.invalid"
        phone = f"0{(base_phone_prefix + i):09d}"[-10:]
        full_name = _synth_name(rng)
        role = Role.LEAD if i < 2 else (Role.STAFF if i < max(6, counts["members"] // 6) else Role.MEMBER)
        status = (
            AccountStatus.LOCKED if i % 40 == 39 else AccountStatus.ACTIVE
        )
        new_users.append(
            User(
                username=uname,
                password=hashed_pw,
                full_name=full_name,
                display_name=full_name,
                email=email,
                normalized_email=email,
                email_canonical=email,
                phone=phone,
                normalized_phone=phone,
                mssv=f"STG{seed % 100:02d}{i:04d}",
                affiliation=Affiliation.KMA,
                role=role,
                account_status=status,
                is_locked=(status == AccountStatus.LOCKED),
                email_verified_at=now - timedelta(days=rng.randint(10, 300)),
            )
        )

    for i in range(counts["guests"]):
        uname = f"{ns}_g_{i:04d}"
        if uname in existing_usernames:
            continue
        email = f"{uname}@guest.example.invalid"
        phone = f"0{(base_phone_prefix + 5000 + i):09d}"[-10:]
        full_name = _synth_name(rng)
        acc_status = AccountStatus.UNVERIFIED if i % 4 == 0 else AccountStatus.ACTIVE
        new_users.append(
            User(
                username=uname,
                password=hashed_pw,
                full_name=full_name,
                display_name=full_name,
                email=email,
                normalized_email=email,
                email_canonical=email,
                phone=phone,
                normalized_phone=phone,
                affiliation=rng.choice([Affiliation.KMA, Affiliation.OTHER_SCHOOL, Affiliation.PUBLIC]),
                role=Role.GUEST,
                account_status=acc_status,
                email_verified_at=None if acc_status == AccountStatus.UNVERIFIED else now - timedelta(days=rng.randint(1, 90)),
            )
        )

    if new_users:
        User.objects.bulk_create(new_users, batch_size=500)

    member_users = list(User.objects.filter(username__startswith=f"{ns}_m_").order_by("id"))
    guest_users = list(User.objects.filter(username__startswith=f"{ns}_g_").order_by("id"))
    all_actors = member_users or list(User.objects.order_by("id")[:5])

    # 2. ClubMembership & DepartmentMembership
    existing_cm_uids = set(ClubMembership.objects.filter(user__in=member_users).values_list("user_id", flat=True))
    cm_objs = []
    dm_objs = []
    existing_dm_pairs = set(
        DepartmentMembership.objects.filter(user__in=member_users).values_list("user_id", "department_id")
    )
    for idx, u in enumerate(member_users):
        if u.id not in existing_cm_uids:
            cm_status = rng.choices(
                [ClubMembershipStatus.ACTIVE, ClubMembershipStatus.SUSPENDED, ClubMembershipStatus.ALUMNI, ClubMembershipStatus.LEFT],
                weights=[82, 6, 8, 4],
            )[0]
            cm_objs.append(
                ClubMembership(
                    user=u,
                    member_code=f"KMG-S{seed % 100:02d}-{idx + 1:04d}",
                    status=cm_status,
                    joined_at=(now - timedelta(days=rng.randint(30, 700))).date(),
                    is_featured=(idx < 6),
                    featured_title="Thành viên nổi bật Staging" if idx < 6 else "",
                )
            )
        dept_primary = depts[idx % len(depts)]
        if (u.id, dept_primary.id) not in existing_dm_pairs:
            dm_objs.append(
                DepartmentMembership(
                    user=u,
                    department=dept_primary,
                    status=DeptMembershipStatus.ACTIVE,
                    joined_at=(now - timedelta(days=rng.randint(20, 400))).date(),
                )
            )
            existing_dm_pairs.add((u.id, dept_primary.id))
        if idx % 4 == 0:
            dept_sec = depts[(idx + 1) % len(depts)]
            if (u.id, dept_sec.id) not in existing_dm_pairs:
                dm_objs.append(
                    DepartmentMembership(
                        user=u,
                        department=dept_sec,
                        status=DeptMembershipStatus.ACTIVE,
                        joined_at=(now - timedelta(days=rng.randint(5, 100))).date(),
                    )
                )
                existing_dm_pairs.add((u.id, dept_sec.id))
    if cm_objs:
        ClubMembership.objects.bulk_create(cm_objs, batch_size=500)
    if dm_objs:
        DepartmentMembership.objects.bulk_create(dm_objs, batch_size=500)

    # 3. Hồ sơ ứng tuyển (MembershipApplication + Legacy Application)
    ma_objs = []
    applicant_pool = guest_users or member_users
    existing_ma = MembershipApplication.objects.filter(motivation__startswith=f"[{ns}]").count()
    to_create_apps = max(0, counts["applications"] - existing_ma)
    half_new = to_create_apps // 2
    for i in range(half_new):
        u = applicant_pool[i % len(applicant_pool)]
        st = rng.choice([
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.DEPT_SCREENED,
            ApplicationStatus.APPROVED,
            ApplicationStatus.REJECTED,
        ])
        ma_objs.append(
            MembershipApplication(
                user=u,
                primary_department=depts[i % len(depts)],
                secondary_department=depts[(i + 1) % len(depts)] if i % 3 == 0 else None,
                declared_skills_text=f"Guitar đệm hát, Vocal {rng.choice(_EMOJI_SAMPLES)}",
                motivation=f"[{ns}] Mong muốn giao lưu âm nhạc KMG #{i}",
                status=st,
            )
        )
    if ma_objs:
        MembershipApplication.objects.bulk_create(ma_objs, batch_size=500)

    rnd, _ = RecruitmentRound.objects.get_or_create(
        name=f"[{ns}] Đợt tuyển Staging {seed}",
        defaults={
            "opens_at": now - timedelta(days=20),
            "closes_at": now + timedelta(days=20),
            "created_by": all_actors[0],
        },
    )
    existing_rec_uids = set(LegacyApplication.objects.filter(round=rnd).values_list("user_id", flat=True))
    rec_objs = []
    for i in range(to_create_apps - half_new):
        if i >= len(applicant_pool):
            break
        u = applicant_pool[i]
        if u.id in existing_rec_uids:
            continue
        existing_rec_uids.add(u.id)
        rec_objs.append(
            LegacyApplication(
                round=rnd,
                user=u,
                department=legacy_depts[i % len(legacy_depts)],
                strengths="Guitar Acoustic & Sáng tác",
                level=rng.choice(SkillLevel.values),
                motivation=f"[{ns}] Ứng tuyển đợt {seed}",
                status=rng.choice(LegacyAppStatus.values),
            )
        )
    if rec_objs:
        LegacyApplication.objects.bulk_create(rec_objs, batch_size=500)

    # 4. Sự kiện & Loại vé & ClubEventProfile
    existing_ev_count = Event.objects.filter(name__startswith=f"[{ns}]").count()
    ev_to_create = max(0, counts["events"] - existing_ev_count)
    new_events = []
    for i in range(ev_to_create):
        st = rng.choices(
            [EventStatus.OPEN, EventStatus.DONE, EventStatus.CLOSED, EventStatus.DRAFT, EventStatus.CANCELLED],
            weights=[35, 30, 15, 10, 10],
        )[0]
        offset_days = -rng.randint(5, 180) if st == EventStatus.DONE else rng.randint(2, 90)
        starts = now + timedelta(days=offset_days)
        new_events.append(
            Event(
                name=f"[{ns}] Đêm nhạc Acoustic KMG #{i + 1} {rng.choice(_EMOJI_SAMPLES)}",
                description=f"Sự kiện âm nhạc mô phỏng staging tiếng Việt có dấu #{i + 1}.",
                location=rng.choice(["Hội trường A - KMA", "Sân khấu ngoài trời KMA", "Acoustic Cafe Hà Nội"]),
                category=rng.choice(EventCategory.values),
                starts_at=starts,
                ends_at=starts + timedelta(hours=3),
                register_deadline=starts - timedelta(hours=6),
                capacity=rng.randint(60, 220),
                budget=rng.randint(15, 120) * 100000,
                status=st,
                visibility=EventVisibility.INTERNAL if i % 5 == 0 else EventVisibility.PUBLIC,
                created_by=all_actors[0],
            )
        )
    if new_events:
        Event.objects.bulk_create(new_events, batch_size=200)

    stg_events = list(Event.objects.filter(name__startswith=f"[{ns}]").order_by("id"))
    existing_tt_eids = set(TicketType.objects.filter(event__in=stg_events).values_list("event_id", flat=True))
    tt_objs = []
    cep_existing_eids = set(ClubEventProfile.objects.filter(event__in=stg_events).values_list("event_id", flat=True))
    cep_objs = []
    for idx, ev in enumerate(stg_events):
        if ev.id not in existing_tt_eids:
            price = 0 if idx % 3 == 0 else rng.choice([30000, 50000, 80000])
            tt_objs.append(TicketType(event=ev, name="Vé Tiêu chuẩn", price=price, quota=max(ev.capacity, 80), sold=0))
        if ev.id not in cep_existing_eids:
            cep_objs.append(
                ClubEventProfile(
                    event=ev,
                    event_scope=ClubEventScope.CLUB_WIDE if ev.visibility == EventVisibility.INTERNAL else ClubEventScope.PUBLIC_SHOW,
                    approval_status=ClubEventApprovalStatus.APPROVED if ev.status != EventStatus.DRAFT else ClubEventApprovalStatus.SUBMITTED,
                    lead_department=depts[idx % len(depts)],
                    proposed_by=all_actors[0],
                    approved_by=all_actors[min(1, len(all_actors) - 1)],
                )
            )
    if tt_objs:
        TicketType.objects.bulk_create(tt_objs, batch_size=200)
    if cep_objs:
        ClubEventProfile.objects.bulk_create(cep_objs, batch_size=200)

    stg_ticket_types = list(TicketType.objects.filter(event__in=stg_events).select_related("event"))
    stg_profiles = list(ClubEventProfile.objects.filter(event__in=stg_events))

    # 5. Vé (Ticket)
    buyer_pool = guest_users + member_users
    existing_tix = Ticket.objects.filter(booking_ref__startswith=f"S{seed % 100:02d}").count()
    tix_to_make = max(0, counts["tickets"] - existing_tix)
    ticket_objs = []
    sold_by_tt: dict[int, int] = {}
    for i in range(tix_to_make):
        tt = stg_ticket_types[i % len(stg_ticket_types)]
        st = rng.choices(
            [TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN, TicketStatus.PENDING, TicketStatus.CANCELLED],
            weights=[40, 35, 15, 10],
        )[0]
        if st != TicketStatus.CANCELLED:
            sold_by_tt[tt.id] = sold_by_tt.get(tt.id, 0) + 1
        code = f"S{seed % 100:02d}{i:09d}"[:12]
        ticket_objs.append(
            Ticket(
                code=code,
                event=tt.event,
                ticket_type=tt,
                user=buyer_pool[i % len(buyer_pool)],
                status=st,
                booking_ref=f"S{seed % 100:02d}{i // 2:05d}"[:8],
                price=tt.price,
                confirmed_at=now - timedelta(days=rng.randint(1, 20)) if st in (TicketStatus.CONFIRMED, TicketStatus.CHECKED_IN) else None,
                checked_in_at=now - timedelta(days=rng.randint(1, 10)) if st == TicketStatus.CHECKED_IN else None,
                checked_in_by=all_actors[0] if st == TicketStatus.CHECKED_IN else None,
            )
        )
    if ticket_objs:
        Ticket.objects.bulk_create(ticket_objs, batch_size=1000)
        for tt in stg_ticket_types:
            delta = sold_by_tt.get(tt.id, 0)
            if delta:
                TicketType.objects.filter(pk=tt.pk).update(sold=tt.sold + delta)

    # 6. Công việc (ClubTask + Legacy Task)
    existing_tasks = ClubTask.objects.filter(title__startswith=f"[{ns}]").count()
    tasks_to_make = max(0, counts["tasks"] - existing_tasks)
    ct_count = int(tasks_to_make * 0.8)
    leg_count = tasks_to_make - ct_count
    ct_objs = []
    for i in range(ct_count):
        wf_status = rng.choice(TaskWorkflowStatus.values)
        is_late_sample = (i % 5 == 0 and wf_status in (TaskWorkflowStatus.ASSIGNED, TaskWorkflowStatus.IN_PROGRESS))
        deadline = now - timedelta(days=rng.randint(1, 15)) if is_late_sample else now + timedelta(days=rng.randint(1, 30))
        ct_objs.append(
            ClubTask(
                title=f"[{ns}] Chuẩn bị tiết mục / hậu cần #{i + 1}",
                description="Mô tả công việc mô phỏng giai đoạn staging KMG.",
                department=depts[i % len(depts)],
                event=stg_events[i % len(stg_events)] if stg_events and i % 3 != 0 else None,
                priority=rng.choice(TaskPriority.values),
                workflow_status=wf_status,
                progress_percent=100 if wf_status == TaskWorkflowStatus.APPROVED else rng.choice([0, 25, 50, 75]),
                deadline=deadline,
                reassignment_needed=(i % 25 == 0),
                created_by=all_actors[0],
            )
        )
    if ct_objs:
        ClubTask.objects.bulk_create(ct_objs, batch_size=500)
        created_ct = list(ClubTask.objects.filter(title__startswith=f"[{ns}]").order_by("-id")[:len(ct_objs)])
        assignees = [
            ClubTaskAssignee(task=t, user=all_actors[idx % len(all_actors)], assigned_by=all_actors[0])
            for idx, t in enumerate(created_ct)
        ]
        ClubTaskAssignee.objects.bulk_create(assignees, batch_size=500)

    leg_objs = [
        LegacyTask(
            event=stg_events[i % len(stg_events)] if stg_events else None,
            department=legacy_depts[i % len(legacy_depts)],
            title=f"[{ns}] Tác vụ cũ #{i + 1}",
            assignee=all_actors[i % len(all_actors)],
            deadline=now + timedelta(days=rng.randint(-5, 25)),
            status=rng.choice(LegacyTaskStatus.values),
            created_by=all_actors[0],
        )
        for i in range(leg_count)
    ]
    if leg_objs:
        LegacyTask.objects.bulk_create(leg_objs, batch_size=500)

    # 7. Điểm danh sự kiện CLB (EventAttendance)
    existing_att = EventAttendance.objects.filter(club_event__in=stg_profiles).count()
    att_to_make = max(0, counts["attendances"] - existing_att)
    existing_att_pairs = set(
        EventAttendance.objects.filter(club_event__in=stg_profiles).values_list("club_event_id", "user_id")
    )
    att_objs = []
    if stg_profiles:
        for prof in stg_profiles:
            for u in all_actors:
                if len(att_objs) >= att_to_make:
                    break
                if (prof.id, u.id) in existing_att_pairs:
                    continue
                existing_att_pairs.add((prof.id, u.id))
                rsvp = rng.choices(
                    [RsvpStatus.CONFIRMED_ATTENDING, RsvpStatus.DECLINED_EXEMPTED, RsvpStatus.PENDING_RESPONSE],
                    weights=[70, 15, 15],
                )[0]
                chk = (
                    CheckinStatus.PRESENT
                    if rsvp == RsvpStatus.CONFIRMED_ATTENDING and rng.random() < 0.78
                    else (CheckinStatus.NO_SHOW if rsvp == RsvpStatus.CONFIRMED_ATTENDING else CheckinStatus.NOT_YET)
                )
                att_objs.append(
                    EventAttendance(
                        club_event=prof,
                        user=u,
                        rsvp_status=rsvp,
                        decline_reason="Bận lịch thi" if rsvp == RsvpStatus.DECLINED_EXEMPTED else "",
                        checkin_status=chk,
                        checked_in_by=all_actors[0] if chk == CheckinStatus.PRESENT else None,
                        checked_in_at=now - timedelta(days=1) if chk == CheckinStatus.PRESENT else None,
                    )
                )
            if len(att_objs) >= att_to_make:
                break
    if att_objs:
        EventAttendance.objects.bulk_create(att_objs, batch_size=1000)

    # 8. Giao dịch tài chính (FinancialTransaction — tuân thủ Maker != Checker & immutability)
    inc_cat, _ = FundCategory.objects.get_or_create(
        code="STG_INCOME", defaults={"name": "Thu sự kiện Staging", "tx_type": FundCategoryType.INCOME}
    )
    exp_cat, _ = FundCategory.objects.get_or_create(
        code="STG_EXPENSE", defaults={"name": "Chi tổ chức Staging", "tx_type": FundCategoryType.EXPENSE}
    )
    adj_cat, _ = FundCategory.objects.get_or_create(
        code="STG_ADJUST", defaults={"name": "Điều chỉnh Staging", "tx_type": FundCategoryType.ADJUSTMENT}
    )
    existing_tx = FinancialTransaction.objects.filter(tx_code__startswith=f"STG{seed % 100:02d}-").count()
    tx_to_make = max(0, counts["finance_txs"] - existing_tx)
    maker = all_actors[0]
    checker = all_actors[1] if len(all_actors) > 1 else all_actors[0]
    confirmed_ids: list[FinancialTransaction] = []
    for i in range(tx_to_make):
        tx_code = f"STG{seed % 100:02d}-{i + 1:05d}"
        if FinancialTransaction.objects.filter(tx_code=tx_code).exists():
            continue
        is_adj = (i % 15 == 14 and bool(confirmed_ids))
        if is_adj:
            base_tx = confirmed_ids[-1]
            FinancialTransaction.objects.create(
                tx_code=tx_code,
                tx_type=TransactionType.ADJUSTMENT,
                status=TransactionStatus.CONFIRMED,
                category=adj_cat,
                department=base_tx.department,
                title=f"Điều chỉnh bù trừ cho {base_tx.tx_code}",
                amount=50000,
                adjustment_direction=AdjustmentDirection.DEBIT,
                adjusted_from=base_tx,
                transaction_date=now.date(),
                created_by=maker,
                approved_by=checker if checker.id != maker.id else None,
                approved_at=now if checker.id != maker.id else None,
            )
            continue
        tx_type = TransactionType.INCOME if i % 3 == 0 else TransactionType.EXPENSE
        status = rng.choices(
            [TransactionStatus.CONFIRMED, TransactionStatus.PENDING_APPROVAL, TransactionStatus.REJECTED],
            weights=[70, 20, 10],
        )[0]
        if checker.id == maker.id and status == TransactionStatus.CONFIRMED:
            status = TransactionStatus.PENDING_APPROVAL
        obj = FinancialTransaction.objects.create(
            tx_code=tx_code,
            tx_type=tx_type,
            status=status,
            category=inc_cat if tx_type == TransactionType.INCOME else exp_cat,
            department=depts[i % len(depts)],
            club_event=stg_profiles[i % len(stg_profiles)] if stg_profiles else None,
            title=f"Giao dịch quỹ mô phỏng #{i + 1}",
            amount=rng.randint(10, 450) * 10000,
            transaction_date=(now - timedelta(days=rng.randint(0, 120))).date(),
            created_by=maker,
            approved_by=checker if status == TransactionStatus.CONFIRMED else None,
            approved_at=now if status == TransactionStatus.CONFIRMED else None,
            rejection_reason="Thiếu hóa đơn hợp lệ" if status == TransactionStatus.REJECTED else "",
        )
        if status == TransactionStatus.CONFIRMED:
            confirmed_ids.append(obj)

    # 9. Tài liệu mật (ConfidentialDocument)
    doc_cat, _ = DocumentCategory.objects.get_or_create(
        department=depts[0], code="STG_DOC", defaults={"name": "Tài liệu Staging"}
    )
    existing_docs = ConfidentialDocument.objects.filter(code__startswith=f"DOC-{seed % 100:02d}-").count()
    docs_to_make = max(0, counts["documents"] - existing_docs)
    doc_objs = [
        ConfidentialDocument(
            code=f"DOC-{seed % 100:02d}-{i + 1:04d}",
            title=f"[{ns}] Hợp âm & Kịch bản Chương trình #{i + 1}",
            description="Tài liệu lưu kho kiểm thử phân quyền.",
            department=depts[i % len(depts)],
            category=doc_cat,
            classification=rng.choice(DocumentClassification.values),
            owner=all_actors[i % len(all_actors)],
        )
        for i in range(docs_to_make)
    ]
    if doc_objs:
        ConfidentialDocument.objects.bulk_create(doc_objs, batch_size=500)

    # 10. Bài đăng & Bình luận mạng xã hội nội bộ (SocialPost & SocialComment)
    existing_posts = SocialPost.objects.filter(content__startswith=f"[{ns}]").count()
    posts_to_make = max(0, counts["posts"] - existing_posts)
    post_objs = [
        SocialPost(
            author=all_actors[i % len(all_actors)],
            department=depts[i % len(depts)],
            visibility=rng.choice(SocialPostVisibility.values),
            content=f"[{ns}] Chia sẻ buổi tập Guitar & Acoustic #{i + 1} {rng.choice(_EMOJI_SAMPLES)} — Âm nhạc gắn kết KMG!",
        )
        for i in range(posts_to_make)
    ]
    if post_objs:
        SocialPost.objects.bulk_create(post_objs, batch_size=500)

    stg_posts = list(SocialPost.objects.filter(content__startswith=f"[{ns}]").order_by("id"))
    existing_comments = SocialComment.objects.filter(post__in=stg_posts).count() if stg_posts else 0
    comments_to_make = max(0, counts["comments"] - existing_comments)
    if stg_posts and comments_to_make > 0:
        comment_objs = [
            SocialComment(
                post=stg_posts[i % len(stg_posts)],
                author=all_actors[i % len(all_actors)],
                content=f"Bình luận staging #{i + 1}: Tiết mục quá cháy! {rng.choice(_EMOJI_SAMPLES)}",
            )
            for i in range(comments_to_make)
        ]
        SocialComment.objects.bulk_create(comment_objs, batch_size=1000)

    # 11. Tin nhắn mã hóa AES-256-GCM (20,000 bản ghi quy mô full)
    conv, _ = Conversation.objects.get_or_create(
        channel_scope_key=f"STAGING:{seed}:CLUB",
        defaults={
            "conv_type": ConversationType.CLUB_WIDE,
            "title": f"[{ns}] Kênh Staging Toàn CLB",
            "encrypted_dek": generate_wrapped_dek(),
            "created_by": all_actors[0],
        },
    )
    existing_cmem = set(ConversationMember.objects.filter(conversation=conv).values_list("user_id", flat=True))
    new_cmems = [
        ConversationMember(conversation=conv, user=u, member_role=ConversationMemberRole.OWNER if idx == 0 else ConversationMemberRole.MEMBER)
        for idx, u in enumerate(all_actors[:50])
        if u.id not in existing_cmem
    ]
    if new_cmems:
        ConversationMember.objects.bulk_create(new_cmems, batch_size=200)

    existing_msgs = ChatMessage.objects.filter(conversation=conv).count()
    msgs_to_make = max(0, counts["messages"] - existing_msgs)
    if msgs_to_make > 0:
        dek = unwrap_dek(conv.encrypted_dek)
        # Dùng 1 vòng lặp sạch: vẫn tạo AES-256-GCM ciphertext thực với nonce 12B độc lập mỗi tin nhắn
        sender_pool = all_actors[:20]
        msg_batch: list[ChatMessage] = []
        for i in range(msgs_to_make):
            sender = sender_pool[i % len(sender_pool)]
            iv, ct = encrypt_message_text(
                dek=dek,
                plaintext=f"Tin nhắn luyện tập #{i + 1} KMG {rng.choice(_EMOJI_SAMPLES)}",
                conversation_id=conv.id,
                sender_id=sender.id,
            )
            msg_batch.append(ChatMessage(conversation=conv, sender=sender, ciphertext=ct, iv_nonce=iv))
            if len(msg_batch) >= 2000:
                ChatMessage.objects.bulk_create(msg_batch, batch_size=1000)
                msg_batch.clear()
        if msg_batch:
            ChatMessage.objects.bulk_create(msg_batch, batch_size=1000)

    # 12. Thông báo (10,000 bản ghi)
    existing_notifs = Notification.objects.filter(title__startswith=f"[{ns}]").count()
    notifs_to_make = max(0, counts["notifications"] - existing_notifs)
    if notifs_to_make > 0:
        notif_batch: list[Notification] = []
        user_cycle = member_users + guest_users
        for i in range(notifs_to_make):
            notif_batch.append(
                Notification(
                    user=user_cycle[i % len(user_cycle)],
                    kind=NotificationKind.ANNOUNCEMENT,
                    title=f"[{ns}] Thông báo lịch tập #{i + 1}",
                    message="Thông báo mô phỏng staging KMG.",
                    is_read=(i % 3 != 0),
                )
            )
            if len(notif_batch) >= 2000:
                Notification.objects.bulk_create(notif_batch, batch_size=1000)
                notif_batch.clear()
        if notif_batch:
            Notification.objects.bulk_create(notif_batch, batch_size=1000)

    # 13. Nhật ký (50,000 bản ghi: AuditLog + AIInteractionLog — không PII thật)
    half_logs = counts["logs"] // 2
    other_logs = counts["logs"] - half_logs
    existing_audits = AuditLog.objects.filter(target__startswith=f"[{ns}]").count()
    audits_to_make = max(0, half_logs - existing_audits)
    if audits_to_make > 0:
        audit_batch: list[AuditLog] = []
        for i in range(audits_to_make):
            audit_batch.append(
                AuditLog(
                    user=all_actors[i % len(all_actors)],
                    action="STAGING_CHECK",
                    target=f"[{ns}]:item:{i}",
                    note="Nhật ký mô phỏng staging",
                    ip_address="192.0.2.10",
                )
            )
            if len(audit_batch) >= 2500:
                AuditLog.objects.bulk_create(audit_batch, batch_size=1000)
                audit_batch.clear()
        if audit_batch:
            AuditLog.objects.bulk_create(audit_batch, batch_size=1000)

    ai_pv = f"s{seed % 10000:04d}-v1"
    existing_ai_logs = AIInteractionLog.objects.filter(prompt_version=ai_pv).count()
    ai_to_make = max(0, other_logs - existing_ai_logs)
    if ai_to_make > 0:
        ai_batch: list[AIInteractionLog] = []
        for i in range(ai_to_make):
            ai_batch.append(
                AIInteractionLog(
                    question=f"Lịch tập Guitar KMG tuần này #{i + 1}?",
                    intent="events_list",
                    source="rules",
                    answer_preview="Câu trả lời mô phỏng không chứa dữ liệu cá nhân.",
                    latency_ms=rng.randint(8, 120),
                    model_name="mock",
                    prompt_version=ai_pv,
                )
            )
            if len(ai_batch) >= 2500:
                AIInteractionLog.objects.bulk_create(ai_batch, batch_size=1000)
                ai_batch.clear()
        if ai_batch:
            AIInteractionLog.objects.bulk_create(ai_batch, batch_size=1000)

    return {
        "members": len(member_users),
        "guests": len(guest_users),
        "applications": MembershipApplication.objects.filter(motivation__startswith=f"[{ns}]").count() + LegacyApplication.objects.filter(round=rnd).count(),
        "events": len(stg_events),
        "tickets": Ticket.objects.filter(booking_ref__startswith=f"S{seed % 100:02d}").count(),
        "tasks": ClubTask.objects.filter(title__startswith=f"[{ns}]").count() + LegacyTask.objects.filter(title__startswith=f"[{ns}]").count(),
        "attendances": EventAttendance.objects.filter(club_event__in=stg_profiles).count(),
        "finance_txs": FinancialTransaction.objects.filter(tx_code__startswith=f"STG{seed % 100:02d}-").count(),
        "documents": ConfidentialDocument.objects.filter(code__startswith=f"DOC-{seed % 100:02d}-").count(),
        "posts": len(stg_posts),
        "comments": SocialComment.objects.filter(post__in=stg_posts).count() if stg_posts else 0,
        "messages": ChatMessage.objects.filter(conversation=conv).count(),
        "notifications": Notification.objects.filter(title__startswith=f"[{ns}]").count(),
        "logs": AuditLog.objects.filter(target__startswith=f"[{ns}]").count() + AIInteractionLog.objects.filter(prompt_version=ai_pv).count(),
    }
