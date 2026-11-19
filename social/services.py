"""
Tầng Nghiệp vụ Phase 4 (`social.services`):

1. Mạng xã hội Nội bộ (`WF19`, `PA-05`, `INV-04`, `SEC-01`):
   - Bài viết đa phạm vi (`PERSONAL`, `CLUB`, `DEPARTMENT`, `CUSTOM_GROUP`), bình luận phân cấp + `@mention`,
     cảm xúc 1 lần/người, chia sẻ (`shared_post`) áp dụng kiểm tra kép `PA-05` nghiêm ngặt.
   - Tải tệp/ảnh đính kèm qua `PrivateVaultStorage` & tái mã hoá Pillow loại bỏ EXIF/script.
   - Kiểm duyệt theo đúng phạm vi (`DEPARTMENT` chỉ thuộc về Trưởng/Phó ban có `dept.post.moderate` tại đúng Ban đó;
     `CLUB` thuộc về `club.social.moderate`; `PERSONAL` & `CUSTOM_GROUP` không bao giờ lọt vào hàng đợi Ban khác).
   - Lưu sổ cái bất biến `SocialModerationLog` (`INV-04` Cố vấn chỉ đọc, cấm mọi thao tác xã hội).

2. Nhắn tin Nội bộ Mã hóa AES-256-GCM (`WF21`, `INV-05`, `BE-07`, `PA-02`, `R03`):
   - `ConversationMember(left_at IS NULL)` là chân lý duy nhất cho `INV-05` (`Zero-Admin-Read`):
     Chủ nhiệm, Phó CN, Trưởng ban, Admin Server không thuộc hội thoại đều bị chặn `403`.
   - Hook vòng đời `PA-02`: tự động rời phòng chat Ban cũ khi Chuyển Ban / Tạm khoá / Rời CLB.
   - Thu hồi tin nhắn trong 15 phút kèm xoá mật mã bản gốc; báo cáo quấy rối kèm chữ ký bằng chứng
     `HMAC-SHA256` (`BE-07`) gửi BCN Nhân sự mà không mở cửa sau đọc toàn bộ hộp thư.
   - Không bao giờ ghi plaintext tin nhắn vào `AuditLog` hay `Notification.message`.

3. Playlist Âm nhạc Cá nhân & Tặng nhạc (`BE-05`, `SEC-04`, `SEC-05`, `R07`, `INV-05`):
   - Playlist `PRIVATE` tuân thủ `INV-05` (tuyệt đối chỉ chủ sở hữu xem/sửa được).
   - Kiểm tra URL nhạc an toàn hoàn toàn ngoại tuyến (whitelist domain/scheme, chặn IP nội bộ chống SSRF `SEC-05`).
   - Tìm người nhận tặng nhạc chống trùng tên (`BE-05`), giới hạn <= 10 kết quả, ẩn Email/SĐT/MSSV & áp Rate Limit (`SEC-04`, `SEC-06`).
"""
from __future__ import annotations

from datetime import timedelta
import hashlib
import io
import ipaddress
import os
import re
from urllib.parse import parse_qs, urlparse
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from accounts.models import AccountStatus, AuditLog, User
from core.security import is_rate_limited
from notifications.models import Notification, NotificationKind
from operations.models import (
    ClubEventApprovalStatus,
    ClubEventProfile,
    ClubTask,
    ClubTaskAssignee,
    EventAttendance,
)
from organization.models import (
    ClubMembershipStatus,
    Department,
    DepartmentMembership,
    DeptMembershipStatus,
    PositionCode,
    ScopeType,
)
from organization.permissions import PermissionEngine
from organization.services import GovernanceError
from programs.services import (
    _is_active_club_actor,
    _is_pure_advisor,
    validate_and_prepare_vault_file,
)

from .crypto import (
    decrypt_message_text,
    encrypt_message_text,
    generate_wrapped_dek,
    sign_abuse_report_snapshot,
    unwrap_dek,
    verify_abuse_report_snapshot,
)
from .models import (
    AbuseReportStatus,
    ChatAttachment,
    ChatMessage,
    ChatReaction,
    ChatReactionEmoji,
    Conversation,
    ConversationMember,
    ConversationMemberRole,
    ConversationType,
    MessageAbuseReport,
    MusicPlaylist,
    MusicProvider,
    MusicShare,
    PlaylistItem,
    PlaylistVisibility,
    SocialAttachmentType,
    SocialComment,
    SocialModerationAction,
    SocialModerationLog,
    SocialModerationStatus,
    SocialPost,
    SocialPostAttachment,
    SocialPostAudienceMember,
    SocialPostVisibility,
    SocialReaction,
    SocialReactionType,
    SocialReport,
    SocialReportStatus,
)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_MENTION_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_.]{2,50})")
_HTTP_VALIDATOR = URLValidator(schemes=["http", "https"])
_RECALL_WINDOW = timedelta(minutes=15)
_SAFE_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_SAFE_SPOTIFY_ID_RE = re.compile(r"^[A-Za-z0-9]{10,40}$")


# ---------------------------------------------------------------------------
# TIỆN ÍCH BẢO MẬT TỆP & URL (`SEC-01`, `SEC-05`)
# ---------------------------------------------------------------------------
def _validate_safe_external_url(raw_url: str, *, field_label: str = "Liên kết") -> str:
    url = (raw_url or "").strip()
    if not url:
        return ""
    try:
        _HTTP_VALIDATOR(url)
    except ValidationError as exc:
        raise GovernanceError(f"{field_label} phải là URL http:// hoặc https:// hợp lệ.") from exc

    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise GovernanceError(f"{field_label} thiếu tên miền hợp lệ.")
    if (
        host == "localhost"
        or host.endswith(".local")
        or host.endswith(".internal")
        or host.endswith(".localhost")
    ):
        raise GovernanceError(f"{field_label} không được trỏ tới máy chủ nội bộ.")

    try:
        ip_obj = ipaddress.ip_address(host)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise GovernanceError(f"{field_label} không được trỏ tới địa chỉ IP nội bộ.")
    except ValueError:
        pass
    return url


def validate_and_prepare_social_attachment(uploaded_file) -> dict:
    """
    Kiểm tra tệp tải lên cho MXH / Tin nhắn (`SEC-01`):
    - Áp dụng bộ lọc đuôi cấm, dung lượng <= 20MB và magic bytes từ `programs.services`.
    - Nếu là ảnh (`.png/.jpg/.jpeg/.webp`): xác thực cấu trúc raster & lưu lại qua Pillow
      để bóc tách sạch metadata EXIF / script ẩn.
    """
    meta = validate_and_prepare_vault_file(uploaded_file)
    _, ext = os.path.splitext(meta["original_filename"])
    ext = ext.lower()
    if ext in _IMAGE_EXTENSIONS:
        meta["content_file"].seek(0)
        raw_bytes = meta["content_file"].read()
        try:
            probe = Image.open(io.BytesIO(raw_bytes))
            probe.verify()
            img = Image.open(io.BytesIO(raw_bytes))
            fmt_map = {
                ".png": ("PNG", "image/png"),
                ".jpg": ("JPEG", "image/jpeg"),
                ".jpeg": ("JPEG", "image/jpeg"),
                ".webp": ("WEBP", "image/webp"),
            }
            pil_fmt, canonical_ct = fmt_map[ext]
            if pil_fmt == "JPEG" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            elif pil_fmt in ("PNG", "WEBP") and img.mode == "P":
                img = img.convert("RGBA")

            out_buf = io.BytesIO()
            img.save(out_buf, format=pil_fmt)
            clean_bytes = out_buf.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise GovernanceError(
                "Hình ảnh đính kèm bị hỏng hoặc không đúng định dạng ảnh thực tế."
            ) from exc

        safe_name = f"{uuid.uuid4().hex}{ext}"
        meta["storage_name"] = safe_name
        meta["content_file"] = ContentFile(clean_bytes, name=safe_name)
        meta["content_type"] = canonical_ct
        meta["file_size"] = len(clean_bytes)
        meta["checksum_sha256"] = hashlib.sha256(clean_bytes).hexdigest()
        meta["attachment_type"] = SocialAttachmentType.IMAGE
    else:
        meta["attachment_type"] = SocialAttachmentType.FILE
    return meta


