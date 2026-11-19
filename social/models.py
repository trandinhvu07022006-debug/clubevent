"""
Mô hình dữ liệu Phase 4: Internal Social, Encrypted Messaging & Music Playlists (`social`):

1. Mạng xã hội Nội bộ (`WF19`, `PA-05`):
   - `SocialPost` (`PERSONAL` | `CLUB` | `DEPARTMENT` | `CUSTOM_GROUP`), soft-delete (`is_deleted`),
     bài chia sẻ (`shared_post` tuân thủ kiểm tra kép `PA-05`), ảnh/tệp đính kèm trong `PrivateVaultStorage` (`SEC-01`).
   - `SocialPostAudienceMember`, `SocialComment` (phân cấp trả lời + `@mention`), `SocialReaction`,
     `SocialReport`, và sổ cái kiểm duyệt bất biến `SocialModerationLog`.
2. Nhắn tin Nội bộ Bảo mật (`WF21`, `INV-05`, `BE-07`, `DB-08`, `PA-02`):
   - `Conversation` (`DIRECT_1ON1`, `DEPARTMENT`, `CLUB_WIDE`, `EVENT`, `TASK`, `CUSTOM_GROUP`),
     chống trùng lặp 1-1 qua `direct_pair_key` (`UNIQUE NULL` trên MySQL 8.4), lưu DEK bọc `encrypted_dek`.
   - `ConversationMember` (`left_at IS NULL` là điều kiện chân lý duy nhất cho `INV-05`).
   - `ChatMessage` (CHỈ lưu `ciphertext` + `iv_nonce` AES-256-GCM, tuyệt đối không lưu plaintext!),
     `ChatAttachment` (`PrivateVaultStorage`), `ChatReaction`, `MessageAbuseReport` (chữ ký `hmac_proof`).
3. Playlist Âm nhạc Cá nhân & Tặng nhạc (`BE-05`, `SEC-04`, `SEC-05`, `R07`, `INV-05`):
   - `MusicPlaylist` (`PRIVATE` mặc định | `CLUB_SHARED`), `PlaylistItem` (chỉ URL/Metadata, không lưu audio vi phạm bản quyền),
     `MusicShare` (tặng nhạc kèm lời nhắn & xác thực thành viên chống nhầm tên).
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.storage import private_vault_storage
from operations.models import ClubEventProfile, ClubTask
from organization.models import Department


def social_post_upload_path(instance, filename: str) -> str:
    return f"social_posts/{instance.post_id or 'tmp'}/{filename}"


def chat_attachment_upload_path(instance, filename: str) -> str:
    return f"chat_attachments/{instance.message_id or 'tmp'}/{filename}"


# ---------------------------------------------------------------------------
# 1. MẠNG XÃ HỘI NỘI BỘ (`WF19`, `PA-05`, `SEC-01`)
# ---------------------------------------------------------------------------
class SocialPostVisibility(models.TextChoices):
    PERSONAL = "PERSONAL", "Riêng tư (Chỉ mình tôi)"
    CLUB = "CLUB", "Toàn CLB KMG"
    DEPARTMENT = "DEPARTMENT", "Nội bộ Ban"
    CUSTOM_GROUP = "CUSTOM_GROUP", "Nhóm thành viên tùy chọn"


class SocialModerationStatus(models.TextChoices):
    PUBLISHED = "PUBLISHED", "Đang hiển thị"
    PENDING_REVIEW = "PENDING_REVIEW", "Chờ kiểm duyệt"
    HIDDEN = "HIDDEN", "Đã ẩn do vi phạm"


class SocialPost(models.Model):
    """Bài viết trên Mạng xã hội Nội bộ KMG."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_posts",
        verbose_name="Tác giả",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="social_posts",
        verbose_name="Ban sở hữu",
    )
    visibility = models.CharField(
        "Phạm vi hiển thị",
        max_length=16,
        choices=SocialPostVisibility.choices,
        default=SocialPostVisibility.CLUB,
        db_index=True,
    )
    content = models.TextField("Nội dung bài viết", max_length=5000, blank=True)
    shared_post = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reposts",
        verbose_name="Bài viết gốc được chia sẻ",
    )
    link_url = models.URLField("Liên kết tham khảo", max_length=300, blank=True)
    moderation_status = models.CharField(
        "Trạng thái kiểm duyệt",
        max_length=16,
        choices=SocialModerationStatus.choices,
        default=SocialModerationStatus.PUBLISHED,
        db_index=True,
    )
    is_deleted = models.BooleanField("Đã xoá mềm", default=False, db_index=True)
    deleted_at = models.DateTimeField("Xoá lúc", null=True, blank=True)
    created_at = models.DateTimeField("Đăng lúc", auto_now_add=True)
    updated_at = models.DateTimeField("Cập nhật lúc", auto_now=True)

    class Meta:
        verbose_name = "Bài viết MXH nội bộ"
        verbose_name_plural = "Bài viết MXH nội bộ"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["visibility", "moderation_status", "is_deleted", "-created_at"],
                name="idx_soc_post_vis_mod_dt",
            ),
            models.Index(
                fields=["department", "is_deleted", "-created_at"],
                name="idx_soc_post_dept_dt",
            ),
            models.Index(
                fields=["author", "is_deleted", "-created_at"],
                name="idx_soc_post_author_dt",
            ),
        ]

    def __str__(self):
        return f"[{self.visibility}] {self.author.public_name} (#{self.pk})"


