"""
Kho lưu trữ tệp nội bộ có kiểm soát quyền truy cập (SEC-01).

Tệp lưu trong `PRIVATE_VAULT_ROOT` (ngoài `MEDIA_ROOT`), tuyệt đối không được
Django `static(MEDIA_URL, ...)` hay Nginx phục vụ công khai. Mọi lượt tải/xem
bắt buộc đi qua View có kiểm tra phân quyền ở Backend.
"""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateVaultStorage(FileSystemStorage):
    """
    Lưu hóa đơn tài chính và tài liệu mật ngoài thư mục `/media/`.
    Đọc động `settings.PRIVATE_VAULT_ROOT` khi `location=None` để tương thích
    hoàn toàn với `override_settings` và không serialize đường dẫn máy cục bộ vào migration.
    """

    def __init__(self, location=None, base_url=None, **kwargs):
        self._explicit_location = location
        if base_url is None:
            base_url = "/congviec/private-vault/"
        super().__init__(location=location, base_url=base_url, **kwargs)

    @property
    def base_location(self):
        return str(self._explicit_location or settings.PRIVATE_VAULT_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)


private_vault_storage = PrivateVaultStorage()
