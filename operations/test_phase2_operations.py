"""
Bộ kiểm thử Phase 2 — Core Management (Công việc, Sự kiện Kép & RSVP, Kỷ luật, Khiếu nại, Nhắc việc, PWA).

Bao phủ các tiêu chí nghiệm thu:
- WF13–WF15: Vòng đời nhiệm vụ, nộp trễ hạn vẫn được (CM-01), trạng thái cá nhân nhóm (CM-02).
- PA-04 / INV-03: Người được giao việc không được tự nghiệm thu (kể cả Trưởng ban).
- TaskReview bất biến (chặn sửa / xoá).
- SEC-01: Tệp bài nộp lưu Private Vault, tải qua view có kiểm tra quyền.
- BE-02: Gắn cờ phân công lại khi thành viên bị tạm khoá / chuyển Ban.
- Cross-Dept READ_ONLY: thành viên Ban khác không xem được nhiệm vụ nội bộ.
- WF09–WF12, INT-01: Sự kiện CLB chỉ BCN duyệt; chỉ PUBLIC_SHOW mới mở PUBLIC.
- CF-02 / BE-03: RSVP miễn trừ thành viên SUSPENDED; khoá sổ RSVP -> AUTO_COMMITTED.
- R04: > 3 vi phạm chỉ tạo DisciplineCase FLAGGED, không bao giờ tự khoá.
- WF24: Thành viên SUSPENDED gửi khiếu nại qua API; người ra quyết định ban đầu không được phán quyết;
  OVERTURNED khôi phục ACTIVE.
- DB-06: Nhắc việc idempotent; PWA manifest & service worker; PA-07 che PII cho Cố vấn; INV-04.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, AuditLog, Role, User, UserProfile
from events.models import EventStatus, EventVisibility
from notifications.models import (
    NotificationKind,
    ReminderStage,
    ReminderTargetType,
    ScheduledReminder,
)
from notifications.services import dispatch_idempotent_reminder
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    PositionCode,
    ScopeType,
)
from organization.permissions import PERMISSIONS_CATALOG, PermissionEngine
from organization.services import (
    GovernanceError,
    approve_club_member,
    bootstrap_organization_catalog,
    server_admin_assign_leadership,
    suspend_club_member,
    transfer_member_department,
)

from .models import (
    Appeal,
    AppealStatus,
    AppealTargetType,
    CheckinStatus,
    ClubEventApprovalStatus,
    ClubEventScope,
    ClubTask,
    DisciplineCase,
    DisciplineStatus,
    EventAttendance,
    RsvpStatus,
    TaskReview,
    TaskReviewDecision,
    TaskWorkflowStatus,
)
from .services import (
    adjudicate_appeal,
    can_view_club_task,
    create_and_assign_task,
    create_club_event,
    finalize_task_review,
    freeze_event_rsvp,
    publish_club_event,
    record_member_event_checkin,
    redact_pii_for_advisor,
    respond_event_rsvp,
    review_club_event,
    run_proactive_operations_cycle,
    submit_appeal,
    submit_club_event_for_approval,
    submit_task_deliverable,
    update_task_progress,
)


def _fresh(user: User) -> User:
    """Đọc lại user để xoá cache `club_membership` sau các thao tác đổi trạng thái."""
    return User.objects.get(pk=user.pk)


class Phase2OperationsBase(TestCase):
    def setUp(self):
        catalog = bootstrap_organization_catalog()
        self.dept_cm = catalog["departments"]["SPECIALTY"]
        self.dept_tt = catalog["departments"]["MEDIA_EVENT"]
        self.positions = catalog["positions"]
        self._seq = 500

        self.server_admin = self._make_user("p2_admin", "Admin Server", role=Role.ADMIN)
        self.chairman = self._make_user("p2_chairman", "Chủ nhiệm")
        ClubMembership.objects.create(
            user=self.chairman, member_code="KMG-2026-0901", status=ClubMembershipStatus.ACTIVE
        )
        DepartmentMembership.objects.create(
            user=self.chairman, department=self.dept_cm, status=DeptMembershipStatus.ACTIVE
        )
        Appointment.objects.create(
            user=self.chairman,
            position=self.positions[PositionCode.CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )

        self.head = self._make_user("p2_head", "Trưởng ban Chuyên môn")
        server_admin_assign_leadership(
            actor=self.server_admin,
            target_user=self.head,
            position_code=PositionCode.DEPT_HEAD,
            department=self.dept_cm,
        )
        self.member_a = self._make_member("p2_a", "Thành viên A", [self.dept_cm])
        self.member_b = self._make_member("p2_b", "Thành viên B", [self.dept_cm])
        self.member_c = self._make_member("p2_c", "Thành viên C (Truyền thông)", [self.dept_tt])

        self.vc_hr = self._make_user("p2_vc", "Phó CN Nhân sự")
        server_admin_assign_leadership(
            actor=self.server_admin,
            target_user=self.vc_hr,
            position_code=PositionCode.VICE_CHAIRMAN,
            portfolios=[GrantBundleCode.PORTFOLIO_HR],
        )
        self.advisor = self._make_user("p2_advisor", "Cố vấn")
        server_admin_assign_leadership(
            actor=self.server_admin,
            target_user=self.advisor,
            position_code=PositionCode.ADVISOR,
        )
        self.head = _fresh(self.head)
        self.chairman = _fresh(self.chairman)

    # ---------------------------------------------------------------- helpers
    def _make_user(self, username, full_name, role=Role.MEMBER) -> User:
        self._seq += 1
        user = User.objects.create_user(
            username=username,
            password="Password@123",
            full_name=full_name,
            display_name=full_name,
            phone=f"0907{self._seq:06d}",
            email=f"{username}@kmg.vn",
            role=role,
            account_status=AccountStatus.ACTIVE,
        )
        UserProfile.objects.create(user=user)
        return user

    def _make_member(self, username, full_name, depts) -> User:
        u = self._make_user(username, full_name)
        approve_club_member(actor=self.chairman, target_user=u, departments=depts)
        return _fresh(u)

    def _task(self, assignees, actor=None, event=None, title="Phối khí tiết mục mở màn"):
        return create_and_assign_task(
            actor=actor or self.head,
            department=self.dept_cm,
            title=title,
            deadline=timezone.now() + timedelta(days=3),
            assignees=assignees,
            event=event,
        )

    def _published_club_event(self, name="Sinh hoạt toàn CLB", scope=ClubEventScope.CLUB_WIDE):
        profile = create_club_event(
            actor=self.head,
            lead_department=self.dept_cm,
            name=name,
            location="Hội trường A",
            starts_at=timezone.now() + timedelta(days=7),
            rsvp_freeze_at=timezone.now() + timedelta(days=5),
            event_scope=scope,
        )
        submit_club_event_for_approval(self.head, profile)
        review_club_event(actor=self.chairman, club_event=profile, approved=True)
        return publish_club_event(actor=self.chairman, club_event=profile)


# ===========================================================================
# 1. CÔNG VIỆC
# ===========================================================================
class TaskWorkflowTests(Phase2OperationsBase):
    def test_full_task_lifecycle_and_immutable_review(self):
        task = self._task([self.member_a])
        self.assertEqual(task.workflow_status, TaskWorkflowStatus.ASSIGNED)

        update_task_progress(actor=self.member_a, task=task, new_status=TaskWorkflowStatus.ACCEPTED)
        update_task_progress(
            actor=self.member_a, task=task, new_status=TaskWorkflowStatus.IN_PROGRESS, progress_percent=60
        )
        submit_task_deliverable(actor=self.member_a, task=task, submission_note="Đã hoàn thành bản phối")
        task.refresh_from_db()
        self.assertEqual(task.workflow_status, TaskWorkflowStatus.SUBMITTED)

        review = finalize_task_review(
            actor=self.head,
            task=task,
            decision=TaskReviewDecision.APPROVED,
            quality_score=4,
            feedback="Bản phối tốt, cân bằng âm sắc.",
        )
        task.refresh_from_db()
        self.assertEqual(task.workflow_status, TaskWorkflowStatus.APPROVED)
        self.assertIsNotNone(task.completed_at)

        review.feedback = "Sửa lén"
        with self.assertRaises(ValueError):
            review.save()
        with self.assertRaises(ValueError):
            review.delete()
        self.assertEqual(TaskReview.objects.get(pk=review.pk).feedback, "Bản phối tốt, cân bằng âm sắc.")

    def test_pa04_assignee_cannot_self_review_even_as_dept_head(self):
        task = self._task([self.head, self.member_a])
        submit_task_deliverable(actor=self.member_a, task=task, submission_note="Nộp bài")
        with self.assertRaises(PermissionDenied):
            finalize_task_review(
                actor=self.head, task=task, decision=TaskReviewDecision.APPROVED, feedback="Tự duyệt"
            )
        # Chủ nhiệm (không tham gia thực hiện) nghiệm thu hợp lệ
        finalize_task_review(
            actor=self.chairman, task=task, decision=TaskReviewDecision.APPROVED, feedback="Đạt"
        )
        self.assertEqual(ClubTask.objects.get(pk=task.pk).workflow_status, TaskWorkflowStatus.APPROVED)

    def test_member_cannot_assign_and_cross_dept_member_cannot_view(self):
        with self.assertRaises(PermissionDenied):
            self._task([self.member_b], actor=self.member_a)
        task = self._task([self.member_a])
        self.assertTrue(can_view_club_task(self.member_a, task))
        self.assertTrue(can_view_club_task(self.head, task))
        self.assertFalse(can_view_club_task(self.member_b, task))  # cùng Ban, không được giao
        self.assertFalse(can_view_club_task(self.member_c, task))  # Ban khác (READ_ONLY)
        self.client.force_login(self.member_c)
        resp = self.client.get(reverse("operations:task_detail", args=[task.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_late_submission_allowed_and_flagged(self):
        task = self._task([self.member_a])
        ClubTask.objects.filter(pk=task.pk).update(deadline=timezone.now() - timedelta(hours=2))
        task.refresh_from_db()
        self.assertTrue(task.is_overdue)
        sub = submit_task_deliverable(actor=self.member_a, task=task, submission_note="Nộp muộn")
        self.assertTrue(sub.is_late)

    def test_group_task_all_assignees_mode_requires_everyone(self):
        task = create_and_assign_task(
            actor=self.head,
            department=self.dept_cm,
            title="Tập hoà âm",
            deadline=timezone.now() + timedelta(days=2),
            assignees=[self.member_a, self.member_b],
            submission_mode="ALL_ASSIGNEES",
        )
        submit_task_deliverable(actor=self.member_a, task=task, submission_note="Phần của A")
        task.refresh_from_db()
        self.assertEqual(task.workflow_status, TaskWorkflowStatus.IN_PROGRESS)
        submit_task_deliverable(actor=self.member_b, task=task, submission_note="Phần của B")
        task.refresh_from_db()
        self.assertEqual(task.workflow_status, TaskWorkflowStatus.SUBMITTED)

    def test_evidence_url_rejects_javascript_scheme(self):
        task = self._task([self.member_a])
        with self.assertRaises(GovernanceError):
            submit_task_deliverable(
                actor=self.member_a,
                task=task,
                submission_note="x",
                evidence_url="javascript:alert(1)",
            )

    def test_sec01_private_vault_download_requires_permission(self):
        vault = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, vault, ignore_errors=True)
        with override_settings(PRIVATE_VAULT_ROOT=vault):
            task = self._task([self.member_a])
            sub = submit_task_deliverable(
                actor=self.member_a,
                task=task,
                submission_note="Có tệp",
                attachment=SimpleUploadedFile("ban-phoi.txt", b"noi dung mat", content_type="text/plain"),
            )
            url = reverse("operations:download_submission", args=[sub.pk])
            self.assertFalse(sub.attachment.url.startswith("/media/"))

            for outsider in (self.member_b, self.member_c):
                self.client.force_login(outsider)
                self.assertEqual(self.client.get(url).status_code, 403)

            for allowed in (self.member_a, self.head):
                self.client.force_login(allowed)
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(b"".join(resp.streaming_content), b"noi dung mat")

    def test_be02_suspension_and_transfer_flag_reassignment(self):
        task_a = self._task([self.member_a], title="Việc của A")
        task_b = self._task([self.member_b], title="Việc của B")

        suspend_club_member(actor=self.chairman, target_user=self.member_a, reason="Vắng nhiều buổi")
        task_a.refresh_from_db()
        self.assertTrue(task_a.reassignment_needed)

        transfer_member_department(
            actor=self.chairman,
            target_user=self.member_b,
            from_department=self.dept_cm,
            to_department=self.dept_tt,
        )
        task_b.refresh_from_db()
        self.assertTrue(task_b.reassignment_needed)
        self.assertFalse(task_b.assignees.filter(user=self.member_b, is_active=True).exists())


# ===========================================================================
# 2. SỰ KIỆN KÉP & RSVP
# ===========================================================================
class ClubEventAndRsvpTests(Phase2OperationsBase):
    def test_club_wide_event_requires_bcn_approval_and_stays_internal(self):
        profile = create_club_event(
            actor=self.head,
            lead_department=self.dept_cm,
            name="Đêm nhạc nội bộ",
            location="Phòng 101",
            starts_at=timezone.now() + timedelta(days=7),
            event_scope=ClubEventScope.CLUB_WIDE,
        )
        self.assertEqual(profile.event.visibility, EventVisibility.INTERNAL)
        self.assertEqual(profile.event.status, EventStatus.DRAFT)
        submit_club_event_for_approval(self.head, profile)

        # Trưởng ban chỉ được đề xuất, không được duyệt sự kiện cấp CLB
        with self.assertRaises(PermissionDenied):
            review_club_event(actor=self.head, club_event=profile, approved=True)

        review_club_event(actor=self.chairman, club_event=profile, approved=True)
        publish_club_event(actor=self.chairman, club_event=profile)
        profile.refresh_from_db()
        profile.event.refresh_from_db()
        self.assertEqual(profile.approval_status, ClubEventApprovalStatus.PUBLISHED)
        self.assertEqual(profile.event.visibility, EventVisibility.INTERNAL)
        self.assertIsNotNone(profile.policy_version_id)

    def test_only_public_show_becomes_public(self):
        profile = self._published_club_event(name="Show Mùa Thu", scope=ClubEventScope.PUBLIC_SHOW)
        profile.event.refresh_from_db()
        self.assertEqual(profile.event.visibility, EventVisibility.PUBLIC)
        self.assertEqual(profile.event.status, EventStatus.OPEN)

    def test_dept_internal_event_approved_by_dept_head(self):
        profile = create_club_event(
            actor=self.head,
            lead_department=self.dept_cm,
            name="Buổi tập Guitar",
            location="Phòng tập",
            starts_at=timezone.now() + timedelta(days=2),
            event_scope=ClubEventScope.DEPT_INTERNAL,
        )
        submit_club_event_for_approval(self.head, profile)
        review_club_event(actor=self.head, club_event=profile, approved=True, auto_publish=True)
        profile.refresh_from_db()
        self.assertEqual(profile.approval_status, ClubEventApprovalStatus.PUBLISHED)
        self.assertTrue(EventAttendance.objects.filter(club_event=profile, user=self.member_a).exists())
        self.assertFalse(EventAttendance.objects.filter(club_event=profile, user=self.member_c).exists())

    def test_cf02_suspended_member_exempt_and_freeze_auto_commits(self):
        suspend_club_member(actor=self.chairman, target_user=self.member_b, reason="Tạm nghỉ kỷ luật")
        profile = self._published_club_event()

        att_b = EventAttendance.objects.get(club_event=profile, user=self.member_b)
        self.assertEqual(att_b.rsvp_status, RsvpStatus.EXEMPT_SUSPENDED)

        with self.assertRaises(GovernanceError):
            respond_event_rsvp(actor=self.member_a, club_event=profile, attending=False, decline_reason="")
        respond_event_rsvp(
            actor=self.member_c, club_event=profile, attending=False, decline_reason="Trùng lịch thi"
        )

        freeze_event_rsvp(profile, actor=self.chairman)
        self.assertEqual(
            EventAttendance.objects.get(club_event=profile, user=self.member_a).rsvp_status,
            RsvpStatus.AUTO_COMMITTED,
        )
        self.assertEqual(
            EventAttendance.objects.get(club_event=profile, user=self.member_b).rsvp_status,
            RsvpStatus.EXEMPT_SUSPENDED,
        )
        self.assertEqual(
            EventAttendance.objects.get(club_event=profile, user=self.member_c).rsvp_status,
            RsvpStatus.DECLINED_PENDING,
        )

        profile.refresh_from_db()
        with self.assertRaises(GovernanceError) as ctx:
            respond_event_rsvp(actor=self.member_a, club_event=profile, attending=True)
        self.assertEqual(ctx.exception.code, "RSVP_FROZEN")

        # Điểm danh không bao giờ ghi NO_SHOW cho người đang tạm khoá
        record_member_event_checkin(actor=self.chairman, attendance=att_b, checkin_status=CheckinStatus.NO_SHOW)
        att_b.refresh_from_db()
        self.assertEqual(att_b.checkin_status, CheckinStatus.NOT_YET)


# ===========================================================================
# 3. KỶ LUẬT & KHIẾU NẠI
# ===========================================================================
class DisciplineAndAppealTests(Phase2OperationsBase):
    def test_r04_more_than_three_violations_flags_without_auto_lock(self):
        for i in range(4):
            profile = self._published_club_event(name=f"Sinh hoạt CLB #{i + 1}")
            att = EventAttendance.objects.get(club_event=profile, user=self.member_a)
            record_member_event_checkin(actor=self.chairman, attendance=att, checkin_status=CheckinStatus.NO_SHOW)
            expected = 1 if i == 3 else 0
            self.assertEqual(
                DisciplineCase.objects.filter(target_user=self.member_a).count(),
                expected,
                msg=f"Sau {i + 1} lần vi phạm",
            )

        case = DisciplineCase.objects.get(target_user=self.member_a)
        self.assertEqual(case.status, DisciplineStatus.FLAGGED)
        self.assertEqual(case.violation_count, 4)
        self.assertEqual(len(case.evidence_snapshot["events"]), 4)
        self.assertIsNotNone(case.policy_version_id)
        refreshed = _fresh(self.member_a)
        self.assertEqual(refreshed.club_status, ClubMembershipStatus.ACTIVE)
        self.assertFalse(refreshed.is_locked)

    def test_exempted_absences_never_count(self):
        for i in range(4):
            profile = self._published_club_event(name=f"Sự kiện miễn trừ #{i + 1}")
            att = respond_event_rsvp(
                actor=self.member_a, club_event=profile, attending=False, decline_reason="Đi thực tập"
            )
            from .services import review_rsvp_exemption

            review_rsvp_exemption(actor=self.chairman, attendance=att, exempted=True)
        self.assertFalse(DisciplineCase.objects.filter(target_user=self.member_a).exists())

    def test_suspended_member_appeal_via_api_and_independent_adjudication(self):
        suspend_club_member(actor=self.chairman, target_user=self.member_a, reason="Vi phạm nội quy")

        self.client.force_login(self.member_a)
        # Workspace bị chặn, nhưng API khiếu nại vẫn mở
        self.assertEqual(self.client.get(reverse("operations:discipline_center")).status_code, 302)
        resp = self.client.post(
            "/api/v1/appeals/",
            data=json.dumps(
                {"target_type": AppealTargetType.MEMBERSHIP_SUSPENSION, "reason": "Tôi có giấy xác nhận ốm."}
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        appeal = Appeal.objects.get(pk=resp.json()["data"]["id"])
        self.assertEqual(appeal.original_actor_id, self.chairman.id)

        # Người ra quyết định ban đầu không được tự phán quyết
        with self.assertRaises(PermissionDenied):
            adjudicate_appeal(
                actor=self.chairman, appeal=appeal, decision_status=AppealStatus.UPHELD, decision_note="Giữ nguyên"
            )
        # Phó CN Nhân sự độc lập chấp nhận khiếu nại -> khôi phục ACTIVE
        adjudicate_appeal(
            actor=_fresh(self.vc_hr),
            appeal=appeal,
            decision_status=AppealStatus.OVERTURNED,
            decision_note="Minh chứng hợp lệ",
        )
        self.assertEqual(_fresh(self.member_a).club_status, ClubMembershipStatus.ACTIVE)

    def test_member_can_appeal_task_review_but_not_others(self):
        task = self._task([self.member_a])
        submit_task_deliverable(actor=self.member_a, task=task, submission_note="Nộp")
        review = finalize_task_review(
            actor=self.head, task=task, decision=TaskReviewDecision.REJECTED, feedback="Chưa đạt"
        )
        with self.assertRaises(PermissionDenied):
            submit_appeal(
                appellant=self.member_b,
                target_type=AppealTargetType.TASK_REVIEW,
                task_review=review,
                reason="Không phải việc của tôi",
            )
        appeal = submit_appeal(
            appellant=self.member_a,
            target_type=AppealTargetType.TASK_REVIEW,
            task_review=review,
            reason="Tôi đã nộp đủ yêu cầu",
        )
        self.assertEqual(appeal.original_actor_id, self.head.id)


# ===========================================================================
# 4. NHẮC VIỆC, PWA, CỐ VẤN & GIAO DIỆN
# ===========================================================================
class RemindersPwaAndDashboardTests(Phase2OperationsBase):
    def test_idempotent_reminder_and_operations_cycle(self):
        kwargs = dict(
            target_type=ReminderTargetType.CLUB_TASK,
            target_id=999,
            recipient=self.member_a,
            stage=ReminderStage.T_48H,
            kind=NotificationKind.TASK_DEADLINE,
            title="Nhắc",
            message="Sắp đến hạn",
        )
        self.assertTrue(dispatch_idempotent_reminder(**kwargs))
        self.assertFalse(dispatch_idempotent_reminder(**kwargs))

        task = self._task([self.member_a])
        ClubTask.objects.filter(pk=task.pk).update(deadline=timezone.now() + timedelta(hours=10))
        first = run_proactive_operations_cycle()
        second = run_proactive_operations_cycle()
        self.assertEqual(first["task_reminders_sent"], 1)
        self.assertEqual(second["task_reminders_sent"], 0)
        self.assertEqual(
            ScheduledReminder.objects.filter(
                target_type=ReminderTargetType.CLUB_TASK, target_id=task.id, stage=ReminderStage.T_12H
            ).count(),
            1,
        )

    def test_operations_cycle_freezes_due_rsvp(self):
        profile = self._published_club_event()
        type(profile).objects.filter(pk=profile.pk).update(rsvp_freeze_at=timezone.now() - timedelta(minutes=1))
        stats = run_proactive_operations_cycle()
        self.assertEqual(stats["frozen_events"], 1)
        self.assertEqual(
            EventAttendance.objects.get(club_event=profile, user=self.member_a).rsvp_status,
            RsvpStatus.AUTO_COMMITTED,
        )

    def test_pwa_manifest_and_service_worker(self):
        resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content)["start_url"], "/workspace/")
        sw = self.client.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertIn("javascript", sw["Content-Type"])
        self.assertEqual(sw["Service-Worker-Allowed"], "/")

    def test_notification_preferences_web_and_api(self):
        self.client.force_login(self.member_a)
        self.client.post(reverse("notifications:update_preferences"), {"email_important": "1"})
        resp = self.client.get("/api/v1/notifications/preferences/")
        data = resp.json()["data"]
        self.assertTrue(data["email_important"])
        self.assertFalse(data["email_task_deadline"])
        resp = self.client.post(
            "/api/v1/notifications/push-subscribe/",
            data=json.dumps(
                {"endpoint": "https://push.example.com/abc", "keys": {"p256dh": "k1", "auth": "k2"}}
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_pii_redactor(self):
        text = "Liên hệ secret.person@kmg.vn hoặc 0987654321"
        masked = redact_pii_for_advisor(text)
        self.assertNotIn("secret.person@kmg.vn", masked)
        self.assertNotIn("0987654321", masked)
        self.assertIn("s***@kmg.vn", masked)

    def test_advisor_read_only_portal_redacts_pii_and_blocks_tasks(self):
        AuditLog.write(self.chairman, "Ghi chú nhân sự", "Hồ sơ", note="SĐT 0987654321, email secret.person@kmg.vn")
        self.client.force_login(self.advisor)
        resp = self.client.get(reverse("organization:advisor_overview"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "secret.person@kmg.vn")
        self.assertNotContains(resp, "0987654321")
        self.assertEqual(self.client.get(reverse("operations:task_list")).status_code, 403)

    def test_inv04_advisor_still_has_no_mutation_permissions(self):
        advisor = _fresh(self.advisor)
        for code, _name, _module, _scope, is_mut in PERMISSIONS_CATALOG:
            if is_mut:
                self.assertFalse(PermissionEngine.authorize(advisor, code), code)

    def test_workspace_pages_render(self):
        task = self._task([self.member_a])
        profile = self._published_club_event()
        self.client.force_login(self.head)
        for url in (
            reverse("organization:workspace_home"),
            reverse("operations:task_list"),
            reverse("operations:task_detail", args=[task.pk]),
            reverse("operations:event_hub"),
            reverse("operations:event_detail", args=[profile.pk]),
            reverse("operations:discipline_center"),
            reverse("notifications:list"),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.force_login(self.chairman)
        self.assertEqual(self.client.get(reverse("organization:governance_center")).status_code, 200)
        self.client.force_login(self.member_a)
        resp = self.client.get(reverse("organization:workspace_home"))
        self.assertContains(resp, task.title)

        # Department Portal: Trưởng ban & thành viên được giao thấy nhiệm vụ; thành viên Ban khác (READ_ONLY) bị ẩn chi tiết việc
        dept_url = reverse("organization:department_detail", args=[self.dept_cm.slug])
        self.assertContains(self.client.get(dept_url), task.title)
        self.client.force_login(self.head)
        self.assertContains(self.client.get(dept_url), task.title)
        self.client.force_login(self.member_c)
        cross_resp = self.client.get(dept_url)
        self.assertEqual(cross_resp.status_code, 200)
        self.assertNotContains(cross_resp, task.title)
        self.assertContains(cross_resp, "READ_ONLY")

    def test_api_task_review_self_review_returns_403(self):
        task = self._task([self.head, self.member_a])
        self.client.force_login(self.head)
        resp = self.client.post(
            f"/api/v1/tasks/{task.pk}/review/",
            data=json.dumps({"decision": "APPROVED", "feedback": "Tự duyệt"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "PERMISSION_DENIED")
