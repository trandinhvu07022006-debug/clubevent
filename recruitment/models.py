"""
Tuyển thành viên theo ĐỢT.

Vì sao không cho "đăng ký là thành viên" như trước: ai tạo tài khoản để mua
vé cũng thành thành viên -> danh sách loãng, Ban không biết ai thật sự sinh
hoạt. Giờ tài khoản tự tạo chỉ là KHÁCH; muốn vào CLB phải nộp đơn trong một
đợt tuyển, chọn Ban, qua casting/phỏng vấn rồi mới được nhận.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from organizing.models import Department


class RecruitmentRound(models.Model):
    """Một đợt tuyển (vd: Tuyển thành viên học kỳ 1). Chỉ nhận đơn trong thời gian mở."""

    name = models.CharField("Tên đợt tuyển", max_length=120)
    description = models.TextField(
        "Thông tin đợt tuyển", blank=True,
        help_text="Yêu cầu, lịch casting/phỏng vấn, quyền lợi… Hiện trên trang Tuyển thành viên.")
    opens_at = models.DateTimeField("Mở nhận đơn")
    closes_at = models.DateTimeField("Hạn nộp đơn")
    departments = models.ManyToManyField(
        Department, blank=True, related_name="recruitment_rounds",
        verbose_name="Ban nhận đơn", help_text="Để trống = mọi Ban đều nhận.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Đợt tuyển"
        verbose_name_plural = "Đợt tuyển"
        ordering = ["-opens_at"]

    def __str__(self):
        return self.name

    @property
    def is_open(self):
        return self.opens_at <= timezone.now() <= self.closes_at

    @property
    def is_upcoming(self):
        return timezone.now() < self.opens_at

    def open_departments(self):
        """Ban nhận đơn trong đợt này (để trống = tất cả)."""
        chosen = self.departments.all()
        return chosen if chosen.exists() else Department.objects.all()

    @classmethod
    def current(cls):
        """Đợt đang mở (sắp hết hạn trước), hoặc None."""
        now = timezone.now()
        return (cls.objects.filter(opens_at__lte=now, closes_at__gte=now)
                .order_by("closes_at").first())

    @classmethod
    def next_upcoming(cls):
        return cls.objects.filter(opens_at__gt=timezone.now()).order_by("opens_at").first()


class ApplicationStatus(models.TextChoices):
    PENDING = "PENDING", "Chờ duyệt"
    INTERVIEW = "INTERVIEW", "Hẹn casting / phỏng vấn"
    ACCEPTED = "ACCEPTED", "Đã nhận"
    REJECTED = "REJECTED", "Chưa phù hợp"
    WITHDRAWN = "WITHDRAWN", "Đã rút đơn"


# Chuyển trạng thái hợp lệ khi DUYỆT (rút đơn là việc của ứng viên, xử lý riêng)
REVIEW_TRANSITIONS = {
    ApplicationStatus.PENDING: [ApplicationStatus.INTERVIEW, ApplicationStatus.ACCEPTED,
                                ApplicationStatus.REJECTED],
    ApplicationStatus.INTERVIEW: [ApplicationStatus.ACCEPTED, ApplicationStatus.REJECTED],
}


class SkillLevel(models.TextChoices):
    NEW = "NEW", "Mới bắt đầu, muốn được học"
    BASIC = "BASIC", "Biết cơ bản"
    GOOD = "GOOD", "Khá, đã tập lâu"
    STAGE = "STAGE", "Đã từng biểu diễn / làm sản phẩm"


class Application(models.Model):
    """Đơn ứng tuyển của một Khách vào một Ban, trong một đợt tuyển."""

    round = models.ForeignKey(RecruitmentRound, on_delete=models.CASCADE,
                              related_name="applications", verbose_name="Đợt tuyển")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="applications", verbose_name="Ứng viên")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True,
                                   related_name="applications", verbose_name="Ban mong muốn")
    strengths = models.CharField(
        "Nhạc cụ / thế mạnh", max_length=200,
        help_text="Vd: Guitar đệm hát, Vocal; hoặc Thiết kế, Chụp ảnh, Dẫn chương trình")
    level = models.CharField("Trình độ", max_length=6, choices=SkillLevel.choices,
                             default=SkillLevel.BASIC)
    portfolio_url = models.URLField(
        "Link video / sản phẩm", blank=True,
        help_text="Không bắt buộc: video cover, SoundCloud, Behance, Drive…")
    motivation = models.TextField("Vì sao bạn muốn tham gia?", max_length=1000)
    status = models.CharField("Trạng thái", max_length=10,
                              choices=ApplicationStatus.choices,
                              default=ApplicationStatus.PENDING, db_index=True)
    interview_at = models.DateTimeField("Lịch casting / phỏng vấn", null=True, blank=True)
    review_note = models.CharField(
        "Lời nhắn cho ứng viên", max_length=255, blank=True,
        help_text="Ứng viên sẽ đọc được: địa điểm casting, cần chuẩn bị gì…")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name="+",
                                 verbose_name="Người duyệt")
    reviewed_at = models.DateTimeField("Duyệt lúc", null=True, blank=True)
    created_at = models.DateTimeField("Nộp lúc", auto_now_add=True)

    class Meta:
        verbose_name = "Đơn ứng tuyển"
        verbose_name_plural = "Đơn ứng tuyển"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["round", "user"],
                                               name="uniq_application_per_round")]

    def __str__(self):
        return f"{self.user} -> {self.department} ({self.get_status_display()})"

    @property
    def is_active(self):
        return self.status in (ApplicationStatus.PENDING, ApplicationStatus.INTERVIEW)

    def next_statuses(self):
        return [(s, ApplicationStatus(s).label)
                for s in REVIEW_TRANSITIONS.get(self.status, [])]

    def can_be_reviewed_by(self, user):
        """Ban chủ nhiệm duyệt mọi đơn; Trưởng ban duyệt đơn vào Ban mình."""
        if not user.is_authenticated:
            return False
        return user.is_lead or bool(self.department_id
                                    and self.department.lead_id == user.pk)
