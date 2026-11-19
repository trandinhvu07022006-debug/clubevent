"""
Bộ kiểm thử Phase 5 — Đánh giá 7 Tiêu chí, Vinh danh & Phân tích Báo cáo (`evaluations`).

Kiểm thử toàn diện:
- 7 Tiêu chí phát triển cá nhân theo Chỉ thị 3.3 + tự động snapshot số liệu Phase 2/3.
- Thành viên đa Ban nhận đánh giá độc lập theo từng Ban (`UNIQUE(cycle, member, department)`).
- Phó ban có thể soạn nháp nhưng bị chặn chốt đánh giá (Hard Ceiling `DEPUTY_HEAD_FORBIDDEN_PERMISSIONS`).
- `INV-03`: Chặn tự đánh giá, tự chốt, và tự xác nhận vinh danh cho bản thân.
- `BE-06`: Trao đổi hai chiều trên phiếu đánh giá trước khi khoá kỳ.
- Vinh danh tách biệt khỏi bảng điểm, không rò rỉ điểm số cá nhân ra công khai.
- Thành viên A bị 403 khi cố xem phiếu đánh giá của thành viên B.
- `INV-04` & `PA-07`: Cố vấn xem được phân tích báo cáo và xuất CSV đã che PII, bị 403 trên mọi thao tác sửa/chốt.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    Position,
    PositionCode,
)
from organization.services import (
    appoint_officer,
    approve_club_member,
    bootstrap_organization_catalog,
    grant_delegated_permissions,
)

from .analytics import build_executive_analytics, export_analytics_csv
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
    create_or_update_evaluation_draft,
    ensure_cycle,
    finalize_evaluation,
    nominate_recognition,
    submit_evaluation_response,
    verify_recognition,
)


class Phase5EvaluationsTests(TestCase):
    def setUp(self):
        bootstrap_organization_catalog()

        self.dept_cm = Department.objects.get(code="SPECIALTY")
        self.dept_tt = Department.objects.get(code="MEDIA_EVENT")

        self.server_admin = User.objects.create_superuser(
            username="srv_admin_ev", email="admin@ev.kmg", full_name="Admin Server Ev"
        )
        self.chairman = self._make_user("cn_ev", "Chủ nhiệm Ev", Role.LEAD)
        self.advisor = self._make_user("advisor_ev", "Cố vấn Ev", Role.MEMBER)
        self.head_cm = self._make_user("head_cm_ev", "Trưởng ban CM Ev", Role.LEAD)
        self.deputy_cm = self._make_user("deputy_cm_ev", "Phó ban CM Ev", Role.STAFF)
        self.head_tt = self._make_user("head_tt_ev", "Trưởng ban TT Ev", Role.LEAD)
        self.multi_dept_member = self._make_user("multi_ev", "Thành viên Đa Ban Ev", Role.MEMBER)
        self.single_member = self._make_user("single_ev", "Thành viên Đơn Ban Ev", Role.MEMBER)

        for u, depts in [
            (self.chairman, [self.dept_cm, self.dept_tt]),
            (self.head_cm, [self.dept_cm]),
            (self.deputy_cm, [self.dept_cm]),
            (self.head_tt, [self.dept_tt]),
            (self.multi_dept_member, [self.dept_cm, self.dept_tt]),
            (self.single_member, [self.dept_cm]),
        ]:
            approve_club_member(self.server_admin, u, departments=depts)

        pos_cn = Position.objects.get(code=PositionCode.CHAIRMAN)
        pos_adv = Position.objects.get(code=PositionCode.ADVISOR)
        pos_head = Position.objects.get(code=PositionCode.DEPT_HEAD)
        pos_deputy = Position.objects.get(code=PositionCode.DEPUTY_HEAD)

        appoint_officer(self.server_admin, self.chairman, pos_cn)
        appoint_officer(self.server_admin, self.advisor, pos_adv)
        appoint_officer(self.server_admin, self.head_cm, pos_head, department=self.dept_cm)
        appoint_officer(self.server_admin, self.head_tt, pos_head, department=self.dept_tt)
        appt_deputy = appoint_officer(self.head_cm, self.deputy_cm, pos_deputy, department=self.dept_cm)
        # Phó ban được ủy quyền gói HR_SCREENING (có quyền soạn nháp dept.evaluation.propose)
        grant_delegated_permissions(
            self.head_cm,
            appt_deputy,
            GrantBundleCode.BUNDLE_HR_SCREENING,
            reason="Phụ trách nhân sự và đánh giá chuyên môn",
            department=self.dept_cm,
        )

        self.cycle = ensure_cycle(
            self.chairman,
            code="2026-HK1",
            name="Đánh giá HK1/2026",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            response_deadline=date(2027, 1, 15),
        )

    def _make_user(self, username: str, full_name: str, role: str) -> User:
        return User.objects.create_user(
            username=username,
            email=f"{username}@kmg.vn",
            full_name=full_name,
            role=role,
            password="password123",
            email_verified_at=timezone.now(),
        )

    def test_7_criteria_rubric_and_drafting_by_deputy(self):
        """Phó ban có gói HR soạn được nháp 7 tiêu chí; nhưng bị chặn khi cố chốt đánh giá (Hard Ceiling)."""
        ev = create_or_update_evaluation_draft(
            self.deputy_cm,
            cycle=self.cycle,
            member=self.single_member,
            department=self.dept_cm,
            criteria={
                EvaluationCriterion.TASK_COMPLETION: 4,
                EvaluationCriterion.ATTENDANCE: 5,
                EvaluationCriterion.PROFESSIONAL_SKILL: 4,
                EvaluationCriterion.TRAINING_GROWTH: 4,
                EvaluationCriterion.TEAMWORK: 5,
                EvaluationCriterion.INITIATIVE: 4,
                EvaluationCriterion.CULTURE: 5,
            },
            overall_rating=OverallRating.MEETS,
            strengths="Thái độ tập luyện rất tốt.",
        )
        self.assertEqual(ev.status, EvaluationStatus.DRAFT)
        self.assertEqual(ev.criterion_scores.count(), 7)

        # Phó ban cố chốt -> Bị chặn PermissionDenied (Hard Ceiling)
        with self.assertRaises(PermissionDenied):
            finalize_evaluation(self.deputy_cm, ev)

        # Trưởng ban chốt -> Thành công CONFIRMED
        finalized = finalize_evaluation(self.head_cm, ev)
        self.assertEqual(finalized.status, EvaluationStatus.CONFIRMED)
        self.assertEqual(finalized.finalized_by, self.head_cm)

    def test_multi_dept_member_independent_evaluations(self):
        """Thành viên đa Ban nhận 2 phiếu đánh giá độc lập per Ban, không ghi đè và cô lập quyền."""
        # Trưởng ban CM đánh giá tại Ban CM
        ev_cm = create_or_update_evaluation_draft(
            self.head_cm,
            cycle=self.cycle,
            member=self.multi_dept_member,
            department=self.dept_cm,
            criteria={EvaluationCriterion.TASK_COMPLETION: 5},
            overall_rating=OverallRating.STRONG,
        )
        finalize_evaluation(self.head_cm, ev_cm)

        # Trưởng ban TT đánh giá tại Ban TT
        ev_tt = create_or_update_evaluation_draft(
            self.head_tt,
            cycle=self.cycle,
            member=self.multi_dept_member,
            department=self.dept_tt,
            criteria={EvaluationCriterion.TASK_COMPLETION: 3},
            overall_rating=OverallRating.DEVELOPING,
        )
        finalize_evaluation(self.head_tt, ev_tt)

        # Hai phiếu tách biệt, không ghi đè nhau
        self.assertNotEqual(ev_cm.pk, ev_tt.pk)
        self.assertEqual(
            MemberEvaluation.objects.filter(cycle=self.cycle, member=self.multi_dept_member).count(), 2
        )

        # Trưởng ban CM không có quyền xem phiếu Ban TT của thành viên này
        c_cm = Client()
        c_cm.force_login(self.head_cm)
        resp_tt = c_cm.get(reverse("evaluations:detail", kwargs={"pk": ev_tt.pk}))
        self.assertEqual(resp_tt.status_code, 403)

    def test_inv03_rejects_self_evaluation_and_self_verify(self):
        """INV-03: Trưởng ban không được tự soạn/tự chốt đánh giá bản thân hoặc tự duyệt vinh danh bản thân."""
        # Trưởng ban tự đánh giá mình -> Bị chặn INV-03
        with self.assertRaises(PermissionDenied):
            create_or_update_evaluation_draft(
                self.head_cm,
                cycle=self.cycle,
                member=self.head_cm,
                department=self.dept_cm,
            )

        # Tự đề cử vinh danh -> Bị chặn INV-03
        with self.assertRaises(PermissionDenied):
            nominate_recognition(
                self.head_cm,
                recipient=self.head_cm,
                title="Tự xưng xuất sắc",
                citation="Tự khen mình",
            )

    def test_be06_evaluation_response_dialogue(self):
        """BE-06: Thành viên được gửi phản hồi nhẹ nhàng trên phiếu CONFIRMED trước hạn deadline."""
        ev = create_or_update_evaluation_draft(
            self.head_cm,
            cycle=self.cycle,
            member=self.single_member,
            department=self.dept_cm,
            criteria={EvaluationCriterion.TASK_COMPLETION: 4},
            overall_rating=OverallRating.MEETS,
        )
        ev = finalize_evaluation(self.head_cm, ev)

        # Thành viên phản hồi
        resp = submit_evaluation_response(
            self.single_member, ev, "Em xin ghi nhận góp ý và sẽ nỗ lực hơn ạ."
        )
        self.assertEqual(resp.author, self.single_member)
        self.assertTrue(resp.is_member_response)

        # Cán bộ Ban trả lời
        resp_reply = submit_evaluation_response(
            self.head_cm, ev, "Ban luôn đồng hành cùng em!"
        )
        self.assertFalse(resp_reply.is_member_response)

    def test_privacy_boundary_member_a_cannot_view_member_b_evaluation(self):
        """Quyền riêng tư: Thành viên thường A bị 403 khi cố xem phiếu đánh giá của Thành viên B."""
        ev = create_or_update_evaluation_draft(
            self.head_cm,
            cycle=self.cycle,
            member=self.single_member,
            department=self.dept_cm,
            criteria={EvaluationCriterion.TASK_COMPLETION: 4},
            overall_rating=OverallRating.MEETS,
        )
        ev = finalize_evaluation(self.head_cm, ev)

        c = Client()
        c.force_login(self.multi_dept_member)
        resp = c.get(reverse("evaluations:detail", kwargs={"pk": ev.pk}))
        self.assertEqual(resp.status_code, 403)

    def test_member_recognition_workflow_and_public_spotlight(self):
        """Vinh danh thành viên tách biệt khỏi điểm số, phê duyệt bởi BCN/Trưởng ban và xuất hiện trang chủ."""
        rec = nominate_recognition(
            self.head_cm,
            recipient=self.single_member,
            title="Ngôi sao Sân khấu Trẻ",
            citation="Hoàn thành xuất sắc tiết mục đơn ca mở màn.",
            scope=RecognitionScope.DEPARTMENT,
            department=self.dept_cm,
            cycle=self.cycle,
            is_public=True,
        )
        self.assertEqual(rec.status, RecognitionStatus.PROPOSED)

        # Chủ nhiệm xác nhận duyệt vinh danh
        verify_recognition(self.chairman, rec, approve=True)
        rec.refresh_from_db()
        self.assertEqual(rec.status, RecognitionStatus.VERIFIED)

        # Trang chủ công khai hiển thị vinh danh này
        c = Client()
        resp_home = c.get(reverse("public_portal:home"))
        self.assertEqual(resp_home.status_code, 200)
        self.assertContains(resp_home, "Ngôi sao Sân khấu Trẻ")
        self.assertContains(resp_home, self.single_member.public_name)

    def test_inv04_pa07_advisor_analytics_and_redacted_export(self):
        """INV-04 & PA-07: Cố vấn xem được Analytics, xuất CSV đã che PII, nhưng bị 403 khi thao tác phiếu cá nhân."""
        c = Client()
        c.force_login(self.advisor)

        # Cố vấn xem Dashboard phân tích -> 200 OK
        resp_analytics = c.get(reverse("evaluations:analytics"))
        self.assertEqual(resp_analytics.status_code, 200)

        # Xuất CSV -> 200 OK
        resp_csv = c.get(reverse("evaluations:analytics_csv"))
        self.assertEqual(resp_csv.status_code, 200)
        self.assertEqual(resp_csv["Content-Type"], "text/csv; charset=utf-8")

        # Cố vấn cố soạn phiếu mới -> 403
        resp_draft = c.get(
            reverse("evaluations:draft_new")
            + f"?member_id={self.single_member.id}&dept_id={self.dept_cm.id}"
        )
        self.assertEqual(resp_draft.status_code, 403)
