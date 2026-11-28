"""Sprint E UI tests: role-based navigation, KMG Soft Icons 1.0, i18n, Light/Dark & legacy/new unification."""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from accounts.models import AccountStatus, Role, User
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
    Position,
    PositionCode,
    ScopeType,
)
from organization.services import bootstrap_organization_catalog


class SprintEProductUITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        catalog = bootstrap_organization_catalog()
        cls.dept = catalog["departments"]["SPECIALTY"]

        cls.guest = User.objects.create_user(
            username="ui_guest", password="Password123!", role=Role.GUEST, account_status=AccountStatus.ACTIVE
        )
        cls.member = cls._make_member("ui_member", Role.MEMBER)
        cls.staff = cls._make_member("ui_staff", Role.STAFF)
        cls.advisor = cls._make_member("ui_advisor", Role.MEMBER)
        Appointment.objects.create(
            user=cls.advisor,
            position=Position.objects.get(code=PositionCode.ADVISOR),
            scope_type=ScopeType.CLUB,
        )
        cls.lead = cls._make_member("ui_lead", Role.LEAD)
        Appointment.objects.create(
            user=cls.lead,
            position=Position.objects.get(code=PositionCode.CHAIRMAN),
            scope_type=ScopeType.CLUB,
        )
        cls.admin = cls._make_member("ui_admin", Role.ADMIN, is_superuser=True, is_staff=True)

    @classmethod
    def _make_member(cls, username: str, role: str, **extra) -> User:
        u = User.objects.create_user(
            username=username,
            password="Password123!",
            email=f"{username}@example.com",
            full_name=username.upper(),
            role=role,
            account_status=AccountStatus.ACTIVE,
            **extra,
        )
        ClubMembership.objects.create(
            user=u,
            member_code=f"KMG-UI-{username.upper()[:12]}",
            status=ClubMembershipStatus.ACTIVE,
        )
        DepartmentMembership.objects.create(
            user=u,
            department=cls.dept,
            status=DeptMembershipStatus.ACTIVE,
        )
        return u

    def test_six_business_groups_kmg_icons_and_dark_mode_tokens(self):
        self.client.force_login(self.member)
        res = self.client.get(reverse("pages:dashboard"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")

        # 6 nhóm nghiệp vụ + Trợ lý AI xuyên suốt; không trùng Hồ sơ cá nhân ở sidebar
        for heading in ("Tổng quan", "Hoạt động &amp; Âm nhạc", "Công việc", "Tổ chức", "Cộng đồng", "Trợ lý AI"):
            self.assertIn(heading, html)
        self.assertNotIn("Quản lý", html)
        self.assertNotIn("Hồ sơ cá nhân", html)

        # KMG Soft Icons 1.0 + Light/Dark theme switcher & tokens
        self.assertIn("kmg-icon", html)
        self.assertIn("themeToggleBtn", html)
        self.assertIn("data-bs-theme", html)
        self.assertIn("kmg_editorial.css", html)
        self.assertIn("tokens.css", html)

    def test_workspace_home_and_task_list_localized_and_dark_safe(self):
        self.client.force_login(self.staff)

        ws = self.client.get(reverse("organization:workspace_home"))
        self.assertEqual(ws.status_code, 200)
        ws_html = ws.content.decode("utf-8")
        self.assertIn("Thành viên chính thức", ws_html)
        self.assertNotIn("alert-light", ws_html)
        self.assertNotIn("text-bg-light", ws_html)
        self.assertNotIn("KMG Platform", ws_html)

        tl = self.client.get(reverse("operations:task_list"))
        self.assertEqual(tl.status_code, 200)
        tl_html = tl.content.decode("utf-8")
        self.assertNotIn("WF13", tl_html)
        self.assertNotIn("INV-01", tl_html)
        self.assertNotIn("KMG Platform", tl_html)
        self.assertIn(reverse("organizing:my_tasks"), tl_html)

        # Legacy <-> Canonical unified navigation links
        mt = self.client.get(reverse("organizing:my_tasks"))
        self.assertEqual(mt.status_code, 200)
        self.assertIn(reverse("operations:task_list"), mt.content.decode("utf-8"))

        dl = self.client.get(reverse("organizing:department_list"))
        self.assertEqual(dl.status_code, 200)
        self.assertIn(reverse("organization:workspace_home"), dl.content.decode("utf-8"))

    def test_role_based_dashboards_render_cleanly(self):
        for user, url_name in (
            (self.guest, "pages:dashboard"),
            (self.member, "organization:workspace_home"),
            (self.staff, "pages:dashboard"),
            (self.advisor, "organization:advisor_overview"),
            (self.lead, "organization:governance_center"),
            (self.admin, "pages:design_system"),
        ):
            self.client.force_login(user)
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200, f"{user.username} failed on {url_name}")
            html = resp.content.decode("utf-8")
            for forbidden in ("D04 v1.1", "Nâng Role", "INV-04", "PA-07", "Hard Read-Only"):
                self.assertNotIn(forbidden, html)

        # AI Chat & Studio localization checks (UI-06 / UI-08)
        self.client.force_login(self.lead)
        chat_html = self.client.get(reverse("aiassist:chat")).content.decode("utf-8")
        self.assertNotIn("Intelligent Music Companion", chat_html)
        self.assertIn("kmg-icon", chat_html)

        studio_html = self.client.get(reverse("aiassist:studio")).content.decode("utf-8")
        self.assertNotIn("LLMOps", studio_html)
        self.assertNotIn("modun", studio_html.lower())
        self.assertNotIn("Eval Suite", studio_html)
