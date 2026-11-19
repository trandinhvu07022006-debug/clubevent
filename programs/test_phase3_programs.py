"""
Bộ kiểm thử Phase 3 — Department Management (`programs`):
1. Kho Tài liệu Mật & Resource-level ACL (`WF20`, `INV-01`, `PA-01`, `SEC-01`, `PA-02`):
   - Tệp lưu vật lý tại `PRIVATE_VAULT_ROOT` ngoài `/media/`, băm SHA-256, đa phiên bản.
   - Chặn tuyệt đối tệp nguy hiểm (`.html`, `.svg`, `.exe`, spoofed magic bytes, rỗng).
   - `Skill != Permission`: có `VERIFIED` Skill Guitar nhưng không có ACL -> 403 + ẩn khỏi Two-Phase Query + ghi `DENIED_ATTEMPT` bền vững; không có Skill nhưng có `USER` ACL -> 200 tải với `X-Content-Type-Options: nosniff`.
   - `HIGHLY_RESTRICTED` trần cứng Phó ban / Phó CN; Break-Glass có kiểm soát cho Chủ nhiệm.
   - `PA-02` tự động thu hồi ACL khi chuyển Ban / kết thúc nhiệm kỳ / tạm khoá.
   - `DocumentAccessLog` & `ProposalReview` bất biến.
2. Quy trình Đề xuất Hoạt động 2 cấp (`WF17`, `WF18`, `INV-03`, `DB-07`):
   - Không duyệt chéo `CLUB` từ cấp Ban; bắt buộc góp ý khi từ chối; chặn tự phê duyệt (`INV-03`);
     chuyển đổi Đề xuất đã duyệt thành `ClubEventProfile` (`DRAFT` + `INTERNAL`) hoặc `TrainingCourse`.
3. Đào tạo Chuyên môn, Lịch tập Band (`BE-04`) & Nhắc lịch Idempotent `T-48h`/`T-12h` (Chỉ thị 3.5).
4. Cổng 3 Ban Chuyên biệt, Chế độ Xem chéo Ban `READ_ONLY` & Cố vấn Hard Read-Only (`INV-04`).
"""
from __future__ import annotations

import atexit
import json
import os
import tempfile
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import AuditLog, Role, User, UserProfile
from events.models import EventVisibility
from notifications.models import (
    Notification,
    NotificationKind,
    ReminderStage,
    ReminderTargetType,
    ScheduledReminder,
)
from operations.models import ClubEventApprovalStatus
from operations.services import create_and_assign_task, run_proactive_operations_cycle
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    PositionCode,
    ScopeType,
    Skill,
    SkillProficiency,
    SkillVerificationStatus,
    UserSkill,
)
from organization.services import (
    GovernanceError,
    appoint_officer,
    bootstrap_organization_catalog,
    end_appointment,
    grant_delegated_permissions,
    suspend_club_member,
    transfer_member_department,
)

from .models import (
    AclPermissionLevel,
    AclSubjectType,
    ConfidentialDocument,
    DepartmentProposal,
    DepartmentShowcaseItem,
    DocumentACLEntry,
    DocumentAccessAction,
    DocumentAccessLog,
    DocumentClassification,
    PracticeResponseStatus,
    ProposalReview,
    ProposalReviewDecision,
    ProposalScope,
    ProposalStatus,
    ProposalType,
    ShowcaseItemType,
    TrainingEnrollmentStatus,
)
from .services import (
    break_glass_document_access,
    can_access_document,
    convert_proposal_to_course,
    convert_proposal_to_event,
    create_confidential_document,
    create_department_showcase_item,
    create_practice_session,
    create_proposal,
    create_training_course,
    enroll_in_training,
    filter_accessible_documents,
    grant_document_acl,
    review_proposal,
    update_practice_participant_status,
    update_training_enrollment_status,
    upload_document_version,
)

TEST_VAULT_TMPDIR = tempfile.TemporaryDirectory()
atexit.register(TEST_VAULT_TMPDIR.cleanup)


def _fresh(user: User) -> User:
    return User.objects.get(pk=user.pk)


