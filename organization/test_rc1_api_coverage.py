"""RC1 QA & RBAC coverage tests for organization API endpoints (AUD-012)."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import AccountStatus, Role
from organization.models import (
    GrantBundleCode,
    PositionCode,
    ResourceAccessRule,
    Skill,
    UserSkill,
)
from organization.services import bootstrap_organization_catalog

User = get_user_model()


class OrganizationGovernanceApiCoverageTests(TestCase):
    def setUp(self):
        self.catalog = bootstrap_organization_catalog()
        depts = list(self.catalog["departments"].values())
        self.dept_a = self.catalog["departments"]["SPECIALTY"]
        self.dept_b = next(d for d in depts if d.pk != self.dept_a.pk)
        self.server_admin = User.objects.create_superuser(
            username="org_srv_admin",
            email="srvadmin@kma.edu.vn",
            password="StrongPass@2026!",
        )
        self.candidate = User.objects.create_user(
            username="org_candidate",
            email="cand@kma.edu.vn",
            password="StrongPass@2026!",
            role=Role.GUEST,
            account_status=AccountStatus.ACTIVE,
        )
        self.chair_user = User.objects.create_user(
            username="org_chair_api",
            email="chair@kma.edu.vn",
            password="StrongPass@2026!",
            role=Role.GUEST,
            account_status=AccountStatus.ACTIVE,
        )
        self.vc_user = User.objects.create_user(
            username="org_vc_api",
            email="vc@kma.edu.vn",
            password="StrongPass@2026!",
            role=Role.GUEST,
            account_status=AccountStatus.ACTIVE,
        )

    def test_leadership_promotion_appointments_grants_lifecycle_and_resources(self):
        # 1. Server admin promotes chairman & dept_head (non-admin denied 403)
        self.client.force_login(self.candidate)
        denied_lead = self.client.post(
            reverse("api_v1:admin_assign_leadership"),
            data=json.dumps({"user_id": self.chair_user.pk, "position_code": PositionCode.CHAIRMAN}),
            content_type="application/json",
        )
        self.assertEqual(denied_lead.status_code, 403)

        self.client.force_login(self.server_admin)
        assign_chair = self.client.post(
            reverse("api_v1:admin_assign_leadership"),
            data=json.dumps({"user_id": self.chair_user.pk, "position_code": PositionCode.CHAIRMAN}),
            content_type="application/json",
        )
        self.assertEqual(assign_chair.status_code, 201, assign_chair.content)

        # Missing user returns 404
        missing_lead = self.client.post(
            reverse("api_v1:admin_assign_leadership"),
            data=json.dumps({"user_id": 999999, "position_code": PositionCode.CHAIRMAN}),
            content_type="application/json",
        )
        self.assertEqual(missing_lead.status_code, 404)

        # 2. Chairman promotes candidate -> member in dept_a
        self.client.force_login(self.chair_user)
        promo = self.client.post(
            reverse("api_v1:members_promote"),
            data=json.dumps({
                "user_id": self.candidate.pk,
                "department_ids": [self.dept_a.pk],
                "note": "Tuyển đạt",
            }),
            content_type="application/json",
        )
        self.assertEqual(promo.status_code, 201, promo.content)
        self.assertTrue(promo.json()["data"]["has_active_club_access"])

        # Department detail & members read access
        d_detail = self.client.get(reverse("api_v1:department_detail", args=[self.dept_a.slug]))
        self.assertEqual(d_detail.status_code, 200)
        d_members = self.client.get(reverse("api_v1:department_members", args=[self.dept_a.slug]))
        self.assertEqual(d_members.status_code, 200)

        # 3. Appoint VC & check singleton / permission grant / revoke / appointment end
        appt_vc = self.client.post(
            reverse("api_v1:appointments_create"),
            data=json.dumps({"user_id": self.vc_user.pk, "position_code": PositionCode.VICE_CHAIRMAN}),
            content_type="application/json",
        )
        # Only server admin appoints top club officers -> 403 for chairman if exclusive, else check status
        if appt_vc.status_code == 403:
            self.client.force_login(self.server_admin)
            appt_vc = self.client.post(
                reverse("api_v1:admin_assign_leadership"),
                data=json.dumps({"user_id": self.vc_user.pk, "position_code": PositionCode.VICE_CHAIRMAN}),
                content_type="application/json",
            )
            self.assertEqual(appt_vc.status_code, 201)
            appt_id = appt_vc.json()["data"]["appointment_id"]
            self.client.force_login(self.chair_user)
        else:
            self.assertEqual(appt_vc.status_code, 201)
            appt_id = appt_vc.json()["data"]["id"]

        grant_resp = self.client.post(
            reverse("api_v1:permission_grants"),
            data=json.dumps({
                "appointment_id": appt_id,
                "bundle_code": GrantBundleCode.PORTFOLIO_FINANCE_DOC,
                "reason": "Cấp quyền tài chính thử nghiệm",
            }),
            content_type="application/json",
        )
        self.assertEqual(grant_resp.status_code, 201, grant_resp.content)
        grant_id = grant_resp.json()["data"]["id"]

        self.client.force_login(self.vc_user)
        grants_list = self.client.get(reverse("api_v1:permission_grants"))
        self.assertEqual(grants_list.status_code, 200)
        self.assertEqual(len(grants_list.json()["data"]["grants"]), 1)

        # Revoke grant & end appointment
        self.client.force_login(self.chair_user)
        rev = self.client.post(
            reverse("api_v1:permission_grant_revoke", args=[grant_id]),
            data=json.dumps({"reason": "Kết thúc kiểm thử"}),
            content_type="application/json",
        )
        self.assertEqual(rev.status_code, 200)

        self.client.force_login(self.server_admin)
        end_res = self.client.post(
            reverse("api_v1:appointment_end", args=[appt_id]),
            data=json.dumps({"reason": "Hết nhiệm kỳ"}),
            content_type="application/json",
        )
        self.assertEqual(end_res.status_code, 200)
        self.assertFalse(end_res.json()["data"]["is_active"])

        # 4. Skills self-add & verify + INV-01 ResourceAccessRule check + lifecycle
        skill = Skill.objects.first()
        self.client.force_login(self.candidate)
        add_sk = self.client.post(
            reverse("api_v1:my_skills"),
            data=json.dumps({"skill_code": skill.code}),
            content_type="application/json",
        )
        self.assertIn(add_sk.status_code, (200, 201))
        self.assertEqual(self.client.get(reverse("api_v1:my_skills")).status_code, 200)
        usk = UserSkill.objects.filter(user=self.candidate, skill=skill).first()
        self.assertIsNotNone(usk)

        # Self-verification blocked (`INV-03`)
        self_ver = self.client.post(
            reverse("api_v1:verify_user_skill", args=[usk.pk]),
            data=json.dumps({"department_id": self.dept_a.pk, "approved": True}),
            content_type="application/json",
        )
        self.assertEqual(self_ver.status_code, 403)

        # Resource access check: missing -> 404, confidential without explicit grant -> 403
        self.assertEqual(
            self.client.get(reverse("api_v1:resource_access_check", args=["no-such-code"])).status_code,
            404,
        )
        rule = ResourceAccessRule.objects.create(
            resource_code="CONF-TEST-01",
            title="Tài liệu mật thử nghiệm",
            department=self.dept_a,
            recommended_skill=skill,
            classification="CONFIDENTIAL",
        )
        self.assertEqual(
            self.client.get(reverse("api_v1:resource_access_check", args=[rule.resource_code])).status_code,
            403,
        )
        # Lifecycle timeline for self -> 200, for out-of-scope user -> 403
        self.assertEqual(
            self.client.get(reverse("api_v1:member_lifecycle", args=[self.candidate.pk])).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("api_v1:member_lifecycle", args=[self.vc_user.pk])).status_code,
            403,
        )