class SocialPostAudienceMember(models.Model):
    """Danh sách thành viên được phép xem bài đăng phạm vi `CUSTOM_GROUP` (`PA-05`)."""

    post = models.ForeignKey(
        SocialPost,
        on_delete=models.CASCADE,
        related_name="audience_members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="custom_post_audiences",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Thành viên xem bài viết tùy chọn"
        verbose_name_plural = "Thành viên xem bài viết tùy chọn"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "user"],
                name="uniq_soc_post_aud_user",
            ),
        ]


class SocialAttachmentType(models.TextChoices):
    IMAGE = "IMAGE", "Hình ảnh"
    FILE = "FILE", "Tệp đính kèm"


class SocialPostAttachment(models.Model):
    """Tệp/ảnh đính kèm bài đăng MXH lưu an toàn trong `PrivateVaultStorage` (`SEC-01`)."""

    post = models.ForeignKey(
        SocialPost,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    attachment_type = models.CharField(
        "Loại tệp",
        max_length=10,
        choices=SocialAttachmentType.choices,
        default=SocialAttachmentType.IMAGE,
    )
    file = models.FileField(
        "Tệp lưu trữ bảo mật",
        upload_to=social_post_upload_path,
        storage=private_vault_storage,
    )
    original_filename = models.CharField("Tên tệp gốc", max_length=255)
    content_type = models.CharField("MIME Type", max_length=120, blank=True)
    file_size = models.PositiveIntegerField("Dung lượng (bytes)", default=0)
    checksum_sha256 = models.CharField("SHA-256", max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tệp đính kèm bài đăng MXH"
        verbose_name_plural = "Tệp đính kèm bài đăng MXH"
        ordering = ["id"]


class SocialComment(models.Model):
    """Bình luận & phản hồi phân cấp (threaded reply + `@mention`)."""

    post = models.ForeignKey(
        SocialPost,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    content = models.TextField("Nội dung bình luận", max_length=2000)
    mentioned_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="social_mentions",
    )
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bình luận MXH"
        verbose_name_plural = "Bình luận MXH"
        ordering = ["created_at", "id"]


class SocialReactionType(models.TextChoices):
    LIKE = "LIKE", "Thích"
    LOVE = "LOVE", "Yêu thích"
    FIRE = "FIRE", "Cháy hết mình"
    CLAP = "CLAP", "Vỗ tay"
    MUSIC = "MUSIC", "Chất nhạc"


class SocialReaction(models.Model):
    """Cảm xúc duy nhất mỗi người dùng trên một bài viết hoặc một bình luận."""

    post = models.ForeignKey(
        SocialPost,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
    )
    comment = models.ForeignKey(
        SocialComment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_reactions",
    )
    reaction_type = models.CharField(
        "Loại cảm xúc",
        max_length=10,
        choices=SocialReactionType.choices,
        default=SocialReactionType.LIKE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cảm xúc MXH"
        verbose_name_plural = "Cảm xúc MXH"
        constraints = [
            models.UniqueConstraint(
                fields=["post", "user"],
                name="uniq_soc_react_post_u",
            ),
            models.UniqueConstraint(
                fields=["comment", "user"],
                name="uniq_soc_react_cmt_u",
            ),
        ]

    def clean(self):
        if (self.post_id is None) == (self.comment_id is None):
            raise ValidationError("Reaction phải gắn vào đúng 1 bài viết HOẶC 1 bình luận.")


class SocialReportStatus(models.TextChoices):
    OPEN = "OPEN", "Chờ xử lý"
    RESOLVED_HIDDEN = "RESOLVED_HIDDEN", "Đã ẩn bài viết"
    RESOLVED_KEPT = "RESOLVED_KEPT", "Giữ nguyên bài viết"
    DISMISSED = "DISMISSED", "Bác bỏ báo cáo"


class SocialReport(models.Model):
    """Phiếu báo cáo bài viết vi phạm phân tuyến theo đúng phạm vi Ban / CLB (`WF19`)."""

    post = models.ForeignKey(
        SocialPost,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="filed_social_reports",
    )
    reason = models.TextField("Lý do báo cáo", max_length=1000)
    status = models.CharField(
        "Trạng thái xử lý",
        max_length=20,
        choices=SocialReportStatus.choices,
        default=SocialReportStatus.OPEN,
        db_index=True,
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_social_reports",
    )
    resolution_note = models.CharField("Ghi chú xử lý", max_length=255, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Báo cáo bài viết MXH"
        verbose_name_plural = "Báo cáo bài viết MXH"
        ordering = ["-created_at", "-id"]


class SocialModerationAction(models.TextChoices):
    HIDE = "HIDE", "Ẩn bài viết"
    RESTORE = "RESTORE", "Khôi phục hiển thị"
    KEEP = "KEEP", "Giữ bài viết"
    DISMISS = "DISMISS", "Bác bỏ báo cáo"


class SocialModerationLog(models.Model):
    """Sổ cái kiểm duyệt MXH bất biến (Append-only Ledger — chặn sửa/xoá)."""

    post = models.ForeignKey(
        SocialPost,
        on_delete=models.CASCADE,
        related_name="moderation_logs",
    )
    report = models.ForeignKey(
        SocialReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="moderation_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="social_moderation_actions",
    )
    action = models.CharField(
        "Hành động kiểm duyệt",
        max_length=16,
        choices=SocialModerationAction.choices,
    )
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Nhật ký kiểm duyệt MXH"
        verbose_name_plural = "Nhật ký kiểm duyệt MXH"
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("SocialModerationLog là sổ cái bất biến, cấm chỉnh sửa.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("SocialModerationLog là sổ cái bất biến, cấm xoá.")


# ---------------------------------------------------------------------------
# 2. NHẮN TIN NỘI BỘ BẢO MẬT MÃ HÓA AES-256-GCM (`WF21`, `INV-05`, `BE-07`)
# ---------------------------------------------------------------------------
class ConversationType(models.TextChoices):
    DIRECT_1ON1 = "DIRECT_1ON1", "Nhắn tin riêng 1-1"
    DEPARTMENT = "DEPARTMENT", "Kênh nhóm Ban"
    CLUB_WIDE = "CLUB_WIDE", "Kênh chung Toàn CLB"
    EVENT = "EVENT", "Nhóm điều phối Sự kiện"
    TASK = "TASK", "Nhóm trao đổi Công việc"
    CUSTOM_GROUP = "CUSTOM_GROUP", "Nhóm trò chuyện tùy chọn"


class Conversation(models.Model):
    """
    Hội thoại nội bộ bảo mật:
    - Chứa DEK riêng đã bọc AES-256-GCM (`encrypted_dek`) bằng `CHAT_MASTER_KEK`.
    - `direct_pair_key` (`UNIQUE NULL`) chống tạo trùng hội thoại 1-1 trên MySQL 8.4.
    - `channel_scope_key` (`UNIQUE NULL`) đảm bảo duy nhất 1 kênh cho Toàn CLB / mỗi Ban / Sự kiện / Task.
    """

    conv_type = models.CharField(
        "Loại hội thoại",
        max_length=16,
        choices=ConversationType.choices,
        db_index=True,
    )
    title = models.CharField("Tên hội thoại", max_length=140, blank=True)
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations",
    )
    club_event = models.ForeignKey(
        ClubEventProfile,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations",
    )
    task = models.ForeignKey(
        ClubTask,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="conversations",
    )
    direct_pair_key = models.CharField(
        "Khóa cặp 1-1 duy nhất",
        max_length=48,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    channel_scope_key = models.CharField(
        "Khóa kênh theo đối tượng",
        max_length=64,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    encrypted_dek = models.TextField("Khóa hội thoại AES-256-GCM đã bọc")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_conversations",
    )
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Hội thoại nội bộ"
        verbose_name_plural = "Hội thoại nội bộ"
        ordering = ["-last_message_at", "-created_at", "-id"]

    def __str__(self):
        return self.title or f"{self.get_conv_type_display()} (#{self.pk})"


class ConversationMemberRole(models.TextChoices):
    OWNER = "OWNER", "Quản trị nhóm"
    MEMBER = "MEMBER", "Thành viên"


class ConversationMember(models.Model):
    """
    Bảng chân lý duy nhất cho Bất biến `INV-05` (`Zero-Admin-Read`) & Hook rời Ban `PA-02`.
    Chỉ thành viên có `left_at IS NULL` mới có quyền đọc/gửi tin nhắn trong hội thoại này.
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversation_memberships",
    )
    member_role = models.CharField(
        "Vai trò trong hội thoại",
        max_length=12,
        choices=ConversationMemberRole.choices,
        default=ConversationMemberRole.MEMBER,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField("Rời hội thoại lúc", null=True, blank=True, db_index=True)
    last_read_message_id = models.PositiveBigIntegerField(null=True, blank=True)
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Thành viên hội thoại"
        verbose_name_plural = "Thành viên hội thoại"
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="uniq_conv_member_user",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "left_at"],
                name="idx_conv_mem_u_left",
            ),
        ]


class ChatMessage(models.Model):
    """
    Bản tin nhắn nội bộ đã mã hóa AES-256-GCM.
    TUYỆT ĐỐI KHÔNG chứa cột văn bản rõ `plaintext`!
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sent_chat_messages",
    )
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )
    ciphertext = models.BinaryField("Bản mã AES-256-GCM")
    iv_nonce = models.BinaryField("Nonce 96-bit", max_length=16)
    has_attachment = models.BooleanField(default=False)
    is_recalled = models.BooleanField("Đã thu hồi", default=False)
    recalled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Tin nhắn mã hóa"
        verbose_name_plural = "Tin nhắn mã hóa"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["conversation", "id"], name="idx_chat_msg_conv_id"),
        ]


class ChatAttachment(models.Model):
    """Tệp/ảnh đính kèm tin nhắn lưu trong `PrivateVaultStorage` (`SEC-01`)."""

    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(
        "Tệp đính kèm bảo mật",
        upload_to=chat_attachment_upload_path,
        storage=private_vault_storage,
    )
    original_filename = models.CharField("Tên tệp gốc", max_length=255)
    content_type = models.CharField("MIME Type", max_length=120, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tệp đính kèm tin nhắn"
        verbose_name_plural = "Tệp đính kèm tin nhắn"


class ChatReactionEmoji(models.TextChoices):
    LIKE = "LIKE", "Thích"
    LOVE = "LOVE", "Thả tim"
    LAUGH = "LAUGH", "Cười"
    FIRE = "FIRE", "Tuyệt vời"
    CLAP = "CLAP", "Vỗ tay"


class ChatReaction(models.Model):
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_reactions",
    )
    emoji = models.CharField(
        max_length=16,
        choices=ChatReactionEmoji.choices,
        default=ChatReactionEmoji.LIKE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Cảm xúc tin nhắn"
        verbose_name_plural = "Cảm xúc tin nhắn"
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user"],
                name="uniq_chat_react_msg_u",
            ),
        ]


