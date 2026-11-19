"""
Bộ kiểm thử toàn diện Phase 4 — Internal Social, Encrypted Messaging & Personal Music (`social`):
1. Mạng xã hội Nội bộ (`WF19`, `PA-05`, `INV-04`, `SEC-01`):
   - Cửa ngõ truy cập: Anonymous -> 302/401, Guest / Member bị tạm khoá -> 403.
   - Bài viết 4 phạm vi (`PERSONAL`, `CUSTOM_GROUP`, `DEPARTMENT`, `CLUB`):
     + `PERSONAL`: duy nhất tác giả xem được; Chủ nhiệm/Admin/Trưởng ban khác đều nhận 403 & ẩn khỏi moderation.
     + `CUSTOM_GROUP`: duy nhất tác giả + `audience_users`.
     + `DEPARTMENT`: thành viên Ban sở hữu + kiểm duyệt viên đúng Ban; chặn chéo Ban `403`; Cán bộ đa Ban chéo vai vẫn tôn trọng quyền Ban sở hữu.
   - **Bất biến `PA-05` (Kiểm tra kép khi Chia sẻ/Repost):**
     + Thành viên đa Ban chia sẻ bài Nội bộ Ban Chuyên môn ra Toàn CLB -> người ngoài Ban (`truongban_kt`) thấy bài chia sẻ nhưng bị che hoàn toàn nội dung & tệp gốc (`shared_post_restricted=True`), và tải trực tiếp tệp gốc trả `403`.
     + Thành viên Ban Chuyên môn vẫn thấy đầy đủ bài gốc & tải được tệp.
   - An toàn tệp & ảnh (`SEC-01`):
     + Tái mã hoá PNG qua Pillow loại bỏ metadata ẩn (tEXt/EXIF), lưu ngoài `MEDIA_ROOT` tại `PRIVATE_VAULT_ROOT`, trả `X-Content-Type-Options: nosniff` + `Cache-Control: private, no-store`.
     + Chặn tệp `.svg`, `.html`, `.exe`, ảnh giả mạo byte rác & URL nội bộ (`127.0.0.1`, `javascript:`).
   - Bình luận phân cấp + `@mention` (chỉ nhắc nếu người được nhắc xem được bài!) + Cảm xúc + Xoá mềm.
   - Kiểm duyệt theo phạm vi + Sổ cái bất biến `SocialModerationLog` + Chặn tự bác bỏ báo cáo (`INV-03`).
   - Cố vấn Độc lập Hard Read-Only (`INV-04`): Xem `CLUB` OK (`200`), cấm 100% tạo bài/chia sẻ/bình luận/cảm xúc/báo cáo/kiểm duyệt (`403`).

2. Nhắn tin Nội bộ Mã hóa AES-256-GCM (`WF21`, `INV-05`, `BE-07`, `DB-08`, `PA-02`, `R03`, `SEC-07`):
   - Bản mã AES-256-GCM trong DB không chứa plaintext; `AuditLog` và `Notification.message` tuyệt đối không lưu plaintext tin nhắn; kiểm tra AAD chống tráo phòng/người gửi.
   - **`INV-05` Zero-Admin-Read & `R03`:** Chủ nhiệm, Admin Server, Cố vấn, Trưởng ban không thuộc hội thoại đều bị `403` trên Web & API & Attachment; `social/admin.py` không đăng ký bất kỳ model riêng tư nào.
   - Chống trùng cặp 1-1 (`DB-08`), nhóm Event/Task/Custom, tệp đính kèm vault.
   - Thu hồi tin nhắn trong 15 phút kèm ghi đè mật mã (`[RECALLED]`); quá 15 phút bị từ chối.
   - **Hook vòng đời `PA-02`:** Chuyển Ban -> tự động đặt `left_at` phòng chat Ban cũ (`403`), vào Ban mới (`200`); Tạm khoá -> thu hồi phòng chat (`403`); Khôi phục -> mở lại (`200`); Rời CLB -> rời toàn bộ kể cả 1-1 DM (`403`).
   - **Tố cáo `BE-07` kèm chữ ký `HMAC-SHA256`:** Nạn nhân tố cáo tin nhắn quấy rối -> Chủ nhiệm / Phó CN Nhân sự xác minh `hmac_valid=True` và xử lý kỷ luật nhưng VẪN bị `403` đọc hộp thư 1-1; giả mạo snapshot làm sai HMAC bị từ chối; chặn bên liên quan tự xử lý (`INV-03`).

3. Playlist Âm nhạc Cá nhân & Tặng nhạc (`BE-05`, `SEC-04`, `SEC-05`, `SEC-06`, `R07`, `INV-05`):
   - Playlist `PRIVATE` tuân thủ tuyệt đối `INV-05` (Chủ nhiệm & Admin Server nhận `403`); `CLUB_SHARED` xem chung nhưng chỉ chủ sở hữu sửa được.
   - Bộ phân tích URL ngoại tuyến (`SEC-05`): không gọi HTTP ra ngoài; hỗ trợ YouTube/Spotify/SoundCloud; chặn `127.0.0.1`, `169.254.169.254`, `10.0.0.1`, `localhost`, `javascript:`.
   - Tìm người nhận tặng nhạc chống trùng tên (`BE-05`, `SEC-04`, `SEC-06`): trả về tối đa `<= 10`, kèm `member_code` & `department_names`, ẩn hoàn toàn `email`/`phone`/`mssv`, và áp Rate Limit `429` vượt 30 req/phút.
   - Tặng nhạc + Thông báo + Lưu 1 chạm về Playlist riêng.
"""
from __future__ import annotations

import atexit
from datetime import timedelta
import io
import json
import os
import tempfile
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from django.conf import settings
from django.contrib import admin as django_admin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, PngImagePlugin

from accounts.models import AccountStatus, AuditLog, Role, User, UserProfile
from notifications.models import Notification, NotificationKind
from operations.models import ClubEventScope
from operations.services import create_and_assign_task, create_club_event
from organization.models import (
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    PositionCode,
    ScopeType,
)
from organization.services import (
    GovernanceError,
    bootstrap_organization_catalog,
    grant_delegated_permissions,
    mark_member_left_club,
    restore_club_member,
    suspend_club_member,
    transfer_member_department,
)