def parse_music_track_url(raw_url: str) -> tuple[str, str, str]:
    """
    Phân tích URL âm nhạc hoàn toàn ngoại tuyến (`SEC-05` — zero outbound HTTP fetch!).
    Trả về `(clean_url, provider, external_track_id)`.
    """
    clean_url = _validate_safe_external_url(raw_url, field_label="Đường dẫn bài hát")
    if not clean_url:
        raise GovernanceError("Vui lòng nhập đường dẫn bài hát hợp lệ.")

    parsed = urlparse(clean_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    # 1. YouTube / YouTube Music
    if host in (
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    ):
        vid = ""
        if host == "youtu.be":
            seg = path.strip("/").split("/")[0] if path.strip("/") else ""
            vid = seg
        else:
            qs = parse_qs(parsed.query)
            if qs.get("v"):
                vid = qs["v"][0]
            elif path.startswith("/shorts/") or path.startswith("/embed/"):
                parts = [p for p in path.split("/") if p]
                if len(parts) >= 2:
                    vid = parts[1]
        if not _SAFE_YT_ID_RE.fullmatch(vid):
            vid = ""
        return clean_url, MusicProvider.YOUTUBE, vid

    # 2. Spotify
    if host in ("open.spotify.com", "spotify.link"):
        tid = ""
        parts = [p for p in path.split("/") if p]
        if "track" in parts:
            idx = parts.index("track")
            if idx + 1 < len(parts):
                candidate = parts[idx + 1]
                if _SAFE_SPOTIFY_ID_RE.fullmatch(candidate):
                    tid = candidate
        return clean_url, MusicProvider.SPOTIFY, tid

    # 3. SoundCloud
    if host in ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com", "on.soundcloud.com"):
        slug = path.strip("/")[:80]
        return clean_url, MusicProvider.SOUNDCLOUD, slug

    return clean_url, MusicProvider.EXTERNAL, ""


def build_safe_embed_info(provider: str, external_track_id: str) -> dict:
    """Sinh dữ liệu nhúng an toàn (chỉ cho YouTube/Spotify ID đã khớp regex chuẩn)."""
    if provider == MusicProvider.YOUTUBE and _SAFE_YT_ID_RE.fullmatch(external_track_id or ""):
        return {
            "can_embed": True,
            "kind": "YOUTUBE",
            "embed_url": f"https://www.youtube-nocookie.com/embed/{external_track_id}",
        }
    if provider == MusicProvider.SPOTIFY and _SAFE_SPOTIFY_ID_RE.fullmatch(external_track_id or ""):
        return {
            "can_embed": True,
            "kind": "SPOTIFY",
            "embed_url": f"https://open.spotify.com/embed/track/{external_track_id}",
        }
    return {"can_embed": False, "kind": provider, "embed_url": ""}


def _assert_not_advisor(actor: User, msg: str = "Cố vấn chỉ có quyền Xem giám sát (`INV-04`)."):
    if _is_pure_advisor(actor):
        raise PermissionDenied(msg)


# ---------------------------------------------------------------------------
# 1. MẠNG XÃ HỘI NỘI BỘ (`WF19`, `PA-05`, `INV-04`)
# ---------------------------------------------------------------------------
def can_moderate_post(actor: User, post: SocialPost) -> bool:
    """
    Phân quyền kiểm duyệt MXH theo đúng phạm vi (`WF19`):
    - Cố vấn (`INV-04`): False.
    - Bài `PERSONAL` hoặc `CUSTOM_GROUP`: False đối với MỌI cán bộ / Admin Server.
    - Bài `DEPARTMENT`: chỉ người có quyền `dept.post.moderate` tại ĐÚNG `post.department`.
    - Bài `CLUB`: chỉ người có quyền `club.social.moderate` (Chủ nhiệm, Admin Server, Phó CN mảng Sự kiện/Truyền thông).
    """
    if not _is_active_club_actor(actor) or _is_pure_advisor(actor):
        return False
    if post.is_deleted:
        return False
    if post.visibility in (SocialPostVisibility.PERSONAL, SocialPostVisibility.CUSTOM_GROUP):
        return False
    if post.visibility == SocialPostVisibility.DEPARTMENT:
        if post.department_id is None:
            return False
        return PermissionEngine.authorize(
            actor, "dept.post.moderate", department=post.department
        )
    if post.visibility == SocialPostVisibility.CLUB:
        return PermissionEngine.authorize(actor, "club.social.moderate")
    return False


def can_view_post(actor: User, post: SocialPost) -> bool:
    """
    Kiểm tra quyền xem một bài viết MXH (`WF19`, `PA-05`):
    - Chỉ Thành viên chính thức `ACTIVE`, Ban Điều hành hoặc Cố vấn (`INV-04`) mới được truy cập.
    - Bài `PERSONAL`: DUY NHẤT tác giả.
    - Bài `CUSTOM_GROUP`: tác giả hoặc người nằm trong danh sách `SocialPostAudienceMember`.
    - Bài `DEPARTMENT`: tác giả, thành viên đang `ACTIVE` của Ban đó, hoặc kiểm duyệt viên Ban đó
      (chặn thành viên/Trưởng ban của Ban khác không sinh hoạt tại Ban sở hữu).
    - Bài `CLUB`: toàn thể thành viên/cán bộ/cố vấn CLB đang hoạt động.
    - Nếu `moderation_status != PUBLISHED`: chỉ tác giả hoặc kiểm duyệt viên hợp lệ của phạm vi đó thấy được.
    """
    if not _is_active_club_actor(actor):
        return False
    if post.is_deleted:
        return False

    scope_ok = False
    if post.visibility == SocialPostVisibility.PERSONAL:
        scope_ok = post.author_id == actor.id
    elif post.visibility == SocialPostVisibility.CUSTOM_GROUP:
        if post.author_id == actor.id:
            scope_ok = True
        else:
            scope_ok = SocialPostAudienceMember.objects.filter(
                post=post, user=actor
            ).exists()
    elif post.visibility == SocialPostVisibility.DEPARTMENT:
        if post.department_id is None:
            scope_ok = False
        elif post.author_id == actor.id:
            scope_ok = True
        elif post.department_id in PermissionEngine.get_active_department_ids(actor):
            scope_ok = True
        elif can_moderate_post(actor, post):
            scope_ok = True
    elif post.visibility == SocialPostVisibility.CLUB:
        scope_ok = True

    if not scope_ok:
        return False

    if post.moderation_status != SocialModerationStatus.PUBLISHED:
        return post.author_id == actor.id or can_moderate_post(actor, post)
    return True


def serialize_post_for_viewer(actor: User, post: SocialPost) -> dict:
    """
    Chuẩn hoá dữ liệu bài đăng cho UI / REST API, thực thi nghiêm ngặt `PA-05`:
    Khi bài viết có `shared_post`, đánh giá `can_view_post(actor, post.shared_post)` độc lập.
    Nếu người xem không có quyền xem bài gốc -> che hoàn toàn nội dung & tệp gốc!
    """
    reactions_qs = list(post.reactions.all())
    reaction_counts: dict[str, int] = {}
    my_reaction = None
    for rx in reactions_qs:
        reaction_counts[rx.reaction_type] = reaction_counts.get(rx.reaction_type, 0) + 1
        if rx.user_id == actor.id:
            my_reaction = rx.reaction_type

    comments = list(
        post.comments.filter(is_deleted=False)
        .select_related("author")
        .prefetch_related("mentioned_users", "reactions")
    )
    comment_map: dict[int, dict] = {}
    root_comments: list[dict] = []
    for c in comments:
        c_reacts: dict[str, int] = {}
        c_my_react = None
        for rx in c.reactions.all():
            c_reacts[rx.reaction_type] = c_reacts.get(rx.reaction_type, 0) + 1
            if rx.user_id == actor.id:
                c_my_react = rx.reaction_type
        node = {
            "id": c.id,
            "author_id": c.author_id,
            "author_name": c.author.public_name,
            "author_avatar": c.author.avatar.url if c.author.avatar else "",
            "content": c.content,
            "parent_id": c.parent_id,
            "mentioned_usernames": [u.username for u in c.mentioned_users.all()],
            "reaction_counts": c_reacts,
            "my_reaction": c_my_react,
            "created_at": c.created_at,
            "replies": [],
        }
        comment_map[c.id] = node

    for c in comments:
        node = comment_map[c.id]
        if c.parent_id and c.parent_id in comment_map:
            comment_map[c.parent_id]["replies"].append(node)
        else:
            root_comments.append(node)

    attachments = [
        {
            "id": att.id,
            "attachment_type": att.attachment_type,
            "original_filename": att.original_filename,
            "content_type": att.content_type,
            "file_size": att.file_size,
        }
        for att in post.attachments.all()
    ]

    # PA-05: Kiểm tra kép bài gốc được chia sẻ!
    shared_post_data = None
    shared_post_restricted = False
    shared_post_placeholder = ""
    if post.shared_post_id is not None:
        orig = post.shared_post
        if orig is not None and can_view_post(actor, orig):
            shared_post_data = {
                "id": orig.id,
                "author_id": orig.author_id,
                "author_name": orig.author.public_name,
                "visibility": orig.visibility,
                "visibility_label": orig.get_visibility_display(),
                "department_name": orig.department.name if orig.department_id else None,
                "content": orig.content,
                "link_url": orig.link_url,
                "created_at": orig.created_at,
                "attachments": [
                    {
                        "id": att.id,
                        "attachment_type": att.attachment_type,
                        "original_filename": att.original_filename,
                        "file_size": att.file_size,
                    }
                    for att in orig.attachments.all()
                ],
            }
        else:
            shared_post_restricted = True
            shared_post_placeholder = "Nội dung gốc thuộc phạm vi giới hạn hoặc không còn tồn tại."

    is_adv = _is_pure_advisor(actor)
    can_mod = can_moderate_post(actor, post)
    return {
        "post": post,
        "id": post.id,
        "author_id": post.author_id,
        "author_name": post.author.public_name,
        "author_username": post.author.username,
        "author_avatar": post.author.avatar.url if post.author.avatar else "",
        "visibility": post.visibility,
        "visibility_label": post.get_visibility_display(),
        "department": {
            "id": post.department_id,
            "name": post.department.name,
            "slug": post.department.slug,
        }
        if post.department_id
        else None,
        "content": post.content,
        "link_url": post.link_url,
        "moderation_status": post.moderation_status,
        "moderation_status_label": post.get_moderation_status_display(),
        "attachments": attachments,
        "reaction_counts": reaction_counts,
        "reaction_total": len(reactions_qs),
        "my_reaction": my_reaction,
        "comments": root_comments,
        "comment_count": len(comments),
        "shared_post_id": post.shared_post_id,
        "shared_post_data": shared_post_data,
        "shared_post_restricted": shared_post_restricted,
        "shared_post_placeholder": shared_post_placeholder,
        "can_interact": not is_adv,
        "can_delete": (not is_adv) and (post.author_id == actor.id or can_mod),
        "can_moderate": can_mod,
        "can_report": (
            (not is_adv)
            and (post.author_id != actor.id)
            and post.visibility in (SocialPostVisibility.CLUB, SocialPostVisibility.DEPARTMENT)
            and post.moderation_status == SocialModerationStatus.PUBLISHED
        ),
        "can_share": (not is_adv) and post.visibility != SocialPostVisibility.PERSONAL,
        "created_at": post.created_at,
    }


def list_visible_posts(
    actor: User,
    *,
    scope: str = "ALL",
    department: Department | None = None,
    limit: int = 50,
) -> list[dict]:
    """Two-phase feed: truy vấn ứng viên thô rồi lọc tuyệt đối qua `can_view_post` tại Backend."""
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền truy cập Mạng xã hội nội bộ CLB.")

    qs = (
        SocialPost.objects.filter(is_deleted=False)
        .select_related("author", "department", "shared_post__author", "shared_post__department")
        .prefetch_related(
            "attachments",
            "reactions",
            "comments__author",
            "comments__mentioned_users",
            "comments__reactions",
            "audience_members",
            "shared_post__attachments",
        )
    )
    if scope == "CLUB":
        qs = qs.filter(visibility=SocialPostVisibility.CLUB)
    elif scope == "PERSONAL":
        qs = qs.filter(visibility=SocialPostVisibility.PERSONAL, author=actor)
    elif scope == "CUSTOM":
        qs = qs.filter(visibility=SocialPostVisibility.CUSTOM_GROUP)
    elif scope == "DEPARTMENT" and department is not None:
        qs = qs.filter(visibility=SocialPostVisibility.DEPARTMENT, department=department)
    elif scope == "MY_DEPTS":
        my_ids = PermissionEngine.get_active_department_ids(actor)
        qs = qs.filter(visibility=SocialPostVisibility.DEPARTMENT, department_id__in=my_ids)

    visible: list[dict] = []
    for p in qs.order_by("-created_at", "-id")[:200]:
        if can_view_post(actor, p):
            visible.append(serialize_post_for_viewer(actor, p))
            if len(visible) >= limit:
                break
    return visible


@transaction.atomic
def create_social_post(
    actor: User,
    *,
    content: str = "",
    visibility: str = SocialPostVisibility.CLUB,
    department: Department | None = None,
    audience_users: list[User] | None = None,
    shared_post: SocialPost | None = None,
    link_url: str = "",
    attachments: list | None = None,
) -> SocialPost:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Chỉ thành viên chính thức CLB KMG mới được đăng bài.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể đăng bài.")

    valid_vis = {c[0] for c in SocialPostVisibility.choices}
    if visibility not in valid_vis:
        raise GovernanceError("Phạm vi hiển thị bài viết không hợp lệ.")

    clean_content = (content or "").strip()
    clean_link = _validate_safe_external_url(link_url, field_label="Liên kết tham khảo")
    upload_list = [f for f in (attachments or []) if f is not None]

    if shared_post is not None:
        if not can_view_post(actor, shared_post):
            raise PermissionDenied("Bạn không có quyền xem hoặc chia sẻ bài viết gốc này.")
        if shared_post.visibility == SocialPostVisibility.PERSONAL:
            raise GovernanceError("Không thể chia sẻ bài viết đang ở chế độ Riêng tư cá nhân.")

    if not clean_content and not upload_list and not clean_link and shared_post is None:
        raise GovernanceError("Bài viết phải có nội dung, tệp đính kèm, liên kết hoặc bài chia sẻ.")

    dept_for_post = None
    if visibility == SocialPostVisibility.DEPARTMENT:
        if department is None:
            raise GovernanceError("Bài viết phạm vi Nội bộ Ban bắt buộc phải chọn Ban.")
        active_depts = PermissionEngine.get_active_department_ids(actor)
        if not (
            department.id in active_depts
            or PermissionEngine.authorize(actor, "dept.post.moderate", department=department)
        ):
            raise PermissionDenied(f"Bạn không thuộc {department.name} để đăng bài vào Ban này.")
        dept_for_post = department

    prepared_files = [validate_and_prepare_social_attachment(f) for f in upload_list]

    post = SocialPost.objects.create(
        author=actor,
        department=dept_for_post,
        visibility=visibility,
        content=clean_content[:5000],
        shared_post=shared_post,
        link_url=clean_link[:300],
        moderation_status=SocialModerationStatus.PUBLISHED,
    )

    if visibility == SocialPostVisibility.CUSTOM_GROUP:
        members_to_add = [
            u
            for u in (audience_users or [])
            if u.pk != actor.pk and _is_active_club_actor(u)
        ]
        SocialPostAudienceMember.objects.bulk_create(
            [SocialPostAudienceMember(post=post, user=u) for u in members_to_add],
            ignore_conflicts=True,
        )

    for pf in prepared_files:
        SocialPostAttachment.objects.create(
            post=post,
            attachment_type=pf["attachment_type"],
            file=pf["content_file"],
            original_filename=pf["original_filename"],
            content_type=pf["content_type"],
            file_size=pf["file_size"],
            checksum_sha256=pf["checksum_sha256"],
        )

    if shared_post is not None and shared_post.author_id != actor.id:
        Notification.objects.create(
            user=shared_post.author,
            kind=NotificationKind.SOCIAL_INTERACTION,
            title=f"{actor.public_name} đã chia sẻ bài viết của bạn"[:120],
            message=f"Bài viết #{shared_post.id} vừa được chia sẻ ở phạm vi {post.get_visibility_display()}."[:255],
            url=f"/workspace/mang-xa-hoi/bai/{post.id}/"[:255],
        )
    return post


@transaction.atomic
def soft_delete_social_post(actor: User, post: SocialPost) -> SocialPost:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền truy cập Mạng xã hội.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if post.is_deleted:
        raise GovernanceError("Bài viết này đã bị xoá trước đó.")
    if post.author_id != actor.id and not can_moderate_post(actor, post):
        raise PermissionDenied("Bạn không có quyền xoá bài viết này.")

    post.is_deleted = True
    post.deleted_at = timezone.now()
    post.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
    AuditLog.write(actor, "Xoá bài viết MXH nội bộ", f"SocialPost #{post.id} ({post.visibility})")
    return post


@transaction.atomic
def add_social_comment(
    actor: User,
    post: SocialPost,
    *,
    content: str,
    parent_comment: SocialComment | None = None,
) -> SocialComment:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Chỉ thành viên CLB đang hoạt động mới được bình luận.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể bình luận.")
    if not can_view_post(actor, post):
        raise PermissionDenied("Bạn không có quyền xem hoặc bình luận bài viết này.")

    clean_text = (content or "").strip()
    if not clean_text:
        raise GovernanceError("Vui lòng nhập nội dung bình luận.")

    if parent_comment is not None and (parent_comment.post_id != post.id or parent_comment.is_deleted):
        raise GovernanceError("Bình luận gốc được trả lời không hợp lệ.")

    comment = SocialComment.objects.create(
        post=post,
        author=actor,
        parent=parent_comment,
        content=clean_text[:2000],
    )

    mentioned_handles = {m.lower() for m in _MENTION_RE.findall(clean_text)}
    mentioned_users = []
    if mentioned_handles:
        for candidate in User.objects.filter(username__in=mentioned_handles, is_locked=False):
            if candidate.pk != actor.id and _is_active_club_actor(candidate):
                # Chỉ nhắc @mention nếu người được nhắc thực sự xem được bài viết
                if can_view_post(candidate, post):
                    mentioned_users.append(candidate)
        if mentioned_users:
            comment.mentioned_users.set(mentioned_users)

    notified_ids = {actor.id}
    if post.author_id != actor.id and post.author_id not in notified_ids:
        Notification.objects.create(
            user=post.author,
            kind=NotificationKind.SOCIAL_INTERACTION,
            title=f"{actor.public_name} đã bình luận bài viết của bạn"[:120],
            message=clean_text[:180],
            url=f"/workspace/mang-xa-hoi/bai/{post.id}/"[:255],
        )
        notified_ids.add(post.author_id)

    for mu in mentioned_users:
        if mu.id not in notified_ids:
            Notification.objects.create(
                user=mu,
                kind=NotificationKind.SOCIAL_INTERACTION,
                title=f"{actor.public_name} đã nhắc tới bạn trong bình luận"[:120],
                message=clean_text[:180],
                url=f"/workspace/mang-xa-hoi/bai/{post.id}/"[:255],
            )
            notified_ids.add(mu.id)

    return comment


@transaction.atomic
def toggle_social_reaction(
    actor: User,
    *,
    reaction_type: str = SocialReactionType.LIKE,
    post: SocialPost | None = None,
    comment: SocialComment | None = None,
) -> dict:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Chỉ thành viên CLB đang hoạt động mới được thả cảm xúc.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể thả cảm xúc.")
    if (post is None) == (comment is None):
        raise GovernanceError("Cần chỉ định đúng 1 bài viết HOẶC 1 bình luận.")
    if reaction_type not in {c[0] for c in SocialReactionType.choices}:
        raise GovernanceError("Loại cảm xúc không hợp lệ.")

    target_post = post if post is not None else comment.post
    if not can_view_post(actor, target_post):
        raise PermissionDenied("Bạn không có quyền truy cập bài viết này.")

    filter_kwargs = {"user": actor, "post": post} if post is not None else {"user": actor, "comment": comment}
    existing = SocialReaction.objects.filter(**filter_kwargs).first()
    if existing is not None:
        if existing.reaction_type == reaction_type:
            existing.delete()
            return {"active": False, "reaction_type": None}
        existing.reaction_type = reaction_type
        existing.save(update_fields=["reaction_type"])
        return {"active": True, "reaction_type": reaction_type}

    SocialReaction.objects.create(
        post=post,
        comment=comment,
        user=actor,
        reaction_type=reaction_type,
    )
    return {"active": True, "reaction_type": reaction_type}


@transaction.atomic
def report_social_post(actor: User, post: SocialPost, reason: str) -> SocialReport:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Chỉ thành viên CLB mới có quyền gửi báo cáo.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể báo cáo.")
    if not can_view_post(actor, post):
        raise PermissionDenied("Bạn không có quyền xem bài viết này.")
    if post.visibility not in (SocialPostVisibility.CLUB, SocialPostVisibility.DEPARTMENT):
        raise GovernanceError("Chỉ có thể báo cáo bài viết thuộc phạm vi Ban hoặc Toàn CLB.")
    if post.author_id == actor.id:
        raise GovernanceError("Bạn không thể tự báo cáo bài viết của chính mình.")

    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise GovernanceError("Vui lòng nêu rõ lý do báo cáo bài viết.")

    if SocialReport.objects.filter(
        post=post, reporter=actor, status=SocialReportStatus.OPEN
    ).exists():
        raise GovernanceError("Bạn đã gửi báo cáo cho bài viết này và đang chờ xử lý.")

    report = SocialReport.objects.create(
        post=post,
        reporter=actor,
        reason=clean_reason[:1000],
    )
    AuditLog.write(actor, "Báo cáo bài viết MXH", f"SocialPost #{post.id}", clean_reason[:120])
    return report


def get_moderation_queue(actor: User) -> list[SocialReport]:
    """
    Hàng đợi kiểm duyệt theo đúng phạm vi (`WF19`):
    - Cố vấn (`INV-04`) bị chặn `403`.
    - Chỉ trả về các báo cáo mà `can_moderate_post(actor, report.post)` là `True`.
    - Bài `PERSONAL`, `CUSTOM_GROUP`, hoặc của Ban khác TUYỆT ĐỐI KHÔNG bao giờ xuất hiện!
    """
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền truy cập hàng đợi kiểm duyệt.")

    can_any_mod = PermissionEngine.authorize(actor, "club.social.moderate") or any(
        PermissionEngine.authorize(actor, "dept.post.moderate", department=d)
        for d in Department.objects.filter(is_active=True)
    )
    if not can_any_mod:
        raise PermissionDenied("Bạn không có quyền kiểm duyệt bài viết MXH.")

    candidates = (
        SocialReport.objects.select_related("post__author", "post__department", "reporter")
        .filter(status=SocialReportStatus.OPEN, post__is_deleted=False)
        .order_by("-created_at", "-id")
    )
    return [r for r in candidates if can_moderate_post(actor, r.post)]


@transaction.atomic
def moderate_social_post(
    actor: User,
    post: SocialPost,
    *,
    action: str,
    note: str = "",
    report: SocialReport | None = None,
) -> SocialModerationLog:
    if not can_moderate_post(actor, post):
        raise PermissionDenied("Bạn không có quyền kiểm duyệt bài viết trong phạm vi này.")
    if action not in {c[0] for c in SocialModerationAction.choices}:
        raise GovernanceError("Hành động kiểm duyệt không hợp lệ.")
    if post.author_id == actor.id and action in (
        SocialModerationAction.KEEP,
        SocialModerationAction.DISMISS,
        SocialModerationAction.RESTORE,
    ):
        raise PermissionDenied("Không thể tự bác bỏ báo cáo hoặc tự khôi phục bài viết của chính mình (`INV-03`).")

    clean_note = (note or "").strip()[:255]
    now = timezone.now()

    if action == SocialModerationAction.HIDE:
        post.moderation_status = SocialModerationStatus.HIDDEN
        post.save(update_fields=["moderation_status", "updated_at"])
        rep_status = SocialReportStatus.RESOLVED_HIDDEN
    elif action == SocialModerationAction.RESTORE:
        post.moderation_status = SocialModerationStatus.PUBLISHED
        post.save(update_fields=["moderation_status", "updated_at"])
        rep_status = SocialReportStatus.RESOLVED_KEPT
    elif action == SocialModerationAction.KEEP:
        post.moderation_status = SocialModerationStatus.PUBLISHED
        post.save(update_fields=["moderation_status", "updated_at"])
        rep_status = SocialReportStatus.RESOLVED_KEPT
    else:  # DISMISS
        rep_status = SocialReportStatus.DISMISSED

    if report is not None and report.post_id != post.id:
        raise GovernanceError("Báo cáo không thuộc bài viết này.")

    target_reports = (
        SocialReport.objects.filter(pk=report.pk, status=SocialReportStatus.OPEN)
        if report is not None
        else SocialReport.objects.filter(post=post, status=SocialReportStatus.OPEN)
    )
    target_reports.update(
        status=rep_status,
        handled_by=actor,
        resolution_note=clean_note,
        resolved_at=now,
    )

    log_entry = SocialModerationLog.objects.create(
        post=post,
        report=report,
        actor=actor,
        action=action,
        note=clean_note,
    )
    AuditLog.write(
        actor,
        f"Kiểm duyệt MXH: {log_entry.get_action_display()}",
        f"SocialPost #{post.id} ({post.visibility})",
        clean_note,
    )
    if post.author_id != actor.id and action in (SocialModerationAction.HIDE, SocialModerationAction.RESTORE):
        Notification.objects.create(
            user=post.author,
            kind=NotificationKind.SOCIAL_INTERACTION,
            title=f"Bài viết #{post.id} đã được {log_entry.get_action_display().lower()}"[:120],
            message=(clean_note or "Ban quản trị nội bộ vừa xử lý bài viết của bạn.")[:255],
            url=f"/workspace/mang-xa-hoi/bai/{post.id}/"[:255],
        )
    return log_entry


# ---------------------------------------------------------------------------
# 2. NHẮN TIN NỘI BỘ BẢO MẬT AES-256-GCM (`WF21`, `INV-05`, `BE-07`, `PA-02`)
# ---------------------------------------------------------------------------
def can_access_conversation(actor: User, conversation: Conversation) -> bool:
    """
    Kiểm tra bất biến `INV-05` (`Zero-Admin-Read`):
    Chỉ người dùng ĐANG là `ConversationMember(left_at IS NULL)` và có tư cách hoạt động hợp lệ
    mới được truy cập. Chủ nhiệm, Phó CN, Trưởng ban, Cố vấn, Admin Server ĐỀU bị `403` nếu
    không phải thành viên phòng chat!
    """
    if not _is_active_club_actor(actor):
        return False
    return ConversationMember.objects.filter(
        conversation=conversation,
        user=actor,
        left_at__isnull=True,
    ).exists()


def _sync_member_into_conversation(
    conv: Conversation,
    user: User,
    *,
    role: str = ConversationMemberRole.MEMBER,
) -> ConversationMember:
    cm, created = ConversationMember.objects.get_or_create(
        conversation=conv,
        user=user,
        defaults={"member_role": role},
    )
    if not created and cm.left_at is not None:
        cm.left_at = None
        cm.save(update_fields=["left_at"])
    return cm


@transaction.atomic
def ensure_club_conversation(created_by: User | None = None) -> Conversation:
    conv = Conversation.objects.select_for_update().filter(
        channel_scope_key="CLUB_WIDE"
    ).first()
    if conv is None:
        conv = Conversation.objects.create(
            conv_type=ConversationType.CLUB_WIDE,
            title="Kênh chung Toàn CLB KMG",
            channel_scope_key="CLUB_WIDE",
            encrypted_dek=generate_wrapped_dek(),
            created_by=created_by,
        )
    active_member_users = User.objects.filter(
        club_membership__status=ClubMembershipStatus.ACTIVE,
        is_locked=False,
    ).filter(
        department_memberships__status=DeptMembershipStatus.ACTIVE
    ).distinct()
    for u in active_member_users:
        if not _is_pure_advisor(u):
            _sync_member_into_conversation(conv, u)
    return conv


@transaction.atomic
def ensure_department_conversation(
    department: Department,
    *,
    created_by: User | None = None,
) -> Conversation:
    scope_key = f"DEPT:{department.id}"
    conv = Conversation.objects.select_for_update().filter(
        channel_scope_key=scope_key
    ).first()
    if conv is None:
        conv = Conversation.objects.create(
            conv_type=ConversationType.DEPARTMENT,
            title=f"Kênh nội bộ {department.name}",
            department=department,
            channel_scope_key=scope_key,
            encrypted_dek=generate_wrapped_dek(),
            created_by=created_by,
        )
    active_dept_users = User.objects.filter(
        department_memberships__department=department,
        department_memberships__status=DeptMembershipStatus.ACTIVE,
        club_membership__status=ClubMembershipStatus.ACTIVE,
        is_locked=False,
    ).distinct()
    for u in active_dept_users:
        if not _is_pure_advisor(u):
            _sync_member_into_conversation(conv, u)
    return conv


@transaction.atomic
def get_or_create_direct_conversation(actor: User, other_user: User) -> Conversation:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền sử dụng Nhắn tin nội bộ.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể nhắn tin.")
    if actor.id == other_user.id:
        raise GovernanceError("Không thể tạo hội thoại 1-1 với chính bản thân mình.")
    if not _is_active_club_actor(other_user) or _is_pure_advisor(other_user):
        raise GovernanceError("Người nhận hiện không ở trạng thái thành viên hoạt động của CLB.")

    lo, hi = sorted([actor.id, other_user.id])
    pair_key = f"{lo}:{hi}"
    conv = Conversation.objects.filter(direct_pair_key=pair_key).first()
    if conv is None:
        try:
            with transaction.atomic():
                conv = Conversation.objects.create(
                    conv_type=ConversationType.DIRECT_1ON1,
                    title="",
                    direct_pair_key=pair_key,
                    encrypted_dek=generate_wrapped_dek(),
                    created_by=actor,
                )
        except IntegrityError:
            conv = Conversation.objects.get(direct_pair_key=pair_key)

    _sync_member_into_conversation(conv, actor)
    _sync_member_into_conversation(conv, other_user)
    return conv


@transaction.atomic
def ensure_event_conversation(actor: User, club_event: ClubEventProfile) -> Conversation:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền truy cập phòng chat Sự kiện.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")

    is_participant = EventAttendance.objects.filter(
        club_event=club_event, user=actor
    ).exists()
    is_manager = (
        club_event.lead_department_id is not None
        and PermissionEngine.authorize(
            actor, "dept.event.manage_internal", department=club_event.lead_department
        )
    ) or PermissionEngine.authorize(actor, "club.event.approve")
    if not (is_participant or is_manager or club_event.proposed_by_id == actor.id):
        raise PermissionDenied("Bạn không thuộc danh sách tham gia hoặc điều phối sự kiện này.")

    scope_key = f"EVENT:{club_event.id}"
    conv = Conversation.objects.filter(channel_scope_key=scope_key).first()
    if conv is None:
        conv = Conversation.objects.create(
            conv_type=ConversationType.EVENT,
            title=f"Sự kiện: {club_event.event.name}"[:140],
            club_event=club_event,
            department=club_event.lead_department,
            channel_scope_key=scope_key,
            encrypted_dek=generate_wrapped_dek(),
            created_by=actor,
        )
    _sync_member_into_conversation(conv, actor, role=ConversationMemberRole.OWNER if is_manager else ConversationMemberRole.MEMBER)
    for att in EventAttendance.objects.select_related("user").filter(club_event=club_event):
        if _is_active_club_actor(att.user) and not _is_pure_advisor(att.user):
            _sync_member_into_conversation(conv, att.user)
    return conv


@transaction.atomic
def ensure_task_conversation(actor: User, task: ClubTask) -> Conversation:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền truy cập phòng chat Công việc.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")

    is_assignee = ClubTaskAssignee.objects.filter(
        task=task, user=actor, is_active=True
    ).exists()
    is_dept_mgr = PermissionEngine.authorize(
        actor, "dept.task.assign", department=task.department
    )
    if not (is_assignee or task.created_by_id == actor.id or is_dept_mgr):
        raise PermissionDenied("Bạn không tham gia hoặc phụ trách công việc này.")

    scope_key = f"TASK:{task.id}"
    conv = Conversation.objects.filter(channel_scope_key=scope_key).first()
    if conv is None:
        conv = Conversation.objects.create(
            conv_type=ConversationType.TASK,
            title=f"Công việc: {task.title}"[:140],
            task=task,
            department=task.department,
            channel_scope_key=scope_key,
            encrypted_dek=generate_wrapped_dek(),
            created_by=actor,
        )
    _sync_member_into_conversation(conv, actor)
    if task.created_by and _is_active_club_actor(task.created_by) and not _is_pure_advisor(task.created_by):
        _sync_member_into_conversation(conv, task.created_by, role=ConversationMemberRole.OWNER)
    for asg in ClubTaskAssignee.objects.select_related("user").filter(task=task, is_active=True):
        if _is_active_club_actor(asg.user) and not _is_pure_advisor(asg.user):
            _sync_member_into_conversation(conv, asg.user)
    return conv


@transaction.atomic
def create_custom_conversation(
    actor: User,
    *,
    title: str,
    member_users: list[User],
) -> Conversation:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Chỉ thành viên CLB đang hoạt động mới được tạo nhóm chat.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể tạo nhóm chat.")

    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Vui lòng nhập tên nhóm trò chuyện.")

    conv = Conversation.objects.create(
        conv_type=ConversationType.CUSTOM_GROUP,
        title=clean_title[:140],
        encrypted_dek=generate_wrapped_dek(),
        created_by=actor,
    )
    _sync_member_into_conversation(conv, actor, role=ConversationMemberRole.OWNER)
    for u in member_users:
        if u.pk != actor.id and _is_active_club_actor(u) and not _is_pure_advisor(u):
            _sync_member_into_conversation(conv, u, role=ConversationMemberRole.MEMBER)
    AuditLog.write(actor, "Tạo nhóm chat nội bộ", clean_title[:120])
    return conv


@transaction.atomic
def leave_conversation(actor: User, conversation: Conversation) -> ConversationMember:
    if not can_access_conversation(actor, conversation):
        raise PermissionDenied("Bạn hiện không phải thành viên của hội thoại này.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    cm = ConversationMember.objects.select_for_update().get(
        conversation=conversation, user=actor, left_at__isnull=True
    )
    cm.left_at = timezone.now()
    cm.save(update_fields=["left_at"])
    AuditLog.write(actor, "Rời hội thoại nội bộ", f"Conversation #{conversation.id}")
    return cm


# ---------------------------------------------------------------------------
# HOOK VÒNG ĐỜI `PA-02` (Tự động rời phòng chat khi Chuyển Ban / Tạm khoá / Rời CLB)
# ---------------------------------------------------------------------------
@transaction.atomic
def sync_user_department_chat_membership(
    user: User,
    department: Department,
    *,
    joined: bool,
) -> None:
    """
    Hook `PA-02`:
    - `joined=False` (Chuyển Ban / Rời Ban): đặt `left_at = NOW()` cho user ở phòng chat Ban cũ.
    - `joined=True` (Gia nhập / Chuyển tới Ban mới): kích hoạt/nối lại tư cách phòng chat Ban mới (nếu phòng đã tồn tại hoặc tạo nếu cần).
    """
    if joined:
        if not _is_pure_advisor(user):
            conv = ensure_department_conversation(department)
            _sync_member_into_conversation(conv, user)
    else:
        ConversationMember.objects.filter(
            user=user,
            conversation__conv_type=ConversationType.DEPARTMENT,
            conversation__department=department,
            left_at__isnull=True,
        ).update(left_at=timezone.now())


@transaction.atomic
def sync_user_club_wide_membership(user: User, *, active: bool) -> None:
    if active:
        if not _is_pure_advisor(user):
            conv = ensure_club_conversation()
            _sync_member_into_conversation(conv, user)
    else:
        ConversationMember.objects.filter(
            user=user,
            conversation__conv_type=ConversationType.CLUB_WIDE,
            left_at__isnull=True,
        ).update(left_at=timezone.now())


@transaction.atomic
def leave_all_club_chats(user: User, *, include_direct: bool = False) -> int:
    """Hook `PA-02`: Tạm khoá hoặc Rời CLB -> thu hồi toàn bộ phòng chat đang tham gia."""
    qs = ConversationMember.objects.filter(user=user, left_at__isnull=True)
    if not include_direct:
        qs = qs.exclude(conversation__conv_type=ConversationType.DIRECT_1ON1)
    return qs.update(left_at=timezone.now())


@transaction.atomic
def send_chat_message(
    actor: User,
    conversation: Conversation,
    *,
    plaintext: str = "",
    attachment_file=None,
    reply_to: ChatMessage | None = None,
) -> ChatMessage:
    if not can_access_conversation(actor, conversation):
        raise PermissionDenied("Bạn không phải thành viên hoạt động của hội thoại này (`INV-05`).")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể gửi tin nhắn.")

    clean_text = (plaintext or "").strip()
    prepared = None
    if attachment_file is not None:
        prepared = validate_and_prepare_social_attachment(attachment_file)
    if not clean_text and prepared is None:
        raise GovernanceError("Vui lòng nhập nội dung tin nhắn hoặc chọn tệp đính kèm.")

    if reply_to is not None and reply_to.conversation_id != conversation.id:
        raise GovernanceError("Tin nhắn được trả lời không thuộc hội thoại này.")

    dek = unwrap_dek(conversation.encrypted_dek)
    iv_nonce, ciphertext = encrypt_message_text(
        dek=dek,
        plaintext=clean_text,
        conversation_id=conversation.id,
        sender_id=actor.id,
    )

    msg = ChatMessage.objects.create(
        conversation=conversation,
        sender=actor,
        reply_to=reply_to,
        ciphertext=ciphertext,
        iv_nonce=iv_nonce,
        has_attachment=prepared is not None,
    )
    if prepared is not None:
        ChatAttachment.objects.create(
            message=msg,
            file=prepared["content_file"],
            original_filename=prepared["original_filename"],
            content_type=prepared["content_type"],
            file_size=prepared["file_size"],
            checksum_sha256=prepared["checksum_sha256"],
        )

    conversation.last_message_at = msg.created_at
    conversation.save(update_fields=["last_message_at"])

    ConversationMember.objects.filter(
        conversation=conversation, user=actor, left_at__isnull=True
    ).update(last_read_message_id=msg.id, last_read_at=timezone.now())

    # WF21: Thông báo ngắn gọn KHÔNG BAO GIỜ kèm nội dung plaintext tin nhắn và KHÔNG ghi AuditLog!
    room_label = conversation.title or conversation.get_conv_type_display()
    other_members = ConversationMember.objects.select_related("user").filter(
        conversation=conversation,
        left_at__isnull=True,
        is_muted=False,
    ).exclude(user=actor)
    notifs = [
        Notification(
            user=cm.user,
            kind=NotificationKind.CHAT_MESSAGE,
            title=f"Tin nhắn mới từ {actor.public_name}"[:120],
            message=f"Bạn có tin nhắn mới trong {room_label}."[:255],
            url=f"/workspace/tin-nhan/{conversation.id}/"[:255],
        )
        for cm in other_members
        if _is_active_club_actor(cm.user)
    ]
    if notifs:
        Notification.objects.bulk_create(notifs)
    return msg


def list_conversations_for_user(actor: User) -> list[dict]:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền truy cập Nhắn tin nội bộ.")

    memberships = list(
        ConversationMember.objects.select_related(
            "conversation", "conversation__department"
        )
        .filter(user=actor, left_at__isnull=True)
        .order_by("-conversation__last_message_at", "-conversation__created_at")
    )
    conv_ids = [m.conversation_id for m in memberships]
    all_peers = (
        ConversationMember.objects.select_related("user")
        .filter(conversation_id__in=conv_ids, left_at__isnull=True)
        .exclude(user=actor)
    )
    peers_by_conv: dict[int, list[User]] = {}
    for p in all_peers:
        peers_by_conv.setdefault(p.conversation_id, []).append(p.user)

    items = []
    for m in memberships:
        c = m.conversation
        peers = peers_by_conv.get(c.id, [])
        if c.conv_type == ConversationType.DIRECT_1ON1 and peers:
            display_title = peers[0].public_name
            peer_user = peers[0]
        else:
            display_title = c.title or c.get_conv_type_display()
            peer_user = peers[0] if len(peers) == 1 else None

        latest_msg = ChatMessage.objects.filter(conversation=c).order_by("-id").first()
        has_unread = bool(
            latest_msg
            and (m.last_read_message_id is None or latest_msg.id > m.last_read_message_id)
            and latest_msg.sender_id != actor.id
        )
        items.append(
            {
                "conversation": c,
                "id": c.id,
                "conv_type": c.conv_type,
                "conv_type_label": c.get_conv_type_display(),
                "display_title": display_title,
                "peer_user": peer_user,
                "member_count": 1 + len(peers),
                "has_unread": has_unread,
                "last_message_at": c.last_message_at or c.created_at,
            }
        )
    return items


def list_decrypted_messages(
    actor: User,
    conversation: Conversation,
    *,
    after_id: int | None = None,
    search_query: str = "",
    mark_read: bool = True,
) -> list[dict]:
    """Giải mã tin nhắn AES-256-GCM trong RAM CHỈ khi `can_access_conversation` == True (`INV-05`)."""
    if not can_access_conversation(actor, conversation):
        raise PermissionDenied("Bạn không có quyền đọc hội thoại này (`INV-05`).")

    dek = unwrap_dek(conversation.encrypted_dek)
    qs = (
        ChatMessage.objects.filter(conversation=conversation)
        .select_related("sender", "reply_to__sender")
        .prefetch_related("attachments", "reactions")
        .order_by("id")
    )
    if after_id is not None:
        qs = qs.filter(id__gt=after_id)

    messages_list = list(qs[:200])
    q_lower = (search_query or "").strip().lower()
    result = []
    max_msg_id = None
    now = timezone.now()

    for msg in messages_list:
        max_msg_id = msg.id
        if msg.is_recalled:
            text = "[Tin nhắn đã thu hồi]"
        else:
            text = decrypt_message_text(
                dek=dek,
                iv_nonce=msg.iv_nonce,
                ciphertext=msg.ciphertext,
                conversation_id=msg.conversation_id,
                sender_id=msg.sender_id,
            )

        if q_lower and q_lower not in text.lower():
            continue

        rx_counts: dict[str, int] = {}
        my_rx = None
        for r in msg.reactions.all():
            rx_counts[r.emoji] = rx_counts.get(r.emoji, 0) + 1
            if r.user_id == actor.id:
                my_rx = r.emoji

        atts = (
            []
            if msg.is_recalled
            else [
                {
                    "id": a.id,
                    "original_filename": a.original_filename,
                    "content_type": a.content_type,
                    "file_size": a.file_size,
                    "is_image": (a.content_type or "").startswith("image/"),
                }
                for a in msg.attachments.all()
            ]
        )

        reply_preview = None
        if msg.reply_to_id:
            reply_preview = {
                "id": msg.reply_to_id,
                "sender_name": msg.reply_to.sender.public_name,
                "is_recalled": msg.reply_to.is_recalled,
            }

        result.append(
            {
                "id": msg.id,
                "sender_id": msg.sender_id,
                "sender_name": msg.sender.public_name,
                "sender_avatar": msg.sender.avatar.url if msg.sender.avatar else "",
                "is_mine": msg.sender_id == actor.id,
                "text": text,
                "is_recalled": msg.is_recalled,
                "attachments": atts,
                "reaction_counts": rx_counts,
                "my_reaction": my_rx,
                "reply_to": reply_preview,
                "can_recall": (
                    (not _is_pure_advisor(actor))
                    and msg.sender_id == actor.id
                    and (not msg.is_recalled)
                    and ((now - msg.created_at) <= _RECALL_WINDOW)
                ),
                "can_report": (
                    (not _is_pure_advisor(actor))
                    and msg.sender_id != actor.id
                    and (not msg.is_recalled)
                ),
                "created_at": msg.created_at,
                "created_at_iso": msg.created_at.isoformat(),
            }
        )

    if mark_read and max_msg_id is not None:
        ConversationMember.objects.filter(
            conversation=conversation, user=actor, left_at__isnull=True
        ).update(last_read_message_id=max_msg_id, last_read_at=timezone.now())

    return result


@transaction.atomic
def recall_chat_message(actor: User, message: ChatMessage) -> ChatMessage:
    if not can_access_conversation(actor, message.conversation):
        raise PermissionDenied("Bạn không có quyền truy cập hội thoại này.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if message.sender_id != actor.id:
        raise PermissionDenied("Chỉ người gửi ban đầu mới được thu hồi tin nhắn của chính mình.")
    if message.is_recalled:
        raise GovernanceError("Tin nhắn này đã được thu hồi trước đó.")
    if (timezone.now() - message.created_at) > _RECALL_WINDOW:
        raise GovernanceError("Đã quá cửa sổ 15 phút để thu hồi tin nhắn này.")

    # Xoá mật mã bản gốc trong CSDL khi thu hồi!
    dek = unwrap_dek(message.conversation.encrypted_dek)
    iv_nonce, ciphertext = encrypt_message_text(
        dek=dek,
        plaintext="[RECALLED]",
        conversation_id=message.conversation_id,
        sender_id=message.sender_id,
    )
    message.ciphertext = ciphertext
    message.iv_nonce = iv_nonce
    message.is_recalled = True
    message.recalled_at = timezone.now()
    message.has_attachment = False
    message.save(
        update_fields=["ciphertext", "iv_nonce", "is_recalled", "recalled_at", "has_attachment"]
    )
    return message


@transaction.atomic
def toggle_chat_reaction(
    actor: User,
    message: ChatMessage,
    *,
    emoji: str = ChatReactionEmoji.LIKE,
) -> dict:
    if not can_access_conversation(actor, message.conversation):
        raise PermissionDenied("Bạn không phải thành viên hội thoại này.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if emoji not in {c[0] for c in ChatReactionEmoji.choices}:
        raise GovernanceError("Biểu tượng cảm xúc không hợp lệ.")
    if message.is_recalled:
        raise GovernanceError("Không thể thả cảm xúc cho tin nhắn đã thu hồi.")

    existing = ChatReaction.objects.filter(message=message, user=actor).first()
    if existing is not None:
        if existing.emoji == emoji:
            existing.delete()
            return {"active": False, "emoji": None}
        existing.emoji = emoji
        existing.save(update_fields=["emoji"])
        return {"active": True, "emoji": emoji}

    ChatReaction.objects.create(message=message, user=actor, emoji=emoji)
    return {"active": True, "emoji": emoji}


@transaction.atomic
def report_message_abuse(
    actor: User,
    message: ChatMessage,
    *,
    reason: str,
) -> MessageAbuseReport:
    """
    Cơ chế `BE-07` dưới kiến trúc `Zero-Admin-Read`:
    Nạn nhân gửi duy nhất bản chụp tin nhắn bị tố cáo kèm chữ ký `HMAC-SHA256` của máy chủ
    tới Ban Chủ nhiệm Nhân sự — tuyệt đối không mở quyền đọc toàn bộ hội thoại!
    """
    if not can_access_conversation(actor, message.conversation):
        raise PermissionDenied("Bạn không có quyền truy cập tin nhắn này.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if message.sender_id == actor.id:
        raise GovernanceError("Không thể tự tố cáo tin nhắn của chính mình.")
    if message.is_recalled:
        raise GovernanceError("Tin nhắn đã được thu hồi.")

    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise GovernanceError("Vui lòng mô tả hành vi vi phạm để Ban Chủ nhiệm xem xét.")

    dek = unwrap_dek(message.conversation.encrypted_dek)
    plaintext_snapshot = decrypt_message_text(
        dek=dek,
        iv_nonce=message.iv_nonce,
        ciphertext=message.ciphertext,
        conversation_id=message.conversation_id,
        sender_id=message.sender_id,
    )
    if not plaintext_snapshot and message.has_attachment:
        plaintext_snapshot = "[Tin nhắn đính kèm tệp/hình ảnh]"

    hmac_proof = sign_abuse_report_snapshot(
        message_id=message.id,
        conversation_id=message.conversation_id,
        sender_id=message.sender_id,
        created_at_iso=message.created_at.isoformat(),
        plaintext_snapshot=plaintext_snapshot,
    )
    try:
        report = MessageAbuseReport.objects.create(
            reporter=actor,
            reported_user=message.sender,
            conversation=message.conversation,
            message=message,
            reason=clean_reason[:1000],
            verified_plaintext_snapshot=plaintext_snapshot,
            hmac_proof=hmac_proof,
        )
    except IntegrityError as exc:
        raise GovernanceError("Bạn đã gửi tố cáo đối với tin nhắn này rồi.") from exc

    # Thông báo cho Chủ nhiệm & Phó CN Nhân sự (`club.member.suspend_temporary`)
    notified_ids: set[int] = set()
    for u in User.objects.filter(is_locked=False).distinct():
        if u.id in (actor.id, message.sender_id) or _is_pure_advisor(u):
            continue
        if PermissionEngine.authorize(u, "club.member.suspend_temporary"):
            Notification.objects.create(
                user=u,
                kind=NotificationKind.ABUSE_REPORT,
                title=f"Báo cáo tin nhắn vi phạm (#{report.id})"[:120],
                message="Có bằng chứng tin nhắn được xác thực HMAC gửi tới BCN Nhân sự xem xét.",
                url="/workspace/tin-nhan/bao-cao/",
            )
            notified_ids.add(u.id)

    AuditLog.write(
        actor,
        "Gửi tố cáo tin nhắn vi phạm (BE-07)",
        f"MessageAbuseReport #{report.id}",
        f"Đối tượng: {message.sender.public_name} · Không ghi nội dung tin nhắn",
    )
    return report


def can_review_abuse_reports(actor: User) -> bool:
    if not _is_active_club_actor(actor) or _is_pure_advisor(actor):
        return False
    return PermissionEngine.authorize(actor, "club.member.suspend_temporary")


def list_abuse_reports_for_reviewer(actor: User) -> list[dict]:
    if not can_review_abuse_reports(actor):
        raise PermissionDenied("Chỉ Chủ nhiệm hoặc Phó CN Nhân sự mới có quyền xem báo cáo vi phạm tin nhắn.")
    reports = (
        MessageAbuseReport.objects.select_related(
            "reporter", "reported_user", "conversation", "message", "handled_by"
        )
        .order_by("-created_at", "-id")
    )
    items = []
    for rep in reports:
        hmac_valid = verify_abuse_report_snapshot(
            message_id=rep.message_id,
            conversation_id=rep.conversation_id,
            sender_id=rep.message.sender_id,
            created_at_iso=rep.message.created_at.isoformat(),
            plaintext_snapshot=rep.verified_plaintext_snapshot,
            hmac_proof=rep.hmac_proof,
        )
        items.append(
            {
                "report": rep,
                "hmac_valid": hmac_valid,
                "can_adjudicate": actor.id not in (rep.reporter_id, rep.reported_user_id)
                and rep.status in (AbuseReportStatus.OPEN, AbuseReportStatus.UNDER_REVIEW),
            }
        )
    return items


@transaction.atomic
def review_message_abuse_report(
    actor: User,
    report: MessageAbuseReport,
    *,
    status: str,
    resolution_note: str = "",
) -> MessageAbuseReport:
    if not can_review_abuse_reports(actor):
        raise PermissionDenied("Bạn không có quyền xử lý báo cáo vi phạm tin nhắn.")
    if actor.id in (report.reporter_id, report.reported_user_id):
        raise PermissionDenied("Không thể tự xử lý báo cáo mà bản thân là bên liên quan (`INV-03`).")
    if status not in {c[0] for c in AbuseReportStatus.choices}:
        raise GovernanceError("Trạng thái xử lý tố cáo không hợp lệ.")

    is_valid = verify_abuse_report_snapshot(
        message_id=report.message_id,
        conversation_id=report.conversation_id,
        sender_id=report.message.sender_id,
        created_at_iso=report.message.created_at.isoformat(),
        plaintext_snapshot=report.verified_plaintext_snapshot,
        hmac_proof=report.hmac_proof,
    )
    if not is_valid:
        raise GovernanceError("Chữ ký HMAC bằng chứng không khớp, từ chối xử lý tự động.", code="HMAC_INVALID")

    report.status = status
    report.handled_by = actor
    report.resolution_note = (resolution_note or "").strip()[:255]
    report.resolved_at = timezone.now()
    report.save(update_fields=["status", "handled_by", "resolution_note", "resolved_at"])
    AuditLog.write(
        actor,
        "Xử lý tố cáo tin nhắn (BE-07)",
        f"MessageAbuseReport #{report.id} -> {report.get_status_display()}",
        report.resolution_note,
    )
    return report


# ---------------------------------------------------------------------------
# 3. PLAYLIST ÂM NHẠC CÁ NHÂN & TẶNG NHẠC (`BE-05`, `SEC-04`, `SEC-05`, `INV-05`)
# ---------------------------------------------------------------------------
def can_view_playlist(actor: User, playlist: MusicPlaylist) -> bool:
    """
    Tuân thủ tuyệt đối `INV-05`:
    - Playlist `PRIVATE` CHỈ duy nhất `playlist.owner` xem được. Chủ nhiệm / Admin Server -> `False` (`403`)!
    - Playlist `CLUB_SHARED`: thành viên/cán bộ/cố vấn CLB đang hoạt động đều xem được.
    """
    if not _is_active_club_actor(actor):
        return False
    if playlist.visibility == PlaylistVisibility.PRIVATE:
        return playlist.owner_id == actor.id
    return playlist.visibility == PlaylistVisibility.CLUB_SHARED


@transaction.atomic
def create_playlist(
    actor: User,
    *,
    title: str,
    description: str = "",
    visibility: str = PlaylistVisibility.PRIVATE,
) -> MusicPlaylist:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Chỉ thành viên CLB đang hoạt động mới được tạo playlist.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể tạo playlist.")
    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Vui lòng nhập tên playlist.")
    if visibility not in {c[0] for c in PlaylistVisibility.choices}:
        raise GovernanceError("Chế độ hiển thị playlist không hợp lệ.")
    return MusicPlaylist.objects.create(
        owner=actor,
        title=clean_title[:120],
        description=(description or "").strip()[:300],
        visibility=visibility,
    )


@transaction.atomic
def update_playlist(
    actor: User,
    playlist: MusicPlaylist,
    *,
    title: str | None = None,
    description: str | None = None,
    visibility: str | None = None,
) -> MusicPlaylist:
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if playlist.owner_id != actor.id:
        raise PermissionDenied("Chỉ chủ sở hữu mới có quyền chỉnh sửa playlist này (`INV-05`).")
    update_fields = ["updated_at"]
    if title is not None and title.strip():
        playlist.title = title.strip()[:120]
        update_fields.append("title")
    if description is not None:
        playlist.description = description.strip()[:300]
        update_fields.append("description")
    if visibility is not None:
        if visibility not in {c[0] for c in PlaylistVisibility.choices}:
            raise GovernanceError("Chế độ hiển thị playlist không hợp lệ.")
        playlist.visibility = visibility
        update_fields.append("visibility")
    playlist.save(update_fields=update_fields)
    return playlist


@transaction.atomic
def add_track_to_playlist(
    actor: User,
    playlist: MusicPlaylist,
    *,
    track_url: str,
    title: str,
    artist_name: str = "",
    duration_seconds: int | None = None,
) -> PlaylistItem:
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if playlist.owner_id != actor.id:
        raise PermissionDenied("Chỉ chủ sở hữu mới được thêm bài hát vào playlist (`INV-05`).")
    clean_title = (title or "").strip()
    if not clean_title:
        raise GovernanceError("Vui lòng nhập tên bài hát.")
    clean_url, provider, ext_id = parse_music_track_url(track_url)
    item = PlaylistItem.objects.create(
        playlist=playlist,
        source_provider=provider,
        external_track_id=ext_id,
        track_url=clean_url[:400],
        title=clean_title[:160],
        artist_name=(artist_name or "").strip()[:120],
        duration_seconds=duration_seconds if (duration_seconds and duration_seconds > 0) else None,
        sort_order=playlist.items.count() + 1,
    )
    playlist.save(update_fields=["updated_at"])
    return item


@transaction.atomic
def remove_track_from_playlist(actor: User, item: PlaylistItem) -> None:
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if item.playlist.owner_id != actor.id:
        raise PermissionDenied("Chỉ chủ sở hữu mới được xoá bài hát khỏi playlist (`INV-05`).")
    playlist = item.playlist
    item.delete()
    playlist.save(update_fields=["updated_at"])


def search_recipients_for_share(request, actor: User, query: str) -> list[dict]:
    """
    Tìm kiếm thành viên nhận quà âm nhạc (`BE-05` + `SEC-04` + `SEC-06`):
    - Áp dụng Rate Limit chặt chẽ theo IP + User ID.
    - Giới hạn tối đa `<= 10` kết quả.
    - Trả về ĐÚNG 5 trường định danh tối thiểu chống trùng tên:
      `id`, `member_code`, `public_name`, `avatar_url`, `department_names`.
    - TUYỆT ĐỐI ẩn `email`, `phone`, `mssv` (`SEC-04`).
    """
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Bạn không có quyền tìm kiếm thành viên nội bộ.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")

    if request is not None and is_rate_limited(
        request,
        scope="social_music_recipient_search",
        limit=30,
        window_seconds=60,
        identifier=str(actor.id),
    ):
        raise GovernanceError(
            "Bạn đang tìm kiếm quá nhanh. Vui lòng chờ 1 phút trước khi thử lại.",
            code="RATE_LIMITED",
        )

    q = (query or "").strip()
    if not q:
        return []

    candidates = list(
        User.objects.select_related("club_membership")
        .filter(
            club_membership__status=ClubMembershipStatus.ACTIVE,
            is_locked=False,
        )
        .exclude(pk=actor.id)
        .filter(
            Q(full_name__icontains=q)
            | Q(display_name__icontains=q)
            | Q(username__icontains=q)
            | Q(club_membership__member_code__icontains=q)
        )
        .distinct()
        .order_by("full_name", "username", "id")[:10]
    )
    user_ids = [u.id for u in candidates]
    dept_map: dict[int, list[str]] = {}
    for dm in DepartmentMembership.objects.select_related("department").filter(
        user_id__in=user_ids,
        status=DeptMembershipStatus.ACTIVE,
        department__is_active=True,
    ):
        dept_map.setdefault(dm.user_id, []).append(dm.department.name)

    return [
        {
            "id": u.id,
            "member_code": u.club_membership.member_code,
            "public_name": u.public_name,
            "avatar_url": u.avatar.url if u.avatar else "",
            "department_names": dept_map.get(u.id, []),
        }
        for u in candidates
    ]


@transaction.atomic
def send_music_share(
    actor: User,
    *,
    recipient: User,
    track_url: str = "",
    title: str = "",
    artist_name: str = "",
    personal_message: str = "",
    source_item: PlaylistItem | None = None,
) -> MusicShare:
    if not _is_active_club_actor(actor):
        raise PermissionDenied("Chỉ thành viên CLB mới có quyền tặng nhạc.")
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể tặng nhạc.")
    if actor.id == recipient.id:
        raise GovernanceError("Không thể tự gửi tặng bài hát cho chính mình.")
    if not _is_active_club_actor(recipient) or _is_pure_advisor(recipient):
        raise GovernanceError("Người nhận hiện không phải thành viên CLB đang hoạt động.")

    if source_item is not None:
        if not can_view_playlist(actor, source_item.playlist):
            raise PermissionDenied("Bạn không có quyền truy cập bài hát nguồn này.")
        clean_url = source_item.track_url
        provider = source_item.source_provider
        clean_title = source_item.title
        clean_artist = source_item.artist_name
    else:
        clean_url, provider, _ = parse_music_track_url(track_url)
        clean_title = (title or "").strip()
        if not clean_title:
            raise GovernanceError("Vui lòng nhập tên bài hát muốn gửi tặng.")
        clean_artist = (artist_name or "").strip()[:120]

    share = MusicShare.objects.create(
        sender=actor,
        recipient=recipient,
        source_playlist_item=source_item,
        source_provider=provider,
        track_url=clean_url[:400],
        title=clean_title[:160],
        artist_name=clean_artist,
        personal_message=(personal_message or "").strip()[:300],
    )
    Notification.objects.create(
        user=recipient,
        kind=NotificationKind.MUSIC_SHARE,
        title=f"{actor.public_name} đã gửi tặng bạn một bài hát"[:120],
        message=(
            f"“{share.title}”" + (f" — {share.personal_message[:100]}" if share.personal_message else "")
        )[:255],
        url="/workspace/nhac/",
    )
    return share


@transaction.atomic
def save_shared_track_to_playlist(
    actor: User,
    music_share: MusicShare,
    target_playlist: MusicPlaylist | None = None,
) -> PlaylistItem:
    _assert_not_advisor(actor, "Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
    if music_share.recipient_id != actor.id:
        raise PermissionDenied("Chỉ người nhận mới được lưu bài hát được tặng này.")

    if target_playlist is not None:
        if target_playlist.owner_id != actor.id:
            raise PermissionDenied("Bạn chỉ có thể lưu bài hát vào playlist của chính mình (`INV-05`).")
        playlist = target_playlist
    else:
        playlist = MusicPlaylist.objects.filter(owner=actor).order_by("-updated_at").first()
        if playlist is None:
            playlist = MusicPlaylist.objects.create(
                owner=actor,
                title="Nhạc được tặng & Yêu thích",
                description="Danh sách lưu các bài hát nhận được từ thành viên KMG.",
                visibility=PlaylistVisibility.PRIVATE,
            )

    item = add_track_to_playlist(
        actor,
        playlist,
        track_url=music_share.track_url,
        title=music_share.title,
        artist_name=music_share.artist_name,
    )
    music_share.is_saved_to_playlist = True
    music_share.saved_item = item
    music_share.save(update_fields=["is_saved_to_playlist", "saved_item"])
    return item
