"""Thu nhỏ ảnh người dùng tải lên trước khi lưu."""
import io
import os

from django.core.files.uploadedfile import InMemoryUploadedFile, UploadedFile

try:
    from PIL import Image, ImageOps
except ImportError:          # Pillow đã có trong requirements, phòng máy thiếu
    Image = None


def shrink_image(upload, max_px, quality=82):
    """
    Thu ảnh về cạnh dài tối đa `max_px`, xoay đúng chiều theo EXIF, bỏ EXIF
    (ảnh điện thoại chứa cả toạ độ GPS nơi chụp) và nén JPEG.

    Ảnh bìa chụp bằng điện thoại thường 4000px, 5 MB; thẻ sự kiện chỉ hiện
    khoảng 400px nên trang chủ 9 thẻ phải tải hàng chục MB. Sau khi thu nhỏ,
    mỗi ảnh còn vài trăm KB.

    Ảnh PNG có nền trong suốt giữ nguyên định dạng PNG. Ảnh động (GIF) và mọi
    trường hợp không đọc được thì trả lại nguyên file - không bao giờ làm hỏng
    việc tải lên.
    """
    # Chỉ xử lý file MỚI tải lên; sửa form mà giữ ảnh cũ thì bỏ qua
    if Image is None or not isinstance(upload, UploadedFile):
        return upload
    try:
        upload.seek(0)
        im = Image.open(upload)
        if getattr(im, "is_animated", False):
            upload.seek(0)
            return upload
        im = ImageOps.exif_transpose(im)
        keep_png = im.mode in ("RGBA", "LA", "P") and (upload.name or "").lower().endswith(".png")
        im.thumbnail((max_px, max_px), Image.LANCZOS)
        buf = io.BytesIO()
        if keep_png:
            im.save(buf, "PNG", optimize=True)
            ext, ctype = ".png", "image/png"
        else:
            im.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True,
                                   progressive=True)
            ext, ctype = ".jpg", "image/jpeg"
    except Exception:
        upload.seek(0)
        return upload
    name = os.path.splitext(os.path.basename(upload.name or "anh"))[0] + ext
    buf.seek(0)
    return InMemoryUploadedFile(buf, getattr(upload, "field_name", None), name,
                                ctype, buf.getbuffer().nbytes, None)