from .crypto import decrypt_message_text, unwrap_dek
from .models import (
    AbuseReportStatus,
    ChatMessage,
    Conversation,
    ConversationMember,
    ConversationType,
    MessageAbuseReport,
    MusicPlaylist,
    MusicProvider,
    PlaylistVisibility,
    SocialModerationAction,
    SocialModerationLog,
    SocialModerationStatus,
    SocialPost,
    SocialPostAttachment,
    SocialPostVisibility,
    SocialReactionType,
)
from .services import (
    add_social_comment,
    add_track_to_playlist,
    create_playlist,
    create_social_post,
    ensure_club_conversation,
    ensure_department_conversation,
    get_moderation_queue,
    get_or_create_direct_conversation,
    moderate_social_post,
    recall_chat_message,
    report_message_abuse,
    report_social_post,
    review_message_abuse_report,
    send_chat_message,
)

TEST_VAULT_TMPDIR = tempfile.TemporaryDirectory()
atexit.register(TEST_VAULT_TMPDIR.cleanup)


def _make_clean_png_bytes(with_text_chunk: bool = False) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (32, 32), color=(42, 128, 200))
    if with_text_chunk:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("Comment", "SECRET_EXIF_MARKER_KMG_999")
        img.save(buf, format="PNG", pnginfo=pnginfo)
    else:
        img.save(buf, format="PNG")
    return buf.getvalue()


