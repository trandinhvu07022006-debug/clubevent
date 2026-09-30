"""Sinh ảnh mã QR dùng chung (vé, VietQR, giấy chứng nhận)."""
import base64
import io


def qr_data_uri(text):
    """
    Sinh mã QR dạng data URI để nhúng thẳng vào thẻ <img>, không cần lưu file.

    Nếu máy chưa cài thư viện qrcode thì trả None, template sẽ hiện mã chữ
    thay thế — vẫn check-in được bằng cách nhập tay.
    """
    try:
        import qrcode
    except ImportError:
        return None
    img = qrcode.make(text)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
