"""Khởi tạo danh mục dùng thật, không sinh tài khoản hoặc dữ liệu hoạt động mẫu."""
from django.core.management.base import BaseCommand
from organization.services import bootstrap_organization_catalog


class Command(BaseCommand):
    help = "Khởi tạo danh mục Ban, chức vụ, quyền, kỹ năng và chính sách KMG; không tạo tài khoản demo."

    def handle(self, *args, **options):
        catalog = bootstrap_organization_catalog()
        self.stdout.write(self.style.SUCCESS(
            f"Đã khởi tạo {len(catalog['departments'])} Ban và "
            f"{len(catalog['positions'])} chức vụ. Không tạo hoặc sửa tài khoản."
        ))
        self.stdout.write("Tạo Admin Server bằng createsuperuser; bổ nhiệm cán bộ qua Quản lý tài khoản.")