@override_settings(PRIVATE_VAULT_ROOT=TEST_VAULT_TMPDIR.name)
class Phase3Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()

    def setUp(self):
        catalog = bootstrap_organization_catalog()
        self.dept_cm = catalog["departments"]["SPECIALTY"]
        self.dept_tt = catalog["departments"]["MEDIA_EVENT"]
        self.dept_kt = catalog["departments"]["TECHNICAL"]
        self.positions = catalog["positions"]
        self.skill_guitar = Skill.objects.get(code="GUITAR_ACOUSTIC")
        self.skill_vocal = Skill.objects.get(code="VOCAL_LEAD")
        self.skill_sound = Skill.objects.get(code="LIVE_SOUND")
        self._seq = 800

        self.server_admin = self._make_user("p3_admin", "Admin Server P3", role=Role.ADMIN)
        self.chairman = self._make_user("p3_chair", "Chủ nhiệm KMG P3")
        ClubMembership.objects.create(
            user=self.chairman, member_code="KMG-2026-8001", status=ClubMembershipStatus.ACTIVE
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

        self.vice_event = self._make_member("p3_pcn_ev", "Phó CN Sự kiện", self.dept_tt, "8002")
        appt_pcn_ev = Appointment.objects.create(
            user=self.vice_event,
            position=self.positions[PositionCode.VICE_CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )
        grant_delegated_permissions(
            actor=self.chairman,
            bound_appointment=appt_pcn_ev,
            bundle_code=GrantBundleCode.PORTFOLIO_EVENT,
            reason="Phụ trách Sự kiện & Truyền thông",
        )

        self.vice_fin = self._make_member("p3_pcn_fin", "Phó CN Tài chính", self.dept_tt, "8003")
        appt_pcn_fin = Appointment.objects.create(
            user=self.vice_fin,
            position=self.positions[PositionCode.VICE_CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )
        grant_delegated_permissions(
            actor=self.chairman,
            bound_appointment=appt_pcn_fin,
            bundle_code=GrantBundleCode.PORTFOLIO_FINANCE_DOC,
            reason="Phụ trách Tài liệu Tài chính",
        )

        self.head_cm = self._make_member("p3_head_cm", "Trưởng ban CM", self.dept_cm, "8004")
        Appointment.objects.create(
            user=self.head_cm,
            position=self.positions[PositionCode.DEPT_HEAD],
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept_cm,
            appointed_by=self.server_admin,
        )

        self.deputy_cm = self._make_member("p3_dep_cm", "Phó ban CM Ủy quyền", self.dept_cm, "8005")
        self.deputy_cm_appt = appoint_officer(
            actor=self.head_cm,
            target_user=self.deputy_cm,
            position=self.positions[PositionCode.DEPUTY_HEAD],
            department=self.dept_cm,
            term_label="2026-2027",
        )
        grant_delegated_permissions(
            actor=self.head_cm,
            bound_appointment=self.deputy_cm_appt,
            bundle_code=GrantBundleCode.BUNDLE_RESOURCE_PROPOSAL,
            department=self.dept_cm,
            reason="Quản lý tài liệu thường & đề xuất",
        )
        grant_delegated_permissions(
            actor=self.head_cm,
            bound_appointment=self.deputy_cm_appt,
            bundle_code=GrantBundleCode.BUNDLE_TRAINING_CONTENT,
            department=self.dept_cm,
            reason="Điều phối đào tạo chuyên môn",
        )

        self.member_guitar = self._make_member(
            "p3_mem_guitar", "TV Có Skill Guitar", self.dept_cm, "8006"
        )
        UserSkill.objects.create(
            user=self.member_guitar,
            skill=self.skill_guitar,
            proficiency=SkillProficiency.ADVANCED,
            verification_status=SkillVerificationStatus.VERIFIED,
            verified_by=self.head_cm,
        )

        self.member_no_guitar = self._make_member(
            "p3_mem_vocal", "TV Không Skill Guitar", self.dept_cm, "8007"
        )
        UserSkill.objects.create(
            user=self.member_no_guitar,
            skill=self.skill_vocal,
            proficiency=SkillProficiency.ADVANCED,
            verification_status=SkillVerificationStatus.VERIFIED,
            verified_by=self.head_cm,
        )

        self.member_tt = self._make_member("p3_mem_tt", "TV Ban Truyền thông", self.dept_tt, "8008")

        self.advisor = self._make_user("p3_advisor", "Cố vấn Nghệ thuật")
        Appointment.objects.create(
            user=self.advisor,
            position=self.positions[PositionCode.ADVISOR],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )

    def _make_user(self, username: str, full_name: str, role: str = Role.MEMBER) -> User:
        self._seq += 1
        u = User.objects.create_user(
            username=username,
            email=f"{username}@kmg.vn",
            password="Password123!",
            full_name=full_name,
            role=role,
            phone=f"0903{self._seq:06d}",
            email_verified_at=timezone.now(),
        )
        UserProfile.objects.get_or_create(user=u)
        return u

    def _make_member(self, username: str, full_name: str, dept, code_suffix: str) -> User:
        u = self._make_user(username, full_name)
        ClubMembership.objects.create(
            user=u, member_code=f"KMG-2026-{code_suffix}", status=ClubMembershipStatus.ACTIVE
        )
        DepartmentMembership.objects.create(
            user=u, department=dept, status=DeptMembershipStatus.ACTIVE
        )
        return _fresh(u)


# ===========================================================================
# 1. KHO TÀI LIỆU MẬT, ACL, MALICIOUS UPLOAD, BREAK-GLASS & PA-02
# ===========================================================================
@override_settings(PRIVATE_VAULT_ROOT=TEST_VAULT_TMPDIR.name)
class ConfidentialVaultAndAclTests(Phase3Base):
    def test_inv01_skill_does_not_grant_acl_and_sec01_private_vault(self):
        secret_bytes = b"Top Secret Guitar Chord Progressions for Liveshow 2026"
        doc, ver = create_confidential_document(
            actor=_fresh(self.head_cm),
            title="Tổng phổ Guitar Mật Liveshow",
            classification=DocumentClassification.RESTRICTED,
            uploaded_file=SimpleUploadedFile("guitar-secret.txt", secret_bytes, content_type="text/plain"),
            department=self.dept_cm,
            recommended_skills=[self.skill_guitar],
        )

        # Kiểm tra SEC-01: lưu trong PRIVATE_VAULT_ROOT, tuyệt đối ngoài MEDIA_ROOT
        stored_path = ver.file.path
        self.assertTrue(os.path.exists(stored_path))
        self.assertTrue(os.path.abspath(stored_path).startswith(os.path.abspath(TEST_VAULT_TMPDIR.name)))
        self.assertFalse(os.path.abspath(stored_path).startswith(os.path.abspath(settings.MEDIA_ROOT)))
        self.assertEqual(len(ver.checksum_sha256), 64)

        # Cấp đích danh USER ACL cho người KHÔNG có skill Guitar (thanhvien_khong_guitar)
        grant_document_acl(
            actor=_fresh(self.head_cm),
            document=doc,
            subject_type=AclSubjectType.USER,
            permission_level=AclPermissionLevel.DOWNLOAD,
            target_user=_fresh(self.member_no_guitar),
            reason="Cần phối hợp hát chính",
        )

        # Cấm cấp ACL theo SKILL (INV-01 / PA-01)
        with self.assertRaises(GovernanceError):
            grant_document_acl(
                actor=_fresh(self.head_cm),
                document=doc,
                subject_type="SKILL",
                permission_level=AclPermissionLevel.DOWNLOAD,
            )

        # Người CÓ Skill Guitar VERIFIED nhưng KHÔNG có ACL -> Two-Phase ẩn & Download bị 403 + DENIED_ATTEMPT
        guitar_user = _fresh(self.member_guitar)
        self.assertFalse(can_access_document(guitar_user, doc, AclPermissionLevel.VIEW))
        self.assertEqual(
            filter_accessible_documents(guitar_user, department=self.dept_cm, skill=self.skill_guitar),
            [],
        )
        self.client.force_login(guitar_user)
        resp_dl_denied = self.client.get(reverse("programs:document_download", args=[doc.pk]))
        self.assertEqual(resp_dl_denied.status_code, 403)
        resp_api_denied = self.client.get(f"/api/v1/documents/{doc.pk}/download/")
        self.assertEqual(resp_api_denied.status_code, 403)
        self.assertEqual(
            DocumentAccessLog.objects.filter(
                document=doc, actor=guitar_user, action=DocumentAccessAction.DENIED_ATTEMPT
            ).count(),
            2,
        )

        # Người KHÔNG có Skill Guitar nhưng CÓ ACL -> Xem & Tải thành công với nosniff
        vocal_user = _fresh(self.member_no_guitar)
        docs_for_vocal = filter_accessible_documents(vocal_user, department=self.dept_cm)
        self.assertEqual([d["document"].pk for d in docs_for_vocal], [doc.pk])
        self.assertFalse(docs_for_vocal[0]["is_skill_recommended"])

        self.client.force_login(vocal_user)
        resp_dl_ok = self.client.get(reverse("programs:document_download", args=[doc.pk]))
        self.assertEqual(resp_dl_ok.status_code, 200)
        self.assertEqual(resp_dl_ok["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment;", resp_dl_ok["Content-Disposition"])
        self.assertEqual(b"".join(resp_dl_ok.streaming_content), secret_bytes)

        # Đa phiên bản v2 -> v1 is_current=False, v2 is_current=True
        v2 = upload_document_version(
            actor=_fresh(self.head_cm),
            document=doc,
            uploaded_file=SimpleUploadedFile("guitar-v2.txt", b"Updated Bridge V2", content_type="text/plain"),
            change_note="Cập nhật Bridge",
        )
        ver.refresh_from_db()
        self.assertFalse(ver.is_current)
        self.assertTrue(v2.is_current)
        self.assertEqual(v2.version_number, 2)

        # Bất biến DocumentAccessLog: không được sửa hay xoá
        log_row = DocumentAccessLog.objects.filter(document=doc).first()
        with self.assertRaises(ValueError):
            log_row.reason = "Tampered"
            log_row.save()
        with self.assertRaises(ValueError):
            log_row.delete()

    def test_wf20_malicious_file_upload_blocked(self):
        actor = _fresh(self.head_cm)
        bad_files = [
            SimpleUploadedFile("xss.html", b"<script>alert(1)</script>", content_type="text/html"),
            SimpleUploadedFile("xss.svg", b"<svg onload=alert(1)></svg>", content_type="image/svg+xml"),
            SimpleUploadedFile("malware.exe", b"MZ\x90\x00binary", content_type="application/octet-stream"),
            SimpleUploadedFile("spoofed.pdf", b"MZ\x90\x00\x03\x00fake-pdf", content_type="application/pdf"),
            SimpleUploadedFile("hidden-script.pdf", b"  <script>alert(1)</script>", content_type="application/pdf"),
            SimpleUploadedFile("empty.txt", b"", content_type="text/plain"),
        ]
        for bad in bad_files:
            with self.assertRaises(GovernanceError, msg=f"Phải chặn tệp {bad.name}"):
                create_confidential_document(
                    actor=actor,
                    title=f"Bad file {bad.name}",
                    classification=DocumentClassification.DEPT_INTERNAL,
                    uploaded_file=bad,
                    department=self.dept_cm,
                )

    def test_highly_restricted_ceiling_and_chairman_break_glass(self):
        doc, _ = create_confidential_document(
            actor=_fresh(self.head_cm),
            title="Tuyệt mật Chiến lược Trưởng ban CM",
            classification=DocumentClassification.HIGHLY_RESTRICTED,
            uploaded_file=SimpleUploadedFile("top-secret.txt", b"Top Executive Data"),
            department=self.dept_cm,
        )

        # Phó ban có BUNDLE_RESOURCE_PROPOSAL & Phó CN Tài chính đều KHÔNG vượt trần HIGHLY_RESTRICTED
        self.assertFalse(can_access_document(_fresh(self.deputy_cm), doc, AclPermissionLevel.VIEW))
        self.assertFalse(can_access_document(_fresh(self.vice_fin), doc, AclPermissionLevel.VIEW))
        # Chỉ Trưởng ban cấp USER ACL đích danh mới được phép (không nhận DEPARTMENT/TASK/POSITION)
        with self.assertRaises(GovernanceError):
            grant_document_acl(
                actor=_fresh(self.head_cm),
                document=doc,
                subject_type=AclSubjectType.DEPARTMENT,
                department=self.dept_cm,
            )

        # Chủ nhiệm không tự động xem Tuyệt mật cấp Ban; GET web trả 403 + form Break-Glass
        chair = _fresh(self.chairman)
        self.assertFalse(can_access_document(chair, doc, AclPermissionLevel.VIEW))
        self.client.force_login(chair)
        resp_403 = self.client.get(reverse("programs:document_detail", args=[doc.pk]))
        self.assertEqual(resp_403.status_code, 403)
        self.assertContains(resp_403, "Break-Glass", status_code=403)

        # Lý do ngắn < 8 ký tự bị từ chối
        with self.assertRaises(GovernanceError):
            break_glass_document_access(actor=chair, document=doc, reason="Ngắn")

        # Lý do hợp lệ -> cấp quyền tạm, ghi DocumentAccessLog(BREAK_GLASS), AuditLog & cảnh báo Trưởng ban
        entry = break_glass_document_access(
            actor=chair,
            document=doc,
            reason="Kiểm tra khẩn cấp sự cố bản quyền trước show diễn",
            duration_hours=12,
        )
        self.assertTrue(entry.is_break_glass)
        self.assertTrue(can_access_document(chair, doc, AclPermissionLevel.DOWNLOAD))
        self.assertTrue(
            DocumentAccessLog.objects.filter(
                document=doc, actor=chair, action=DocumentAccessAction.BREAK_GLASS
            ).exists()
        )
        self.assertTrue(AuditLog.objects.filter(user=chair, target__contains=doc.code).exists())
        self.assertTrue(
            Notification.objects.filter(
                user=self.head_cm, kind=NotificationKind.DOCUMENT_SECURITY
            ).exists()
        )

    def test_pa02_auto_revoke_acl_on_transfer_end_appointment_and_suspend(self):
        doc, _ = create_confidential_document(
            actor=_fresh(self.head_cm),
            title="Hồ sơ ACL kiểm tra PA-02",
            classification=DocumentClassification.RESTRICTED,
            uploaded_file=SimpleUploadedFile("pa02.txt", b"PA-02 Lifecycle Bound"),
            department=self.dept_cm,
        )

        # 1. Cấp ACL cho TV Ban CM -> Chuyển sang Ban Truyền thông -> Tự thu hồi ngay lập tức!
        mem = _fresh(self.member_no_guitar)
        grant_document_acl(
            actor=_fresh(self.head_cm),
            document=doc,
            subject_type=AclSubjectType.USER,
            permission_level=AclPermissionLevel.DOWNLOAD,
            target_user=mem,
            reason="Gắn sinh hoạt Ban CM",
        )
        self.assertTrue(can_access_document(mem, doc, AclPermissionLevel.DOWNLOAD))
        transfer_member_department(
            actor=_fresh(self.chairman),
            target_user=mem,
            from_department=self.dept_cm,
            to_department=self.dept_tt,
            note="Điều chuyển sang Ban Truyền thông",
        )
        self.assertFalse(can_access_document(_fresh(mem), doc, AclPermissionLevel.DOWNLOAD))

        # 2. Kết thúc nhiệm kỳ Phó ban -> Tự thu hồi ACL
        dep_user = _fresh(self.deputy_cm)
        grant_document_acl(
            actor=_fresh(self.head_cm),
            document=doc,
            subject_type=AclSubjectType.USER,
            permission_level=AclPermissionLevel.DOWNLOAD,
            target_user=dep_user,
            reason="Cấp theo nhiệm kỳ Phó ban",
        )
        end_appointment(actor=_fresh(self.head_cm), appointment=self.deputy_cm_appt, reason="Hết nhiệm kỳ")
        self.assertFalse(can_access_document(_fresh(dep_user), doc, AclPermissionLevel.DOWNLOAD))

        # 3. Tạm khoá thành viên -> Thu hồi toàn bộ ACL
        g_user = _fresh(self.member_guitar)
        grant_document_acl(
            actor=_fresh(self.head_cm),
            document=doc,
            subject_type=AclSubjectType.USER,
            permission_level=AclPermissionLevel.DOWNLOAD,
            target_user=g_user,
            reason="Cấp cho thành viên Guitar",
        )
        self.assertTrue(can_access_document(g_user, doc, AclPermissionLevel.DOWNLOAD))
        suspend_club_member(actor=_fresh(self.chairman), target_user=g_user, reason="Tạm nghỉ")
        self.assertFalse(can_access_document(_fresh(g_user), doc, AclPermissionLevel.DOWNLOAD))

    def test_task_and_position_acl_grant(self):
        doc, _ = create_confidential_document(
            actor=_fresh(self.head_cm),
            title="Kịch bản Show phối hợp Task",
            classification=DocumentClassification.RESTRICTED,
            uploaded_file=SimpleUploadedFile("task-acl.txt", b"Task ACL Content"),
            department=self.dept_cm,
        )
        task = create_and_assign_task(
            actor=_fresh(self.head_cm),
            department=self.dept_cm,
            title="Nhiệm vụ đọc kịch bản",
            description="Thực hiện đọc kịch bản",
            deadline=timezone.now() + timedelta(days=2),
            assignees=[_fresh(self.member_guitar)],
        )
        grant_document_acl(
            actor=_fresh(self.head_cm),
            document=doc,
            subject_type=AclSubjectType.TASK,
            task=task,
            permission_level=AclPermissionLevel.DOWNLOAD,
        )
        self.assertTrue(can_access_document(_fresh(self.member_guitar), doc, AclPermissionLevel.DOWNLOAD))
        self.assertFalse(can_access_document(_fresh(self.member_no_guitar), doc, AclPermissionLevel.DOWNLOAD))


# ===========================================================================
# 2. QUY TRÌNH ĐỀ XUẤT HOẠT ĐỘNG 2 CẤP & CHUYỂN ĐỔI (`WF17`, `WF18`, `INV-03`)
# ===========================================================================
@override_settings(PRIVATE_VAULT_ROOT=TEST_VAULT_TMPDIR.name)
class ProposalWorkflowTests(Phase3Base):
    def test_two_tier_approval_inv03_and_conversion_to_event_and_course(self):
        mem = _fresh(self.member_guitar)
        prop = create_proposal(
            actor=mem,
            department=self.dept_cm,
            title="Show Kỷ niệm 5 Năm KMG",
            proposal_type=ProposalType.EVENT,
            scope=ProposalScope.CLUB,
            summary="Kế hoạch tổ chức liveshow tại Hội trường A1",
            estimated_budget=12000000,
            submit_immediately=True,
        )
        self.assertEqual(prop.status, ProposalStatus.SUBMITTED)

        # Trưởng ban KHÔNG thể tự duyệt cuối đề xuất cấp CLB -> phải trình BCN (ESCALATE_BCN)
        with self.assertRaises(PermissionDenied):
            review_proposal(
                actor=_fresh(self.head_cm),
                proposal=prop,
                decision=ProposalReviewDecision.APPROVE,
                feedback="Cố tình duyệt vượt cấp",
            )
        review_proposal(
            actor=_fresh(self.head_cm),
            proposal=prop,
            decision=ProposalReviewDecision.ESCALATE_BCN,
            feedback="Ban Chuyên môn thông qua nội dung nghệ thuật, trình BCN.",
        )
        prop.refresh_from_db()
        self.assertEqual(prop.status, ProposalStatus.UNDER_REVIEW)
        self.assertTrue(prop.is_escalated_to_bcn)

        # Từ chối / Trả sửa bắt buộc có nhận xét
        with self.assertRaises(GovernanceError):
            review_proposal(
                actor=_fresh(self.vice_event),
                proposal=prop,
                decision=ProposalReviewDecision.REQUEST_REVISION,
                feedback="",
            )

        # Phó CN Sự kiện phê duyệt cuối -> APPROVED
        rev = review_proposal(
            actor=_fresh(self.vice_event),
            proposal=prop,
            decision=ProposalReviewDecision.APPROVE,
            feedback="BCN phê duyệt ngân sách & địa điểm",
        )
        prop.refresh_from_db()
        self.assertEqual(prop.status, ProposalStatus.APPROVED)

        # ProposalReview bất biến (không sửa / không xoá)
        with self.assertRaises(ValueError):
            rev.feedback = "Sửa biên bản"
            rev.save()
        with self.assertRaises(ValueError):
            rev.delete()

        # Chuyển đổi thành Dự thảo Sự kiện Kép (`INT-01`: DRAFT + INTERNAL)
        ce = convert_proposal_to_event(actor=_fresh(self.vice_event), proposal=prop)
        prop.refresh_from_db()
        self.assertEqual(prop.status, ProposalStatus.IN_PROGRESS)
        self.assertEqual(prop.linked_event_id, ce.id)
        self.assertEqual(ce.approval_status, ClubEventApprovalStatus.DRAFT)
        self.assertEqual(ce.event.visibility, EventVisibility.INTERNAL)

        # Chặn chuyển đổi lần 2 vì đang IN_PROGRESS
        with self.assertRaises(GovernanceError):
            convert_proposal_to_event(actor=_fresh(self.vice_event), proposal=prop)

        # INV-03: Chặn tự phê duyệt đề xuất của chính mình (ngay cả khi Chủ nhiệm tự tạo đề xuất)
        self_prop = create_proposal(
            actor=_fresh(self.chairman),
            department=self.dept_cm,
            title="Chủ nhiệm tự đề xuất",
            proposal_type=ProposalType.TRAINING,
            scope=ProposalScope.DEPARTMENT,
            summary="Kế hoạch đào tạo nội bộ",
            submit_immediately=True,
        )
        with self.assertRaises(PermissionDenied):
            review_proposal(
                actor=_fresh(self.chairman),
                proposal=self_prop,
                decision=ProposalReviewDecision.APPROVE,
                feedback="Tự duyệt của chính mình",
            )
        # Trưởng ban CM khác phê duyệt giúp -> Chuyển đổi thành TrainingCourse
        review_proposal(
            actor=_fresh(self.head_cm),
            proposal=self_prop,
            decision=ProposalReviewDecision.APPROVE,
            feedback="Đồng ý triển khai",
        )
        course = convert_proposal_to_course(actor=_fresh(self.head_cm), proposal=self_prop)
        self_prop.refresh_from_db()
        self.assertEqual(self_prop.linked_course_id, course.id)
        self.assertEqual(self_prop.status, ProposalStatus.IN_PROGRESS)


# ===========================================================================
# 3. ĐÀO TẠO CHUYÊN MÔN, LỊCH TẬP BAND (`BE-04`) & NHẮC LỊCH IDEMPOTENT
# ===========================================================================
@override_settings(PRIVATE_VAULT_ROOT=TEST_VAULT_TMPDIR.name)
class TrainingPracticeAndRemindersTests(Phase3Base):
    def test_training_waitlist_practice_rsvp_and_idempotent_reminders(self):
        now = timezone.now()
        course = create_training_course(
            actor=_fresh(self.deputy_cm),
            department=self.dept_cm,
            title="Lớp Guitar Fingerstyle Giới hạn",
            location="Phòng Studio B204",
            starts_at=now + timedelta(hours=10),
            ends_at=now + timedelta(hours=12),
            capacity=1,
            instructor=_fresh(self.head_cm),
        )
        e1 = enroll_in_training(actor=_fresh(self.member_guitar), course=course)
        e2 = enroll_in_training(actor=_fresh(self.member_no_guitar), course=course)
        self.assertEqual(e1.status, TrainingEnrollmentStatus.ENROLLED)
        self.assertEqual(e2.status, TrainingEnrollmentStatus.WAITLIST)

        # Tạo buổi tập Band với 2 nhân sự: 1 người giữ lịch, 1 người xin phép vắng (EXCUSED)
        ps = create_practice_session(
            actor=_fresh(self.deputy_cm),
            department=self.dept_cm,
            title="Tập Band Thanh Âm",
            location="Studio B204",
            starts_at=now + timedelta(hours=36),
            ends_at=now + timedelta(hours=38),
            participants_specs=[
                (_fresh(self.member_guitar), "Guitar Lead", self.skill_guitar),
                (_fresh(self.member_no_guitar), "Vocal Chính", self.skill_vocal),
            ],
        )
        part_excused = ps.participants.get(user=self.member_no_guitar)
        update_practice_participant_status(
            actor=_fresh(self.member_no_guitar),
            participant=part_excused,
            new_status=PracticeResponseStatus.EXCUSED,
            note="Trùng lịch thi",
        )

        # Chạy vòng nhắc việc tự động lần 1 & lần 2 -> Đảm bảo idempotent và bỏ qua người EXCUSED
        run1 = run_proactive_operations_cycle(now=now)
        run2 = run_proactive_operations_cycle(now=now)

        # TrainingCourse: e1 (ENROLLED) + instructor (head_cm) nhận T_12H (=2 nhắc lịch); e2 WAITLIST không bị làm phiền
        self.assertEqual(run1["training_reminders_sent"], 2)
        self.assertEqual(run2["training_reminders_sent"], 0)
        # PracticeSession: chỉ member_guitar nhận T_48H (=1), bỏ qua part_excused!
        self.assertEqual(run1["practice_reminders_sent"], 1)
        self.assertEqual(run2["practice_reminders_sent"], 0)
        self.assertEqual(
            ScheduledReminder.objects.filter(
                target_type=ReminderTargetType.TRAINING_SESSION,
                target_id=course.id,
                stage=ReminderStage.T_12H,
            ).count(),
            2,
        )
        self.assertEqual(
            ScheduledReminder.objects.filter(
                target_type=ReminderTargetType.PRACTICE_SESSION,
                target_id=ps.id,
                stage=ReminderStage.T_48H,
            ).count(),
            1,
        )

        # Xác nhận hoàn thành đào tạo
        completed = update_training_enrollment_status(
            actor=_fresh(self.deputy_cm),
            enrollment=e1,
            new_status=TrainingEnrollmentStatus.COMPLETED,
            attendance_count=1,
            completion_note="Đạt chuẩn biểu diễn",
        )
        self.assertIsNotNone(completed.completed_at)


# ===========================================================================
# 4. CỐ VẤN HARD READ-ONLY (`INV-04`), CỔNG 3 BAN & REST API PHASE 3
# ===========================================================================
@override_settings(PRIVATE_VAULT_ROOT=TEST_VAULT_TMPDIR.name)
class AdvisorPortalsAndApiTests(Phase3Base):
    def test_inv04_advisor_read_only_and_specialized_dept_portals(self):
        # Tạo Showcase chuyên biệt cho cả 3 Ban + 1 đề xuất cấp CLB + 1 tài liệu nội bộ CLB + 1 tài liệu mật
        create_department_showcase_item(
            actor=_fresh(self.head_cm),
            department=self.dept_cm,
            category_label="Hòa âm Acoustic",
            item_type=ShowcaseItemType.REPERTOIRE,
            title="Bộ Tiết mục Tiêu chuẩn Ban Chuyên môn",
            summary="Tổng hợp beat và sheet chuẩn cho thành viên mới.",
        )
        create_confidential_document(
            actor=_fresh(self.chairman),
            title="Nội quy Chung KMG",
            classification=DocumentClassification.CLUB_INTERNAL,
            uploaded_file=SimpleUploadedFile("club-rules.txt", b"Club Internal Rules"),
        )
        secret_doc, _ = create_confidential_document(
            actor=_fresh(self.head_cm),
            title="Tài liệu Mật Ban Chuyên môn",
            classification=DocumentClassification.RESTRICTED,
            uploaded_file=SimpleUploadedFile("secret-cm.txt", b"Secret Department Info"),
            department=self.dept_cm,
        )
        club_prop = create_proposal(
            actor=_fresh(self.member_guitar),
            department=self.dept_cm,
            title="Đề xuất Hội diễn Toàn CLB",
            scope=ProposalScope.CLUB,
            summary="Hội diễn âm nhạc học kỳ",
            submit_immediately=True,
        )

        # Cố vấn xem trang tổng quan, đề xuất cấp CLB, kho tài liệu (chỉ thấy CLUB_INTERNAL), đào tạo -> 200 & ẩn nút sửa
        adv = _fresh(self.advisor)
        self.client.force_login(adv)
        self.assertEqual(self.client.get(reverse("organization:advisor_overview")).status_code, 200)
        self.assertEqual(self.client.get(reverse("programs:proposal_hub")).status_code, 200)
        self.assertEqual(self.client.get(reverse("programs:proposal_detail", args=[club_prop.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("programs:training_practice_hub")).status_code, 200)
        vault_resp = self.client.get(reverse("programs:document_vault"))
        self.assertEqual(vault_resp.status_code, 200)
        self.assertContains(vault_resp, "Nội quy Chung KMG")
        self.assertNotContains(vault_resp, "Tài liệu Mật Ban Chuyên môn")

        # Cố vấn bị chặn 403 trên mọi thao tác ghi (INV-04) & tải tài liệu mật
        self.assertEqual(
            self.client.post(
                reverse("programs:proposal_detail", args=[club_prop.pk]),
                {"action": "comment", "body": "Cố tình comment"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("programs:document_vault"),
                {"action": "create_document", "title": "Hack"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("programs:department_add_showcase", args=[self.dept_cm.slug]),
                {"title": "Hack", "summary": "Hack"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("programs:document_download", args=[secret_doc.pk])).status_code,
            403,
        )

        # Xem chéo Ban (`member_tt` ghé xem `dept_cm`) -> 200 READ_ONLY, không thấy tài liệu RESTRICTED
        self.client.force_login(_fresh(self.member_tt))
        cross = self.client.get(reverse("organization:department_detail", args=[self.dept_cm.slug]))
        self.assertEqual(cross.status_code, 200)
        self.assertContains(cross, "READ_ONLY")
        self.assertContains(cross, "Bộ Tiết mục Tiêu chuẩn Ban Chuyên môn")
        self.assertNotContains(cross, "Tài liệu Mật Ban Chuyên môn")

        # Kiểm tra cả 3 Cổng Ban (Truyền thông, Chuyên môn, Kỹ thuật Demo) & REST API Phase 3
        self.client.force_login(_fresh(self.chairman))
        for dept in (self.dept_tt, self.dept_cm, self.dept_kt):
            self.assertEqual(
                self.client.get(reverse("organization:department_detail", args=[dept.slug])).status_code,
                200,
            )

        # API Documents & Proposals
        api_docs = self.client.get("/api/v1/documents/")
        self.assertEqual(api_docs.status_code, 200)
        api_prop = self.client.post(
            "/api/v1/proposals/",
            data=json.dumps(
                {
                    "department_id": self.dept_kt.id,
                    "title": "Nâng cấp Micro Không dây Demo",
                    "proposal_type": "PURCHASE_EQUIPMENT",
                    "scope": "DEPARTMENT",
                    "summary": "Đề xuất mua thêm 2 bộ pin sạc chuyên dụng",
                    "submit_immediately": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(api_prop.status_code, 201)
        new_prop_id = api_prop.json()["data"]["id"]
        # Chủ nhiệm gửi đề xuất rồi tự duyệt qua API -> 403 INV-03
        api_self_approve = self.client.post(
            f"/api/v1/proposals/{new_prop_id}/review/",
            data=json.dumps({"decision": "APPROVE", "feedback": "Tự duyệt"}),
            content_type="application/json",
        )
        self.assertEqual(api_self_approve.status_code, 403)
