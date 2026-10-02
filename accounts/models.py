"""
M1 - Tài khoản & phân quyền.

Dùng custom user model thay cho User mặc định của Django để thêm MSSV và
role. Phải khai báo AUTH_USER_MODEL ngay từ đầu dự án, đổi về sau rất mệt.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """
    Admin > Trưởng BTC > TV BTC > Thành viên > Khách.

    KHÁCH: ai cũng tự tạo tài khoản online được - để đặt vé, xem sự kiện.
    THÀNH VIÊN chính thức chỉ có qua ĐỢT TUYỂN (app recruitment): nộp đơn,
    casting/phỏng vấn, được nhận mới lên Thành viên và vào Ban. Nhờ vậy danh
    sách thành viên không bị "loãng" bởi người chỉ đăng ký để mua vé.
    """
    GUEST = "GUEST", "Khách"
    MEMBER = "MEMBER", "Thành viên"
    STAFF = "STAFF", "Thành viên BTC"
    LEAD = "LEAD", "Trưởng BTC"
    ADMIN = "ADMIN", "Admin"


class Affiliation(models.TextChoices):
    """
    Người dùng là ai. Show của CLB mở cho cả người ngoài (sinh viên trường
    khác, người đi làm, phụ huynh...), nên MSSV KHÔNG bắt buộc với mọi người:
    chỉ sinh viên Học viện mới phải khai MSSV.
    """
    KMA = "KMA", "Sinh viên Học viện Kỹ thuật Mật mã"
    OTHER_SCHOOL = "OTHER", "Sinh viên trường khác"
    PUBLIC = "PUBLIC", "Không phải sinh viên"


class User(AbstractUser):
    """Người dùng hệ thống. Đăng nhập bằng username, hiển thị theo họ tên."""

    affiliation = models.CharField("Đối tượng", max_length=6,
                                   choices=Affiliation.choices, default=Affiliation.KMA)
    # Để trống thì lưu NULL, KHÔNG lưu "": cột unique cho phép nhiều NULL
    # nhưng chỉ một chuỗi rỗng -> người thứ hai bỏ trống sẽ bị báo trùng.
    mssv = models.CharField("MSSV", max_length=20, unique=True, null=True, blank=True)
    school = models.CharField("Trường / đơn vị", max_length=120, blank=True)
    full_name = models.CharField("Họ tên", max_length=120, blank=True)
    phone = models.CharField("Số điện thoại", max_length=20, blank=True)
    role = models.CharField("Vai trò", max_length=10,
                            choices=Role.choices, default=Role.GUEST)
    avatar = models.ImageField("Ảnh đại diện", upload_to="avatars/",
                               null=True, blank=True)
    is_locked = models.BooleanField("Bị khoá", default=False)
    created_at = models.DateTimeField("Ngày tạo", auto_now_add=True)

    class Meta:
        verbose_name = "Người dùng"
        verbose_name_plural = "Người dùng"
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("email"),
                name="uniq_user_email_ci",
                condition=~models.Q(email="")
            )
        ]

    def __str__(self):
        return f"{self.full_name or self.username} ({self.get_role_display()})"

    # --- Các hàm kiểm tra quyền, dùng chung cho view và template ---
    @property
    def is_kma_student(self):
        return self.affiliation == Affiliation.KMA

    @property
    def is_club_member(self):
        """Thành viên CHÍNH THỨC trở lên (đã qua đợt tuyển), không phải Khách."""
        return self.role != Role.GUEST

    @property
    def is_staff_btc(self):
        """Là Thành viên BTC trở lên (TV BTC, Trưởng BTC, Admin)."""
        return self.role in (Role.STAFF, Role.LEAD, Role.ADMIN)

    @property
    def is_lead(self):
        """Là Trưởng BTC trở lên."""
        return self.role in (Role.LEAD, Role.ADMIN)

    @property
    def is_admin_role(self):
        return self.role == Role.ADMIN


class AuditLog(models.Model):
    """
    F0.2 - Nhật ký thao tác.

    Ghi lại các hành động quan trọng: gán role, huỷ sự kiện, xác nhận thanh
    toán, check-in. Dùng để truy vết khi có tranh chấp.
    """
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True,
                            verbose_name="Người thực hiện")
    action = models.CharField("Hành động", max_length=60)
    target = models.CharField("Đối tượng", max_length=200, blank=True)
    note = models.CharField("Ghi chú", max_length=255, blank=True)
    created_at = models.DateTimeField("Thời gian", auto_now_add=True)

    class Meta:
        verbose_name = "Nhật ký thao tác"
        verbose_name_plural = "Nhật ký thao tác"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at:%d/%m %H:%M}] {self.user} - {self.action}"

    @classmethod
    def write(cls, user, action, target="", note=""):
        """Hàm tiện dụng để ghi log từ bất kỳ service nào."""
        return cls.objects.create(user=user, action=action,
                                  target=str(target)[:200], note=note[:255])
