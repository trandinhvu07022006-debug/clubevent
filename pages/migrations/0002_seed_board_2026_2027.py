"""
Nạp Ban Quản trị KMG nhiệm kỳ 2026 - 2027 (thông tin thật của CLB).

Đặt ở migration để cài mới là có ngay, không phụ thuộc seed_demo. Ảnh và
liên kết tới Ban/tài khoản do Admin bổ sung trong trang quản trị.
"""
from django.db import migrations

BOARD = [
    ("Trần Nhật Hoàng", "Chủ nhiệm", 0),
    ("Trần Đình Vũ", "Phó chủ nhiệm", 1),
    ("Lưu Nhật Linh", "Trưởng ban Chuyên môn", 2),
    ("Phan Tiến Đạt", "Trưởng ban Truyền thông & Sự kiện", 3),
]


def add_board(apps, schema_editor):
    ClubOfficer = apps.get_model("pages", "ClubOfficer")
    for name, position, order in BOARD:
        ClubOfficer.objects.get_or_create(
            name=name, term="2026 - 2027",
            defaults={"position": position, "order": order, "is_current": True})


def remove_board(apps, schema_editor):
    ClubOfficer = apps.get_model("pages", "ClubOfficer")
    ClubOfficer.objects.filter(term="2026 - 2027",
                               name__in=[b[0] for b in BOARD]).delete()


class Migration(migrations.Migration):
    dependencies = [("pages", "0001_initial")]
    operations = [migrations.RunPython(add_board, remove_board)]
