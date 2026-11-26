"""
Mô hình dữ liệu cho quy trình Đánh giá & Cải tiến AI (LLMOps):
  1. ClubKnowledge    : Kho tri thức CLB phục vụ RAG Grounding.
  2. AIPromptProfile  : Quản trị giọng văn, chỉ dẫn & ví dụ Few-Shot cho từng tác vụ AI.
  3. AIInteractionLog : Nhật ký hỏi đáp & đánh giá 👍/👎 (đã che PII theo mẫu).
"""
from django.core.exceptions import ValidationError
from django.db import models

# Số ví dụ few-shot tối đa được đưa vào prompt
MAX_FEW_SHOT = 3


class KnowledgeCategory(models.TextChoices):
    GENERAL = "GENERAL", "Thông tin chung CLB"
    EVENT = "EVENT", "Sự kiện & Vé"
    RECRUITMENT = "RECRUITMENT", "Tuyển thành viên"
    FINANCE = "FINANCE", "Tài chính & Quỹ"
    RULE = "RULE", "Nội quy & Quy định"


class KnowledgeVisibility(models.TextChoices):
    PUBLIC = "PUBLIC", "Công khai"
    INTERNAL = "INTERNAL", "Nội bộ CLB"
    CONFIDENTIAL = "CONFIDENTIAL", "Mật / Quản trị"


class ClubKnowledge(models.Model):
    """Một mục tri thức/FAQ của CLB dùng làm dữ liệu nền (RAG) cho trợ lý AI."""

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
    keywords = models.CharField(
        "Từ khoá gợi nhớ", max_length=255, blank=True,
        help_text="Phân cách bằng dấu phẩy, vd: tuyen quan, casting, ban truyen thong",
    )
    content = models.TextField("Nội dung tri thức")
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
        return f"[{self.get_category_display()}] {self.title}"


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
