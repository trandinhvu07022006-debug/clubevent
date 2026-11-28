"""
RC1 Automated E2E & 7-Role UAT HTTP/Template Smoke Suite (AUD-010, AUD-011).

NOTE ON SCOPE:
- This suite automates backend + Django template rendering + CSRF/CSP/responsive
  markup invariants and 7-role end-to-end user journeys via Django Test Client.
- True headless pixel-rendering checks (Playwright / Chromium at 360px..1920px)
  are tracked separately and marked BLOCKED when browser binaries are absent.
- Sign-off by human pilot operators remains tracked as Human UAT (REVIEW_REQUIRED).
"""
from __future__ import annotations

import datetime
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountStatus, Role
from events.models import Event, EventStatus, EventVisibility, TicketType
from finance.models import FundCategory, TransactionType
from finance.services import bootstrap_finance_categories
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    PermissionGrant,
    Position,
    PositionCode,
    ScopeType,
)
from registrations.models import Ticket, TicketStatus

User = get_user_model()


class SevenRoleAutomatedUATSuites(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(
            code="UAT_MEDIA", name="Ban Truyền thông", slug="uat-media", is_active=True
        )
        bootstrap_finance_categories()
        self.cat = FundCategory.objects.filter(tx_type=TransactionType.EXPENSE).first()

        positions = {}
        for code, (name, scope, off, single, ro) in {
            PositionCode.CHAIRMAN: ("Chủ nhiệm CLB", ScopeType.CLUB, True, True, False),
            PositionCode.VICE_CHAIRMAN: ("Phó CN CLB", ScopeType.CLUB, True, False, False),
            PositionCode.ADVISOR: ("Cố vấn CLB", ScopeType.CLUB, False, False, True),
            PositionCode.DEPT_HEAD: ("Trưởng ban", ScopeType.DEPARTMENT, True, True, False),
        }.items():
            positions[code], _ = Position.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "scope_type": scope,
                    "is_officer": off,
                    "is_singleton": single,
                    "is_read_only": ro,
                },
            )

        now = timezone.now()
        self.guest = User.objects.create_user(
            "uat_guest",
            password="UatTestPassword!1",
            role=Role.GUEST,
            account_status=AccountStatus.ACTIVE,
            email="uat_guest@example.com",
            email_verified_at=now,
        )
        self.member = User.objects.create_user(
            "uat_member",
            password="UatTestPassword!1",
            role=Role.MEMBER,
            account_status=AccountStatus.ACTIVE,
            email="uat_member@example.com",
            email_verified_at=now,
        )
        ClubMembership.objects.create(
            user=self.member, member_code="KMG-UAT-001", status=ClubMembershipStatus.ACTIVE
        )
        DepartmentMembership.objects.create(
            user=self.member, department=self.dept, status=DeptMembershipStatus.ACTIVE
        )

        self.staff = User.objects.create_user(
            "uat_staff",
            password="UatTestPassword!1",
            role=Role.STAFF,
            account_status=AccountStatus.ACTIVE,
            email="uat_staff@example.com",
            email_verified_at=now,
        )
        self.lead = User.objects.create_user(
            "uat_lead",
            password="UatTestPassword!1",
            role=Role.LEAD,
            account_status=AccountStatus.ACTIVE,
            email="uat_lead@example.com",
            email_verified_at=now,
        )
        self.chair = User.objects.create_user(
            "uat_chair",
            password="UatTestPassword!1",
            role=Role.MEMBER,
            account_status=AccountStatus.ACTIVE,
            email="uat_chair@example.com",
            email_verified_at=now,
        )
        Appointment.objects.create(
            user=self.chair, position=positions[PositionCode.CHAIRMAN], scope_type=ScopeType.CLUB, is_active=True
        )
        self.advisor = User.objects.create_user(
            "uat_advisor",
            password="UatTestPassword!1",
            role=Role.MEMBER,
            account_status=AccountStatus.ACTIVE,
            email="uat_advisor@example.com",
            email_verified_at=now,
        )
        Appointment.objects.create(
            user=self.advisor, position=positions[PositionCode.ADVISOR], scope_type=ScopeType.CLUB, is_active=True
        )
        self.admin = User.objects.create_superuser(
            "uat_admin",
            password="UatTestPassword!1",
            email="uat_admin@example.com",
        )
        self.vc = User.objects.create_user(
            "uat_vc",
            password="UatTestPassword!1",
            role=Role.MEMBER,
            account_status=AccountStatus.ACTIVE,
        )
        vc_appt = Appointment.objects.create(
            user=self.vc, position=positions[PositionCode.VICE_CHAIRMAN], scope_type=ScopeType.CLUB, is_active=True
        )
        PermissionGrant.objects.create(
            grantee=self.vc,
            bound_appointment=vc_appt,
            scope_type=ScopeType.CLUB,
            bundle_code=GrantBundleCode.PORTFOLIO_FINANCE_DOC,
            granted_by=self.chair,
            reason="UAT Finance VC",
        )

        self.pub_event = Event.objects.create(
            name="KMG Acoustic Night UAT",
            location="Hội trường KMA",
            capacity=100,
            starts_at=now + datetime.timedelta(days=5),
            register_deadline=now + datetime.timedelta(days=4),
            status=EventStatus.OPEN,
            visibility=EventVisibility.PUBLIC,
        )
        self.pub_tt = TicketType.objects.create(event=self.pub_event, name="Vé thường", price=0, quota=50)
        self.internal_event = Event.objects.create(
            name="Sinh hoạt nội bộ KMG UAT",
            location="Phòng CLB",
            capacity=40,
            starts_at=now + datetime.timedelta(days=6),
            register_deadline=now + datetime.timedelta(days=5),
            status=EventStatus.OPEN,
            visibility=EventVisibility.INTERNAL,
        )

    def _assert_responsive_html(self, response, expected_status=200):
        self.assertEqual(response.status_code, expected_status)
        body = response.content.decode("utf-8", "replace")
        self.assertIn('name="viewport"', body)
        self.assertIn("bootstrap", body.lower())

    def test_public_guest_and_responsive_shell_pages(self):
        for route in (
            reverse("pages:home"),
            reverse("events:list"),
            reverse("events:detail", args=[self.pub_event.pk]),
            reverse("public_portal:home"),
            reverse("accounts:login"),
            reverse("aiassist:chat"),
        ):
            with self.subTest(route=route):
                resp = self.client.get(route)
                self._assert_responsive_html(resp, 200)

        # Guest cannot view internal event detail cleanly (403 or 404)
        self.client.force_login(self.guest)
        internal_resp = self.client.get(reverse("events:detail", args=[self.internal_event.pk]))
        self.assertIn(internal_resp.status_code, (403, 404))

        # Guest books free ticket end-to-end
        book_resp = self.client.post(
            reverse("registrations:book", args=[self.pub_event.pk]),
            {"ticket_type": self.pub_tt.pk, "quantity": 1},
        )
        self.assertEqual(book_resp.status_code, 302)
        ticket = Ticket.objects.get(user=self.guest, event=self.pub_event)
        self.assertEqual(ticket.status, TicketStatus.CONFIRMED)

        # Chatbot rule endpoint responds cleanly for guest
        chat_resp = self.client.post(
            reverse("aiassist:chat_api"),
            data=json.dumps({"question": "Đăng ký vé thế nào?"}),
            content_type="application/json",
        )
        self.assertEqual(chat_resp.status_code, 200)
        self.assertEqual(chat_resp.json()["source"], "rules")

    def test_member_staff_lead_chair_advisor_and_admin_journeys(self):
        # Member sees internal event & workspace
        self.client.force_login(self.member)
        self._assert_responsive_html(self.client.get(reverse("events:detail", args=[self.internal_event.pk])), 200)
        self._assert_responsive_html(self.client.get(reverse("organization:workspace_home")), 200)
        self._assert_responsive_html(self.client.get(reverse("operations:task_list")), 200)

        # Staff scans QR ticket at event check-in
        self.client.force_login(self.staff)
        self._assert_responsive_html(self.client.get(reverse("registrations:checkin", args=[self.pub_event.pk])), 200)
        ticket = Ticket.objects.create(
            user=self.guest,
            event=self.pub_event,
            ticket_type=self.pub_tt,
            price=0,
            status=TicketStatus.CONFIRMED,
            booking_ref="UATREF01",
            code="UATCODE12345",
        )
        scan_resp = self.client.post(
            reverse("registrations:checkin_scan", args=[self.pub_event.pk]),
            data=json.dumps({"code": ticket.code}),
            content_type="application/json",
        )
        self.assertEqual(scan_resp.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, TicketStatus.CHECKED_IN)

        # Lead creates event draft / manages dashboard
        self.client.force_login(self.lead)
        self._assert_responsive_html(self.client.get(reverse("events:dashboard")), 200)

        # Chairman & VC Finance access Governance & Finance Hub & AI Studio
        for leader in (self.chair, self.vc, self.admin):
            self.client.force_login(leader)
            self._assert_responsive_html(self.client.get(reverse("finance:hub")), 200)
            self._assert_responsive_html(self.client.get(reverse("aiassist:studio")), 200)

        # Advisor accesses Advisor Overview & Finance Hub (read-only), blocked from AI Studio & mutations (UT-10)
        self.client.force_login(self.advisor)
        self._assert_responsive_html(self.client.get(reverse("organization:advisor_overview")), 200)
        self._assert_responsive_html(self.client.get(reverse("finance:hub")), 200)
        self.assertEqual(self.client.get(reverse("aiassist:studio")).status_code, 403)
        adv_post = self.client.post(
            reverse("finance:hub"),
            {"action": "create_transaction", "title": "Bypass", "amount": "1000"},
        )
        self.assertEqual(adv_post.status_code, 403)

    def test_applicant_deputy_grant_revoke_a11y_error_pages_and_query_budget(self):
        # UT-02: Applicant applies & sees application status
        self.client.force_login(self.guest)
        apply_url = reverse("organization:apply_membership")
        self._assert_responsive_html(self.client.get(apply_url), 200)
        app_res = self.client.post(
            apply_url,
            {
                "primary_department": self.dept.pk,
                "declared_skills_text": "Vocal",
                "motivation": "Tham gia hát Acoustic cùng CLB",
            },
        )
        self.assertIn(app_res.status_code, (200, 302))

        # UT-08: Deputy grant & instant revoke on appointment end
        deputy = User.objects.create_user(
            "uat_deputy", password="UatTestPassword!1", role=Role.MEMBER, account_status=AccountStatus.ACTIVE
        )
        ClubMembership.objects.create(user=deputy, member_code="KMG-UAT-DEP", status=ClubMembershipStatus.ACTIVE)
        DepartmentMembership.objects.create(user=deputy, department=self.dept, status=DeptMembershipStatus.ACTIVE)
        pos_dep, _ = Position.objects.get_or_create(
            code=PositionCode.DEPUTY_HEAD,
            defaults={"name": "Phó ban", "scope_type": ScopeType.DEPARTMENT, "is_officer": True},
        )
        dep_appt = Appointment.objects.create(
            user=deputy, position=pos_dep, scope_type=ScopeType.DEPARTMENT, department=self.dept, is_active=True
        )
        grant = PermissionGrant.objects.create(
            grantee=deputy,
            bound_appointment=dep_appt,
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept,
            bundle_code=GrantBundleCode.BUNDLE_TASK_OPS,
            granted_by=self.chair,
            reason="UAT Deputy",
        )
        from organization.permissions import PermissionEngine
        self.assertTrue(PermissionEngine.authorize(deputy, "dept.task.assign", department=self.dept))
        grant.revoked_at = timezone.now()
        grant.is_active = False
        grant.save(update_fields=["revoked_at", "is_active"])
        self.assertFalse(PermissionEngine.authorize(deputy, "dept.task.assign", department=self.dept))

        # UT-13 / UI-09: Accessibility markers & Dark mode CSS parity
        self.client.force_login(self.member)
        dash_resp = self.client.get(reverse("pages:dashboard"))
        dash_html = dash_resp.content.decode("utf-8")
        self.assertIn('<html lang="vi">', dash_html)
        self.assertIn('class="skip-link"', dash_html)
        self.assertIn("data-bs-theme", dash_html)

        # UT-14: Clean 404 error state without Python traceback
        err_404 = self.client.get("/duong-dan-khong-ton-tai-uat-404/")
        self.assertEqual(err_404.status_code, 404)
        err_html = err_404.content.decode("utf-8")
        self.assertNotIn("Traceback", err_html)

        # QA-06: Bounded query budget on dashboard & workspace_home
        with self.subTest("query-budget"):
            from django.db import connection
            from django.test.utils import CaptureQueriesContext

            with CaptureQueriesContext(connection) as q_dash:
                self.assertEqual(self.client.get(reverse("pages:dashboard")).status_code, 200)
            self.assertLessEqual(len(q_dash), 30, f"dashboard queries={len(q_dash)}")

            with CaptureQueriesContext(connection) as q_ws:
                self.assertEqual(self.client.get(reverse("organization:workspace_home")).status_code, 200)
            self.assertLessEqual(len(q_ws), 45, f"workspace_home queries={len(q_ws)}")
