"""Phase 6 QA coverage tests for organization.api_views auth, OTP, sessions, and departments endpoints."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import AccountStatus, Role, UserSession
from organization.models import (
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
)
from organization.services import bootstrap_organization_catalog

User = get_user_model()


class OrganizationAuthAndDeptApiTests(TestCase):
    def setUp(self):
        self.catalog = bootstrap_organization_catalog()
        self.dept_cm = self.catalog["departments"]["SPECIALTY"]
        self.guest = User.objects.create_user(
            username="api_guest",
            email="api_guest@kma.edu.vn",
            phone="0981112233",
            password="Password@123",
            role=Role.GUEST,
            account_status=AccountStatus.UNVERIFIED,
        )
        self.member = User.objects.create_user(
            username="api_member",
            email="api_member@kma.edu.vn",
            password="Password@123",
            role=Role.MEMBER,
            account_status=AccountStatus.ACTIVE,
        )
        ClubMembership.objects.create(
            user=self.member, member_code="KMG-2026-7701", status=ClubMembershipStatus.ACTIVE
        )
        DepartmentMembership.objects.create(
            user=self.member, department=self.dept_cm, status=DeptMembershipStatus.ACTIVE
        )

    @override_settings(SMS_PROVIDER="console")
    def test_auth_register_otp_and_me_flow(self):
        # Bad JSON returns 400
        bad = self.client.post(
            reverse("api_v1:auth_register"),
            data="{bad json",
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 400)

        # Register valid account via API
        with patch("accounts.services.secrets.randbelow", return_value=246810):
            reg = self.client.post(
                reverse("api_v1:auth_register"),
                data=json.dumps({
                    "username": "api_new_student",
                    "full_name": "Sinh Vien API",
                    "email": "apisv@kma.edu.vn",
                    "phone": "0988776655",
                    "mssv": "AT200999",
                    "password1": "StrongPass@2026!",
                    "password2": "StrongPass@2026!",
                    "otp_channel": "SMS",
                }),
                content_type="application/json",
            )
        self.assertEqual(reg.status_code, 201, reg.content)
        self.assertTrue(reg.json()["data"]["otp_sent"])

        # Verify OTP activates account
        ver = self.client.post(
            reverse("api_v1:auth_otp_verify"),
            data=json.dumps({"code": "246810", "channel": "SMS"}),
            content_type="application/json",
        )
        self.assertEqual(ver.status_code, 200)
        self.assertEqual(ver.json()["data"]["account_status"], AccountStatus.ACTIVE)

        # Auth me returns active context
        me = self.client.get(reverse("api_v1:auth_me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["data"]["username"], "api_new_student")

        # Re-send OTP via API
        with patch("accounts.services.secrets.randbelow", return_value=135791):
            resend = self.client.post(
                reverse("api_v1:auth_otp_send"),
                data=json.dumps({"channel": "EMAIL"}),
                content_type="application/json",
            )
        self.assertEqual(resend.status_code, 200)

    def test_sessions_list_revoke_and_departments_acl(self):
        self.client.force_login(self.guest)
        # Guest blocked from internal departments list
        self.assertEqual(self.client.get(reverse("api_v1:departments_list")).status_code, 403)

        # Session list + revoke errors & valid remote revoke
        sess_key = self.client.session.session_key
        cur_sess = UserSession.objects.create(
            user=self.guest, session_key=sess_key, device_label="Current", ip_address="127.0.0.1"
        )
        other_sess = UserSession.objects.create(
            user=self.guest, session_key="remote_device_key", device_label="Phone", ip_address="127.0.0.2"
        )
        self.assertEqual(self.client.get(reverse("api_v1:auth_sessions")).status_code, 200)
        self.assertEqual(
            self.client.post(reverse("api_v1:auth_session_revoke", args=[cur_sess.pk])).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(reverse("api_v1:auth_session_revoke", args=[999999])).status_code,
            404,
        )
        ok_rev = self.client.post(reverse("api_v1:auth_session_revoke", args=[other_sess.pk]))
        self.assertEqual(ok_rev.status_code, 200)

        # Active member reads departments list with access_mode
        self.client.force_login(self.member)
        depts = self.client.get(reverse("api_v1:departments_list"))
        self.assertEqual(depts.status_code, 200)
        self.assertGreaterEqual(len(depts.json()["data"]["departments"]), 1)
