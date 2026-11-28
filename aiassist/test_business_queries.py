"""Comprehensive authorization & success-path tests for `aiassist.business_queries`."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, Role, User
from aiassist.business_queries import (
    query_club_analytics,
    query_department_ops,
    query_finance_summary,
    query_my_evaluations,
    query_my_practice,
    query_my_recruitment_status,
    query_my_training,
)
from evaluations.models import (
    EvaluationCycle,
    EvaluationStatus,
    MemberEvaluation,
    OverallRating,
)
from finance.models import (
    AdjustmentDirection,
    FinancialTransaction,
    FundCategory,
    TransactionStatus,
    TransactionType,
)
from operations.models import ClubTask, TaskWorkflowStatus
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
    ScopeType,
    Skill,
    SkillCategory,
    SkillProficiency,
    UserSkill,
)
from organization.services import (
    bootstrap_organization_catalog,
    end_appointment,
    grant_delegated_permissions,
)
from programs.models import (
    PracticeParticipant,
    PracticeSession,
    PracticeSessionStatus,
    TrainingCourse,
    TrainingCourseStatus,
    TrainingEnrollment,
    TrainingEnrollmentStatus,
)
from recruitment.models import Application, ApplicationStatus, RecruitmentRound
from organizing.models import Department as OrganizingDepartment


class BusinessQueriesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        catalog = bootstrap_organization_catalog()
        cls.dept_cm = catalog["departments"]["SPECIALTY"]
        cls.dept_tt = Department.objects.filter(is_active=True).exclude(pk=cls.dept_cm.pk).first()

        cls.pos_president = Position.objects.get(code=PositionCode.CHAIRMAN)
        cls.pos_vice = Position.objects.get(code=PositionCode.VICE_CHAIRMAN)
        cls.pos_advisor = Position.objects.get(code=PositionCode.ADVISOR)
        cls.pos_dept_head = Position.objects.get(code=PositionCode.DEPT_HEAD)

        cls.server_admin = User.objects.create_user(
            username="bq_srv_admin",
            password="Password123!",
            email="bq_srv_admin@example.com",
            role=Role.ADMIN,
            account_status=AccountStatus.ACTIVE,
            is_superuser=True,
            is_staff=True,
        )
        cls.president = cls._make_member("bq_president", cls.dept_cm, role=Role.LEAD)
        Appointment.objects.create(
            user=cls.president,
            position=cls.pos_president,
            scope_type=ScopeType.CLUB,
            department=None,
        )

        cls.treasurer = cls._make_member("bq_treasurer", cls.dept_cm, role=Role.LEAD)
        treasurer_appt = Appointment.objects.create(
            user=cls.treasurer,
            position=cls.pos_vice,
            scope_type=ScopeType.CLUB,
            department=None,
        )
        grant_delegated_permissions(
            cls.president,
            treasurer_appt,
            GrantBundleCode.PORTFOLIO_FINANCE_DOC,
            reason="Phụ trách tài chính",
        )

        cls.advisor = cls._make_member("bq_advisor", cls.dept_cm, role=Role.MEMBER)
        Appointment.objects.create(
            user=cls.advisor,
            position=cls.pos_advisor,
            scope_type=ScopeType.CLUB,
            department=None,
        )

        cls.head_cm = cls._make_member("bq_head_cm", cls.dept_cm, role=Role.LEAD)
        cls.head_cm_appt = Appointment.objects.create(
            user=cls.head_cm,
            position=cls.pos_dept_head,
            scope_type=ScopeType.DEPARTMENT,
            department=cls.dept_cm,
        )

        cls.member_cm = cls._make_member("bq_member_cm", cls.dept_cm, role=Role.MEMBER)
        cls.outsider = User.objects.create_user(
            username="bq_outsider",
            password="Password123!",
            email="bq_outsider@example.com",
            role=Role.GUEST,
            account_status=AccountStatus.ACTIVE,
        )
        cls.locked_user = cls._make_member("bq_locked", cls.dept_cm, role=Role.LEAD)
        Appointment.objects.create(
            user=cls.locked_user,
            position=cls.pos_dept_head,
            scope_type=ScopeType.DEPARTMENT,
            department=cls.dept_tt,
        )
        cls.locked_user.is_locked = True
        cls.locked_user.account_status = AccountStatus.LOCKED
        cls.locked_user.save(update_fields=["is_locked", "account_status"])

    @classmethod
    def _make_member(cls, username: str, dept: Department, role: str = Role.MEMBER) -> User:
        user = User.objects.create_user(
            username=username,
            password="Password123!",
            email=f"{username}@example.com",
            full_name=username.replace("_", " ").title(),
            role=role,
            account_status=AccountStatus.ACTIVE,
        )
        ClubMembership.objects.create(
            user=user,
            member_code=f"KMG-BQ-{username.upper()[:14]}",
            status=ClubMembershipStatus.ACTIVE,
        )
        DepartmentMembership.objects.create(
            user=user,
            department=dept,
            status=DeptMembershipStatus.ACTIVE,
        )
        return user

    # ── 1. query_my_practice ─────────────────────────────────────────
    def test_query_my_practice_personal_and_club_fallback_and_guards(self):
        now = timezone.now()
        session1 = PracticeSession.objects.create(
            title="Tập Acoustic",
            department=self.dept_cm,
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=2),
            location="Phòng nhạc A",
            status=PracticeSessionStatus.SCHEDULED,
            created_by=self.head_cm,
        )
        PracticeParticipant.objects.create(session=session1, user=self.member_cm)

        res = query_my_practice(self.member_cm)
        self.assertIn("Tập Acoustic", res["text"])
        self.assertEqual(res["links"][0]["url"], reverse("programs:training_practice_hub"))

        # Club member without personal participant gets general club sessions
        res_other = query_my_practice(self.head_cm)
        self.assertIn("buổi tập sắp tới", res_other["text"])
        self.assertIn("Tập Acoustic", res_other["text"])

        # Outsider without internal view permission gets empty message
        res_out = query_my_practice(self.outsider)
        self.assertIn("chưa có lịch tập", res_out["text"])

        # Anonymous & locked guards
        self.assertIn("đăng nhập", query_my_practice(AnonymousUser())["text"])
        self.assertIn("bị khóa", query_my_practice(self.locked_user)["text"])

    # ── 2. query_my_recruitment_status ───────────────────────────────
    def test_query_my_recruitment_status_success_empty_and_guards(self):
        from organization.models import MembershipApplication

        self.assertIn("chưa nộp đơn", query_my_recruitment_status(self.outsider)["text"])

        # Canonical MembershipApplication alone must be found (AI-06)
        MembershipApplication.objects.create(
            user=self.outsider,
            primary_department=self.dept_cm,
            declared_skills_text="Guitar đệm hát",
            motivation="Yêu thích âm nhạc KMG",
        )
        res_canon = query_my_recruitment_status(self.outsider)
        self.assertIn("Hồ sơ gia nhập KMG", res_canon["text"])
        self.assertIn(self.dept_cm.name, res_canon["text"])
        self.assertEqual(res_canon["links"][0]["url"], reverse("organization:apply_membership"))

        org_dept = OrganizingDepartment.objects.create(name="Ban Chuyên môn", slug="chuyen-mon-bq")
        r_round = RecruitmentRound.objects.create(
            name="Tuyển thành viên K18",
            opens_at=timezone.now() - timedelta(days=1),
            closes_at=timezone.now() + timedelta(days=10),
        )
        Application.objects.create(
            round=r_round,
            user=self.outsider,
            department=org_dept,
            status=ApplicationStatus.INTERVIEW,
            interview_at=timezone.now() + timedelta(days=2),
        )
        res = query_my_recruitment_status(self.outsider)
        self.assertIn("Tuyển thành viên K18", res["text"])
        self.assertIn("Lịch phỏng vấn/casting", res["text"])
        self.assertIn(reverse("recruitment:home"), [l["url"] for l in res["links"]])

        self.assertIn("đăng nhập", query_my_recruitment_status(None)["text"])
        self.assertIn("bị khóa", query_my_recruitment_status(self.locked_user)["text"])

    # ── 3. query_my_training ─────────────────────────────────────────
    def test_query_my_training_enrolled_open_empty_and_guards(self):
        now = timezone.now()
        self.assertIn("chưa tham gia khóa đào tạo", query_my_training(self.member_cm)["text"])

        course = TrainingCourse.objects.create(
            title="Thanh nhạc cơ bản",
            department=self.dept_cm,
            starts_at=now + timedelta(days=3),
            ends_at=now + timedelta(days=3, hours=2),
            status=TrainingCourseStatus.OPEN,
            created_by=self.head_cm,
        )
        # Other member sees open course
        res_open = query_my_training(self.head_cm)
        self.assertIn("Các khóa đào tạo đang mở", res_open["text"])
        self.assertIn("Thanh nhạc cơ bản", res_open["text"])

        # Enrolled member + skill
        TrainingEnrollment.objects.create(
            course=course,
            user=self.member_cm,
            status=TrainingEnrollmentStatus.ENROLLED,
        )
        skill = Skill.objects.first() or Skill.objects.create(
            code="VOCAL_BQ",
            name="Thanh nhạc",
            category=SkillCategory.MUSIC,
        )
        UserSkill.objects.create(
            user=self.member_cm,
            skill=skill,
            proficiency=SkillProficiency.INTERMEDIATE,
        )
        res_enrolled = query_my_training(self.member_cm)
        self.assertIn("Khóa đào tạo bạn đã đăng ký", res_enrolled["text"])
        self.assertIn("Thanh nhạc cơ bản", res_enrolled["text"])
        self.assertIn("Kỹ năng đã ghi nhận", res_enrolled["text"])
        self.assertEqual(res_enrolled["links"][0]["url"], reverse("programs:training_practice_hub"))

        self.assertIn("đăng nhập", query_my_training(AnonymousUser())["text"])
        self.assertIn("bị khóa", query_my_training(self.locked_user)["text"])

    # ── 4. query_my_evaluations ──────────────────────────────────────
    def test_query_my_evaluations_confirmed_draft_empty_and_guards(self):
        cycle = EvaluationCycle.objects.create(
            code="2026-BQ",
            name="Kỳ đánh giá BQ 2026",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 6, 30),
        )
        # Draft evaluation must NOT be shown
        MemberEvaluation.objects.create(
            cycle=cycle,
            member=self.member_cm,
            department=self.dept_cm,
            status=EvaluationStatus.DRAFT,
            overall_rating=OverallRating.MEETS,
            drafted_by=self.head_cm,
        )
        res_empty = query_my_evaluations(self.member_cm)
        self.assertIn("chưa có kỳ đánh giá", res_empty["text"])
        self.assertEqual(res_empty["links"][0]["url"], reverse("evaluations:hub"))

        # Confirmed evaluation IS shown with valid evaluations:hub link
        MemberEvaluation.objects.create(
            cycle=cycle,
            member=self.member_cm,
            department=self.dept_tt,
            status=EvaluationStatus.CONFIRMED,
            overall_rating=OverallRating.STRONG,
            drafted_by=self.head_cm,
            finalized_by=self.president,
        )
        res_ok = query_my_evaluations(self.member_cm)
        self.assertIn("Kỳ đánh giá BQ 2026", res_ok["text"])
        self.assertEqual(res_ok["links"][0]["url"], reverse("evaluations:hub"))

        self.assertIn("đăng nhập", query_my_evaluations(AnonymousUser())["text"])
        self.assertIn("bị khóa", query_my_evaluations(self.locked_user)["text"])

    # ── 5. query_department_ops (scoped by dept.task.assign) ─────────
    def test_query_department_ops_scope_revocation_and_guards(self):
        now = timezone.now()
        ClubTask.objects.create(
            title="Task Ban Chuyên môn",
            department=self.dept_cm,
            created_by=self.head_cm,
            deadline=now - timedelta(days=1),  # overdue
            workflow_status=TaskWorkflowStatus.ASSIGNED,
        )
        ClubTask.objects.create(
            title="Task Ban Truyền thông",
            department=self.dept_tt,
            created_by=self.president,
            deadline=now + timedelta(days=2),
            workflow_status=TaskWorkflowStatus.SUBMITTED,
        )

        # Dept Head CM sees ONLY Ban Chuyên môn (1 open, 0 submitted, 1 overdue)
        res_cm = query_department_ops(self.head_cm)
        self.assertIn("Ban Chuyên môn", res_cm["text"])
        self.assertIn("1 đầu việc đang mở", res_cm["text"])
        self.assertIn("0 chờ duyệt nộp, 1 quá hạn", res_cm["text"])
        self.assertEqual(res_cm["links"][0]["url"], reverse("operations:task_list"))

        # President sees club-wide (2 open, 1 submitted, 1 overdue)
        res_pres = query_department_ops(self.president)
        self.assertIn("toàn CLB", res_pres["text"])
        self.assertIn("2 đầu việc đang mở", res_pres["text"])

        # Regular member, outsider, locked, anonymous -> denied
        for actor in (self.member_cm, self.outsider, self.locked_user, AnonymousUser()):
            res_denied = query_department_ops(actor)
            self.assertIn("không có quyền", res_denied["text"])
            self.assertEqual(res_denied["links"], [])

        # Revoked appointment -> immediately denied
        end_appointment(self.server_admin, self.head_cm_appt, reason="Hết nhiệm kỳ")
        res_revoked = query_department_ops(self.head_cm)
        self.assertIn("không có quyền", res_revoked["text"])

    # ── 6. query_finance_summary (club.finance.view_summary) ─────────
    def test_query_finance_summary_permissions_revocation_and_guards(self):
        cat = FundCategory.objects.create(code="BQ_CAT", name="Quỹ sự kiện")
        FinancialTransaction.objects.create(
            tx_code="BQ-IN-01",
            tx_type=TransactionType.INCOME,
            category=cat,
            title="Thu tài trợ",
            amount=Decimal("500000"),
            transaction_date=date(2026, 5, 1),
            status=TransactionStatus.CONFIRMED,
            created_by=self.treasurer,
            approved_by=self.president,
            approved_at=timezone.now(),
        )
        FinancialTransaction.objects.create(
            tx_code="BQ-OUT-01",
            tx_type=TransactionType.EXPENSE,
            category=cat,
            title="Chi dây đàn",
            amount=Decimal("150000"),
            transaction_date=date(2026, 5, 2),
            status=TransactionStatus.CONFIRMED,
            created_by=self.treasurer,
            approved_by=self.president,
            approved_at=timezone.now(),
        )
        FinancialTransaction.objects.create(
            tx_code="BQ-PEND-01",
            tx_type=TransactionType.EXPENSE,
            category=cat,
            title="Chờ duyệt",
            amount=Decimal("100000"),
            transaction_date=date(2026, 5, 3),
            status=TransactionStatus.PENDING_APPROVAL,
            created_by=self.treasurer,
        )

        # Treasurer, Advisor, President allowed
        for actor in (self.treasurer, self.advisor, self.president):
            res_ok = query_finance_summary(actor)
            self.assertIn("500.000đ", res_ok["text"])
            self.assertIn("150.000đ", res_ok["text"])
            self.assertIn("350.000đ", res_ok["text"])
            self.assertIn("1 khoản đang chờ duyệt", res_ok["text"])
            self.assertEqual(res_ok["links"][0]["url"], reverse("finance:hub"))

        # Dept head (no club finance perm), regular member, outsider, locked, anonymous -> denied
        for actor in (self.head_cm, self.member_cm, self.outsider, self.locked_user, AnonymousUser()):
            res_denied = query_finance_summary(actor)
            self.assertIn("không có quyền", res_denied["text"])
            self.assertEqual(res_denied["links"], [])

        # Revoke treasurer appointment -> denied
        treasurer_appt = Appointment.objects.get(user=self.treasurer, is_active=True)
        end_appointment(self.server_admin, treasurer_appt, reason="Miễn nhiệm")
        self.assertIn("không có quyền", query_finance_summary(self.treasurer)["text"])

    # ── 7. query_club_analytics (organization:governance_center/advisor_overview) ──
    def test_query_club_analytics_routes_revocation_and_guards(self):
        # President -> governance_center
        res_pres = query_club_analytics(self.president)
        self.assertIn("thành viên chính thức", res_pres["text"])
        self.assertEqual(res_pres["links"][0]["url"], reverse("organization:governance_center"))

        # Advisor -> advisor_overview
        res_adv = query_club_analytics(self.advisor)
        self.assertIn("thành viên chính thức", res_adv["text"])
        self.assertEqual(res_adv["links"][0]["url"], reverse("organization:advisor_overview"))

        # Dept head, member, outsider, locked, anonymous -> denied
        for actor in (self.head_cm, self.member_cm, self.outsider, self.locked_user, AnonymousUser()):
            res_denied = query_club_analytics(actor)
            self.assertIn("không có quyền", res_denied["text"])
            self.assertEqual(res_denied["links"], [])

        # Revoke advisor appointment -> denied
        adv_appt = Appointment.objects.get(user=self.advisor, is_active=True)
        end_appointment(self.server_admin, adv_appt, reason="Kết thúc")
        self.assertIn("không có quyền", query_club_analytics(self.advisor)["text"])

    def test_finance_adjustment_and_json_sse_endpoints(self):
        import json as _json

        cat = FundCategory.objects.create(code="BQ_ADJ", name="Quỹ điều chỉnh")
        base_tx = FinancialTransaction.objects.create(
            tx_code="BQ-BASE-IN",
            tx_type=TransactionType.INCOME,
            category=cat,
            title="Thu gốc",
            amount=Decimal("100000"),
            transaction_date=date(2026, 5, 3),
            status=TransactionStatus.CONFIRMED,
            created_by=self.treasurer,
            approved_by=self.president,
            approved_at=timezone.now(),
        )
        FinancialTransaction.objects.create(
            tx_code="BQ-ADJ-CR",
            tx_type=TransactionType.ADJUSTMENT,
            adjustment_direction=AdjustmentDirection.CREDIT,
            adjusted_from=base_tx,
            category=cat,
            title="Bù tăng",
            amount=Decimal("200000"),
            transaction_date=date(2026, 5, 4),
            status=TransactionStatus.CONFIRMED,
            created_by=self.treasurer,
            approved_by=self.president,
            approved_at=timezone.now(),
        )
        res_pres = query_finance_summary(self.president)
        self.assertIn("300.000đ", res_pres["text"])

        # JSON & SSE endpoint checks
        self.client.force_login(self.member_cm)
        r_json_denied = self.client.post(
            reverse("aiassist:chat_api"),
            data=_json.dumps({"question": "Tình hình thu chi quỹ CLB thế nào?"}),
            content_type="application/json",
        )
        self.assertEqual(r_json_denied.status_code, 200)
        self.assertIn("không có quyền", r_json_denied.json()["text"])

        self.client.force_login(self.president)
        r_sse_ok = self.client.post(
            reverse("aiassist:chat_stream_api"),
            data=_json.dumps({"question": "Tình hình thu chi quỹ CLB thế nào?"}),
            content_type="application/json",
        )
        self.assertEqual(r_sse_ok.status_code, 200)
        sse_body = b"".join(r_sse_ok.streaming_content).decode("utf-8")
        self.assertIn("300.000đ", sse_body)
