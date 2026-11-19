"""
Lệnh khởi tạo dữ liệu chuẩn & đa Persona cho KMG Club Management Platform (Phase 1 & Phase 2).

Chạy idempotent (chạy nhiều lần liên tiếp vẫn an toàn 100%):
    python manage.py seed_kmg

Bao phủ toàn bộ các nhóm vai trò theo Ma trận Phân quyền Chuẩn `D04 v1.2` và dữ liệu vận hành Phase 2:
- Admin Server (`admin` — tài khoản quản trị hạ tầng duy nhất có đặc quyền nâng cấp Chủ nhiệm / Phó CN / Trưởng ban / Cố vấn),
- Chủ nhiệm (`chunhiem`), Phó CN Mảng Nhân sự (`phocn_nhansu`), Phó CN Mảng Sự kiện (`phocn_sukien`),
- Cố vấn Độc lập Read-Only (`covan`),
- Trưởng ban Chuyên môn kiêm Thành viên thường Ban Truyền thông (`truongban_cm` — đa ban chéo vai!),
- Trưởng ban Truyền thông (`truongban_tt`), Trưởng ban Kỹ thuật Demo (`truongban_kt`),
- Phó ban Chuyên môn Đã ủy quyền (`phoban_cm_uyquyen`) vs Mặc định chưa ủy quyền (`phoban_cm_macdinh`),
- Thành viên đa Ban có Skill Guitar (`thanhvien_daban`) vs Thành viên không có Skill Guitar nhưng được cấp ACL (`thanhvien_khong_guitar`),
- Thành viên tạm khoá (`thanhvien_tamkhoa`), Ứng viên Guest (`ungvien_guest`), và Khách mới xác minh OTP (`khach_moi`).
- Phase 2: Công việc nhóm `ALL_ASSIGNEES`, bài nộp + `TaskReview` bất biến, Sự kiện Kép 3 cấp (`DEPT_INTERNAL`, `CLUB_WIDE` chờ RSVP, `PUBLIC_SHOW`) phối hợp liên Ban, Thông báo chính thức CLB và Hồ sơ cảnh báo chuyên cần mẫu.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import AccountStatus, Role, User, UserProfile
from events.models import Event, EventCategory, EventStatus, EventVisibility
from organization.models import (
    ApplicationStatus,
    Appointment,
    ClubMembership,
    ClubMembershipStatus,
    DepartmentMembership,
    DeptMembershipStatus,
    GrantBundleCode,
    LifecycleEventType,
    MembershipApplication,
    PermissionGrant,
    PositionCode,
    ResourceAccessRule,
    ResourceClassification,
    ScopeType,
    Skill,
    SkillProficiency,
)
from organization.services import (
    add_member_to_department,
    appoint_officer,
    approve_club_member,
    bootstrap_organization_catalog,
    declare_user_skill,
    grant_delegated_permissions,
    record_lifecycle_event,
    submit_membership_application,
    suspend_club_member,
    verify_user_skill,
)

DEMO_PASSWORD = "Kmg@2026!"


class Command(BaseCommand):
    help = "Khởi tạo idempotent dữ liệu tổ chức, phân quyền D04 v1.1 và sự kiện mẫu cho KMG Platform."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_SEED:
            raise CommandError("Dữ liệu demo bị tắt. Dùng bootstrap_kmg cho môi trường pilot.")
        catalog = bootstrap_organization_catalog()
        depts = catalog["departments"]
        positions = catalog["positions"]

        dept_tt = depts["MEDIA_EVENT"]
        dept_cm = depts["SPECIALTY"]
        dept_kt = depts["TECHNICAL"]

        now = timezone.now()

        def ensure_user(
            username: str,
            full_name: str,
            email: str,
            phone: str,
            btc_role: str = Role.MEMBER,
            bio: str = "",
            show_phone: bool = False,
            is_superuser: bool = False,
            is_staff: bool = False,
        ) -> User:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "full_name": full_name,
                    "display_name": full_name,
                    "email": email,
                    "phone": phone,
                    "role": btc_role,
                    "is_superuser": is_superuser,
                    "is_staff": is_staff,
                    "account_status": AccountStatus.ACTIVE,
                    "email_verified_at": now if email else None,
                    "phone_verified_at": now if phone else None,
                },
            )
            if not created and not user.check_password(DEMO_PASSWORD):
                raise CommandError(
                    f"Tài khoản {username!r} đã có mật khẩu khác dữ liệu mẫu. "
                    "Dừng seed để bảo vệ tài khoản; dùng cơ sở dữ liệu demo riêng."
                )
            needs_save = created
            if (
                user.role != btc_role
                or user.is_superuser != is_superuser
                or user.is_staff != is_staff
                or (email and not user.email_verified_at)
                or (phone and not user.phone_verified_at)
            ):
                needs_save = True
            if needs_save:
                if created or not user.check_password(DEMO_PASSWORD):
                    user.set_password(DEMO_PASSWORD)
                user.full_name = full_name
                user.display_name = full_name
                user.email = email
                user.phone = phone
                user.role = btc_role
                user.is_superuser = is_superuser
                user.is_staff = is_staff
                user.account_status = AccountStatus.ACTIVE
                if email:
                    user.email_verified_at = user.email_verified_at or now
                if phone:
                    user.phone_verified_at = user.phone_verified_at or now
                user.save()
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "bio": bio,
                    "privacy_show_email": True,
                    "privacy_show_phone": show_phone,
                    "privacy_show_dob": False,
                },
            )
            return user

        # 0. Khởi tạo Admin Server (Tầng quản trị hạ tầng duy nhất có đặc quyền nâng cấp Lãnh đạo cấp cao)
        admin_server = ensure_user(
            "admin",
            "Quản trị viên Server (Admin)",
            "admin@kmg.vn",
            "0901000100",
            btc_role=Role.ADMIN,
            bio="Admin Server KMG Platform · Duyệt nâng cấp Chủ nhiệm, Phó CN, Trưởng ban.",
            show_phone=False,
            is_superuser=True,
            is_staff=True,
        )

        # 1. Khởi tạo Chủ nhiệm CLB (Được Admin Server nâng cấp, tách biệt hoàn toàn khỏi Role.ADMIN)
        chunhiem = ensure_user(
            "chunhiem",
            "Nguyễn Minh Khôi",
            "chunhiem@kmg.vn",
            "0901000101",
            btc_role=Role.LEAD,
            bio="Chủ nhiệm CLB Âm nhạc KMG · Producer & Guitarist.",
            show_phone=True,
        )
        cm_cn = ClubMembership.objects.filter(user=chunhiem).first()
        if cm_cn is None:
            cm_cn = ClubMembership.objects.create(
                user=chunhiem,
                member_code=f"KMG-{timezone.localdate().year}-0001",
                status=ClubMembershipStatus.ACTIVE,
                is_featured=True,
                featured_title="Chủ nhiệm CLB KMG",
                approved_by=admin_server,
            )
            record_lifecycle_event(
                user=chunhiem,
                event_type=LifecycleEventType.APPROVED_CLUB,
                actor=admin_server,
                title=f"Admin Server kích hoạt thành viên sáng lập ({cm_cn.member_code})",
            )
        DepartmentMembership.objects.get_or_create(
            user=chunhiem,
            department=dept_cm,
            defaults={"status": DeptMembershipStatus.ACTIVE},
        )
        active_chair_appt = Appointment.objects.filter(
            position=positions[PositionCode.CHAIRMAN],
            is_active=True,
            ended_at__isnull=True,
        ).first()
        if active_chair_appt is None:
            appt_cn = Appointment(
                user=chunhiem,
                position=positions[PositionCode.CHAIRMAN],
                scope_type=ScopeType.CLUB,
                term_label="2026-2027",
                title_note="Điều hành toàn diện CLB KMG",
                appointed_by=admin_server,
            )
            appt_cn.save()
            record_lifecycle_event(
                user=chunhiem,
                event_type=LifecycleEventType.APPOINTED,
                actor=admin_server,
                title="Admin Server nâng cấp Chủ nhiệm CLB (Toàn CLB)",
            )
        else:
            chunhiem = active_chair_appt.user
            if chunhiem.role == Role.ADMIN and chunhiem.username == "chunhiem":
                chunhiem.role = Role.LEAD
                chunhiem.save(update_fields=["role"])

        def ensure_active_member(
            user: User,
            member_depts: list,
            featured: bool = False,
            featured_title: str = "",
        ) -> ClubMembership:
            cm = ClubMembership.objects.filter(user=user).first()
            if cm is None:
                cm = approve_club_member(
                    actor=chunhiem,
                    target_user=user,
                    departments=member_depts,
                    note="Gia nhập đội ngũ nòng cốt KMG",
                )
            else:
                for d in member_depts:
                    if not DepartmentMembership.objects.filter(
                        user=user, department=d, status=DeptMembershipStatus.ACTIVE
                    ).exists():
                        if cm.status == ClubMembershipStatus.ACTIVE:
                            add_member_to_department(
                                actor=chunhiem,
                                target_user=user,
                                department=d,
                                note="Sinh hoạt đa Ban",
                            )
            if featured and (not cm.is_featured or cm.featured_title != featured_title):
                cm.is_featured = True
                cm.featured_title = featured_title
                cm.save(update_fields=["is_featured", "featured_title", "updated_at"])
            return cm

        def ensure_appointment(
            actor: User,
            target_user: User,
            pos_code: str,
            department=None,
            title_note: str = "",
        ) -> Appointment:
            pos = positions[pos_code]
            existing = Appointment.objects.filter(
                user=target_user,
                position=pos,
                department=department,
                is_active=True,
                ended_at__isnull=True,
            ).first()
            if existing:
                return existing
            # Nếu vị trí đơn nhiệm đang do người khác giữ từ lần seed khác thì lấy bản ghi đó
            if pos.is_singleton:
                singleton_existing = Appointment.objects.filter(
                    position=pos,
                    department=department,
                    is_active=True,
                    ended_at__isnull=True,
                ).first()
                if singleton_existing:
                    return singleton_existing
            return appoint_officer(
                actor=actor,
                target_user=target_user,
                position=pos,
                department=department,
                term_label="2026-2027",
                title_note=title_note,
            )

        def ensure_grant(
            actor: User,
            appt: Appointment,
            bundle_code: str,
            reason: str,
        ) -> PermissionGrant:
            existing = PermissionGrant.objects.filter(
                bound_appointment=appt,
                bundle_code=bundle_code,
                is_active=True,
                revoked_at__isnull=True,
            ).first()
            if existing:
                return existing
            return grant_delegated_permissions(
                actor=actor,
                bound_appointment=appt,
                bundle_code=bundle_code,
                department=appt.department,
                reason=reason,
            )

        # 2. Hai Phó chủ nhiệm + 1 Cố vấn (do Admin Server nâng cấp; Chủ nhiệm phân Mảng phụ trách)
        phocn_nhansu = ensure_user(
            "phocn_nhansu",
            "Trần Hà Linh",
            "halinh.hr@kmg.vn",
            "0901000102",
            btc_role=Role.LEAD,
            bio="Phó Chủ nhiệm phụ trách Nhân sự & Văn hóa tổ chức KMG.",
        )
        ensure_active_member(phocn_nhansu, [dept_tt], featured=True, featured_title="Phó Chủ nhiệm Nhân sự")
        appt_pcn_hr = ensure_appointment(
            admin_server, phocn_nhansu, PositionCode.VICE_CHAIRMAN, title_note="Mảng Nhân sự & Tổ chức"
        )
        ensure_grant(chunhiem, appt_pcn_hr, GrantBundleCode.PORTFOLIO_HR, "Phân công phụ trách Nhân sự CLB")
        ensure_grant(
            chunhiem,
            appt_pcn_hr,
            GrantBundleCode.PORTFOLIO_FINANCE_DOC,
            "Phân công phụ trách Tài chính & Hồ sơ CLB",
        )

        phocn_sukien = ensure_user(
            "phocn_sukien",
            "Lê Hoàng Nam",
            "hoangnam.event@kmg.vn",
            "0901000103",
            btc_role=Role.LEAD,
            bio="Phó Chủ nhiệm phụ trách Sản xuất Sự kiện & Truyền thông công khai.",
        )
        ensure_active_member(phocn_sukien, [dept_tt])
        appt_pcn_ev = ensure_appointment(
            admin_server, phocn_sukien, PositionCode.VICE_CHAIRMAN, title_note="Mảng Sự kiện & Truyền thông"
        )
        ensure_grant(chunhiem, appt_pcn_ev, GrantBundleCode.PORTFOLIO_EVENT, "Phân công phụ trách Sự kiện CLB")

        covan = ensure_user(
            "covan",
            "ThS. Vũ Quốc Bảo",
            "quocbao.advisor@kmg.vn",
            "0901000104",
            btc_role=Role.MEMBER,
            bio="Cố vấn nghệ thuật & định hướng phát triển CLB KMG (Chế độ Giám sát Read-Only).",
        )
        ensure_appointment(admin_server, covan, PositionCode.ADVISOR, title_note="Cố vấn nghệ thuật độc lập")

        # 3. Các Trưởng ban (do Admin Server nâng cấp; truongban_cm đồng thời là Thành viên thường ở Ban Truyền thông!)
        truongban_cm = ensure_user(
            "truongban_cm",
            "Phạm Gia Huy",
            "giahuy.cm@kmg.vn",
            "0901000105",
            btc_role=Role.LEAD,
            bio="Trưởng ban Chuyên môn · Lead Guitarist & Hòa âm phối khí.",
        )
        ensure_active_member(
            truongban_cm,
            [dept_cm, dept_tt],
            featured=True,
            featured_title="Trưởng ban Chuyên môn",
        )
        ensure_appointment(
            admin_server, truongban_cm, PositionCode.DEPT_HEAD, department=dept_cm, title_note="Chỉ đạo nghệ thuật"
        )

        truongban_tt = ensure_user(
            "truongban_tt",
            "Đặng Khánh Vy",
            "khanhvy.tt@kmg.vn",
            "0901000106",
            btc_role=Role.LEAD,
            bio="Trưởng ban Truyền thông sự kiện · Art Director.",
        )
        ensure_active_member(
            truongban_tt,
            [dept_tt],
            featured=True,
            featured_title="Trưởng ban Truyền thông sự kiện",
        )
        ensure_appointment(
            admin_server, truongban_tt, PositionCode.DEPT_HEAD, department=dept_tt, title_note="Điều hành truyền thông"
        )

        truongban_kt = ensure_user(
            "truongban_kt",
            "Hoàng Đức Minh",
            "ducminh.kt@kmg.vn",
            "0901000107",
            btc_role=Role.STAFF,
            bio="Trưởng ban Kỹ thuật (Demo) · FOH Live Sound Engineer.",
        )
        ensure_active_member(truongban_kt, [dept_kt])
        ensure_appointment(
            admin_server, truongban_kt, PositionCode.DEPT_HEAD, department=dept_kt, title_note="Vận hành Ban Kỹ thuật Demo"
        )

        # 4. Hai Phó ban Chuyên môn: 1 người được ủy quyền 2 gói, 1 người mặc định chưa ủy quyền
        phoban_cm_uyquyen = ensure_user(
            "phoban_cm_uyquyen",
            "Bùi Thảo Nguyên",
            "thaonguyen.cm@kmg.vn",
            "0901000108",
            btc_role=Role.STAFF,
            bio="Phó ban Chuyên môn phụ trách Đào tạo Vocal & Điều phối lịch tập.",
        )
        ensure_active_member(phoban_cm_uyquyen, [dept_cm])
        appt_pb_uq = ensure_appointment(
            truongban_cm,
            phoban_cm_uyquyen,
            PositionCode.DEPUTY_HEAD,
            department=dept_cm,
            title_note="Đào tạo & Điều phối lịch tập",
        )
        ensure_grant(
            truongban_cm,
            appt_pb_uq,
            GrantBundleCode.BUNDLE_TASK_OPS,
            "Ủy quyền giao và duyệt bài tập chuyên môn",
        )
        ensure_grant(
            truongban_cm,
            appt_pb_uq,
            GrantBundleCode.BUNDLE_TRAINING_CONTENT,
            "Ủy quyền xác minh kỹ năng thành viên Ban Chuyên môn",
        )

        phoban_cm_macdinh = ensure_user(
            "phoban_cm_macdinh",
            "Ngô Tuấn Kiệt",
            "tuankiet.cm@kmg.vn",
            "0901000109",
            btc_role=Role.MEMBER,
            bio="Phó ban Chuyên môn (chế độ quyền mặc định chưa cấp gói mở rộng).",
        )
        ensure_active_member(phoban_cm_macdinh, [dept_cm])
        ensure_appointment(
            truongban_cm,
            phoban_cm_macdinh,
            PositionCode.DEPUTY_HEAD,
            department=dept_cm,
            title_note="Hỗ trợ hậu cần phòng tập",
        )

        # 5. Thành viên đa Ban có Skill Guitar vs Thành viên không có Skill Guitar nhưng được cấp ACL
        thanhvien_daban = ensure_user(
            "thanhvien_daban",
            "Đỗ Quang Anh",
            "quanganh.member@kmg.vn",
            "0901000110",
            btc_role=Role.MEMBER,
            bio="Thành viên đa Ban (Chuyên môn & Kỹ thuật) · Acoustic Guitar & FOH Assistant.",
        )
        ensure_active_member(
            thanhvien_daban,
            [dept_cm, dept_kt],
            featured=True,
            featured_title="Nghệ sĩ Guitar Acoustic tiêu biểu",
        )

        thanhvien_khong_guitar = ensure_user(
            "thanhvien_khong_guitar",
            "Lý Mai Phương",
            "maiphuong.vocal@kmg.vn",
            "0901000111",
            btc_role=Role.MEMBER,
            bio="Ca sĩ chính Ban Chuyên môn (được Trưởng ban cấp quyền đọc bản phối Guitar mật).",
        )
        ensure_active_member(thanhvien_khong_guitar, [dept_cm])

        # Hồ sơ kỹ năng đã xác minh & chờ xác minh
        skill_guitar = Skill.objects.get(code="GUITAR_ACOUSTIC")
        skill_sound = Skill.objects.get(code="LIVE_SOUND")
        skill_vocal = Skill.objects.get(code="VOCAL_LEAD")

        for holder, sk, prof, verifier in [
            (thanhvien_daban, skill_guitar, SkillProficiency.ADVANCED, truongban_cm),
            (thanhvien_daban, skill_sound, SkillProficiency.INTERMEDIATE, truongban_kt),
            (thanhvien_khong_guitar, skill_vocal, SkillProficiency.ADVANCED, phoban_cm_uyquyen),
        ]:
            us = declare_user_skill(
                user=holder,
                skill=sk,
                proficiency=prof,
                experience_note=f"Biểu diễn thực tế tại KMG ({sk.name})",
            )
            dept_for_verify = dept_kt if sk == skill_sound else dept_cm
            verify_user_skill(
                actor=verifier,
                user_skill=us,
                department=dept_for_verify,
                approved=True,
                review_note="Đã thẩm định trực tiếp tại phòng tập KMG",
            )

        # 6. Thành viên bị tạm khoá & Ứng viên Guest đang chờ sơ duyệt
        thanhvien_tamkhoa = ensure_user(
            "thanhvien_tamkhoa",
            "Phan Minh Quân",
            "minhquan.suspended@kmg.vn",
            "0901000112",
            bio="Thành viên đang tạm nghỉ học kỳ để ôn thi chuyên ngành.",
        )
        cm_susp = ensure_active_member(thanhvien_tamkhoa, [dept_tt])
        if cm_susp.status != ClubMembershipStatus.SUSPENDED:
            suspend_club_member(
                actor=chunhiem,
                target_user=thanhvien_tamkhoa,
                reason="Tạm ngưng sinh hoạt theo đơn xin bảo lưu học kỳ",
            )

        ungvien_guest = ensure_user(
            "ungvien_guest",
            "Võ Ngọc Trâm",
            "ngoctram.guest@kmg.vn",
            "0901000113",
            bio="Khách yêu âm nhạc đăng ký ứng tuyển vào Ban Chuyên môn KMG.",
        )
        if not MembershipApplication.objects.filter(
            user=ungvien_guest,
            status__in=[ApplicationStatus.SUBMITTED, ApplicationStatus.DEPT_SCREENED],
        ).exists():
            submit_membership_application(
                user=ungvien_guest,
                primary_department=dept_cm,
                secondary_department=dept_tt,
                declared_skills_text="Hát Acoustic Pop/Ballad, biết đệm Ukulele cơ bản",
                motivation="Mong muốn được rèn luyện thanh nhạc bài bản và đứng trên sân khấu KMG Live.",
            )

        ensure_user(
            "khach_moi",
            "Đinh Nhật Minh",
            "",
            "0901000114",
            bio="Tài khoản đăng ký qua SĐT & đã xác minh SMS OTP (mặc định là Khách chờ nâng role & phân ban).",
        )

        # 7. Tài nguyên ACL minh họa trực quan Chỉ thị 3.4 (`Skill != Permission`)
        rule_public, _ = ResourceAccessRule.objects.update_or_create(
            resource_code="DOC-KMG-HANDBOOK-2026",
            defaults={
                "resource_type": "DOCUMENT",
                "title": "Sổ tay Văn hoá & Quy tắc Sinh hoạt CLB KMG 2026",
                "department": dept_tt,
                "classification": ResourceClassification.PUBLIC_CLUB,
                "created_by": chunhiem,
            },
        )
        rule_dept, _ = ResourceAccessRule.objects.update_or_create(
            resource_code="DOC-CM-REHEARSAL-SOP",
            defaults={
                "resource_type": "DOCUMENT",
                "title": "Quy trình Dàn dựng Band & Lịch Phòng tập Ban Chuyên môn",
                "department": dept_cm,
                "classification": ResourceClassification.DEPARTMENT_INTERNAL,
                "created_by": truongban_cm,
            },
        )
        rule_secret_guitar, _ = ResourceAccessRule.objects.update_or_create(
            resource_code="DOC-CM-SECRET-GUITAR-SCORE",
            defaults={
                "resource_type": "DOCUMENT",
                "title": "Tài liệu Hòa âm Guitar Mật — Liveshow Kỷ niệm KMG (Chưa công bố)",
                "department": dept_cm,
                "classification": ResourceClassification.RESTRICTED_ACL,
                "recommended_skill": skill_guitar,
                "created_by": truongban_cm,
            },
        )
        # Cấp đích danh cho thanhvien_khong_guitar (KHÔNG có skill Guitar),
        # nhưng KHÔNG cấp cho thanhvien_daban (CÓ skill Guitar VERIFIED) -> Chứng minh Skill != Permission!
        rule_secret_guitar.allowed_users.set([thanhvien_khong_guitar])

        # 8. Sự kiện PUBLIC vs Sự kiện INTERNAL (`INT-01`)
        ev_public, _ = Event.objects.update_or_create(
            name="KMG Acoustic Night: Thanh Âm Mùa Thu",
            defaults={
                "description": "Đêm nhạc Acoustic thường niên mở cửa đón khán giả yêu nhạc toàn trường.",
                "location": "Hội trường Lớn A1",
                "category": EventCategory.MUSIC,
                "starts_at": now + timedelta(days=14),
                "ends_at": now + timedelta(days=14, hours=3),
                "register_deadline": now + timedelta(days=12),
                "capacity": 250,
                "status": EventStatus.OPEN,
                "visibility": EventVisibility.PUBLIC,
                "created_by": phocn_sukien,
            },
        )
        ev_internal, _ = Event.objects.update_or_create(
            name="[Nội bộ KMG] Tổng duyệt & Ghép Band Chuyên môn Tháng 11",
            defaults={
                "description": "Buổi ghép band nội bộ bắt buộc dành riêng cho thành viên chính thức KMG.",
                "location": "Phòng Studio KMG B204",
                "category": EventCategory.MUSIC,
                "starts_at": now + timedelta(days=5),
                "ends_at": now + timedelta(days=5, hours=3),
                "register_deadline": now + timedelta(days=3),
                "capacity": 60,
                "status": EventStatus.OPEN,
                "visibility": EventVisibility.INTERNAL,
                "created_by": truongban_cm,
            },
        )

        # 9. Dữ liệu Vận hành Cốt lõi (Phase 2 — Core Management, 100% idempotent)
        from operations.models import (
            ClubAnnouncement,
            ClubEventApprovalStatus,
            ClubEventProfile,
            ClubEventScope,
            ClubTask,
            DisciplineCase,
            EventDepartmentRole,
            EventDeptRoleType,
            TaskPriority,
            TaskReviewDecision,
            TaskSubmissionMode,
            TaskWorkflowStatus,
        )
        from operations.services import (
            broadcast_announcement,
            create_and_assign_task,
            create_club_event,
            finalize_task_review,
            propose_manual_discipline_case,
            review_club_event,
            submit_club_event_for_approval,
            submit_task_deliverable,
            update_task_progress,
        )
        from organization.models import PolicyVersion

        def fresh(u: User) -> User:
            return User.objects.get(pk=u.pk)

        rsvp_policy = PolicyVersion.objects.filter(
            policy_key="CLUB_EVENT_DEFAULT_RSVP", is_current=True
        ).first()

        # 9a. Gắn hồ sơ ClubEventProfile cho Show công khai & Sinh hoạt nội bộ Ban (nếu chưa có)
        ce_public, pub_created = ClubEventProfile.objects.get_or_create(
            event=ev_public,
            defaults={
                "event_scope": ClubEventScope.PUBLIC_SHOW,
                "approval_status": ClubEventApprovalStatus.PUBLISHED,
                "lead_department": dept_tt,
                "require_club_rsvp": False,
                "policy_version": rsvp_policy,
                "proposal_note": "Show diễn thương mại mở bán vé thường niên của CLB KMG.",
                "proposed_by": truongban_tt,
                "approved_by": phocn_sukien,
                "approved_at": now,
                "published_at": now,
            },
        )
        if pub_created:
            EventDepartmentRole.objects.get_or_create(
                club_event=ce_public,
                department=dept_tt,
                defaults={"role_type": EventDeptRoleType.LEAD, "responsibility_note": "Truyền thông, bán vé & đón khách"},
            )
            EventDepartmentRole.objects.get_or_create(
                club_event=ce_public,
                department=dept_cm,
                defaults={"role_type": EventDeptRoleType.CO_ORGANIZER, "responsibility_note": "Biên tập kịch bản âm nhạc & band biểu diễn"},
            )
            EventDepartmentRole.objects.get_or_create(
                club_event=ce_public,
                department=dept_kt,
                defaults={"role_type": EventDeptRoleType.SUPPORT, "responsibility_note": "Vận hành âm thanh FOH & ánh sáng sân khấu"},
            )

        ce_dept, dept_ev_created = ClubEventProfile.objects.get_or_create(
            event=ev_internal,
            defaults={
                "event_scope": ClubEventScope.DEPT_INTERNAL,
                "approval_status": ClubEventApprovalStatus.PUBLISHED,
                "lead_department": dept_cm,
                "require_club_rsvp": False,
                "policy_version": rsvp_policy,
                "proposal_note": "Ghép band & căn chỉnh tempo cho các tiết mục Ban Chuyên môn.",
                "proposed_by": truongban_cm,
                "approved_by": truongban_cm,
                "approved_at": now,
                "published_at": now,
            },
        )
        if dept_ev_created:
            EventDepartmentRole.objects.get_or_create(
                club_event=ce_dept,
                department=dept_cm,
                defaults={"role_type": EventDeptRoleType.LEAD, "responsibility_note": "Chủ trì tập luyện chuyên môn"},
            )

        # 9b. Sự kiện toàn CLB phối hợp liên Ban đang chờ thành viên phản hồi RSVP
        club_wide_name = "[Toàn CLB] KMG Showcase & Tổng duyệt Acoustic Mùa Thu"
        ce_club_wide = ClubEventProfile.objects.filter(event__name=club_wide_name).first()
        if ce_club_wide is None:
            ce_club_wide = create_club_event(
                actor=fresh(truongban_cm),
                lead_department=dept_cm,
                name=club_wide_name,
                location="Hội trường Studio KMG A102",
                starts_at=now + timedelta(days=9),
                ends_at=now + timedelta(days=9, hours=3),
                rsvp_freeze_at=now + timedelta(days=7),
                event_scope=ClubEventScope.CLUB_WIDE,
                capacity=120,
                description="Buổi tổng duyệt toàn CLB bắt buộc trước thềm đêm nhạc lớn. Thành viên vui lòng xác nhận RSVP đúng hạn.",
                proposal_note="Phối hợp 3 Ban: Chuyên môn điều phối tiết mục, Truyền thông ghi hình hậu trường, Kỹ thuật vận hành FOH.",
                supporting_departments=[
                    (dept_tt, EventDeptRoleType.CO_ORGANIZER, "Ghi hình backstage & điều phối check-in thành viên"),
                    (dept_kt, EventDeptRoleType.SUPPORT, "Lắp đặt hệ thống mixer FOH, monitor & micro không dây"),
                ],
            )
            submit_club_event_for_approval(fresh(truongban_cm), ce_club_wide)
            review_club_event(
                actor=fresh(phocn_sukien),
                club_event=ce_club_wide,
                approved=True,
                review_note="Nhất trí kế hoạch tổng duyệt liên Ban, ban hành RSVP toàn CLB.",
                auto_publish=True,
            )

        # 9c. Công việc Đa chiều & Công việc Nhóm (`ClubTask` + `TaskReview` bất biến)
        t1_title = "Dựng beat & hòa âm Acoustic tiết mục mở màn Showcase"
        if not ClubTask.objects.filter(title=t1_title, department=dept_cm).exists():
            t1 = create_and_assign_task(
                actor=fresh(truongban_cm),
                department=dept_cm,
                title=t1_title,
                description="Phối hợp Guitar Acoustic và Vocal thu bản guide cho toàn band tập luyện ghép nhịp.",
                deadline=now + timedelta(days=4),
                assignees=[fresh(thanhvien_daban), fresh(thanhvien_khong_guitar)],
                priority=TaskPriority.HIGH,
                submission_mode=TaskSubmissionMode.ALL_ASSIGNEES,
                recommended_skill=skill_guitar,
                event=ce_club_wide.event,
                category_tag="Hòa âm",
                lead_user=fresh(thanhvien_daban),
            )
            update_task_progress(
                actor=fresh(thanhvien_daban),
                task=t1,
                new_status=TaskWorkflowStatus.IN_PROGRESS,
                progress_percent=65,
            )

        t2_title = "Thiết kế bộ nhận diện & ấn phẩm truyền thông Showcase Mùa Thu"
        if not ClubTask.objects.filter(title=t2_title, department=dept_tt).exists():
            t2 = create_and_assign_task(
                actor=fresh(truongban_tt),
                department=dept_tt,
                title=t2_title,
                description="Xuất bộ poster, banner sân khấu và khung avatar theo đúng màu nhận diện KMG.",
                deadline=now + timedelta(days=5),
                assignees=[fresh(truongban_cm)],
                priority=TaskPriority.MEDIUM,
                submission_mode=TaskSubmissionMode.ANY_ONE,
                event=ev_public,
                category_tag="Thiết kế",
            )
            submit_task_deliverable(
                actor=fresh(truongban_cm),
                task=t2,
                submission_note="Đã hoàn thiện trọn bộ ấn phẩm PNG/SVG chuẩn in ấn và đăng tải kênh CLB.",
                evidence_url="https://kmg.vn/showcase-media-kit",
            )
            finalize_task_review(
                actor=fresh(truongban_tt),
                task=t2,
                decision=TaskReviewDecision.APPROVED,
                quality_score=5,
                feedback="Bố cục chuẩn Editorial KMG, hình ảnh sắc nét đúng quy cách.",
            )

        t3_title = "Kiểm tra danh sách micro không dây & line mixer B204"
        if not ClubTask.objects.filter(title=t3_title, department=dept_kt).exists():
            create_and_assign_task(
                actor=fresh(truongban_kt),
                department=dept_kt,
                title=t3_title,
                description="Kiểm tra pin, thử tiếng DI box guitar và đánh nhãn từng line trước buổi tổng duyệt.",
                deadline=now + timedelta(hours=20),
                assignees=[fresh(thanhvien_daban)],
                priority=TaskPriority.URGENT,
                submission_mode=TaskSubmissionMode.ANY_ONE,
                recommended_skill=skill_sound,
                event=ev_internal,
                category_tag="Âm thanh",
            )

        # 9d. Thông báo điều hành chính thức cấp CLB
        ann_title = "Lịch tổng duyệt toàn CLB & chốt RSVP Showcase Mùa Thu"
        if not ClubAnnouncement.objects.filter(title=ann_title).exists():
            broadcast_announcement(
                actor=fresh(chunhiem),
                title=ann_title,
                content=(
                    "Ban Chủ nhiệm thông báo lịch Tổng duyệt Showcase toàn CLB. "
                    "Các thành viên vui lòng vào mục Sự kiện Nội bộ & RSVP để xác nhận tham gia "
                    "hoặc gửi đơn xin vắng có lý do trước hạn chốt 48 giờ."
                ),
                department=None,
                is_pinned=True,
                send_email=False,
            )

        # 9e. Hồ sơ cảnh báo chuyên cần mẫu minh bạch (`R04` — không tự khoá)
        if not DisciplineCase.objects.filter(target_user=thanhvien_tamkhoa).exists():
            propose_manual_discipline_case(
                actor=fresh(phocn_nhansu),
                target_user=fresh(thanhvien_tamkhoa),
                department=dept_tt,
                summary="Hồ sơ đối chiếu chuyên cần trước kỳ bảo lưu học kỳ (đang chờ BCN rà soát minh chứng).",
                evidence_note="Ghi nhận vắng 02 buổi sinh hoạt trước thời điểm nộp đơn bảo lưu.",
            )

        # 10. Dữ liệu Department Management (Phase 3 — Kho Tài liệu Mật, Đề xuất, Đào tạo, Lịch tập & Showcase)
        from django.core.files.uploadedfile import SimpleUploadedFile
        from programs.models import (
            AclPermissionLevel,
            AclSubjectType,
            ConfidentialDocument,
            DepartmentProposal,
            DepartmentShowcaseItem,
            DocumentACLEntry,
            DocumentCategory,
            DocumentClassification,
            PracticeResponseStatus,
            PracticeSession,
            ProposalReviewDecision,
            ProposalScope,
            ProposalType,
            ShowcaseItemType,
            TrainingCourse,
        )
        from programs.services import (
            create_confidential_document,
            create_department_showcase_item,
            create_practice_session,
            create_proposal,
            create_training_course,
            enroll_in_training,
            grant_document_acl,
            review_proposal,
            update_practice_participant_status,
        )

        cat_cm_score, _ = DocumentCategory.objects.update_or_create(
            code="CAT-CM-SCORE",
            defaults={
                "department": dept_cm,
                "name": "Tổng phổ & Bản phối Hòa âm",
                "description": "Tài liệu tổng phổ, sheet nhạc, hợp âm và track guide biểu diễn.",
                "display_order": 1,
            },
        )
        cat_cm_sop, _ = DocumentCategory.objects.update_or_create(
            code="CAT-CM-SOP",
            defaults={
                "department": dept_cm,
                "name": "Giáo trình Đào tạo & Quy trình Phòng tập",
                "description": "Quy trình ghép band, đánh giá thanh nhạc và giáo trình ban Chuyên môn.",
                "display_order": 2,
            },
        )
        cat_tt_media, _ = DocumentCategory.objects.update_or_create(
            code="CAT-TT-MEDIA",
            defaults={
                "department": dept_tt,
                "name": "Ấn phẩm, Kịch bản Truyền thông & Brand Kit",
                "description": "Kịch bản MC, guideline truyền thông và quy chuẩn hình ảnh KMG.",
                "display_order": 3,
            },
        )
        cat_kt_stage, _ = DocumentCategory.objects.update_or_create(
            code="CAT-KT-STAGE",
            defaults={
                "department": dept_kt,
                "name": "Sơ đồ FOH & Danh mục Thiết bị (Demo)",
                "description": "Stage plot, thông số mixer số và nhật ký bảo trì micro/âm thanh.",
                "display_order": 4,
            },
        )

        def ensure_vault_doc(
            *,
            actor: User,
            title: str,
            classification: str,
            department=None,
            category=None,
            custom_label: str = "",
            description: str = "",
            skills=None,
            filename: str = "kmg-doc.txt",
            content_bytes: bytes = b"KMG Confidential Vault Document",
        ) -> ConfidentialDocument:
            existing = ConfidentialDocument.objects.filter(title=title).first()
            if existing:
                return existing
            upload = SimpleUploadedFile(filename, content_bytes, content_type="text/plain")
            doc, _ = create_confidential_document(
                actor=fresh(actor),
                title=title,
                classification=classification,
                uploaded_file=upload,
                department=department,
                category=category,
                custom_category_label=custom_label,
                description=description,
                recommended_skills=skills or [],
                change_note="Khởi tạo dữ liệu chuẩn Kho Mật KMG",
            )
            return doc

        ensure_vault_doc(
            actor=chunhiem,
            title="Sổ tay Văn hoá & Quy chế Hoạt động KMG 2026",
            classification=DocumentClassification.CLUB_INTERNAL,
            department=dept_tt,
            category=cat_tt_media,
            custom_label="Quy chế Toàn CLB",
            description="Tài liệu nội bộ toàn CLB dành cho toàn thể thành viên chính thức và Cố vấn.",
            filename="so-tay-kmg-2026.txt",
            content_bytes=b"KMG Club Cultural & Operations Handbook 2026\n",
        )
        doc_cm_sop = ensure_vault_doc(
            actor=truongban_cm,
            title="Quy trình Dàn dựng Band & Phối hợp Phòng tập B204",
            classification=DocumentClassification.DEPT_INTERNAL,
            department=dept_cm,
            category=cat_cm_sop,
            custom_label="SOP Phòng tập",
            description="Lưu hành nội bộ cho thành viên Ban Chuyên môn.",
            filename="sop-phong-tap-b204.txt",
            content_bytes=b"Rehearsal SOP: Check monitor balance before vocal warm-up.\n",
        )
        doc_secret_guitar = ensure_vault_doc(
            actor=truongban_cm,
            title="Bản phối Hòa âm Guitar Mật — Liveshow Acoustic KMG",
            classification=DocumentClassification.RESTRICTED,
            department=dept_cm,
            category=cat_cm_score,
            custom_label="Bản phối Liveshow",
            description="Tài liệu mật chỉ thành viên trong danh sách ACL mới được mở xem/tải (Skill Guitar chỉ để gợi ý).",
            skills=[skill_guitar],
            filename="hoa-am-guitar-liveshow.txt",
            content_bytes=b"Am7 - D9 - Gmaj7 - Cmaj7 | Acoustic Lead Arrangement (Restricted).\n",
        )
        if not DocumentACLEntry.objects.filter(
            document=doc_secret_guitar,
            subject_type=AclSubjectType.USER,
            user=thanhvien_khong_guitar,
            is_active=True,
        ).exists():
            grant_document_acl(
                actor=fresh(truongban_cm),
                document=doc_secret_guitar,
                subject_type=AclSubjectType.USER,
                permission_level=AclPermissionLevel.DOWNLOAD,
                target_user=fresh(thanhvien_khong_guitar),
                reason="Ca sĩ chính cần đọc bản phối Guitar để bắt tông bè (dù không có kỹ năng Guitar).",
            )

        ensure_vault_doc(
            actor=truongban_cm,
            title="Kịch bản Điều hành Trưởng ban & Quỹ Dàn dựng Chuyên môn 2026",
            classification=DocumentClassification.HIGHLY_RESTRICTED,
            department=dept_cm,
            category=cat_cm_sop,
            custom_label="Tuyệt mật Điều hành",
            description="Giới hạn chỉ Trưởng ban và đích danh USER ACL (hoặc Chủ nhiệm mở Break-Glass khẩn cấp).",
            filename="tuyet-mat-ban-chuyen-mon.txt",
            content_bytes=b"Highly Restricted Executive Script & Budget Plan.\n",
        )

        # 10b. Đề xuất Hoạt động 2 cấp (`WF17`, `INV-03`)
        prop_club_title = "Đêm nhạc Acoustic Kỷ niệm Thành lập KMG 2026"
        if not DepartmentProposal.objects.filter(title=prop_club_title).exists():
            p_club = create_proposal(
                actor=fresh(thanhvien_daban),
                department=dept_cm,
                title=prop_club_title,
                proposal_type=ProposalType.EVENT,
                scope=ProposalScope.CLUB,
                summary="Tổ chức đêm diễn quy mô toàn CLB với 12 tiết mục Acoustic kết hợp trình diễn Live Band.",
                objectives="Gắn kết 3 Ban Chuyên môn - Truyền thông - Kỹ thuật và tuyển sinh cộng tác viên.",
                estimated_budget=8500000,
                proposed_start_at=now + timedelta(days=30),
                proposed_location="Hội trường Lớn A1",
                submit_immediately=True,
            )
            review_proposal(
                actor=fresh(truongban_cm),
                proposal=p_club,
                decision=ProposalReviewDecision.ESCALATE_BCN,
                feedback="Nhất trí kịch bản nghệ thuật cấp Ban, kính trình Ban Chủ nhiệm phê duyệt tổ chức cấp CLB.",
            )

        prop_dept_title = "Workshop Kỹ thuật Guitar Đệm hát & FOH Cơ bản"
        if not DepartmentProposal.objects.filter(title=prop_dept_title).exists():
            p_dept = create_proposal(
                actor=fresh(phoban_cm_uyquyen),
                department=dept_cm,
                title=prop_dept_title,
                proposal_type=ProposalType.TRAINING,
                scope=ProposalScope.DEPARTMENT,
                summary="Chuỗi 02 buổi hướng dẫn giữ nhịp metronome, bấm hợp âm nâng cao và kết nối DI Box.",
                objectives="Nâng chất lượng biểu diễn Acoustic cho thành viên Ban Chuyên môn.",
                estimated_budget=500000,
                proposed_start_at=now + timedelta(days=12),
                proposed_location="Phòng Studio KMG B204",
                submit_immediately=True,
            )
            review_proposal(
                actor=fresh(truongban_cm),
                proposal=p_dept,
                decision=ProposalReviewDecision.APPROVE,
                feedback="Phê duyệt tổ chức cấp Ban; giao Phó ban triển khai khóa đào tạo.",
            )

        # 10c. Khóa Đào tạo & Lịch Tập luyện Band (`WF18`, `BE-04`)
        course_vocal_title = "Lớp Thanh nhạc & Điều tiết Hơi thở KMG"
        course_vocal = TrainingCourse.objects.filter(title=course_vocal_title).first()
        if course_vocal is None:
            course_vocal = create_training_course(
                actor=fresh(truongban_cm),
                department=dept_cm,
                title=course_vocal_title,
                description="Luyện lấy hơi bụng, mở khẩu hình và giữ cao độ khi hát cùng Acoustic Band.",
                custom_category="Thanh nhạc",
                target_skill=skill_vocal,
                instructor=fresh(thanhvien_khong_guitar),
                location="Phòng Studio KMG B204",
                starts_at=now + timedelta(days=4),
                ends_at=now + timedelta(days=4, hours=2),
                capacity=15,
            )
            enroll_in_training(actor=fresh(thanhvien_daban), course=course_vocal)

        course_foh_title = "Thực hành Bàn Mixer FOH & Cân chỉnh Micro Live"
        if not TrainingCourse.objects.filter(title=course_foh_title).exists():
            course_foh = create_training_course(
                actor=fresh(truongban_kt),
                department=dept_kt,
                title=course_foh_title,
                description="Quy trình Soundcheck Gain, EQ lọc hú feedback và Routing Monitor sân khấu.",
                custom_category="Kỹ thuật FOH",
                target_skill=skill_sound,
                instructor=fresh(truongban_kt),
                location="Hội trường Studio KMG A102",
                starts_at=now + timedelta(days=6),
                ends_at=now + timedelta(days=6, hours=2),
                capacity=12,
            )
            enroll_in_training(actor=fresh(thanhvien_daban), course=course_foh)

        rehearsal_title = "Ghép Band Tiết mục Mở màn Showcase Mùa Thu"
        if not PracticeSession.objects.filter(title=rehearsal_title).exists():
            ps = create_practice_session(
                actor=fresh(truongban_cm),
                department=dept_cm,
                title=rehearsal_title,
                repertoire_note="Bài 1: Thanh Âm Mùa Thu (Tempo 92 BPM) · Bài 2: Giai Điệu Chạm Tim.",
                location="Phòng Studio KMG B204",
                starts_at=now + timedelta(days=3),
                ends_at=now + timedelta(days=3, hours=2),
                club_event=ce_club_wide,
                participants_specs=[
                    (fresh(thanhvien_daban), "Guitar Acoustic Lead", skill_guitar),
                    (fresh(thanhvien_khong_guitar), "Vocal Chính", skill_vocal),
                    (fresh(truongban_kt), "Kỹ thuật Âm thanh Monitor", skill_sound),
                ],
            )
            my_part = ps.participants.filter(user=thanhvien_daban).first()
            if my_part:
                update_practice_participant_status(
                    actor=fresh(thanhvien_daban),
                    participant=my_part,
                    new_status=PracticeResponseStatus.CONFIRMED,
                    note="Đã chuẩn bị dây đàn và capo.",
                )

        # 10d. Chuyên mục Chuyên biệt cho cả 3 Ban (`DepartmentShowcaseItem`)
        for dept_obj, cat_lbl, i_type, s_title, s_summary, ext_url, l_doc in [
            (
                dept_tt,
                "Truyền thông & Recap",
                ShowcaseItemType.MEDIA_PORTFOLIO,
                "Bộ nhận diện & Recap Mùa Thu KMG Showcase",
                "Kho ảnh hậu trường, teaser video và khung avatar đồng bộ nhận diện Xanh mực trầm & Vàng sân khấu.",
                "https://kmg.vn/showcase-media-kit",
                None,
            ),
            (
                dept_cm,
                "Dàn dựng Chuyên môn",
                ShowcaseItemType.REPERTOIRE,
                "Tiêu chuẩn Dàn dựng Band & Tổng phổ KMG",
                "Hệ thống sheet nhạc hợp âm chuẩn, quy trình ghép band và tiêu chí thẩm định kỹ năng nghệ thuật.",
                "",
                doc_cm_sop,
            ),
            (
                dept_kt,
                "Hệ thống FOH (Demo)",
                ShowcaseItemType.EQUIPMENT_SPEC,
                "Cấu hình 24-Channel Digital Mixer & Monitor Stage Plot",
                "Danh mục line-in micro không dây, DI Box Acoustic Guitar và sơ đồ phân bố loa Monitor sân khấu.",
                "",
                None,
            ),
        ]:
            if not DepartmentShowcaseItem.objects.filter(department=dept_obj, title=s_title).exists():
                create_department_showcase_item(
                    actor=fresh(
                        truongban_tt if dept_obj == dept_tt else (truongban_kt if dept_obj == dept_kt else truongban_cm)
                    ),
                    department=dept_obj,
                    category_label=cat_lbl,
                    item_type=i_type,
                    title=s_title,
                    summary=s_summary,
                    external_url=ext_url,
                    linked_document=l_doc,
                    is_pinned=True,
                )

        # 11. Dữ liệu Mạng xã hội Nội bộ, Nhắn tin Bảo mật AES-256-GCM & Playlist Âm nhạc (Phase 4 — 100% idempotent)
        from social.models import (
            ChatMessage,
            MusicPlaylist,
            MusicShare,
            PlaylistVisibility,
            SocialPost,
            SocialPostVisibility,
            SocialReactionType,
        )
        from social.services import (
            add_social_comment,
            add_track_to_playlist,
            create_playlist,
            create_social_post,
            ensure_club_conversation,
            ensure_department_conversation,
            get_or_create_direct_conversation,
            send_chat_message,
            send_music_share,
            toggle_social_reaction,
        )

        # 11a. Bài viết Mạng xã hội Nội bộ (`WF19`, `PA-05`)
        club_post_txt = (
            "Không khí tập Acoustic chuẩn bị cho KMG Acoustic Night tối nay thật sự bùng nổ! "
            "Cảm ơn @thanhvien_khong_guitar và anh em các Ban đã cháy hết mình."
        )
        p_club = SocialPost.objects.filter(
            author=thanhvien_daban, visibility=SocialPostVisibility.CLUB, content=club_post_txt
        ).first()
        if p_club is None:
            p_club = create_social_post(
                fresh(thanhvien_daban),
                content=club_post_txt,
                visibility=SocialPostVisibility.CLUB,
                link_url="https://www.youtube.com/watch?v=jfKfPfyJRdk",
            )
            add_social_comment(
                fresh(thanhvien_khong_guitar),
                p_club,
                content="Tối mai tiếp tục khớp nhịp bridge đoạn cao trào nhé @thanhvien_daban!",
            )
            toggle_social_reaction(
                fresh(truongban_cm),
                reaction_type=SocialReactionType.FIRE,
                post=p_club,
            )

        dept_cm_txt = (
            "[Nội bộ Ban Chuyên môn] Lưu ý kiểm tra dây guitar acoustic và phân bè vocal "
            "trước buổi ghép band phòng B204."
        )
        p_dept_cm = SocialPost.objects.filter(
            author=truongban_cm,
            visibility=SocialPostVisibility.DEPARTMENT,
            department=dept_cm,
            content=dept_cm_txt,
        ).first()
        if p_dept_cm is None:
            p_dept_cm = create_social_post(
                fresh(truongban_cm),
                content=dept_cm_txt,
                visibility=SocialPostVisibility.DEPARTMENT,
                department=dept_cm,
            )

        # Minh họa PA-05: Thành viên đa ban chia sẻ bài Nội bộ CM ra Toàn CLB -> Ban ngoài không thấy gốc!
        pa05_share_txt = "Mọi người nhớ giữ sức khoẻ cổ họng cho đêm nhạc sắp tới nhé!"
        if not SocialPost.objects.filter(
            author=thanhvien_daban,
            visibility=SocialPostVisibility.CLUB,
            shared_post=p_dept_cm,
        ).exists():
            create_social_post(
                fresh(thanhvien_daban),
                content=pa05_share_txt,
                visibility=SocialPostVisibility.CLUB,
                shared_post=p_dept_cm,
            )

        personal_txt = "Ghi chú cá nhân: Cần luyện lại hợp âm chặn Bm7 và chuyển hợp âm Fmaj7 mượt hơn."
        if not SocialPost.objects.filter(
            author=thanhvien_daban, visibility=SocialPostVisibility.PERSONAL
        ).exists():
            create_social_post(
                fresh(thanhvien_daban),
                content=personal_txt,
                visibility=SocialPostVisibility.PERSONAL,
            )

        # 11b. Hội thoại Nhắn tin Mã hóa AES-256-GCM (`WF21`, `INV-05`)
        conv_club = ensure_club_conversation(created_by=fresh(chunhiem))
        if not ChatMessage.objects.filter(conversation=conv_club).exists():
            send_chat_message(
                fresh(chunhiem),
                conv_club,
                plaintext="Chào mừng mọi người đến với Kênh chung Toàn CLB KMG (bảo mật AES-256-GCM)!",
            )

        conv_cm = ensure_department_conversation(dept_cm, created_by=fresh(truongban_cm))
        ensure_department_conversation(dept_tt, created_by=fresh(truongban_tt))
        ensure_department_conversation(dept_kt, created_by=fresh(truongban_kt))
        if not ChatMessage.objects.filter(conversation=conv_cm).exists():
            send_chat_message(
                fresh(truongban_cm),
                conv_cm,
                plaintext="Anh em Ban Chuyên môn chốt tempo 92 BPM cho tiết mục mở màn nhé.",
            )

        conv_dm = get_or_create_direct_conversation(
            fresh(thanhvien_daban), fresh(thanhvien_khong_guitar)
        )
        if not ChatMessage.objects.filter(conversation=conv_dm).exists():
            send_chat_message(
                fresh(thanhvien_daban),
                conv_dm,
                plaintext="Phương ơi bản phối Guitar Acoustic tông C trưởng anh vừa chỉnh xong rồi nhé.",
            )

        # 11c. Playlist Âm nhạc Cá nhân & Tặng nhạc (`BE-05`, `INV-05`)
        if not MusicPlaylist.objects.filter(owner=thanhvien_khong_guitar).exists():
            pl_priv = create_playlist(
                fresh(thanhvien_khong_guitar),
                title="Góc Nhạc Riêng — Mai Phương",
                description="Danh sách luyện giọng buổi sáng (chế độ Riêng tư `INV-05`).",
                visibility=PlaylistVisibility.PRIVATE,
            )
            add_track_to_playlist(
                fresh(thanhvien_khong_guitar),
                pl_priv,
                track_url="https://www.youtube.com/watch?v=5qap5aO4i9A",
                title="Lofi Acoustic Morning Warm-up",
                artist_name="KMG Vocal Studio",
                duration_seconds=215,
            )

        pl_shared = MusicPlaylist.objects.filter(
            owner=thanhvien_daban, visibility=PlaylistVisibility.CLUB_SHARED
        ).first()
        if pl_shared is None:
            pl_shared = create_playlist(
                fresh(thanhvien_daban),
                title="Acoustic Setlist Đêm Mùa Thu KMG",
                description="Những ca khúc truyền cảm hứng cho buổi showcase tháng 11.",
                visibility=PlaylistVisibility.CLUB_SHARED,
            )
            it_shared = add_track_to_playlist(
                fresh(thanhvien_daban),
                pl_shared,
                track_url="https://www.youtube.com/watch?v=jfKfPfyJRdk",
                title="Thanh Âm Mùa Thu (Acoustic Demo)",
                artist_name="KMG Band",
                duration_seconds=240,
            )
            if not MusicShare.objects.filter(
                sender=thanhvien_daban, recipient=thanhvien_khong_guitar
            ).exists():
                send_music_share(
                    fresh(thanhvien_daban),
                    recipient=fresh(thanhvien_khong_guitar),
                    source_item=it_shared,
                    personal_message="Tặng em bài tham khảo cho tiết mục mở màn thứ Sáu nha!",
                )

        # 12. Dữ liệu Quỹ CLB Bất biến, Đánh giá 7 Tiêu chí & Vinh danh (Phase 5 — 100% idempotent)
        from datetime import date
        from evaluations.models import (
            EvaluationCriterion,
            EvaluationCriterionScore,
            EvaluationCycle,
            EvaluationCycleStatus,
            EvaluationResponse,
            EvaluationStatus,
            MemberEvaluation,
            MemberRecognition,
            OverallRating,
            RatingLevel,
            RecognitionScope,
            RecognitionStatus,
        )
        from evaluations.services import (
            create_or_update_evaluation_draft,
            ensure_cycle,
            finalize_evaluation,
            nominate_recognition,
            submit_evaluation_response,
            verify_recognition,
        )
        from finance.models import (
            AdjustmentDirection,
            ContributionStatus,
            FinancialTransaction,
            FundCategory,
            MemberContribution,
            TransactionStatus,
            TransactionType,
        )
        from finance.services import (
            bootstrap_finance_categories,
            create_adjustment_transaction,
            create_financial_transaction,
            record_member_contribution,
            review_financial_transaction,
            sync_legacy_expense_to_ledger,
        )
        from organizing.models import Expense

        bootstrap_finance_categories()
        cat_dues = FundCategory.objects.get(code="THU-QUY")
        cat_sponsor = FundCategory.objects.get(code="THU-TAI-TRO")
        cat_event = FundCategory.objects.get(code="CHI-SU-KIEN")
        cat_rehearsal = FundCategory.objects.get(code="CHI-TAP-LUYEN")

        # 12a. Giao dịch Quỹ & Maker-Checker (Chủ nhiệm/Phó CN duyệt độc lập)
        if not FinancialTransaction.objects.filter(title__contains="Tài trợ").exists():
            tx_sponsor = create_financial_transaction(
                fresh(chunhiem),
                tx_type=TransactionType.INCOME,
                category=cat_sponsor,
                title="Tài trợ Đêm nhạc Mùa Thu từ Doanh nghiệp Cựu Sinh viên",
                amount=15000000,
                transaction_date=date(2026, 3, 1),
                description="Hợp đồng tài trợ kim cương đêm diễn Showcase KMG 2026.",
            )
            review_financial_transaction(fresh(phocn_nhansu), tx_sponsor, approve=True)

        if not FinancialTransaction.objects.filter(title__contains="Thuê Studio").exists():
            tx_studio = create_financial_transaction(
                fresh(truongban_cm),
                tx_type=TransactionType.EXPENSE,
                category=cat_rehearsal,
                title="Thuê Studio diễn tập 4 buổi ghép Band",
                amount=2400000,
                transaction_date=date(2026, 3, 10),
                department=dept_cm,
                description="Phòng tập B204 có dàn âm thanh và bộ trống Jazz.",
            )
            review_financial_transaction(fresh(chunhiem), tx_studio, approve=True)

        if not FinancialTransaction.objects.filter(title__contains="In ấn Backdrop").exists():
            create_financial_transaction(
                fresh(truongban_tt),
                tx_type=TransactionType.EXPENSE,
                category=cat_event,
                title="In ấn Backdrop sân khấu & Standee đón khách",
                amount=1800000,
                transaction_date=date(2026, 3, 15),
                department=dept_tt,
                description="Chờ duyệt chi cho đêm diễn cuối tháng 3.",
            )

        # CM-03 Bridge: Kết chuyển 1 khoản chi legacy sang sổ cái quỹ
        legacy_exp = Expense.objects.filter(ledger_transaction__isnull=True).first()
        if legacy_exp and not hasattr(legacy_exp, "ledger_transaction"):
            try:
                tx_sync = sync_legacy_expense_to_ledger(fresh(chunhiem), legacy_exp)
                review_financial_transaction(fresh(phocn_nhansu), tx_sync, approve=True)
            except Exception:
                pass

        # Đóng góp quỹ thành viên
        if not MemberContribution.objects.filter(member=thanhvien_daban, period_label="2026-HK1").exists():
            record_member_contribution(
                fresh(chunhiem),
                member=fresh(thanhvien_daban),
                period_label="2026-HK1",
                title="Đóng góp quỹ HK1/2026",
                amount=200000,
                department=dept_cm,
                paid_on=date(2026, 1, 15),
                note="Nộp chuyển khoản ngân hàng",
            )
            # Tự duyệt phiếu thu quỹ
            tx_c = FinancialTransaction.objects.filter(title__contains="Đóng góp quỹ HK1/2026 (Đỗ Quang Anh)").first()
            if tx_c and tx_c.status == TransactionStatus.PENDING_APPROVAL:
                review_financial_transaction(fresh(phocn_nhansu), tx_c, approve=True)

        # 12b. Kỳ Đánh giá 2026-HK1, 7 Tiêu chí & Phản hồi BE-06
        cycle_2026 = ensure_cycle(
            fresh(chunhiem),
            code="2026-HK1",
            name="Đánh giá Hoạt động & Phát triển Học kỳ 1 / 2026",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            response_deadline=date(2027, 1, 15),
        )
        if cycle_2026.response_deadline and cycle_2026.response_deadline < date(2027, 1, 1):
            cycle_2026.response_deadline = date(2027, 1, 15)
            cycle_2026.ends_on = date(2026, 12, 31)
            cycle_2026.save(update_fields=["response_deadline", "ends_on"])

        # Đánh giá Đỗ Quang Anh tại Ban Chuyên môn (Chốt)
        ev_cm = MemberEvaluation.objects.filter(
            cycle=cycle_2026, member=thanhvien_daban, department=dept_cm
        ).first()
        if not ev_cm:
            ev_cm = create_or_update_evaluation_draft(
                fresh(truongban_cm),
                cycle=cycle_2026,
                member=fresh(thanhvien_daban),
                department=dept_cm,
                criteria={
                    EvaluationCriterion.TASK_COMPLETION: 5,
                    EvaluationCriterion.ATTENDANCE: 4,
                    EvaluationCriterion.PROFESSIONAL_SKILL: 5,
                    EvaluationCriterion.TRAINING_GROWTH: 5,
                    EvaluationCriterion.TEAMWORK: 4,
                    EvaluationCriterion.INITIATIVE: 4,
                    EvaluationCriterion.CULTURE: 5,
                },
                overall_rating=OverallRating.STRONG,
                strengths="Kỹ năng Guitar Acoustic điêu luyện, hỗ trợ các bạn trong ban tập ghép rất nhiệt tình.",
                growth_areas="Cần chú ý giữ tempo chuẩn hơn ở các đoạn chuyển nhịp phức tạp.",
                development_plan="Tham gia solo tiết mục Acoustic tại Minishow tháng 5.",
            )
        if ev_cm.status == EvaluationStatus.DRAFT:
            ev_cm = finalize_evaluation(fresh(truongban_cm), ev_cm)

        if not EvaluationResponse.objects.filter(evaluation=ev_cm).exists():
            submit_evaluation_response(
                fresh(thanhvien_daban),
                ev_cm,
                "Em cảm ơn anh Huy và Ban đã góp ý! Em sẽ luyện thêm với máy đập nhịp Metronome hàng ngày.",
            )

        # Đánh giá Đỗ Quang Anh tại Ban Kỹ thuật Demo (Bản nháp - thành viên đa Ban nhận đánh giá độc lập!)
        if not MemberEvaluation.objects.filter(
            cycle=cycle_2026, member=thanhvien_daban, department=dept_kt
        ).exists():
            create_or_update_evaluation_draft(
                fresh(truongban_kt),
                cycle=cycle_2026,
                member=fresh(thanhvien_daban),
                department=dept_kt,
                criteria={
                    EvaluationCriterion.TASK_COMPLETION: 4,
                    EvaluationCriterion.ATTENDANCE: 4,
                    EvaluationCriterion.PROFESSIONAL_SKILL: 4,
                    EvaluationCriterion.TRAINING_GROWTH: 3,
                    EvaluationCriterion.TEAMWORK: 5,
                    EvaluationCriterion.INITIATIVE: 3,
                    EvaluationCriterion.CULTURE: 4,
                },
                overall_rating=OverallRating.MEETS,
                strengths="Hỗ trợ lắp đặt thiết bị FOH nhanh nhẹn, nắm vững sơ đồ line-in.",
                growth_areas="Cần làm quen thêm với mixer digital Behringer X32.",
            )

        # 12c. Vinh danh Thành viên Tiêu biểu
        if not MemberRecognition.objects.filter(recipient=thanhvien_daban, title__contains="Nghệ sĩ Cống hiến").exists():
            rec_qa = nominate_recognition(
                fresh(truongban_cm),
                recipient=fresh(thanhvien_daban),
                title="Nghệ sĩ Cống hiến Ban Chuyên môn HK1/2026",
                citation="Đóng góp xuất sắc trong toàn bộ các buổi diễn Showcase và luôn đi đầu trong các buổi jam session.",
                scope=RecognitionScope.DEPARTMENT,
                department=dept_cm,
                cycle=cycle_2026,
                is_public=True,
            )
            verify_recognition(fresh(chunhiem), rec_qa, approve=True, is_public=True)

        if not MemberRecognition.objects.filter(recipient=thanhvien_khong_guitar, title__contains="Giọng ca Triển vọng").exists():
            rec_mp = nominate_recognition(
                fresh(truongban_cm),
                recipient=fresh(thanhvien_khong_guitar),
                title="Giọng ca Triển vọng KMG 2026",
                citation="Tiến bộ vượt bậc sau khoá đào tạo thanh nhạc và hoàn thành xuất sắc tiết mục mở màn đêm Acoustic.",
                scope=RecognitionScope.CLUB,
                cycle=cycle_2026,
                is_public=True,
            )
            verify_recognition(fresh(chunhiem), rec_mp, approve=True, is_public=True)

        self.stdout.write(
            self.style.SUCCESS(
                "Đã khởi tạo thành công toàn bộ dữ liệu KMG Platform (Phase 1, 2, 3, 4 & 5 — Finance & Evaluations)!"
            )
        )