class AbuseReportStatus(models.TextChoices):
    OPEN = "OPEN", "Chờ BCN xem xét"
    UNDER_REVIEW = "UNDER_REVIEW", "Đang xác minh"
    ACTION_TAKEN = "ACTION_TAKEN", "Đã xử lý kỷ luật"
    DISMISSED = "DISMISSED", "Bác bỏ tố cáo"


class MessageAbuseReport(models.Model):
    """
    Báo cáo tin nhắn quấy rối/vi phạm dưới kiến trúc `Zero-Admin-Read` (`BE-07`, `DB-08`):
    - Chỉ chụp duy nhất nội dung tin nhắn bị tố cáo + chữ ký `HMAC-SHA256` của máy chủ
      để người tố cáo không thể ngụy tạo lời khai, đồng thời Ban Chủ nhiệm Nhân sự vẫn
      KHÔNG xem được các tin nhắn còn lại trong hộp thư riêng!
    """

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_abuse_reports_filed",
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_abuse_reports_against",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="abuse_reports",
    )
    message = models.ForeignKey(
        ChatMessage,
        on_delete=models.CASCADE,
        related_name="abuse_reports",
    )
    reason = models.TextField("Mô tả hành vi vi phạm", max_length=1000)
    verified_plaintext_snapshot = models.TextField("Bản chụp nguyên văn được xác thực HMAC")
    hmac_proof = models.CharField("Chữ ký HMAC-SHA256", max_length=64)
    status = models.CharField(
        "Trạng thái xử lý",
        max_length=16,
        choices=AbuseReportStatus.choices,
        default=AbuseReportStatus.OPEN,
        db_index=True,
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_abuse_reports",
    )
    resolution_note = models.CharField("Kết luận xử lý", max_length=255, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tố cáo vi phạm tin nhắn"
        verbose_name_plural = "Tố cáo vi phạm tin nhắn"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["reporter", "message"],
                name="uniq_msg_abuse_rep_msg",
            ),
        ]


