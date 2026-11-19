from django.db import models

from accounts.models import User


class NotificationKind(models.TextChoices):
    TICKET_CONFIRMED = "TICKET_OK", "Vé đã xác nhận"
    TICKET_PENDING = "TICKET_PEND", "Vé chờ thanh toán"
    TICKET_EXPIRED = "TICKET_EXP", "Vé hết hạn thanh toán"
    EVENT_CANCELLED = "EVENT_CXL", "Sự kiện bị huỷ"
    EVENT_REMINDER = "REMINDER", "Nhắc lịch"
    WAITLIST_PROMOTED = "WAIT_OK", "Có vé từ danh sách chờ"
    WAITLIST_EXPIRED = "WAIT_EXP", "Danh sách chờ kết thúc"
    TASK_ASSIGNED = "TASK", "Được giao việc"
    # Phase 2 — Core Operations & Proactive Reminders (Mục 3.5)
    TASK_DUE = "TASK_DUE", "Nhắc hạn công việc"
    TASK_REVIEWED = "TASK_REV", "Kết quả duyệt công việc"
    EVENT_RSVP = "EVENT_RSVP", "Nhắc phản hồi sự kiện"
    ANNOUNCEMENT = "ANNOUNCE", "Thông báo chính thức CLB"
    DISCIPLINE_ALERT = "DISCIPLINE", "Cảnh báo tư cách / kỷ luật"
    APPEAL_UPDATE = "APPEAL", "Cập nhật khiếu nại"
    GOVERNANCE = "GOVERNANCE", "Quyết định tổ chức"
    # Phase 3 — Department Management, Training, Practice, Proposals & Vault
    TRAINING_REMINDER = "TRAINING", "Nhắc lịch đào tạo"
    PRACTICE_REMINDER = "PRACTICE", "Nhắc lịch tập luyện"
    PROPOSAL_UPDATE = "PROPOSAL", "Cập nhật đề xuất"
    DOCUMENT_SECURITY = "DOC_SEC", "Cảnh báo bảo mật tài liệu"
    # Phase 4 — Internal Social, Messaging & Music Playlist
    SOCIAL_INTERACTION = "SOCIAL", "Tương tác mạng xã hội"
    CHAT_MESSAGE = "CHAT", "Tin nhắn nội bộ mới"
    MUSIC_SHARE = "MUSIC_SHARE", "Được tặng bài hát"
    ABUSE_REPORT = "ABUSE", "Báo cáo vi phạm nội dung"
    # Phase 5 — Immutable Finance, 7-Criteria Evaluation & Recognition
    FINANCE_TX = "FINANCE", "Cập nhật Quỹ & Tài chính CLB"
    EVALUATION = "EVAL", "Đánh giá định kỳ & Phản hồi"
    RECOGNITION = "RECOG", "Vinh danh thành viên KMG"
    # Tuyển thành viên & Vé
    APPLICATION = "APPLY", "Kết quả ứng tuyển"
    TICKET_TRANSFER = "TICKET_TRF", "Chuyển nhượng vé"


NotificationKind.TASK_DEADLINE = NotificationKind.TASK_DUE


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=16, choices=NotificationKind.choices)
    title = models.CharField(max_length=120)
    message = models.CharField(max_length=255)
    url = models.CharField(max_length=255, blank=True)  # đường dẫn NỘI BỘ, vd "/ve/cua-toi/"
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Thông báo"
        verbose_name_plural = "Thông báo"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]

    def __str__(self):
        return f"{self.user} - {self.title}"

    @property
    def icon(self):
        """Icon Bootstrap theo loại thông báo, dùng ở chuông và trang danh sách."""
        return {
            NotificationKind.TICKET_CONFIRMED: "bi-check-circle",
            NotificationKind.TICKET_PENDING: "bi-hourglass-split",
            NotificationKind.TICKET_EXPIRED: "bi-x-circle",
            NotificationKind.EVENT_CANCELLED: "bi-calendar-x",
            NotificationKind.EVENT_REMINDER: "bi-alarm",
            NotificationKind.WAITLIST_PROMOTED: "bi-stars",
            NotificationKind.WAITLIST_EXPIRED: "bi-hourglass-bottom",
            NotificationKind.TASK_ASSIGNED: "bi-list-task",
            NotificationKind.TASK_DEADLINE: "bi-hourglass-top",
            NotificationKind.TASK_REVIEWED: "bi-clipboard2-check",
            NotificationKind.EVENT_RSVP: "bi-calendar2-check",
            NotificationKind.ANNOUNCEMENT: "bi-megaphone",
            NotificationKind.DISCIPLINE_ALERT: "bi-exclamation-octagon",
            NotificationKind.APPEAL_UPDATE: "bi-shield-check",
            NotificationKind.GOVERNANCE: "bi-award",
            NotificationKind.TRAINING_REMINDER: "bi-mortarboard",
            NotificationKind.PRACTICE_REMINDER: "bi-music-note-list",
            NotificationKind.PROPOSAL_UPDATE: "bi-lightbulb",
            NotificationKind.DOCUMENT_SECURITY: "bi-shield-lock-fill",
            NotificationKind.SOCIAL_INTERACTION: "bi-chat-heart",
            NotificationKind.CHAT_MESSAGE: "bi-chat-dots-fill",
            NotificationKind.MUSIC_SHARE: "bi-music-note-beamed",
            NotificationKind.ABUSE_REPORT: "bi-flag-fill",
            NotificationKind.FINANCE_TX: "bi-cash-coin",
            NotificationKind.EVALUATION: "bi-clipboard2-pulse",
            NotificationKind.RECOGNITION: "bi-trophy-fill",
            NotificationKind.APPLICATION: "bi-person-check",
            NotificationKind.TICKET_TRANSFER: "bi-arrow-left-right",
        }.get(self.kind, "bi-bell")


