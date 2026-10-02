"""Ban Quản trị CLB theo nhiệm kỳ - hiện trên trang Giới thiệu và trang chủ."""
from django.conf import settings
from django.db import models

from organizing.models import Department


class ClubOfficer(models.Model):
    """
    Một người trong Ban Quản trị (Chủ nhiệm, Phó chủ nhiệm, Trưởng ban…).

    Lưu ở CSDL để mỗi nhiệm kỳ Admin tự cập nhật trong trang quản trị (kèm
    ảnh), không phải sửa code. Gắn với tài khoản (không bắt buộc) để dùng
    ảnh đại diện khi chưa tải ảnh riêng.
    """

    name = models.CharField("Họ tên", max_length=120)
    position = models.CharField("Chức vụ", max_length=80,
                                help_text="Vd: Chủ nhiệm, Phó chủ nhiệm, Trưởng ban Chuyên môn")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name="officers",
                                   verbose_name="Ban phụ trách")
    term = models.CharField("Nhiệm kỳ", max_length=20, default="2026 - 2027")
    photo = models.ImageField("Ảnh", upload_to="officers/", null=True, blank=True)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name="officer_profile",
                                verbose_name="Tài khoản")
    order = models.PositiveSmallIntegerField("Thứ tự", default=0)
    is_current = models.BooleanField("Đương nhiệm", default=True)

    class Meta:
        verbose_name = "Thành viên Ban Quản trị"
        verbose_name_plural = "Ban Quản trị"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.position}: {self.name} ({self.term})"

    @property
    def photo_url(self):
        if self.photo:
            return self.photo.url
        if self.user_id and self.user.avatar:
            return self.user.avatar.url
        return ""

    @property
    def initials(self):
        parts = self.name.split()
        return (parts[-1][0] if parts else "?").upper()
