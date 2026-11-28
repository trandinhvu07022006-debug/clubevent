"""Rehearsal & idempotency tests for Unified Business System consolidation (`BUS-01`, `BUS-03`)."""
from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role, User
from operations.models import ClubTask, TaskWorkflowStatus
from organization.business_consolidation import run_unified_business_rehearsal
from organization.models import (
    ApplicationStatus as CanonAppStatus,
    Department as OrgDepartment,
    DepartmentMembership,
    MembershipApplication,
)
from organization.services import bootstrap_organization_catalog
from organizing.models import (
    Department as LegacyDepartment,
    Task as LegacyTask,
    TaskPriority as LegacyPriority,
    TaskStatus as LegacyTaskStatus,
)
from recruitment.models import (
    Application as LegacyApplication,
    ApplicationStatus as LegacyAppStatus,
    RecruitmentRound,
)


class UnifiedBusinessRehearsalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        bootstrap_organization_catalog()
        cls.lead = User.objects.create_user("bus_lead", password="Password123!", role=Role.LEAD)
        cls.member = User.objects.create_user("bus_member", password="Password123!", role=Role.MEMBER)
        cls.applicant = User.objects.create_user("bus_applicant", password="Password123!", role=Role.GUEST)

        cls.l_dept = LegacyDepartment.objects.create(
            name="Ban Sân Khấu Cũ",
            slug="ban-san-khau-cu",
            description="Điều phối âm thanh ánh sáng",
            lead=cls.lead,
            order=9,
        )
        cls.l_dept.members.add(cls.member)

        now = timezone.now()
        cls.l_task_dept = LegacyTask.objects.create(
            title="Kiểm tra micro trước show",
            description="Test 4 mic không dây",
            department=cls.l_dept,
            assignee=cls.member,
            created_by=cls.lead,
            status=LegacyTaskStatus.DONE,
            priority=LegacyPriority.HIGH,
            deadline=now + timedelta(days=1),
            done_at=now,
        )
        cls.l_task_general = LegacyTask.objects.create(
            title="Họp tổng kết tháng",
            description="Việc chung CLB",
            department=None,
            created_by=cls.lead,
            status=LegacyTaskStatus.TODO,
            priority=LegacyPriority.NORMAL,
        )

        cls.r_round = RecruitmentRound.objects.create(
            name="Đợt tuyển thử nghiệm",
            opens_at=now - timedelta(days=2),
            closes_at=now + timedelta(days=5),
        )
        cls.l_app = LegacyApplication.objects.create(
            round=cls.r_round,
            user=cls.applicant,
            department=cls.l_dept,
            strengths="Guitar Acoustic",
            motivation="Muốn đóng góp cho CLB KMG",
            status=LegacyAppStatus.INTERVIEW,
            interview_at=now + timedelta(days=3),
            review_note="Chuẩn bị 1 bài tự chọn",
        )

    def test_dry_run_makes_zero_writes_and_reports_unmapped(self):
        before_depts = OrgDepartment.objects.count()
        before_tasks = ClubTask.objects.count()
        before_apps = MembershipApplication.objects.count()

        rep = run_unified_business_rehearsal(dry_run=True)
        self.assertTrue(rep.ok, rep.errors)
        self.assertEqual(rep.created["Department"], 1)
        self.assertEqual(rep.created["ClubTask"], 2)
        self.assertEqual(rep.created["MembershipApplication"], 1)
        self.assertTrue(any("không gắn Ban" in n for n in rep.unmapped_notes))

        # Dry-run must roll back all writes
        self.assertEqual(OrgDepartment.objects.count(), before_depts)
        self.assertEqual(ClubTask.objects.count(), before_tasks)
        self.assertEqual(MembershipApplication.objects.count(), before_apps)

    def test_execute_idempotent_and_preserves_legacy_tables(self):
        first = run_unified_business_rehearsal(dry_run=False)
        self.assertTrue(first.ok, first.errors)
        self.assertEqual(first.created["Department"], 1)
        self.assertEqual(first.created["ClubTask"], 2)
        self.assertEqual(first.created["MembershipApplication"], 1)

        canon_dept = OrgDepartment.objects.get(slug="ban-san-khau-cu")
        self.assertTrue(
            DepartmentMembership.objects.filter(user=self.member, department=canon_dept).exists()
        )
        done_task = ClubTask.objects.get(category_tag=f"legacy_task:{self.l_task_dept.id}")
        self.assertEqual(done_task.workflow_status, TaskWorkflowStatus.APPROVED)

        canon_app = MembershipApplication.objects.get(user=self.applicant, primary_department=canon_dept)
        self.assertEqual(canon_app.status, CanonAppStatus.DEPT_SCREENED)
        self.assertIn("Chuẩn bị 1 bài tự chọn", canon_app.screening_note)

        # Second run must be 100% idempotent (created=0, skipped=all)
        second = run_unified_business_rehearsal(dry_run=False)
        self.assertTrue(second.ok)
        self.assertEqual(second.created, {"Department": 0, "DepartmentMembership": 0, "ClubTask": 0, "MembershipApplication": 0})
        self.assertEqual(second.skipped_duplicate["Department"], 1)
        self.assertEqual(second.skipped_duplicate["ClubTask"], 2)
        self.assertEqual(second.skipped_duplicate["MembershipApplication"], 1)

        # Legacy tables remain completely untouched
        self.assertEqual(LegacyDepartment.objects.count(), 1)
        self.assertEqual(LegacyTask.objects.count(), 2)
        self.assertEqual(LegacyApplication.objects.count(), 1)

        # Management command dry-run works cleanly
        from io import StringIO
        buf = StringIO()
        call_command("audit_unified_business", stdout=buf)
        self.assertIn('"dry_run": true', buf.getvalue().lower())