# ---------------------------------------------------------------------------
# 3. PERSONAL MUSIC PLAYLIST & TẶNG NHẠC (`BE-05`, `SEC-04`, `SEC-05`, `INV-05`)
# ---------------------------------------------------------------------------
class PlaylistVisibility(models.TextChoices):
    PRIVATE = "PRIVATE", "Riêng tư (Chỉ chủ sở hữu)"
    CLUB_SHARED = "CLUB_SHARED", "Chia sẻ với Thành viên CLB"


class MusicPlaylist(models.Model):
    """
    Danh sách nhạc cá nhân:
    - Mặc định `PRIVATE`: tuân thủ `INV-05`, không một ai khác (kể cả Chủ nhiệm / Admin) được xem.
    - Cho phép chuyển sang `CLUB_SHARED` để chia sẻ gu âm nhạc với thành viên trong CLB.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="music_playlists",
        verbose_name="Chủ sở hữu",
    )
    title = models.CharField("Tên playlist", max_length=120)
    description = models.CharField("Mô tả ngắn", max_length=300, blank=True)
    visibility = models.CharField(
        "Chế độ hiển thị",
        max_length=16,
        choices=PlaylistVisibility.choices,
        default=PlaylistVisibility.PRIVATE,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Playlist âm nhạc"
        verbose_name_plural = "Playlist âm nhạc"
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"{self.title} ({self.owner.public_name})"


class MusicProvider(models.TextChoices):
    YOUTUBE = "YOUTUBE", "YouTube"
    SPOTIFY = "SPOTIFY", "Spotify"
    SOUNDCLOUD = "SOUNDCLOUD", "SoundCloud"
    EXTERNAL = "EXTERNAL", "Liên kết hợp lệ"


class PlaylistItem(models.Model):
    """Bài hát trong playlist (CHỈ lưu liên kết & metadata, chống vi phạm bản quyền `R07` & chống SSRF `SEC-05`)."""

    playlist = models.ForeignKey(
        MusicPlaylist,
        on_delete=models.CASCADE,
        related_name="items",
    )
    source_provider = models.CharField(
        "Nền tảng nguồn",
        max_length=16,
        choices=MusicProvider.choices,
        default=MusicProvider.YOUTUBE,
    )
    external_track_id = models.CharField("Track/Video ID", max_length=80, blank=True)
    track_url = models.URLField("Đường dẫn bài hát", max_length=400)
    title = models.CharField("Tên bài hát", max_length=160)
    artist_name = models.CharField("Nghệ sĩ / Ban nhạc", max_length=120, blank=True)
    duration_seconds = models.PositiveIntegerField("Thời lượng (giây)", null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bài hát trong Playlist"
        verbose_name_plural = "Bài hát trong Playlist"
        ordering = ["sort_order", "-added_at", "-id"]


class MusicShare(models.Model):
    """Tặng bài hát cho thành viên trong CLB qua xác thực định danh (`BE-05`, `SEC-04`)."""

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_music_shares",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_music_shares",
    )
    source_playlist_item = models.ForeignKey(
        PlaylistItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shares",
    )
    source_provider = models.CharField(
        "Nền tảng nguồn",
        max_length=16,
        choices=MusicProvider.choices,
        default=MusicProvider.YOUTUBE,
    )
    track_url = models.URLField("Đường dẫn bài hát", max_length=400)
    title = models.CharField("Tên bài hát", max_length=160)
    artist_name = models.CharField("Nghệ sĩ / Ban nhạc", max_length=120, blank=True)
    personal_message = models.CharField("Lời nhắn gửi tặng", max_length=300, blank=True)
    is_saved_to_playlist = models.BooleanField(default=False)
    saved_item = models.ForeignKey(
        PlaylistItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Lời tặng âm nhạc"
        verbose_name_plural = "Lời tặng âm nhạc"
        ordering = ["-created_at", "-id"]
