"""
Bộ Kiểm thử Tự động Toàn diện Ma trận Phân quyền Chuẩn `D04 v1.1` (Phase 1 — Module 03):

Bao phủ đầy đủ 10 Persona & 6 Bất biến Bảo mật (`INV-01` .. `INV-06`):
1. Guest & Ứng viên bị chặn `403` khỏi `/workspace/` và `/api/v1/departments/`.
2. Thành viên thường thuộc Ban A: `MEMBER` ở Ban A, `READ_ONLY` ở Ban B (ẩn SĐT riêng tư, chặn thao tác ghi).
3. Trưởng ban A kiêm Thành viên thường ở Ban B và không thuộc Ban C (Đa ban chéo vai):
   `MANAGE` ở Ban A, `MEMBER` (cấm giao việc/xác minh skill/bổ nhiệm Phó ban!) ở Ban B, `READ_ONLY` ở Ban C.
4. Phó ban 3 tầng (Chỉ thị 3.1): Mặc định (`403` trên giao việc/xác minh skill/sơ duyệt) -> Cấp Gói năng lực
   (`BUNDLE_TASK_OPS` + `BUNDLE_TRAINING_CONTENT`) -> Trần cứng (Hard Ceiling chặn bổ nhiệm Phó ban khác & tự ủy quyền,
   kể cả khi nhét vào `CUSTOM` grant!) -> Thu hồi tức thời khi hủy grant hoặc kết thúc nhiệm kỳ (`INV-02`, `INV-06`).
5. Phó chủ nhiệm 3 tầng (Chỉ thị 3.1): Mặc định -> Mảng Nhân sự (`PORTFOLIO_HR`) duyệt được thành viên nhưng
   Mảng Sự kiện (`PORTFOLIO_EVENT`) bị `403`, và cả hai đều bị Trần cứng chặn bổ nhiệm Trưởng ban / Phó CN / Cố vấn!
6. Khóa Đơn nhiệm Đương nhiệm (`singleton_active_key` `UNIQUE NULL`): Chặn `409 CONFLICT_SINGLETON` khi bổ nhiệm
   Chủ nhiệm thứ 2 hoặc Trưởng ban thứ 2 cùng Ban; cho phép bổ nhiệm người kế nhiệm ngay sau `end_appointment`
   mà vẫn bảo toàn nguyên vẹn bản ghi lịch sử của người tiền nhiệm!
7. Cố vấn Hard Read-Only (`INV-04`): Xem được `/workspace/giam-sat/` và tổng quan các Ban, bị chặn `403`
   trên toàn bộ quyền ghi/phê duyệt và không được xem danh sách nhiệm vụ cá nhân trong Ban (`dept.task.view_own`).
8. `Skill != Permission` (`INV-01` & Chỉ thị 3.4): Thành viên CÓ kỹ năng Guitar `VERIFIED` vẫn bị từ chối
   tài liệu Guitar `RESTRICTED_ACL` nếu không nằm trong ACL; thành viên KHÔNG có kỹ năng Guitar nhưng được
   Trưởng ban cấp vào `allowed_users` thì ĐƯỢC truy cập!
9. Sổ cái Lịch sử Thành viên 8+ chặng Bất biến (Chỉ thị 3.2): Chặn `.save()` sửa và `.delete()` xoá trên
   `MemberLifecycleEvent`; chuyển Ban lưu vết lịch sử và tự động kết thúc chức vụ tại Ban cũ.
10. Phân tách trách nhiệm (`INV-03`) & Bí mật tin nhắn riêng tư tuyệt đối (`INV-05`).
"""
from __future__ import annotations

import json

from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import AccountStatus, Role, User, UserProfile
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    LifecycleEventType,
    MemberLifecycleEvent,
    Permission,
    PermissionGrant,
    PositionCode,
    ResourceAccessRule,
    ResourceClassification,
    ScopeType,
    Skill,
    SkillProficiency,
)
from organization.permissions import PERMISSIONS_CATALOG, PermissionEngine
from organization.services import (
    GovernanceError,
    appoint_officer,
    approve_club_member,
    bootstrap_organization_catalog,
    declare_user_skill,
    end_appointment,
    grant_delegated_permissions,
    mark_member_left_club,
    restore_club_member,
    revoke_permission_grant,
    screen_membership_application,
    submit_membership_application,
    suspend_club_member,
    transfer_member_department,
    verify_user_skill,
)


