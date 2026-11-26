"""
Mô hình dữ liệu cho quy trình Đánh giá & Cải tiến AI (LLMOps):
  1. ClubKnowledge    : Kho tri thức CLB phục vụ RAG Grounding.
  2. AIPromptProfile  : Quản trị giọng văn, chỉ dẫn & ví dụ Few-Shot cho từng tác vụ AI.
  3. AIInteractionLog : Nhật ký hỏi đáp & đánh giá 👍/👎 (đã che PII theo mẫu).
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .egress import CLASSIFICATION_CHOICES, DataClassification

# Số ví dụ few-shot tối đa được đưa vào prompt
MAX_FEW_SHOT = 3


class KnowledgeCategory(models.TextChoices):
    GENERAL = "GENERAL", "Thông tin chung CLB"
    EVENT = "EVENT", "Sự kiện & Vé"
    RECRUITMENT = "RECRUITMENT", "Tuyển thành viên"
    FINANCE = "FINANCE", "Tài chính & Quỹ"
    RULE = "RULE", "Nội quy & Quy định"
    MUSIC = "MUSIC", "Kiến thức âm nhạc"
    STUDENT_LIFE = "STUDENT_LIFE", "Đời sống sinh viên"
    TRAINING = "TRAINING", "Đào tạo & Kỹ năng"
    TECH = "TECH", "Kỹ thuật & Thiết bị"


class KnowledgeVisibility(models.TextChoices):
    PUBLIC = "PUBLIC", "Công khai"
    INTERNAL = "INTERNAL", "Nội bộ CLB"
    CONFIDENTIAL = "CONFIDENTIAL", "Mật / Quản trị"


class ApprovalStatus(models.TextChoices):
    DRAFT = "DRAFT", "Bản nháp"
    PENDING = "PENDING", "Chờ phê duyệt"
    APPROVED = "APPROVED", "Đã phê duyệt"
    ARCHIVED = "ARCHIVED", "Lưu trữ / Hết hạn"


class ClubKnowledge(models.Model):
    """Một mục tri thức/FAQ của CLB dùng làm dữ liệu nền (RAG) cho trợ lý AI."""

    knowledge_id = models.CharField(
        "Mã định danh", max_length=64, unique=True, null=True, blank=True, db_index=True,
        help_text="Mã duy nhất (vd: K01, MUSIC-K01) để đồng bộ không trùng lặp.",
    )
    title = models.CharField("Tiêu đề", max_length=160)
    category = models.CharField(
        "Danh mục", max_length=16, choices=KnowledgeCategory.choices,
        default=KnowledgeCategory.GENERAL,
    )
    visibility = models.CharField(
        "Phân loại truy cập",
        max_length=16,
        choices=KnowledgeVisibility.choices,
        default=KnowledgeVisibility.INTERNAL,
        db_index=True,
    )
    approval_status = models.CharField(
        "Trạng thái phê duyệt",
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.APPROVED,
        db_index=True,
    )
    keywords = models.CharField(
        "Từ khoá gợi nhớ", max_length=255, blank=True,
        help_text="Phân cách bằng dấu phẩy, vd: tuyen quan, casting, ban truyen thong",
    )
    content = models.TextField("Nội dung tri thức")
    source_urls = models.JSONField("Nguồn tham chiếu", default=list, blank=True)
    source_note = models.CharField("Ghi chú nguồn", max_length=255, blank=True)
    version = models.CharField("Phiên bản", max_length=24, default="1.0")
    effective_date = models.DateField("Ngày hiệu lực", null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_knowledge_items",
        verbose_name="Người phụ trách",
    )
    is_admin_edited = models.BooleanField("Đã được quản trị chỉnh sửa", default=False)
    revision_history = models.JSONField("Lịch sử chỉnh sửa", default=list, blank=True)
    priority = models.PositiveSmallIntegerField(
        "Độ ưu tiên", default=10,
        help_text="Số càng nhỏ càng ưu tiên khi ngữ cảnh dài.",
    )
    is_active = models.BooleanField("Đang áp dụng", default=True)
    updated_at = models.DateTimeField("Cập nhật lúc", auto_now=True)

    class Meta:
        verbose_name = "Tri thức CLB (RAG)"
        verbose_name_plural = "Kho tri thức CLB (RAG)"
        ordering = ["priority", "-updated_at"]

    def __str__(self):
        prefix = f"{self.knowledge_id} · " if self.knowledge_id else ""
        return f"[{self.get_category_display()}] {prefix}{self.title}"


class AITaskKey(models.TextChoices):
    CHATBOT = "chatbot", "Trợ lý hỏi đáp (Chatbot)"
    SUGGEST_TASKS = "suggest_tasks", "Gợi ý công việc BTC"
    EVENT_MARKETING = "event_marketing", "Biên tập truyền thông sự kiện"
    SCREEN_APPLICATION = "screen_application", "Sàng lọc đơn tuyển thành viên"
    POSTMORTEM = "postmortem", "Báo cáo tổng kết sự kiện"
    PROPOSAL_REVIEW = "proposal_review", "Thẩm định đề xuất hoạt động"
    OPERATIONS_ANALYTICS = "operations_analytics", "Phân tích KPI vận hành CLB"
    SOCIAL_DIGEST = "social_digest", "Tóm tắt bảng tin nội bộ"


class AIPromptProfile(models.Model):
    """
    Cấu hình giọng văn, chỉ dẫn bổ sung và ví dụ Few-Shot cho từng tác vụ AI.
    Cho phép Ban Chủ nhiệm tinh chỉnh hành vi AI ngay trên Admin/Studio mà không sửa code.
    """

    task_key = models.CharField(
        "Tác vụ AI", max_length=32, unique=True, choices=AITaskKey.choices,
    )
    brand_voice = models.TextField(
        "Giọng văn thương hiệu (Brand Voice)", blank=True,
        help_text="Mô tả phong cách trả lời mong muốn của CLB.",
    )
    extra_instructions = models.TextField(
        "Chỉ dẫn bổ sung", blank=True,
        help_text="Các quy tắc riêng áp dụng thêm vào prompt gốc.",
    )
    few_shot_examples = models.JSONField(
        "Ví dụ mẫu Few-Shot", default=list, blank=True,
        help_text='Danh sách JSON các cặp mẫu: [{"input": "...", "output": "..."}]',
    )
    is_active = models.BooleanField("Đang kích hoạt", default=True)
    updated_at = models.DateTimeField("Cập nhật lúc", auto_now=True)

    class Meta:
        verbose_name = "Cấu hình Prompt AI"
        verbose_name_plural = "Cấu hình Prompt AI"
        ordering = ["task_key"]

    def __str__(self):
        return self.get_task_key_display()

    def clean(self):
        """Báo lỗi ngay trên Admin/Studio thay vì âm thầm bỏ qua ví dụ sai."""
        if self.few_shot_examples in (None, ""):
            self.few_shot_examples = []
        examples = self.few_shot_examples
        valid = (
            isinstance(examples, list)
            and len(examples) <= MAX_FEW_SHOT
            and all(isinstance(e, dict)
                    and all(isinstance(e.get(k), str) and e[k].strip()
                            for k in ("input", "output"))
                    for e in examples)
        )
        if not valid:
            raise ValidationError({"few_shot_examples": (
                f"Cần danh sách tối đa {MAX_FEW_SHOT} mục dạng "
                '[{"input": "...", "output": "..."}], không để trống.')})


class FeedbackRating(models.TextChoices):
    NONE = "NONE", "Chưa đánh giá"
    UP = "UP", "Hữu ích (👍)"
    DOWN = "DOWN", "Chưa đúng (👎)"


class AIInteractionLog(models.Model):
    """
    Nhật ký hỏi đáp phục vụ đánh giá chất lượng.
    Không có trường user/IP. Nội dung được che PII theo mẫu (aiassist/privacy.py,
    xem giới hạn ở đó); câu trả lời cá nhân (vé, công việc) không được lưu.
    """

    question = models.CharField("Câu hỏi (đã che PII)", max_length=500)
    intent = models.CharField("Ý định nhận diện", max_length=64, blank=True)
    source = models.CharField("Nguồn trả lời", max_length=16, default="rules")
    answer_preview = models.TextField("Câu trả lời", blank=True)
    feedback = models.CharField(
        "Đánh giá người dùng", max_length=8, choices=FeedbackRating.choices,
        default=FeedbackRating.NONE,
    )
    feedback_note = models.CharField("Góp ý ngắn", max_length=255, blank=True)
    classification = models.CharField(
        "Phân loại dữ liệu",
        max_length=16,
        choices=CLASSIFICATION_CHOICES,
        default=DataClassification.INTERNAL.value,
        db_index=True,
    )
    latency_ms = models.PositiveIntegerField("Thời gian xử lý (ms)", null=True, blank=True)
    model_name = models.CharField("Model AI", max_length=64, blank=True)
    prompt_version = models.CharField("Phiên bản prompt", max_length=12, blank=True)
    created_at = models.DateTimeField("Thời gian", auto_now_add=True)

    class Meta:
        verbose_name = "Nhật ký tương tác AI"
        verbose_name_plural = "Nhật ký tương tác AI"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.source}/{self.feedback}] {self.question[:60]}"


class MusicLevel(models.TextChoices):
    NEWBIE = "NEWBIE", "Mới bắt đầu"
    BASIC = "BASIC", "Cơ bản"
    INTERMEDIATE = "INTERMEDIATE", "Trung cấp"
    ADVANCED = "ADVANCED", "Nâng cao"


class MusicLearningProfile(models.Model):
    """Hồ sơ học nhạc cá nhân hóa của thành viên/sinh viên (cho phép bật/tắt/xóa)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="music_learning_profile",
        verbose_name="Người học",
    )
    personalization_enabled = models.BooleanField("Cho phép cá nhân hóa AI", default=True)
    instrument = models.CharField("Nhạc cụ / Bộ môn chính", max_length=64, default="Guitar")
    level = models.CharField(
        "Trình độ hiện tại", max_length=16, choices=MusicLevel.choices, default=MusicLevel.NEWBIE,
    )
    goal = models.CharField("Mục tiêu học tập", max_length=200, blank=True, default="Đệm hát cơ bản")
    favorite_genres = models.CharField("Thể loại yêu thích", max_length=160, blank=True)
    daily_minutes = models.PositiveSmallIntegerField("Thời gian tập mỗi ngày (phút)", default=20)
    current_challenges = models.TextField("Khó khăn hiện tại", blank=True)
    active_plan = models.JSONField("Lộ trình luyện tập hiện tại", default=dict, blank=True)
    mentor_notes = models.TextField("Nhận xét của mentor", blank=True)
    updated_at = models.DateTimeField("Cập nhật lúc", auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ học nhạc AI"
        verbose_name_plural = "Hồ sơ học nhạc AI"

    def __str__(self):
        return f"{self.user} — {self.instrument} ({self.get_level_display()})"


class MusicPracticeLog(models.Model):
    """Nhật ký luyện tập nhạc thực tế để tính tiến độ (không tự sinh % giả)."""

    profile = models.ForeignKey(
        MusicLearningProfile,
        on_delete=models.CASCADE,
        related_name="practice_logs",
        verbose_name="Hồ sơ học nhạc",
    )
    practiced_at = models.DateField("Ngày tập", auto_now_add=True)
    duration_minutes = models.PositiveSmallIntegerField("Thời lượng (phút)", default=15)
    focus_topic = models.CharField("Nội dung luyện tập", max_length=160)
    completed_exercise = models.BooleanField("Hoàn thành bài tập", default=True)
    self_rating = models.PositiveSmallIntegerField("Tự đánh giá (1-5)", default=3)
    notes = models.CharField("Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField("Ghi nhận lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Nhật ký luyện tập"
        verbose_name_plural = "Nhật ký luyện tập"
        ordering = ["-practiced_at", "-created_at"]

    def __str__(self):
        return f"{self.profile.instrument}: {self.focus_topic} ({self.duration_minutes}p)"