class NotificationPreference(models.Model):
    """Tùy chọn nhận thông báo đa kênh của từng thành viên (Chỉ thị 3.5 & DB-06)."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="notification_preference",
        verbose_name="Người dùng",
    )
    email_important = models.BooleanField("Email thông báo quan trọng", default=True)
    email_task_deadline = models.BooleanField("Email nhắc hạn công việc", default=True)
    email_event_rsvp = models.BooleanField("Email nhắc phản hồi sự kiện", default=True)
    web_push_enabled = models.BooleanField("Thông báo đẩy PWA trên thiết bị", default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cài đặt thông báo"
        verbose_name_plural = "Cài đặt thông báo"

    def __str__(self):
        return f"Cài đặt thông báo: {self.user}"


class PushSubscription(models.Model):
    """Đăng ký nhận Web Push Notification chuẩn W3C VAPID / PWA (DB-06)."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
        verbose_name="Người dùng",
    )
    endpoint = models.CharField("Push Endpoint", max_length=500)
    p256dh = models.CharField("Khóa P-256DH", max_length=255)
    auth = models.CharField("Khóa Auth", max_length=128)
    user_agent = models.CharField("Thiết bị / Trình duyệt", max_length=255, blank=True)
    is_active = models.BooleanField("Đang kích hoạt", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Đăng ký Push PWA"
        verbose_name_plural = "Đăng ký Push PWA"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "endpoint"],
                name="uniq_push_sub_user_endpoint",
            )
        ]

    def __str__(self):
        return f"Push PWA ({self.user})"


class ReminderTargetType(models.TextChoices):
    CLUB_TASK = "CLUB_TASK", "Công việc CLB"
    EVENT_RSVP = "EVENT_RSVP", "Phản hồi RSVP Sự kiện"
    TRAINING_SESSION = "TRAINING_SESSION", "Khóa / Buổi đào tạo"
    PRACTICE_SESSION = "PRACTICE_SESSION", "Buổi tập luyện / Rehearsal"


class ReminderStage(models.TextChoices):
    ASSIGNED = "ASSIGNED", "Ngay khi giao / mở"
    T_48H = "T_48H", "Trước hạn 48 giờ"
    T_12H = "T_12H", "Trước hạn 12 giờ"
    OVERDUE = "OVERDUE", "Vừa quá hạn"
    FROZEN = "FROZEN", "Đã chốt danh sách"


class ScheduledReminder(models.Model):
    """Sổ cái chống gửi trùng lịch nhắc tự động (`idempotency` — DB-06)."""

    target_type = models.CharField(
        "Loại đối tượng", max_length=20, choices=ReminderTargetType.choices
    )
    target_id = models.PositiveBigIntegerField("ID đối tượng")
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="scheduled_reminders",
        verbose_name="Người nhận",
    )
    stage = models.CharField("Mốc nhắc", max_length=16, choices=ReminderStage.choices)
    sent_in_app = models.BooleanField("Đã gửi trên web", default=False)
    sent_email = models.BooleanField("Đã gửi email", default=False)
    sent_at = models.DateTimeField("Gửi lúc", auto_now_add=True)
    notification = models.OneToOneField(
        Notification, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="scheduled_reminder",
    )
    email_category = models.CharField(max_length=32, blank=True)
    email_pending = models.BooleanField(default=False, db_index=True)
    email_attempts = models.PositiveIntegerField(default=0)
    email_last_attempt_at = models.DateTimeField(null=True, blank=True)
    email_last_error = models.CharField(max_length=80, blank=True)

    class Meta:
        verbose_name = "Lịch sử nhắc việc tự động"
        verbose_name_plural = "Lịch sử nhắc việc tự động"
        ordering = ["-sent_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["target_type", "target_id", "recipient", "stage"],
                name="uniq_scheduled_reminder_once",
            )
        ]

    def __str__(self):
        return f"{self.target_type}#{self.target_id} -> {self.recipient} ({self.stage})"