@override_settings(PRIVATE_VAULT_ROOT=TEST_VAULT_TMPDIR.name)
class Phase4SocialBase(TestCase):
    def setUp(self):
        cache.clear()
        catalog = bootstrap_organization_catalog()
        self.dept_cm = catalog["departments"]["SPECIALTY"]
        self.dept_tt = catalog["departments"]["MEDIA_EVENT"]
        self.dept_kt = catalog["departments"]["TECHNICAL"]
        self.positions = catalog["positions"]
        self._seq = 900

        self.server_admin = self._make_user("p4_admin", "Admin Server P4", role=Role.ADMIN)
        self.chairman = self._make_member("p4_chair", "Chủ nhiệm KMG", self.dept_cm, "9001")
        Appointment.objects.create(
            user=self.chairman,
            position=self.positions[PositionCode.CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )

        # Phó CN Sự kiện (có club.social.moderate)
        self.vc_event = self._make_member("p4_vc_ev", "Phó CN Sự kiện", self.dept_tt, "9002")
        appt_vc_ev = Appointment.objects.create(
            user=self.vc_event,
            position=self.positions[PositionCode.VICE_CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )
        grant_delegated_permissions(
            self.server_admin,
            appt_vc_ev,
            GrantBundleCode.PORTFOLIO_EVENT,
            reason="Phụ trách truyền thông sự kiện P4",
        )

        # Phó CN Nhân sự (có club.member.suspend_temporary để duyệt BE-07)
        self.vc_hr = self._make_member("p4_vc_hr", "Phó CN Nhân sự", self.dept_cm, "9003")
        appt_vc_hr = Appointment.objects.create(
            user=self.vc_hr,
            position=self.positions[PositionCode.VICE_CHAIRMAN],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )
        grant_delegated_permissions(
            self.server_admin,
            appt_vc_hr,
            GrantBundleCode.PORTFOLIO_HR,
            reason="Phụ trách nhân sự kỷ luật P4",
        )

        # Cố vấn Độc lập Hard Read-Only (INV-04)
        self.advisor = self._make_user("p4_advisor", "Cố vấn Chuyên môn")
        Appointment.objects.create(
            user=self.advisor,
            position=self.positions[PositionCode.ADVISOR],
            scope_type=ScopeType.CLUB,
            appointed_by=self.server_admin,
        )

        # Trưởng ban CM (kiêm Thành viên thường Ban TT — đa ban chéo vai!)
        self.head_cm = self._make_member("p4_head_cm", "Trưởng ban CM", self.dept_cm, "9004")
        Appointment.objects.create(
            user=self.head_cm,
            position=self.positions[PositionCode.DEPT_HEAD],
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept_cm,
            appointed_by=self.server_admin,
        )
        DepartmentMembership.objects.create(
            user=self.head_cm, department=self.dept_tt, status=DeptMembershipStatus.ACTIVE
        )

        # Trưởng ban TT & Trưởng ban KT
        self.head_tt = self._make_member("p4_head_tt", "Trưởng ban TT", self.dept_tt, "9005")
        Appointment.objects.create(
            user=self.head_tt,
            position=self.positions[PositionCode.DEPT_HEAD],
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept_tt,
            appointed_by=self.server_admin,
        )
        self.head_kt = self._make_member("p4_head_kt", "Trưởng ban KT", self.dept_kt, "9006")
        Appointment.objects.create(
            user=self.head_kt,
            position=self.positions[PositionCode.DEPT_HEAD],
            scope_type=ScopeType.DEPARTMENT,
            department=self.dept_kt,
            appointed_by=self.server_admin,
        )

        # Thành viên đa ban (CM + KT) & thành viên CM
        self.member_multi = self._make_member("p4_multi", "Minh Quân Đa Ban", self.dept_cm, "9007")
        DepartmentMembership.objects.create(
            user=self.member_multi, department=self.dept_kt, status=DeptMembershipStatus.ACTIVE
        )
        self.member_cm = self._make_member("p4_mem_cm", "Mai Phương CM", self.dept_cm, "9008")
        self.member_tt = self._make_member("p4_mem_tt", "Ngọc Lan TT", self.dept_tt, "9009")

        # Guest & Suspended member
        self.guest = self._make_user("p4_guest", "Khách P4")
        self.suspended = self._make_member("p4_susp", "TV Tạm khoá P4", self.dept_kt, "9010")
        suspend_club_member(self.chairman, self.suspended, reason="Tạm khoá test P4")

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _make_user(self, username: str, full_name: str, *, role: str = Role.MEMBER) -> User:
        self._seq += 1
        u = User.objects.create_user(
            username=username,
            email=f"{username}@kmg.local",
            phone=f"0911{self._seq:06d}",
            mssv=f"B22DCCN{self._seq:03d}",
            full_name=full_name,
            display_name=full_name,
            password="Password123!",
            role=role,
            account_status=AccountStatus.ACTIVE,
            email_verified_at=timezone.now(),
        )
        UserProfile.objects.get_or_create(user=u)
        return u

    def _make_member(self, username: str, full_name: str, dept, code_suffix: str) -> User:
        u = self._make_user(username, full_name)
        ClubMembership.objects.create(
            user=u,
            member_code=f"KMG-2026-{code_suffix}",
            status=ClubMembershipStatus.ACTIVE,
        )
        DepartmentMembership.objects.create(
            user=u, department=dept, status=DeptMembershipStatus.ACTIVE
        )
        return u

    @staticmethod
    def _fresh(user: User) -> User:
        return User.objects.get(pk=user.pk)


class Phase4InternalSocialTests(Phase4SocialBase):
    def test_access_gates_guest_suspended_and_anonymous(self):
        resp_anon_web = self.client.get(reverse("social:feed"))
        self.assertEqual(resp_anon_web.status_code, 302)
        resp_anon_api = self.client.get("/api/v1/social/posts/")
        self.assertEqual(resp_anon_api.status_code, 401)

        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse("social:feed")).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/social/posts/").status_code, 403)

        # Thành viên đang bị SUSPENDED -> Middleware điều hướng về cổng trạng thái (302) và chặn API (403)
        self.client.force_login(self.suspended)
        resp_susp = self.client.get(reverse("social:feed"))
        self.assertEqual(resp_susp.status_code, 302)
        self.assertIn(reverse("accounts:membership_status"), resp_susp["Location"])
        self.assertEqual(self.client.get("/api/v1/social/posts/").status_code, 403)

    def test_personal_and_custom_group_strict_isolation(self):
        p_personal = create_social_post(
            self._fresh(self.member_cm),
            content="Nhật ký riêng tư cực kỳ bí mật #PersonalOnly",
            visibility=SocialPostVisibility.PERSONAL,
        )
        p_custom = create_social_post(
            self._fresh(self.member_cm),
            content="Bài nhóm hẹp CM + Đa Ban",
            visibility=SocialPostVisibility.CUSTOM_GROUP,
            audience_users=[self._fresh(self.member_multi)],
        )

        # Chủ nhiệm, Admin Server, Trưởng ban khác đều bị 403 khi xem PERSONAL hoặc CUSTOM_GROUP ngoài danh sách
        for outsider in (self.chairman, self.server_admin, self.head_kt, self.member_tt):
            self.client.force_login(outsider)
            self.assertEqual(
                self.client.get(reverse("social:post_detail", args=[p_personal.id])).status_code,
                403,
            )
            self.assertEqual(
                self.client.get(f"/api/v1/social/posts/{p_personal.id}/").status_code,
                403,
            )
            self.assertEqual(
                self.client.get(f"/api/v1/social/posts/{p_custom.id}/").status_code,
                403,
            )
            feed_payload = self.client.get("/api/v1/social/posts/").json()["data"]
            ids_seen = {item["id"] for item in feed_payload}
            self.assertNotIn(p_personal.id, ids_seen)
            self.assertNotIn(p_custom.id, ids_seen)

        # Tác giả xem PERSONAL OK; member_multi xem CUSTOM_GROUP OK
        self.client.force_login(self.member_cm)
        self.assertEqual(
            self.client.get(f"/api/v1/social/posts/{p_personal.id}/").status_code, 200
        )
        self.client.force_login(self.member_multi)
        self.assertEqual(
            self.client.get(f"/api/v1/social/posts/{p_custom.id}/").status_code, 200
        )

    def test_pa05_repost_dual_visibility_and_attachment_protection(self):
        png_data = _make_clean_png_bytes(with_text_chunk=True)
        uploaded_png = SimpleUploadedFile("stage_map.png", png_data, content_type="image/png")

        # 1. Tạo bài Nội bộ Ban Chuyên môn có tệp ảnh đính kèm & EXIF comment
        p_dept_cm = create_social_post(
            self._fresh(self.head_cm),
            content="Tài liệu Acoustic CM Internal Secret 2026",
            visibility=SocialPostVisibility.DEPARTMENT,
            department=self.dept_cm,
            attachments=[uploaded_png],
        )
        att = SocialPostAttachment.objects.get(post=p_dept_cm)
        # File lưu ngoài MEDIA_ROOT & nằm trong PRIVATE_VAULT_ROOT + Pillow đã bóc tEXt
        self.assertIn(os.path.abspath(settings.PRIVATE_VAULT_ROOT), os.path.abspath(att.file.path))
        self.assertNotIn(os.path.abspath(settings.MEDIA_ROOT), os.path.abspath(att.file.path))
        reopened = Image.open(att.file.path)
        self.assertNotIn("SECRET_EXIF_MARKER_KMG_999", json.dumps(reopened.info))
        reopened.close()

        # 2. Thành viên đa Ban chia sẻ bài CM ra phạm vi Toàn CLB (`CLUB`)
        repost = create_social_post(
            self._fresh(self.member_multi),
            content="Mời anh em cổ vũ tiết mục sắp tới nhé!",
            visibility=SocialPostVisibility.CLUB,
            shared_post=p_dept_cm,
        )

        # 3. Trưởng ban Kỹ thuật (không thuộc CM) xem được bài chia sẻ nhưng bị che 100% gốc (`PA-05`)
        self.client.force_login(self.head_kt)
        api_detail = self.client.get(f"/api/v1/social/posts/{repost.id}/")
        self.assertEqual(api_detail.status_code, 200)
        data = api_detail.json()["data"]
        self.assertTrue(data["shared_post_restricted"])
        self.assertIsNone(data["shared_post_data"])
        self.assertIn("giới hạn", data["shared_post_placeholder"])
        self.assertNotIn("Acoustic CM Internal Secret", api_detail.content.decode("utf-8"))

        # Và không được lách luật bằng cách tải thẳng ID tệp ảnh gốc!
        self.assertEqual(
            self.client.get(reverse("social:attachment_download", args=[att.id])).status_code, 403
        )
        self.assertEqual(
            self.client.get(f"/api/v1/social/attachments/{att.id}/download/").status_code, 403
        )

        # Giao diện Web của head_kt cũng che gốc
        web_repost = self.client.get(reverse("social:post_detail", args=[repost.id]))
        self.assertEqual(web_repost.status_code, 200)
        self.assertNotIn("Acoustic CM Internal Secret", web_repost.content.decode("utf-8"))

        # 4. Thành viên Ban CM xem đầy đủ cả phần chia sẻ gốc lẫn tải tệp an toàn (`nosniff`, `private, no-store`)
        self.client.force_login(self.member_cm)
        cm_detail = self.client.get(f"/api/v1/social/posts/{repost.id}/").json()["data"]
        self.assertFalse(cm_detail["shared_post_restricted"])
        self.assertEqual(cm_detail["shared_post_data"]["id"], p_dept_cm.id)
        self.assertIn("Acoustic CM Internal Secret", cm_detail["shared_post_data"]["content"])

        dl = self.client.get(reverse("social:attachment_download", args=[att.id]))
        self.assertEqual(dl.status_code, 200)
        self.assertEqual(dl["X-Content-Type-Options"], "nosniff")
        self.assertEqual(dl["Cache-Control"], "private, no-store")

        # 5. Không được chia sẻ bài PERSONAL
        p_priv = create_social_post(
            self._fresh(self.member_cm),
            content="Ghi chú riêng",
            visibility=SocialPostVisibility.PERSONAL,
        )
        with self.assertRaises(GovernanceError):
            create_social_post(
                self._fresh(self.member_cm),
                content="Share private",
                visibility=SocialPostVisibility.CLUB,
                shared_post=p_priv,
            )

    def test_upload_validation_and_dangerous_urls(self):
        bad_svg = SimpleUploadedFile("xss.svg", b"<svg onload=alert(1)></svg>", content_type="image/svg+xml")
        with self.assertRaises(GovernanceError):
            create_social_post(
                self._fresh(self.member_cm),
                content="Bad attachment",
                attachments=[bad_svg],
            )
        spoofed_png = SimpleUploadedFile("fake.png", b"NOT_A_REAL_PNG_AT_ALL", content_type="image/png")
        with self.assertRaises(GovernanceError):
            create_social_post(
                self._fresh(self.member_cm),
                content="Spoofed png",
                attachments=[spoofed_png],
            )
        with self.assertRaises(GovernanceError):
            create_social_post(
                self._fresh(self.member_cm),
                content="Local SSRF url",
                link_url="http://127.0.0.1:8000/secret",
            )

    def test_comments_mentions_reactions_and_soft_delete(self):
        p_cm = create_social_post(
            self._fresh(self.member_cm),
            content="Lịch tập CM tối nay",
            visibility=SocialPostVisibility.DEPARTMENT,
            department=self.dept_cm,
        )
        # Nhắc @p4_head_kt (người ngoài Ban CM) -> KHÔNG gửi notification leak; @p4_head_cm -> CÓ gửi!
        c1 = add_social_comment(
            self._fresh(self.member_multi),
            p_cm,
            content="Nhờ @p4_head_cm và @p4_head_kt xem qua nhé!",
        )
        self.assertEqual(
            list(c1.mentioned_users.values_list("username", flat=True)),
            ["p4_head_cm"],
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.head_cm, kind=NotificationKind.SOCIAL_INTERACTION
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                user=self.head_kt, kind=NotificationKind.SOCIAL_INTERACTION
            ).exists()
        )

        # Phản hồi phân cấp + cảm xúc + soft-delete qua API
        self.client.force_login(self.member_cm)
        r_reply = self.client.post(
            f"/api/v1/social/posts/{p_cm.id}/comments/",
            data=json.dumps({"content": "Đã rõ cảm ơn!", "parent_id": c1.id}),
            content_type="application/json",
        )
        self.assertEqual(r_reply.status_code, 201)
        r_react = self.client.post(
            f"/api/v1/social/posts/{p_cm.id}/react/",
            data=json.dumps({"reaction_type": SocialReactionType.FIRE}),
            content_type="application/json",
        )
        self.assertEqual(r_react.status_code, 200)
        self.assertTrue(r_react.json()["data"]["active"])

        r_del = self.client.delete(f"/api/v1/social/posts/{p_cm.id}/")
        self.assertEqual(r_del.status_code, 200)
        p_cm.refresh_from_db()
        self.assertTrue(p_cm.is_deleted)

    def test_scoped_moderation_immutable_ledger_and_inv03(self):
        p_cm = create_social_post(
            self._fresh(self.member_cm),
            content="Bài Ban CM cần kiểm duyệt",
            visibility=SocialPostVisibility.DEPARTMENT,
            department=self.dept_cm,
        )
        p_tt = create_social_post(
            self._fresh(self.member_tt),
            content="Bài Ban TT cần kiểm duyệt",
            visibility=SocialPostVisibility.DEPARTMENT,
            department=self.dept_tt,
        )
        p_club = create_social_post(
            self._fresh(self.member_multi),
            content="Bài Toàn CLB cần kiểm duyệt",
            visibility=SocialPostVisibility.CLUB,
        )

        rep_cm = report_social_post(self._fresh(self.member_multi), p_cm, "Nội dung chưa chuẩn Ban CM")
        rep_tt = report_social_post(self._fresh(self.head_cm), p_tt, "Nội dung chưa chuẩn Ban TT")
        rep_club = report_social_post(self._fresh(self.member_cm), p_club, "Spam ở Toàn CLB")

        # Trưởng ban CM (dù đồng thời là TV Ban TT) CHỈ thấy rep_cm trong moderation queue!
        cm_queue = get_moderation_queue(self._fresh(self.head_cm))
        self.assertEqual([r.id for r in cm_queue], [rep_cm.id])

        # Trưởng ban CM KHÔNG được kiểm duyệt bài Ban TT hoặc Toàn CLB
        with self.assertRaises(PermissionDenied):
            moderate_social_post(self._fresh(self.head_cm), p_tt, action=SocialModerationAction.HIDE, report=rep_tt)
        with self.assertRaises(PermissionDenied):
            moderate_social_post(self._fresh(self.head_cm), p_club, action=SocialModerationAction.HIDE, report=rep_club)

        # Trưởng ban CM kiểm duyệt hợp lệ bài Ban CM -> Tạo ledger bất biến
        mod_log = moderate_social_post(
            self._fresh(self.head_cm),
            p_cm,
            action=SocialModerationAction.HIDE,
            note="Ẩn do sai quy chuẩn Ban",
            report=rep_cm,
        )
        p_cm.refresh_from_db()
        self.assertEqual(p_cm.moderation_status, SocialModerationStatus.HIDDEN)
        with self.assertRaises(ValueError):
            mod_log.note = "Cố tình sửa"
            mod_log.save()
        with self.assertRaises(ValueError):
            mod_log.delete()

        # Phó CN Sự kiện có `club.social.moderate` -> chỉ thấy rep_club trong queue
        self.client.force_login(self.vc_event)
        q_api = self.client.get("/api/v1/social/moderation/queue/").json()["data"]
        self.assertEqual([item["id"] for item in q_api], [rep_club.id])
        res_mod = self.client.post(
            f"/api/v1/social/posts/{p_club.id}/moderate/",
            data=json.dumps({"action": SocialModerationAction.HIDE, "note": "Vi phạm nội quy CLB", "report_id": rep_club.id}),
            content_type="application/json",
        )
        self.assertEqual(res_mod.status_code, 200)

        # INV-03: Không thể tự giữ/bác bỏ báo cáo đối với bài của chính mình
        p_head = create_social_post(
            self._fresh(self.head_cm),
            content="Bài của chính Trưởng ban CM",
            visibility=SocialPostVisibility.DEPARTMENT,
            department=self.dept_cm,
        )
        rep_self = report_social_post(self._fresh(self.member_cm), p_head, "Thắc mắc nội dung")
        with self.assertRaises(PermissionDenied):
            moderate_social_post(
                self._fresh(self.head_cm),
                p_head,
                action=SocialModerationAction.DISMISS,
                report=rep_self,
            )

    def test_advisor_hard_read_only_social_inv04(self):
        p_club = create_social_post(
            self._fresh(self.member_cm),
            content="Tin sinh hoạt chung CLB",
            visibility=SocialPostVisibility.CLUB,
        )
        self.client.force_login(self.advisor)
        # Cố vấn xem được bảng tin CLB
        self.assertEqual(self.client.get(reverse("social:feed")).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/social/posts/{p_club.id}/").status_code, 200)

        # Nhưng MỌI thao tác ghi đều trả 403!
        self.assertEqual(
            self.client.post(
                "/api/v1/social/posts/",
                data=json.dumps({"content": "Cố vấn đăng thử", "visibility": "CLUB"}),
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/social/posts/{p_club.id}/comments/",
                data=json.dumps({"content": "Bình luận thử"}),
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/social/posts/{p_club.id}/react/",
                data=json.dumps({"reaction_type": "LIKE"}),
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/social/posts/{p_club.id}/report/",
                data=json.dumps({"reason": "Báo cáo thử"}),
                content_type="application/json",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/v1/social/moderation/queue/").status_code, 403
        )


class Phase4EncryptedMessagingTests(Phase4SocialBase):
    def test_aes256_gcm_db_zero_plaintext_and_aad_integrity(self):
        conv_dm = get_or_create_direct_conversation(
            self._fresh(self.member_cm), self._fresh(self.member_multi)
        )
        secret_text = "MaBiMatNoiBo_AES256GCM_Test_7788"
        msg = send_chat_message(
            self._fresh(self.member_cm), conv_dm, plaintext=secret_text
        )

        # 1. CSDL, AuditLog và Notification TUYỆT ĐỐI không lưu plaintext (`WF21`)
        self.assertNotIn(secret_text.encode("utf-8"), bytes(msg.ciphertext))
        self.assertFalse(
            AuditLog.objects.filter(
                Q(action__icontains=secret_text)
                | Q(target__icontains=secret_text)
                | Q(note__icontains=secret_text)
            ).exists()
        )
        self.assertFalse(Notification.objects.filter(message__icontains=secret_text).exists())

        # 2. Giải mã thành công với đúng DEK + AAD `(conv_id, sender_id)`
        dek = unwrap_dek(conv_dm.encrypted_dek)
        self.assertEqual(
            decrypt_message_text(
                dek=dek,
                iv_nonce=msg.iv_nonce,
                ciphertext=msg.ciphertext,
                conversation_id=conv_dm.id,
                sender_id=self.member_cm.id,
            ),
            secret_text,
        )

        # 3. Tráo AAD `sender_id` hoặc `conversation_id` thất bại giải mã (`InvalidTag`)
        with self.assertRaises(InvalidTag):
            decrypt_message_text(
                dek=dek,
                iv_nonce=msg.iv_nonce,
                ciphertext=msg.ciphertext,
                conversation_id=conv_dm.id,
                sender_id=self.member_multi.id,
            )

        # 4. DB-08 chống trùng cặp 1-1 ngược chiều
        conv_dm_rev = get_or_create_direct_conversation(
            self._fresh(self.member_multi), self._fresh(self.member_cm)
        )
        self.assertEqual(conv_dm.id, conv_dm_rev.id)

    def test_zero_admin_read_inv05_and_django_admin_isolation_r03(self):
        # R03: Django Admin KHÔNG đăng ký bất kỳ model riêng tư nào của `social`
        for model_cls in (Conversation, ConversationMember, ChatMessage, MusicPlaylist):
            self.assertNotIn(model_cls, django_admin.site._registry)

        conv_dm = get_or_create_direct_conversation(
            self._fresh(self.member_cm), self._fresh(self.member_tt)
        )
        png = SimpleUploadedFile("chat_img.png", _make_clean_png_bytes(), content_type="image/png")
        msg = send_chat_message(
            self._fresh(self.member_cm), conv_dm, plaintext="Tin nhắn riêng tư 1-1", attachment_file=png
        )
        att = msg.attachments.first()

        # Chủ nhiệm, Admin Server, Cố vấn, Trưởng ban ĐỀU nhận 403!
        for outsider in (self.chairman, self.server_admin, self.advisor, self.head_cm):
            self.client.force_login(outsider)
            self.assertEqual(
                self.client.get(reverse("social:conversation_detail", args=[conv_dm.id])).status_code,
                403,
            )
            self.assertEqual(
                self.client.get(f"/api/v1/messages/conversations/{conv_dm.id}/messages/").status_code,
                403,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/v1/messages/conversations/{conv_dm.id}/messages/",
                    data=json.dumps({"plaintext": "Đọc/gửi lén"}),
                    content_type="application/json",
                ).status_code,
                403,
            )
            self.assertEqual(
                self.client.get(reverse("social:chat_attachment_download", args=[att.id])).status_code,
                403,
            )

    def test_recall_window_and_cryptographic_wipe(self):
        conv_dm = get_or_create_direct_conversation(
            self._fresh(self.member_cm), self._fresh(self.member_multi)
        )
        secret_msg = "Tin nhan se bi thu hoi mat ma"
        m1 = send_chat_message(self._fresh(self.member_cm), conv_dm, plaintext=secret_msg)

        # Người khác không thu hồi được tin của tôi
        with self.assertRaises(PermissionDenied):
            recall_chat_message(self._fresh(self.member_multi), m1)

        # Thu hồi trong 15 phút qua API
        self.client.force_login(self.member_cm)
        res = self.client.post(f"/api/v1/messages/{m1.id}/recall/")
        self.assertEqual(res.status_code, 200)
        m1.refresh_from_db()
        self.assertTrue(m1.is_recalled)

        # Bản mã trong DB đã bị ghi đè, không giải mã được ra text gốc nữa!
        dek = unwrap_dek(conv_dm.encrypted_dek)
        self.assertEqual(
            decrypt_message_text(
                dek=dek,
                iv_nonce=m1.iv_nonce,
                ciphertext=m1.ciphertext,
                conversation_id=conv_dm.id,
                sender_id=self.member_cm.id,
            ),
            "[RECALLED]",
        )

        # Quá 15 phút bị chặn
        m2 = send_chat_message(self._fresh(self.member_cm), conv_dm, plaintext="Tin quá hạn thu hồi")
        ChatMessage.objects.filter(pk=m2.pk).update(
            created_at=timezone.now() - timedelta(minutes=16)
        )
        m2.refresh_from_db()
        with self.assertRaises(GovernanceError):
            recall_chat_message(self._fresh(self.member_cm), m2)

    def test_pa02_lifecycle_auto_leave_on_transfer_suspend_restore_leave(self):
        conv_club = ensure_club_conversation(created_by=self._fresh(self.chairman))
        conv_cm = ensure_department_conversation(self.dept_cm, created_by=self._fresh(self.head_cm))
        conv_tt = ensure_department_conversation(self.dept_tt, created_by=self._fresh(self.head_tt))
        conv_dm = get_or_create_direct_conversation(
            self._fresh(self.member_cm), self._fresh(self.member_multi)
        )

        # 1. Chuyển Ban (CM -> TT): Tự động rời chat Ban CM (`403`) & gia nhập chat Ban TT (`200`)
        transfer_member_department(
            self._fresh(self.chairman),
            self._fresh(self.member_cm),
            self.dept_cm,
            self.dept_tt,
            note="Điều chuyển nhân sự Test PA-02",
        )
        self.client.force_login(self.member_cm)
        self.assertEqual(
            self.client.get(f"/api/v1/messages/conversations/{conv_cm.id}/messages/").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/messages/conversations/{conv_tt.id}/messages/").status_code,
            200,
        )

        # 2. Tạm khoá thành viên -> Thu hồi quyền khỏi phòng chat CLB/Ban (`403`)
        suspend_club_member(
            self._fresh(self.chairman), self._fresh(self.member_cm), reason="Tạm khoá test PA-02"
        )
        self.client.force_login(self.member_cm)
        self.assertEqual(
            self.client.get(f"/api/v1/messages/conversations/{conv_club.id}/messages/").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/messages/conversations/{conv_dm.id}/messages/").status_code,
            403,
        )

        # 3. Khôi phục -> Kích hoạt lại chat CLB & Ban mới TT
        restore_club_member(
            self._fresh(self.chairman), self._fresh(self.member_cm), reason="Mở khoá sau kỷ luật"
        )
        self.client.force_login(self.member_cm)
        self.assertEqual(
            self.client.get(f"/api/v1/messages/conversations/{conv_tt.id}/messages/").status_code,
            200,
        )

        # 4. Rời CLB -> `left_at` đặt cho TẤT CẢ hội thoại kể cả DM 1-1
        mark_member_left_club(
            self._fresh(self.chairman), self._fresh(self.member_cm), reason="Tốt nghiệp ra trường"
        )
        dm_mem = ConversationMember.objects.get(conversation=conv_dm, user=self.member_cm)
        self.assertIsNotNone(dm_mem.left_at)
        self.client.force_login(self.member_cm)
        self.assertEqual(
            self.client.get(f"/api/v1/messages/conversations/{conv_dm.id}/messages/").status_code,
            403,
        )

    def test_be07_message_abuse_report_hmac_without_backdoor(self):
        conv_dm = get_or_create_direct_conversation(
            self._fresh(self.member_cm), self._fresh(self.member_multi)
        )
        benign_secret = "Chuyện riêng vô hại trước đó 12345"
        abusive_msg_text = "Nội dung xúc phạm cần BCN xử lý XYZ"
        send_chat_message(self._fresh(self.member_cm), conv_dm, plaintext=benign_secret)
        bad_msg = send_chat_message(
            self._fresh(self.member_multi), conv_dm, plaintext=abusive_msg_text
        )

        # Nạn nhân gửi báo cáo BE-07
        report = report_message_abuse(
            self._fresh(self.member_cm), bad_msg, reason="Lời lẽ công kích cá nhân"
        )

        # Phó CN Nhân sự xem báo cáo có chữ ký HMAC hợp lệ, nhưng TUYỆT ĐỐI KHÔNG đọc được hộp thư 1-1!
        self.client.force_login(self.vc_hr)
        api_rep = self.client.get("/api/v1/messages/abuse-reports/")
        self.assertEqual(api_rep.status_code, 200)
        rep_items = api_rep.json()["data"]
        self.assertEqual(len(rep_items), 1)
        self.assertTrue(rep_items[0]["hmac_valid"])
        self.assertEqual(rep_items[0]["verified_plaintext_snapshot"], abusive_msg_text)

        # Vẫn bị 403 đọc hộp thư 1-1 và không hề thấy benign_secret
        self.assertEqual(
            self.client.get(f"/api/v1/messages/conversations/{conv_dm.id}/messages/").status_code,
            403,
        )

        # Giả mạo snapshot trong DB khiến HMAC sai -> từ chối xử lý (`HMAC_INVALID`)
        MessageAbuseReport.objects.filter(pk=report.pk).update(
            verified_plaintext_snapshot="Nội dung bị sửa lén"
        )
        report.refresh_from_db()
        with self.assertRaises(GovernanceError) as ctx:
            review_message_abuse_report(
                self._fresh(self.vc_hr), report, status=AbuseReportStatus.ACTION_TAKEN
            )
        self.assertEqual(ctx.exception.code, "HMAC_INVALID")

        # Khôi phục snapshot chuẩn & Phó CN Nhân sự kết luận thành công
        MessageAbuseReport.objects.filter(pk=report.pk).update(
            verified_plaintext_snapshot=abusive_msg_text
        )
        report.refresh_from_db()
        review_message_abuse_report(
            self._fresh(self.vc_hr),
            report,
            status=AbuseReportStatus.ACTION_TAKEN,
            resolution_note="Đã nhắc nhở kỷ luật cảnh cáo.",
        )
        self.assertEqual(report.status, AbuseReportStatus.ACTION_TAKEN)

        # INV-03: Nếu Chủ nhiệm là người bị tố cáo trong DM thì chính Chủ nhiệm bị 403 xử lý
        conv_chair = get_or_create_direct_conversation(
            self._fresh(self.chairman), self._fresh(self.member_tt)
        )
        m_chair = send_chat_message(self._fresh(self.chairman), conv_chair, plaintext="Test msg")
        rep_chair = report_message_abuse(
            self._fresh(self.member_tt), m_chair, reason="Kiểm tra INV-03"
        )
        with self.assertRaises(PermissionDenied):
            review_message_abuse_report(
                self._fresh(self.chairman), rep_chair, status=AbuseReportStatus.DISMISSED
            )

    def test_event_and_task_room_access_control(self):
        ce = create_club_event(
            actor=self._fresh(self.head_cm),
            lead_department=self.dept_cm,
            name="Showcase KMG P4",
            location="Hội trường A",
            starts_at=timezone.now() + timedelta(days=7),
            ends_at=timezone.now() + timedelta(days=7, hours=2),
            event_scope=ClubEventScope.DEPT_INTERNAL,
        )
        # Thành viên ngoài Ban CM chưa tham gia sự kiện -> 403 tạo phòng chat sự kiện
        self.client.force_login(self.member_tt)
        self.assertEqual(
            self.client.post(
                "/api/v1/messages/conversations/",
                data=json.dumps({"conv_type": "EVENT", "club_event_id": ce.id}),
                content_type="application/json",
            ).status_code,
            403,
        )
        # Trưởng ban phụ trách -> 201 tạo phòng chat sự kiện
        self.client.force_login(self.head_cm)
        self.assertEqual(
            self.client.post(
                "/api/v1/messages/conversations/",
                data=json.dumps({"conv_type": "EVENT", "club_event_id": ce.id}),
                content_type="application/json",
            ).status_code,
            201,
        )

        # Task room
        task = create_and_assign_task(
            actor=self._fresh(self.head_cm),
            department=self.dept_cm,
            title="Chuẩn bị loa kiểm âm",
            deadline=timezone.now() + timedelta(days=2),
            assignees=[self._fresh(self.member_cm)],
        )
        self.client.force_login(self.member_cm)
        self.assertEqual(
            self.client.post(
                "/api/v1/messages/conversations/",
                data=json.dumps({"conv_type": "TASK", "task_id": task.id}),
                content_type="application/json",
            ).status_code,
            201,
        )


class Phase4MusicPlaylistAndGiftingTests(Phase4SocialBase):
    def test_private_playlist_inv05_strict_isolation(self):
        pl_priv = create_playlist(
            self._fresh(self.member_cm),
            title="Nhạc Ngủ Riêng Tư",
            visibility=PlaylistVisibility.PRIVATE,
        )
        add_track_to_playlist(
            self._fresh(self.member_cm),
            pl_priv,
            track_url="https://www.youtube.com/watch?v=jfKfPfyJRdk",
            title="Lofi Study",
        )
        pl_shared = create_playlist(
            self._fresh(self.member_cm),
            title="Setlist CLB KMG",
            visibility=PlaylistVisibility.CLUB_SHARED,
        )

        # INV-05: Chủ nhiệm, Admin Server, Cố vấn, bạn khác ĐỀU bị 403 trên playlist PRIVATE!
        for outsider in (self.chairman, self.server_admin, self.advisor, self.member_tt):
            self.client.force_login(outsider)
            self.assertEqual(
                self.client.get(reverse("social:playlist_detail", args=[pl_priv.id])).status_code,
                403,
            )
            self.assertEqual(
                self.client.get(f"/api/v1/music/playlists/{pl_priv.id}/").status_code, 403
            )
            # CLUB_SHARED xem được (200)
            self.assertEqual(
                self.client.get(f"/api/v1/music/playlists/{pl_shared.id}/").status_code, 200
            )
            # Nhưng không ai ngoài owner sửa được CLUB_SHARED
            self.assertEqual(
                self.client.patch(
                    f"/api/v1/music/playlists/{pl_shared.id}/",
                    data=json.dumps({"title": "Đổi tên lén"}),
                    content_type="application/json",
                ).status_code,
                403,
            )

        # Chính chủ xem sửa được 200
        self.client.force_login(self.member_cm)
        self.assertEqual(
            self.client.get(f"/api/v1/music/playlists/{pl_priv.id}/").status_code, 200
        )

    def test_offline_url_parser_and_ssrf_guard_sec05(self):
        pl = create_playlist(self._fresh(self.member_cm), title="Test SEC-05")
        with patch("urllib.request.urlopen", side_effect=AssertionError("Không được gọi HTTP ra ngoài!")):
            it_yt = add_track_to_playlist(
                self._fresh(self.member_cm),
                pl,
                track_url="https://youtu.be/5qap5aO4i9A",
                title="YT Short",
            )
            self.assertEqual(it_yt.source_provider, MusicProvider.YOUTUBE)
            self.assertEqual(it_yt.external_track_id, "5qap5aO4i9A")

            it_sp = add_track_to_playlist(
                self._fresh(self.member_cm),
                pl,
                track_url="https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp",
                title="Spotify Track",
            )
            self.assertEqual(it_sp.source_provider, MusicProvider.SPOTIFY)

        # Chặn mọi địa chỉ SSRF / nội bộ / javascript
        for bad_url in (
            "http://127.0.0.1:6379/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/internal",
            "http://localhost:8000/admin/",
            "javascript:alert(1)",
        ):
            with self.assertRaises(GovernanceError):
                add_track_to_playlist(
                    self._fresh(self.member_cm), pl, track_url=bad_url, title="SSRF Bad"
                )

    def test_disambiguation_search_zero_pii_cap10_rate_limit_and_gifting(self):
        # Tạo 12 thành viên trùng họ tên để kiểm tra chống nhầm tên BE-05, ẩn PII SEC-04 & giới hạn <= 10
        for idx in range(1, 13):
            dept = self.dept_cm if idx % 2 == 0 else self.dept_kt
            self._make_member(f"dup_ma_{idx}", "Nguyễn Minh Anh", dept, f"85{idx:02d}")

        self.client.force_login(self.member_cm)
        r = self.client.get("/api/v1/music/recipients/search/?q=Nguyễn Minh Anh")
        self.assertEqual(r.status_code, 200)
        results = r.json()["data"]
        self.assertLessEqual(len(results), 10)
        self.assertEqual(len(results), 10)
        first = results[0]
        self.assertEqual(
            set(first.keys()),
            {"id", "member_code", "public_name", "avatar_url", "department_names"},
        )
        self.assertNotIn("email", first)
        self.assertNotIn("phone", first)
        self.assertNotIn("mssv", first)

        # Gửi tặng bài hát cho 1 người nhận đích danh qua API -> Lưu 1 chạm về Playlist riêng
        target_id = results[0]["id"]
        r_gift = self.client.post(
            "/api/v1/music/shares/",
            data=json.dumps(
                {
                    "recipient_user_id": target_id,
                    "track_url": "https://www.youtube.com/watch?v=jfKfPfyJRdk",
                    "title": "Thanh Âm Acoustic",
                    "personal_message": "Chúc biểu diễn thật tự tin!",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r_gift.status_code, 201)
        share_id = r_gift.json()["data"]["id"]

        target_user = User.objects.get(pk=target_id)
        self.assertTrue(
            Notification.objects.filter(
                user=target_user, kind=NotificationKind.MUSIC_SHARE
            ).exists()
        )

        # Người ngoài không được lưu hộ quà của target_user
        self.client.force_login(self.member_multi)
        self.assertEqual(
            self.client.post(f"/api/v1/music/shares/{share_id}/save/").status_code, 403
        )

        # Chủ quà lưu 1 chạm vào playlist của chính mình
        self.client.force_login(target_user)
        r_save = self.client.post(f"/api/v1/music/shares/{share_id}/save/")
        self.assertEqual(r_save.status_code, 200)
        self.assertTrue(MusicPlaylist.objects.filter(owner=target_user).exists())

        # SEC-06 Rate limit: 30 req/phút trong search (nhớ cache đã reset ở setUp, vừa gọi 1 lần -> 29 lần OK, lần thứ 31 trả 429)
        self.client.force_login(self.member_cm)
        for _ in range(29):
            ok_r = self.client.get("/api/v1/music/recipients/search/?q=Minh")
            self.assertEqual(ok_r.status_code, 200)
        limited_r = self.client.get("/api/v1/music/recipients/search/?q=Minh")
        self.assertEqual(limited_r.status_code, 429)
        self.assertEqual(limited_r.json()["error"]["code"], "RATE_LIMITED")


class Phase4PortalSmokeTests(Phase4SocialBase):
    def test_web_views_and_flows_render_cleanly_for_member_hr_and_advisor(self):
        ensure_club_conversation(created_by=self._fresh(self.chairman))
        conv_cm = ensure_department_conversation(self.dept_cm, created_by=self._fresh(self.head_cm))
        p_club = create_social_post(
            self._fresh(self.member_cm),
            content="Bài viết smoke test giao diện",
            visibility=SocialPostVisibility.CLUB,
        )
        pl = create_playlist(
            self._fresh(self.member_cm),
            title="Playlist Smoke",
            visibility=PlaylistVisibility.CLUB_SHARED,
        )

        # 1. Thành viên chính thức
        self.client.force_login(self.member_cm)
        for url in (
            reverse("organization:workspace_home"),
            reverse("accounts:profile"),
            reverse("social:feed"),
            reverse("social:post_detail", args=[p_club.id]),
            reverse("social:messaging_inbox"),
            reverse("social:conversation_detail", args=[conv_cm.id]),
            reverse("social:music_hub"),
            reverse("social:playlist_detail", args=[pl.id]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, f"GET {url} failed for member")

        # Kiểm tra luồng rời hội thoại tự nguyện
        self.assertEqual(
            self.client.post(f"/api/v1/messages/conversations/{conv_cm.id}/leave/").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(reverse("social:conversation_detail", args=[conv_cm.id])).status_code,
            403,
        )

        # 2. Phó CN Nhân sự xem trang báo cáo vi phạm `BE-07`
        self.client.force_login(self.vc_hr)
        self.assertEqual(self.client.get(reverse("social:abuse_reports")).status_code, 200)

        # 3. Cố vấn (`INV-04`): /workspace/ chuyển về /workspace/giam-sat/, các cổng xã hội/nhạc đọc 200 & ghi 403
        self.client.force_login(self.advisor)
        r_ws = self.client.get(reverse("organization:workspace_home"))
        self.assertEqual(r_ws.status_code, 302)
        self.assertIn(reverse("organization:advisor_overview"), r_ws["Location"])
        for url in (
            reverse("organization:advisor_overview"),
            reverse("accounts:profile"),
            reverse("social:feed"),
            reverse("social:messaging_inbox"),
            reverse("social:music_hub"),
            reverse("social:playlist_detail", args=[pl.id]),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, f"GET {url} failed for advisor")

        self.assertEqual(self.client.get(reverse("social:abuse_reports")).status_code, 403)
        self.assertEqual(
            self.client.post(
                reverse("social:music_hub"),
                {"action": "create_playlist", "title": "Cố vấn tạo thử"},
            ).status_code,
            403,
        )