class CanonicalPermissionMatrixV11Tests(TestCase):
    def setUp(self):
        catalog = bootstrap_organization_catalog()
        self.dept_tt = catalog["departments"]["MEDIA_EVENT"]
        self.dept_cm = catalog["departments"]["SPECIALTY"]
        self.dept_kt = catalog["departments"]["TECHNICAL"]
        self.positions = catalog["positions"]

        self._phone_seq = 100

        # Khởi tạo Admin Server (tầng hạ tầng duy nhất có đặc quyền nâng cấp Lãnh đạo cấp cao)
        self.server_admin = self._make_user(
            "server_admin", "Admin Server", phone="0900000000", role=Role.ADMIN
        )

        # Khởi tạo Chủ nhiệm CLB (do Admin Server nâng cấp)
        self.chairman = self._make_user("chairman", "Chủ nhiệm CLB", phone="0900000001")
        ClubMembership.objects.create(
            user=self.chairman,
            member_code="KMG-2026-0001",
            status=ClubMembershipStatus.ACTIVE,
        )
        DepartmentMembership.objects.create(
            user=self.chairman,
            department=self.dept_cm,
            status=DeptMembershipStatus.ACTIVE,
        )
        self.chair_appt = Appointment.objects.create(
            user=self.chairman,
            position=self.positions[PositionCode.CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )

    def _make_user(
        self,
        username: str,
        full_name: str,
        phone: str | None = None,
        role: str = Role.MEMBER,
    ) -> User:
        if phone is None:
            self._phone_seq += 1
            phone = f"0908{self._phone_seq:06d}"
        user = User.objects.create_user(
            username=username,
            password="Password@123",
            full_name=full_name,
            display_name=full_name,
            phone=phone,
            email=f"{username}@kmg.vn",
            role=role,
            account_status=AccountStatus.ACTIVE,
        )
        UserProfile.objects.create(
            user=user,
            privacy_show_email=True,
            privacy_show_phone=False,
            privacy_show_dob=False,
        )
        return user

    def _make_active_member(self, username: str, full_name: str, depts: list) -> User:
        u = self._make_user(username, full_name)
        approve_club_member(actor=self.chairman, target_user=u, departments=depts)
        return u

    # ------------------------------------------------------------------
    # 1. Guest, Onboarding WF01 & Cross-Department Read-Only + PII Privacy
    # ------------------------------------------------------------------
    def test_guest_blocked_from_workspace_and_full_wf01_onboarding_to_member(self):
        """Guest bị chặn 403 khỏi `/workspace/`, nhưng nộp được đơn ứng tuyển WF01 -> sơ duyệt -> duyệt CLB."""
        guest = self._make_user("guest_applicant", "Ứng viên Mới")
        c_guest = Client()
        c_guest.force_login(guest)

        self.assertEqual(
            c_guest.get(reverse("organization:workspace_home")).status_code, 403
        )
        self.assertEqual(
            c_guest.get(reverse("api_v1:departments_list")).status_code, 403
        )

        # Nộp đơn ứng tuyển vào Ban Chuyên môn
        app = submit_membership_application(
            user=guest,
            primary_department=self.dept_cm,
            secondary_department=self.dept_kt,
            declared_skills_text="Guitar Acoustic",
            motivation="Đam mê biểu diễn âm nhạc cùng KMG",
        )
        # Trưởng ban Chuyên môn sơ duyệt (nhưng Trưởng ban Truyền thông KHÔNG được sơ duyệt đơn Ban Chuyên môn!)
        head_cm = self._make_active_member("head_cm_1", "Trưởng ban CM", [self.dept_cm])
        head_tt = self._make_active_member("head_tt_1", "Trưởng ban TT", [self.dept_tt])
        appoint_officer(
            self.server_admin, head_cm, self.positions[PositionCode.DEPT_HEAD], self.dept_cm
        )
        appoint_officer(
            self.server_admin, head_tt, self.positions[PositionCode.DEPT_HEAD], self.dept_tt
        )

        with self.assertRaises(PermissionDenied):
            screen_membership_application(head_tt, app, note="Sơ duyệt trái ban")

        screen_membership_application(head_cm, app, note="Đạt vòng thử giọng")
        approve_club_member(
            actor=self.chairman,
            target_user=guest,
            departments=[self.dept_cm],
            application=app,
        )

        # Sau khi được duyệt: vào được `/workspace/`, ở chế độ `MEMBER` tại Ban CM và `READ_ONLY` tại Ban TT
        self.assertEqual(
            c_guest.get(reverse("organization:workspace_home")).status_code, 200
        )
        self.assertEqual(
            PermissionEngine.get_department_access_mode(guest, self.dept_cm), "MEMBER"
        )
        self.assertEqual(
            PermissionEngine.get_department_access_mode(guest, self.dept_tt),
            "READ_ONLY",
        )

        # Xem chéo danh sách thành viên Ban TT qua API: SĐT cá nhân của Trưởng ban TT phải bị ẩn "(Đã ẩn)"!
        roster_resp = c_guest.get(
            reverse("api_v1:department_members", args=[self.dept_tt.slug])
        )
        self.assertEqual(roster_resp.status_code, 200)
        roster_data = roster_resp.json()["data"]
        self.assertEqual(roster_data["access_mode"], "READ_ONLY")
        self.assertEqual(roster_data["members"][0]["phone"], "(Đã ẩn)")

    # ------------------------------------------------------------------
    # 2. Đa Ban Chéo Vai: Trưởng ban A kiêm Thành viên thường Ban B, ngoài Ban C
    # ------------------------------------------------------------------
    def test_multi_department_cross_role_head_of_dept_a_is_ordinary_member_in_dept_b(self):
        """Trưởng ban CM sinh hoạt như thành viên thường ở Ban TT tuyệt đối không có quyền Trưởng ban ở Ban TT."""
        cross_officer = self._make_active_member(
            "cross_head", "Trưởng CM kiêm TV TT", [self.dept_cm, self.dept_tt]
        )
        appoint_officer(
            self.server_admin,
            cross_officer,
            self.positions[PositionCode.DEPT_HEAD],
            self.dept_cm,
        )

        # Kiểm tra chế độ truy cập trên cả 3 Ban
        self.assertEqual(
            PermissionEngine.get_department_access_mode(cross_officer, self.dept_cm),
            "MANAGE",
        )
        self.assertEqual(
            PermissionEngine.get_department_access_mode(cross_officer, self.dept_tt),
            "MEMBER",
        )
        self.assertEqual(
            PermissionEngine.get_department_access_mode(cross_officer, self.dept_kt),
            "READ_ONLY",
        )

        # Tại Ban Chuyên môn (Ban mình quản lý): đầy đủ quyền Trưởng ban
        self.assertTrue(
            PermissionEngine.authorize(
                cross_officer, "dept.task.assign", department=self.dept_cm
            )
        )
        self.assertTrue(
            PermissionEngine.authorize(
                cross_officer, "dept.deputy.appoint", department=self.dept_cm
            )
        )
        self.assertTrue(
            PermissionEngine.authorize(
                cross_officer, "dept.permission.delegate", department=self.dept_cm
            )
        )

        # Tại Ban Truyền thông (nơi chỉ là Thành viên thường): xem được việc cá nhân nhưng CẤM điều hành!
        self.assertTrue(
            PermissionEngine.authorize(
                cross_officer, "dept.task.view_personal_self", department=self.dept_tt
            )
        )
        for forbidden_in_b in (
            "dept.task.assign",
            "dept.task.approve",
            "dept.skill.verify",
            "dept.member.manage",
            "dept.deputy.appoint",
            "dept.permission.delegate",
        ):
            self.assertFalse(
                PermissionEngine.authorize(
                    cross_officer, forbidden_in_b, department=self.dept_tt
                ),
                f"Trưởng ban CM không được có quyền '{forbidden_in_b}' tại Ban TT!",
            )

        # Tại Ban Kỹ thuật (không phải thành viên Ban): chỉ READ_ONLY, không có cả `dept.task.view_personal_self`
        self.assertTrue(
            PermissionEngine.authorize(
                cross_officer, "dept.page.view", department=self.dept_kt
            )
        )
        self.assertFalse(
            PermissionEngine.authorize(
                cross_officer, "dept.task.view_personal_self", department=self.dept_kt
            )
        )

    # ------------------------------------------------------------------
    # 3. Phó ban 3 Tầng + Trần Cứng + Thu hồi Tức thời (Chỉ thị 3.1 & 3.2)
    # ------------------------------------------------------------------
    def test_deputy_head_three_tier_bundles_hard_ceiling_and_instant_revocation(self):
        """Phó ban: Mặc định khóa điều hành -> Mở đúng gói được cấp -> Chặn trần cứng -> Thu hồi tức thời."""
        head = self._make_active_member("cm_head", "Trưởng ban CM", [self.dept_cm])
        deputy = self._make_active_member("cm_deputy", "Phó ban CM", [self.dept_cm])
        peer = self._make_active_member("cm_peer", "Thành viên CM", [self.dept_cm])

        appoint_officer(
            self.server_admin, head, self.positions[PositionCode.DEPT_HEAD], self.dept_cm
        )
        deputy_appt = appoint_officer(
            head, deputy, self.positions[PositionCode.DEPUTY_HEAD], self.dept_cm
        )

        # Tầng 1 (Baseline): Phó ban chưa được cấp gói nào -> xem được tiến độ, nhưng cấm giao việc & xác minh skill
        self.assertTrue(
            PermissionEngine.authorize(
                deputy, "dept.progress.view_summary", department=self.dept_cm
            )
        )
        self.assertFalse(
            PermissionEngine.authorize(
                deputy, "dept.task.assign", department=self.dept_cm
            )
        )
        self.assertFalse(
            PermissionEngine.authorize(
                deputy, "dept.skill.verify", department=self.dept_cm
            )
        )

        skill_guitar = Skill.objects.get(code="GUITAR_ACOUSTIC")
        peer_skill = declare_user_skill(peer, skill_guitar, SkillProficiency.INTERMEDIATE)
        with self.assertRaises(PermissionDenied):
            verify_user_skill(deputy, peer_skill, self.dept_cm, approved=True)

        # Tầng 2 (Delegated Bundles): Trưởng ban cấp BUNDLE_TASK_OPS + BUNDLE_TRAINING_CONTENT
        g_task = grant_delegated_permissions(
            actor=head,
            bound_appointment=deputy_appt,
            bundle_code=GrantBundleCode.BUNDLE_TASK_OPS,
            department=self.dept_cm,
            reason="Ủy quyền giao bài tập",
        )
        g_train = grant_delegated_permissions(
            actor=head,
            bound_appointment=deputy_appt,
            bundle_code=GrantBundleCode.BUNDLE_TRAINING_CONTENT,
            department=self.dept_cm,
            reason="Ủy quyền thẩm định kỹ năng",
        )
        self.assertTrue(
            PermissionEngine.authorize(
                deputy, "dept.task.assign", department=self.dept_cm
            )
        )
        # Bây giờ Phó ban xác minh được kỹ năng của thành viên trong Ban CM (nhưng vẫn cấm ở Ban khác!)
        verify_user_skill(deputy, peer_skill, self.dept_cm, approved=True)
        self.assertFalse(
            PermissionEngine.authorize(
                deputy, "dept.task.assign", department=self.dept_tt
            )
        )

        # Tầng 3 (Hard Ceiling): Kể cả cố tạo gói CUSTOM nhét quyền bổ nhiệm Phó ban / quyền cấp CLB,
        # PermissionEngine vẫn chặn tuyệt đối!
        custom_grant = PermissionGrant.objects.create(
            grantee=deputy,
            bound_appointment=deputy_appt,
            bundle_code=GrantBundleCode.CUSTOM,
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept_cm,
            reason="Thử vượt trần cứng",
            granted_by=head,
        )
        custom_grant.custom_permissions.set(
            Permission.objects.filter(
                code__in=[
                    "dept.deputy.appoint",
                    "dept.permission.delegate",
                    "club.member.approve",
                ]
            )
        )
        self.assertFalse(
            PermissionEngine.authorize(
                deputy, "dept.deputy.appoint", department=self.dept_cm
            )
        )
        self.assertFalse(
            PermissionEngine.authorize(
                deputy, "dept.permission.delegate", department=self.dept_cm
            )
        )
        self.assertFalse(PermissionEngine.authorize(deputy, "club.member.approve"))

        # Thu hồi lẻ gói BUNDLE_TASK_OPS -> mất quyền giao việc ngay lập tức (`INV-06`)
        revoke_permission_grant(head, g_task, reason="Kết thúc đợt giao bài")
        self.assertFalse(
            PermissionEngine.authorize(
                deputy, "dept.task.assign", department=self.dept_cm
            )
        )
        self.assertTrue(
            PermissionEngine.authorize(
                deputy, "dept.skill.verify", department=self.dept_cm
            )
        )

        # Kết thúc nhiệm kỳ Phó ban (`end_appointment`) -> thu hồi dây chuyền mọi gói quyền còn lại tức thời (`INV-02`)!
        end_appointment(head, deputy_appt, reason="Hết nhiệm kỳ Phó ban")
        self.assertFalse(
            PermissionEngine.authorize(
                deputy, "dept.skill.verify", department=self.dept_cm
            )
        )
        g_train.refresh_from_db()
        self.assertFalse(g_train.is_active)
        self.assertIsNotNone(g_train.revoked_at)

    # ------------------------------------------------------------------
    # 4. Phó Chủ nhiệm 3 Tầng + Trần Cứng Độc quyền Chủ nhiệm / Admin Server
    # ------------------------------------------------------------------
    def test_vice_chairman_portfolios_isolation_and_hard_ceiling(self):
        """Phó CN mặc định được nâng role & phân ban thành viên; Mảng HR/Sự kiện tách biệt; cấm bổ nhiệm Trưởng ban."""
        vc_hr = self._make_active_member("vc_hr", "Phó CN Nhân sự", [self.dept_tt])
        vc_ev = self._make_active_member("vc_ev", "Phó CN Sự kiện", [self.dept_tt])
        candidate_1 = self._make_user("vc_candidate_1", "Khách 1")
        candidate_2 = self._make_user("vc_candidate_2", "Khách 2")

        # Chỉ Admin Server mới được nâng cấp Phó chủ nhiệm (Chủ nhiệm tự bổ nhiệm bị chặn 403!)
        with self.assertRaises(PermissionDenied):
            appoint_officer(
                self.chairman, vc_hr, self.positions[PositionCode.VICE_CHAIRMAN]
            )

        appt_hr = appoint_officer(
            self.server_admin, vc_hr, self.positions[PositionCode.VICE_CHAIRMAN]
        )
        appt_ev = appoint_officer(
            self.server_admin, vc_ev, self.positions[PositionCode.VICE_CHAIRMAN]
        )

        # Theo chính sách v1.2: Cả Chủ nhiệm và Phó CN (kể cả chưa giao mảng riêng) đều được nâng role & phân ban cho Khách!
        self.assertTrue(PermissionEngine.authorize(vc_hr, "club.member.approve"))
        self.assertTrue(PermissionEngine.authorize(vc_ev, "club.member.approve"))
        approve_club_member(vc_ev, candidate_1, [self.dept_cm])
        approve_club_member(vc_hr, candidate_2, [self.dept_cm])

        # Nhưng trước khi giao Mảng Nhân sự (`PORTFOLIO_HR`), Phó CN chưa được tạm khoá thành viên hay bổ nhiệm Phó ban!
        self.assertFalse(PermissionEngine.authorize(vc_hr, "club.member.suspend_temporary"))
        self.assertFalse(PermissionEngine.authorize(vc_ev, "club.event.approve"))

        grant_delegated_permissions(
            self.chairman,
            appt_hr,
            GrantBundleCode.PORTFOLIO_HR,
            reason="Phụ trách Nhân sự",
        )
        grant_delegated_permissions(
            self.chairman,
            appt_ev,
            GrantBundleCode.PORTFOLIO_EVENT,
            reason="Phụ trách Sự kiện",
        )

        # Phó CN Sự kiện cố tạm khoá thành viên / bổ nhiệm Phó ban -> bị chặn 403; nhưng duyệt sự kiện CLB thì được phép
        with self.assertRaises(PermissionDenied):
            suspend_club_member(vc_ev, candidate_1, reason="Tạm khoá trái mảng")
        self.assertTrue(PermissionEngine.authorize(vc_ev, "club.event.approve"))

        # Phó CN Nhân sự tạm khoá / khôi phục & bổ nhiệm Phó ban thành công, nhưng KHÔNG duyệt được sự kiện CLB
        suspend_club_member(vc_hr, candidate_2, reason="Bảo lưu")
        restore_club_member(vc_hr, candidate_2, reason="Quay lại")
        appoint_officer(
            vc_hr,
            candidate_2,
            self.positions[PositionCode.DEPUTY_HEAD],
            department=self.dept_cm,
        )
        self.assertFalse(PermissionEngine.authorize(vc_hr, "club.event.approve"))

        # Trần cứng: Cả Phó CN lẫn Chủ nhiệm đều TUYỆT ĐỐI KHÔNG bổ nhiệm được Trưởng ban (độc quyền Admin Server)!
        for non_server_admin in (vc_hr, vc_ev, self.chairman):
            with self.assertRaises(PermissionDenied):
                appoint_officer(
                    non_server_admin,
                    candidate_1,
                    self.positions[PositionCode.DEPT_HEAD],
                    department=self.dept_cm,
                )
        for forbidden_vc_perm in (
            "server.leadership.manage",
            "club.officer.appoint_head",
            "club.permission.delegate",
            "club.governance.manage_departments",
            "club.governance.update_policy",
            "club.member.expel_permanent",
        ):
            self.assertFalse(PermissionEngine.authorize(vc_hr, forbidden_vc_perm))
            self.assertFalse(PermissionEngine.authorize(vc_ev, forbidden_vc_perm))

    # ------------------------------------------------------------------
    # 5. Khóa Đơn nhiệm (`singleton_active_key`) & Bàn giao Nhiệm kỳ (Chỉ thị 3.2)
    # ------------------------------------------------------------------
    def test_singleton_active_key_prevents_dual_dept_heads_and_allows_succession_after_term_end(self):
        """MySQL 8.4 chặn 409 khi bổ nhiệm Trưởng ban thứ 2 cùng Ban; cho phép kế nhiệm sau khi miễn nhiệm."""
        h1 = self._make_active_member("head_old", "Trưởng ban Nhiệm kỳ 1", [self.dept_cm])
        h2 = self._make_active_member("head_new", "Trưởng ban Nhiệm kỳ 2", [self.dept_cm])

        create_url = reverse("api_v1:appointments_create")

        # Chủ nhiệm gọi API bổ nhiệm Trưởng ban -> bị chặn 403 PERMISSION_DENIED (chỉ Admin Server được phép)!
        c_chair = Client()
        c_chair.force_login(self.chairman)
        r_chair_forbidden = c_chair.post(
            create_url,
            data=json.dumps(
                {
                    "user_id": h1.id,
                    "position_code": PositionCode.DEPT_HEAD,
                    "department_id": self.dept_cm.id,
                    "term_label": "2025-2026",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r_chair_forbidden.status_code, 403)

        c_admin = Client()
        c_admin.force_login(self.server_admin)

        # Admin Server bổ nhiệm Trưởng ban 1 qua REST API -> 201 Created
        r1 = c_admin.post(
            create_url,
            data=json.dumps(
                {
                    "user_id": h1.id,
                    "position_code": PositionCode.DEPT_HEAD,
                    "department_id": self.dept_cm.id,
                    "term_label": "2025-2026",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 201)
        appt1_id = r1.json()["data"]["id"]

        # Cố bổ nhiệm Trưởng ban 2 cho cùng Ban Chuyên môn khi Trưởng ban 1 chưa kết thúc -> 409 CONFLICT_SINGLETON!
        r_conflict = c_admin.post(
            create_url,
            data=json.dumps(
                {
                    "user_id": h2.id,
                    "position_code": PositionCode.DEPT_HEAD,
                    "department_id": self.dept_cm.id,
                    "term_label": "2026-2027",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r_conflict.status_code, 409)
        self.assertEqual(r_conflict.json()["error"]["code"], "CONFLICT_SINGLETON")

        # Kết thúc nhiệm kỳ Trưởng ban 1 qua API -> thu hồi quyền tức thời nhưng giữ nguyên bản ghi lịch sử
        r_end = c_admin.post(
            reverse("api_v1:appointment_end", args=[appt1_id]),
            data=json.dumps({"reason": "Hoàn thành xuất sắc nhiệm kỳ 2025-2026"}),
            content_type="application/json",
        )
        self.assertEqual(r_end.status_code, 200)
        self.assertFalse(
            PermissionEngine.authorize(h1, "dept.task.assign", department=self.dept_cm)
        )

        # Bổ nhiệm Trưởng ban 2 kế nhiệm ngay lập tức -> 201 Created!
        r2 = c_admin.post(
            create_url,
            data=json.dumps(
                {
                    "user_id": h2.id,
                    "position_code": PositionCode.DEPT_HEAD,
                    "department_id": self.dept_cm.id,
                    "term_label": "2026-2027",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 201)
        self.assertTrue(
            PermissionEngine.authorize(h2, "dept.task.assign", department=self.dept_cm)
        )
        # Cả 2 bản ghi nhiệm kỳ (1 lịch sử + 1 đương nhiệm) cùng tồn tại trong CSDL!
        self.assertEqual(
            Appointment.objects.filter(
                department=self.dept_cm, position__code=PositionCode.DEPT_HEAD
            ).count(),
            2,
        )

    # ------------------------------------------------------------------
    # 6. Cố vấn Hard Read-Only (`INV-04`)
    # ------------------------------------------------------------------
    def test_inv04_advisor_hard_read_only_across_entire_platform(self):
        """Cố vấn xem được Dashboard giám sát & tổng quan Ban, nhưng bị khóa 100% quyền ghi và việc cá nhân."""
        advisor = self._make_user("pure_advisor", "Cố vấn Độc lập")
        appoint_officer(
            self.server_admin, advisor, self.positions[PositionCode.ADVISOR]
        )

        self.assertTrue(PermissionEngine.authorize(advisor, "club.overview.supervise"))
        self.assertTrue(
            PermissionEngine.authorize(
                advisor, "dept.page.view", department=self.dept_cm
            )
        )
        # Ma trận khởi đầu của User: Cố vấn -> Xem nhiệm vụ cá nhân trong Ban = KHÔNG
        self.assertFalse(
            PermissionEngine.authorize(
                advisor, "dept.task.view_personal_self", department=self.dept_cm
            )
        )

        # Toàn bộ quyền có `is_mutation=True` trong danh mục đều trả False với Cố vấn!
        for code, _, _, scope, is_mut in PERMISSIONS_CATALOG:
            if is_mut:
                dept_arg = self.dept_cm if scope == ScopeType.DEPARTMENT else None
                self.assertFalse(
                    PermissionEngine.authorize(advisor, code, department=dept_arg),
                    f"INV-04 vi phạm: Cố vấn không được có quyền ghi '{code}'!",
                )

        c_adv = Client()
        c_adv.force_login(advisor)
        self.assertEqual(
            c_adv.get(reverse("organization:advisor_overview")).status_code, 200
        )
        self.assertEqual(
            c_adv.get(reverse("organization:governance_center")).status_code, 403
        )

    # ------------------------------------------------------------------
    # 7. `Skill != Permission` (`INV-01` & Chỉ thị 3.4)
    # ------------------------------------------------------------------
    def test_inv01_skill_never_grants_permission_on_restricted_acl_resources(self):
        """Thành viên có Skill Guitar VERIFIED bị chặn tài liệu Guitar mật; người không có Skill nhưng có ACL được mở."""
        guitarist = self._make_active_member(
            "skilled_guitarist", "Tay Guitar Đã Xác Minh", [self.dept_cm]
        )
        vocalist_with_acl = self._make_active_member(
            "vocalist_acl", "Ca Sĩ Không Biết Guitar Nhưng Được Cấp ACL", [self.dept_cm]
        )
        outsider_other_dept = self._make_active_member(
            "tt_outsider", "Thành viên Ban Truyền thông", [self.dept_tt]
        )

        skill_guitar = Skill.objects.get(code="GUITAR_ACOUSTIC")
        us = declare_user_skill(guitarist, skill_guitar, SkillProficiency.MASTER)
        verify_user_skill(self.chairman, us, self.dept_cm, approved=True)

        secret_guitar_doc = ResourceAccessRule.objects.create(
            resource_type="DOCUMENT",
            resource_code="TEST-SECRET-GUITAR-TAB",
            title="Bản Phối Guitar Mật Show Lớn",
            department=self.dept_cm,
            classification=ResourceClassification.RESTRICTED_ACL,
            recommended_skill=skill_guitar,
            created_by=self.chairman,
        )
        secret_guitar_doc.allowed_users.add(vocalist_with_acl)

        dept_internal_doc = ResourceAccessRule.objects.create(
            resource_type="DOCUMENT",
            resource_code="TEST-CM-INTERNAL",
            title="Tài liệu Nội bộ Ban Chuyên môn",
            department=self.dept_cm,
            classification=ResourceClassification.DEPARTMENT_INTERNAL,
            created_by=self.chairman,
        )

        # 1. Guitarist CÓ kỹ năng Guitar MASTER VERIFIED nhưng không nằm trong ACL -> BỊ TỪ CHỐI!
        self.assertFalse(
            PermissionEngine.can_access_resource(guitarist, secret_guitar_doc)
        )
        # 2. Vocalist KHÔNG có kỹ năng Guitar nhưng được cấp ACL đích danh -> ĐƯỢC PHÉP!
        self.assertTrue(
            PermissionEngine.can_access_resource(vocalist_with_acl, secret_guitar_doc)
        )
        # 3. Tài liệu nội bộ Ban CM: thành viên Ban CM đọc được, thành viên Ban TT xem chéo bị chặn!
        self.assertTrue(
            PermissionEngine.can_access_resource(guitarist, dept_internal_doc)
        )
        self.assertFalse(
            PermissionEngine.can_access_resource(outsider_other_dept, dept_internal_doc)
        )

        # Kiểm tra qua REST API `/api/v1/resources/<code>/access-check/`
        c_guitar = Client()
        c_guitar.force_login(guitarist)
        r_denied = c_guitar.get(
            reverse("api_v1:resource_access_check", args=["TEST-SECRET-GUITAR-TAB"])
        )
        self.assertEqual(r_denied.status_code, 403)
        self.assertEqual(r_denied.json()["error"]["code"], "PERMISSION_DENIED")

        c_vocal = Client()
        c_vocal.force_login(vocalist_with_acl)
        r_allowed = c_vocal.get(
            reverse("api_v1:resource_access_check", args=["TEST-SECRET-GUITAR-TAB"])
        )
        self.assertEqual(r_allowed.status_code, 200)
        self.assertTrue(r_allowed.json()["data"]["access_granted"])

    # ------------------------------------------------------------------
    # 8. Lịch sử Thành viên 8+ Chặng Bất biến, Chuyển Ban, INV-03 & INV-05
    # ------------------------------------------------------------------
    def test_immutable_member_lifecycle_transfer_dept_separation_of_duties_and_inv05(self):
        """Sổ cái vòng đời chặn sửa/xóa, ghi đủ các chặng chuyển ban/tạm khóa/rời CLB, chặn tự duyệt & đọc trộm chat."""
        member = self._make_active_member(
            "lifecycle_member", "Thành viên Đầy Đủ Vòng Đời", [self.dept_cm]
        )
        head_cm = self._make_active_member("head_self_check", "Trưởng ban CM", [self.dept_cm])
        appoint_officer(
            self.server_admin, head_cm, self.positions[PositionCode.DEPT_HEAD], self.dept_cm
        )

        # INV-03: Trưởng ban không được tự xác minh kỹ năng cho chính mình!
        skill_guitar = Skill.objects.get(code="GUITAR_ACOUSTIC")
        own_skill = declare_user_skill(head_cm, skill_guitar, SkillProficiency.ADVANCED)
        with self.assertRaises(PermissionDenied):
            verify_user_skill(head_cm, own_skill, self.dept_cm, approved=True)

        # INV-05: Kể cả Chủ nhiệm CLB lẫn Admin Server cũng bị cấm đọc nội dung tin nhắn riêng tư của người khác!
        self.assertFalse(
            PermissionEngine.authorize(self.chairman, "messaging.private.read_others")
        )
        self.assertFalse(
            PermissionEngine.authorize(self.server_admin, "messaging.private.read_others")
        )

        # Bổ nhiệm Phó ban tại Ban CM -> Chuyển Ban sang Ban KT (tự động kết thúc chức Phó ban ở Ban CM!)
        appoint_officer(
            head_cm, member, self.positions[PositionCode.DEPUTY_HEAD], self.dept_cm
        )
        self.assertTrue(
            PermissionEngine.authorize(
                member, "dept.assist.coordinate_view", department=self.dept_cm
            )
        )
        transfer_member_department(
            actor=self.chairman,
            target_user=member,
            from_department=self.dept_cm,
            to_department=self.dept_kt,
            note="Điều chuyển tăng cường kỹ thuật âm thanh",
        )
        self.assertFalse(
            PermissionEngine.authorize(
                member, "dept.assist.coordinate_view", department=self.dept_cm
            )
        )
        self.assertFalse(
            PermissionEngine.authorize(
                member, "dept.task.view_personal_self", department=self.dept_cm
            )
        )
        # Bản ghi tại Ban cũ vẫn được giữ với trạng thái TRANSFERRED (không xóa mất!)
        self.assertTrue(
            DepartmentMembership.objects.filter(
                user=member,
                department=self.dept_cm,
                status=DeptMembershipStatus.TRANSFERRED,
            ).exists()
        )

        # Tạm khoá -> Khôi phục -> Chuyển Cựu thành viên (Rời CLB)
        suspend_club_member(self.chairman, member, reason="Bảo lưu ngắn hạn")
        restore_club_member(self.chairman, member, reason="Quay lại hoạt động")
        mark_member_left_club(self.chairman, member, as_alumni=True, reason="Tốt nghiệp đại học")

        recorded_types = set(
            member.lifecycle_events.values_list("event_type", flat=True)
        )
        for expected in (
            LifecycleEventType.APPROVED_CLUB,
            LifecycleEventType.JOINED_DEPT,
            LifecycleEventType.APPOINTED,
            LifecycleEventType.ROLE_ENDED,
            LifecycleEventType.TRANSFERRED_DEPT,
            LifecycleEventType.SUSPENDED,
            LifecycleEventType.RESTORED,
            LifecycleEventType.LEFT_CLUB,
        ):
            self.assertIn(expected, recorded_types)

        # Kiểm chứng bất biến tuyệt đối: Cố sửa hoặc cố xóa bất kỳ mốc lịch sử nào đều ném ValueError!
        ev = member.lifecycle_events.first()
        ev.title = "Cố tình sửa lịch sử"
        with self.assertRaises(ValueError):
            ev.save()
        with self.assertRaises(ValueError):
            ev.delete()
