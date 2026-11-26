"""Kiểm thử hồi quy cho UI/UX Sprint 1, Design Tokens và KMG Soft Icons 1.0."""
from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, User


class DesignSystemSprint1Tests(TestCase):
    def setUp(self):
        self.guest = User.objects.create_user(username="ui_guest", password="StrongPass!123", role=Role.GUEST)
        self.admin = User.objects.create_user(username="ui_admin", password="StrongPass!123", role=Role.ADMIN)

    def test_required_css_and_icon_assets_exist(self):
        for static_path in (
            "css/tokens.css",
            "css/app.css",
            "css/site.css",
            "css/sidebar.css",
            "css/kmg_editorial.css",
            "css/components/icons.css",
            "icons/kmg/guitar.svg",
            "icons/kmg/sparkles.svg",
            "icons/kmg/calendar.svg",
        ):
            self.assertIsNotNone(finders.find(static_path), f"Thiếu asset static: {static_path}")

    def test_kmg_icon_templatetag_renders_soft_svg_safely(self):
        tpl = Template('{% load ui %}{% kmg_icon "guitar" "lg" "text-primary" "<script>" %}')
        rendered = tpl.render(Context({}))
        self.assertIn('viewBox="0 0 24 24"', rendered)
        self.assertIn("kmg-icon kmg-icon-lg text-primary", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_portal_and_base_include_editorial_css_and_clean_sidebar_icon(self):
        portal_resp = self.client.get(reverse("public_portal:home"))
        self.assertEqual(portal_resp.status_code, 200)
        self.assertContains(portal_resp, "css/tokens.css")
        self.assertContains(portal_resp, "css/kmg_editorial.css")

        self.client.force_login(self.admin)
        dash_resp = self.client.get(reverse("pages:dashboard"))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertContains(dash_resp, "css/kmg_editorial.css")
        self.assertNotContains(dash_resp, "bi-grid-1x2-fill text-primary")

    @override_settings(DEBUG=False)
    def test_design_system_showcase_access_control(self):
        url = reverse("pages:design_system")
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.admin)
        admin_resp = self.client.get(url)
        self.assertEqual(admin_resp.status_code, 200)
        self.assertContains(admin_resp, "KMG Soft Icons 1.0")
        self.assertContains(admin_resp, "Bootstrap Icons")
