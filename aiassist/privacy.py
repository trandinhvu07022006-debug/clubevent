"""
Che thông tin cá nhân (PII) trước khi LƯU log hoặc GỬI cho dịch vụ AI.

Giới hạn cần nói đúng khi bảo vệ: đây là che theo MẪU, không phải "Zero PII".
Bắt được email, số điện thoại, MSSV dạng 2 chữ + 6 số, mã vé, dãy số dài và
những họ tên mà hệ thống đã biết trước. Tên người khác, địa chỉ hay MSSV
định dạng lạ gõ tự do trong câu thì KHÔNG bắt được.
"""
import re
import unicodedata

# Thứ tự quan trọng: mẫu cụ thể chạy trước mẫu tổng quát.
_PATTERNS = (
    ("[email]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("[sđt]", re.compile(r"(?<!\w)(?:\+?84|0)(?:[ .\-]?\d){9}(?!\w)")),
    ("[mssv]", re.compile(r"(?<!\w)[A-Za-z]{2}\d{6}(?!\w)")),
    # Mã vé: 12 ký tự hex (registrations.models.make_ticket_code)
    ("[mã vé]", re.compile(r"(?<!\w)[0-9A-Fa-f]{12}(?!\w)")),
    # CCCD/CMND, số tài khoản...
    ("[dãy số]", re.compile(r"(?<!\w)\d{9,}(?!\w)")),
)


def redact(text, names=()):
    """
    Trả về `text` đã che PII.

    `names`: họ tên đã biết (vd người đang đăng nhập). Chỉ che tên từ 2 chữ trở
    lên để không xoá nhầm từ thường ("An", "Anh"...).
    """
    result = unicodedata.normalize("NFC", str(text or ""))
    for label, pattern in _PATTERNS:
        result = pattern.sub(label, result)
    for name in names:
        words = unicodedata.normalize("NFC", str(name or "")).split()
        if len(words) < 2:
            continue
        pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)"
        result = re.sub(pattern, "[họ tên]", result, flags=re.IGNORECASE)
    return result


def known_names(user):
    """Các họ tên của người dùng đang đăng nhập (rỗng nếu là khách)."""
    if not (user and user.is_authenticated):
        return ()
    return tuple(filter(None, (getattr(user, "full_name", ""),
                               getattr(user, "display_name", ""))))


_INJECTION_DELIMITERS_RE = re.compile(
    r"(?:<\|(?:im_start|im_end|system|assistant|user)\|>|"
    r"</?(?:system|USER_QUERY|INSTRUCTIONS|CONTEXT)>|"
    r"^\s*#{2,}\s*(?:SYSTEM|INSTRUCTIONS|DEVELOPER)\s*:?)",
    re.IGNORECASE | re.MULTILINE,
)

_INJECTION_PHRASES_RE = re.compile(
    r"(?:ignore\s+(?:all\s+)?previous\s+instructions|"
    r"disregard\s+(?:all\s+)?rules|"
    r"reveal\s+(?:system\s+prompt|api[_\s]?key|secret)|"
    r"bo\s+qua\s+(?:tat\s+ca\s+|moi\s+)?quy\s+tac|"
    r"in\s+ra\s+(?:api\s+key|mat\s+khau|system\s+prompt))",
    re.IGNORECASE,
)


def sanitize_untrusted_input(text: str) -> str:
    """Loại bỏ ký tự điều khiển và thẻ giả mạo ranh giới prompt trong câu hỏi người dùng."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", str(text or ""))
    cleaned = _INJECTION_DELIMITERS_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def has_prompt_injection_signal(text: str) -> bool:
    """Nhận diện dấu hiệu thử chèn chỉ thị hệ thống (chỉ dùng phòng vệ/giám sát)."""
    raw = str(text or "")
    norm = unicodedata.normalize("NFD", raw).replace("đ", "d")
    norm = "".join(c for c in norm if unicodedata.category(c) != "Mn")
    return bool(
        _INJECTION_DELIMITERS_RE.search(raw)
        or _INJECTION_PHRASES_RE.search(raw)
        or _INJECTION_PHRASES_RE.search(norm)
    )
