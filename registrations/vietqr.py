"""
F4.7 - Sinh mã VietQR chuyển khoản, hoàn toàn OFFLINE (không gọi API ngoài).

Chuỗi VietQR theo chuẩn EMVCo: mỗi trường = ID 2 số + độ dài 2 số + giá trị.
App ngân hàng nào ở Việt Nam cũng quét được, tự điền STK, số tiền, nội dung.

Thiếu cấu hình ngân hàng trong .env (BANK_BIN, BANK_ACCOUNT, BANK_ACCOUNT_NAME)
thì mọi hàm trả None và giao diện ẩn phần VietQR - không bao giờ lỗi.
"""
from django.conf import settings

from core.qr import qr_data_uri


def tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"


def crc16_ccitt(data: str) -> str:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, không đảo bit, không XOR cuối."""
    crc = 0xFFFF
    for byte in data.encode("ascii"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def vietqr_payload(bin_code, account, amount, content):
    merchant = (tlv("00", "A000000727")
                + tlv("01", tlv("00", bin_code) + tlv("01", account))
                + tlv("02", "QRIBFTTA"))                  # chuyển tới SỐ TÀI KHOẢN
    payload = (tlv("00", "01")                             # phiên bản định dạng
               + tlv("01", "12")                           # 12 = QR động (có số tiền)
               + tlv("38", merchant)
               + tlv("53", "704")                          # VND
               + tlv("54", str(int(amount)))
               + tlv("58", "VN")
               + tlv("62", tlv("08", content))             # nội dung chuyển khoản
               + "6304")                                   # CRC: tag+độ dài, chưa có giá trị
    return payload + crc16_ccitt(payload)


def bank_configured():
    return bool(settings.BANK_BIN and settings.BANK_ACCOUNT
                and settings.BANK_ACCOUNT_NAME)


def transfer_content(booking_ref):
    """Nội dung CK: 12 ký tự ASCII hoa, app ngân hàng nào cũng nhận."""
    return f"KMG {booking_ref}"


def payment_info(booking_ref, amount):
    """
    Gói đủ thông tin để hiển thị khối chuyển khoản: ảnh QR + các dòng chữ.
    Trả None khi chưa cấu hình ngân hàng hoặc số tiền bằng 0.
    """
    if not bank_configured() or not amount:
        return None
    content = transfer_content(booking_ref)
    return {
        "qr": qr_data_uri(vietqr_payload(settings.BANK_BIN, settings.BANK_ACCOUNT,
                                         amount, content)),
        "bank_name": settings.BANK_NAME or settings.BANK_BIN,
        "account": settings.BANK_ACCOUNT,
        "account_name": settings.BANK_ACCOUNT_NAME,
        "amount": int(amount),
        "content": content,
    }
