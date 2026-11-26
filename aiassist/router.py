"""
AI Intent Router & Vietnamese Normalization for KMG AI.

Handles:
  - Vietnamese with diacritics, without diacritics, abbreviations, and student slang.
  - Multi-intent detection and disambiguation (e.g. preventing "lich" in "lich tap"
    or "lich thi" from being hijacked by upcoming_events).
  - Security / prompt-injection / role-spoofing pre-check (always fail-closed).
"""
from __future__ import annotations

import re
import unicodedata

from .privacy import _INJECTION_PHRASES_RE

# Slang & abbreviations common among Vietnamese students (applied on normalized text)
_SLANG_REPLACEMENTS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(?:ko|k|kh|hok|hong|hông)\b"), "khong"),
    (re.compile(r"\b(?:dc|đc|duocj)\b"), "duoc"),
    (re.compile(r"\bck\b"), "chuyen khoan"),
    (re.compile(r"\b(?:e|em)\b"), "em"),
    (re.compile(r"\bm\b"), "minh"),
    (re.compile(r"\bbh\b"), "bao gio"),
    (re.compile(r"\bntn\b"), "nhu the nao"),
    (re.compile(r"\bhnay\b"), "hom nay"),
    (re.compile(r"\btnay\b"), "toi nay"),
    (re.compile(r"\bcv\b"), "cong viec"),
    (re.compile(r"\btv\b"), "thanh vien"),
    (re.compile(r"\bbcn\b"), "ban chu nhiem"),
    (re.compile(r"\bsdt\b"), "so dien thoai"),
    (re.compile(r"\bmssv\b"), "ma so sinh vien"),
    (re.compile(r"\bcheck[\s\-_]*in\b"), "check in"),
)

_ROLE_SPOOF_RE = re.compile(
    r"(?:coi\s+(?:em|toi|minh)\s+la\s+(?:truong\s+ban|pho\s+ban|chu\s+nhiem|admin|co\s+van|ban\s+chu\s+nhiem)"
    r"|gia\s+su\s+(?:em|toi|minh)\s+la\s+(?:truong\s+ban|admin|chu\s+nhiem)"
    r"|xem\s+(?:ma\s+)?(?:ve|ho\s+so|diem|luong|tai\s+chinh)\s+cua\s+(?:nguoi\s+khac|ban\s+khac|nguoi\s+nay)"
    r"|mien\s+diem\s+danh|tu\s+(?:duyet|phe\s+duyet|them\s+em|sua\s+quyen|chuyen\s+tien))",
    re.IGNORECASE,
)

_SENSITIVE_DATA_PROBE_RE = re.compile(
    r"(?:in\s+ra|cho\s+(?:xin|biet)|tiet\s+lo|gui\s+cho)\s+"
    r"(?:otp|mat\s+khau|password|api\s*key|secret\s*key|khoa\s+ma\s+hoa|tin\s+nhan\s+rieng|ma\s+ve\s+cua\s+nguoi\s+khac)",
    re.IGNORECASE,
)


def normalize_vi(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics (preserving 'đ' -> 'd')."""
    s = (text or "").lower().strip().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def prepare_query(question: str) -> str:
    """
    Normalize query for intent & RAG matching:
      - Distinguish "bạn" (person -> _nguoi_) from "ban" (department) before stripping diacritics.
      - Expand common student abbreviations/slang.
      - Strip vocatives ("các bạn ơi", "bạn ơi").
    """
    text = unicodedata.normalize("NFC", (question or "").lower())
    text = re.sub(r"\bbạn\b", " _nguoi_ ", text)
    text = " ".join(normalize_vi(text).split())
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"([a-z])\1{2,}", r"\1", text)
    for pattern, repl in _SLANG_REPLACEMENTS:
        text = pattern.sub(repl, text)
    text = re.sub(r"\b(?:(?:cac|moi) )?(?:_nguoi_|ban) oi\b", " ", text)
    return " ".join(text.split())


def is_security_violation(question: str) -> tuple[bool, str]:
    """
    Detect explicit jailbreak, role spoofing, unauthorized write requests,
    or sensitive secret/PII extraction attempts.
    (Stray delimiter tags are stripped by `sanitize_untrusted_input` downstream.)
    """
    raw = str(question or "")
    norm = prepare_query(raw)
    if _INJECTION_PHRASES_RE.search(raw) or _INJECTION_PHRASES_RE.search(norm):
        return True, (
            "Mình không thể thực hiện yêu cầu thay đổi quy tắc hệ thống hoặc tiết lộ thông tin bảo mật. "
            "Mình chỉ hỗ trợ tra cứu và học nhạc trong phạm vi quyền hợp lệ của bạn."
        )
    if _ROLE_SPOOF_RE.search(norm):
        return True, (
            "Quyền truy cập và thao tác hệ thống luôn được xác thực theo tài khoản thực tế trên máy chủ, "
            "không dựa vào chức danh tự khai và mình không tự thực hiện thay đổi dữ liệu giúp bạn. "
            "Vui lòng liên hệ Trưởng ban hoặc Ban Chủ nhiệm nếu cần xử lý."
        )
    if _SENSITIVE_DATA_PROBE_RE.search(norm):
        return True, (
            "Vì lý do bảo mật và quyền riêng tư, mình không thể cung cấp OTP, mật khẩu, API key, "
            "khóa mã hóa, tin nhắn riêng hay thông tin vé của người khác."
        )
    return False, ""


# Music & Student-life cues that must NEVER be hijacked by broad event keywords ("lich", "co gi")
_MUSIC_STRONG_CUES = (
    "hop am", "bam f", "bam hop am", "chuyen hop am", "rai ngon", "quat cha",
    "fingerstyle", "capo", "len day", "tieng re", "guitar", "piano", "keyboard",
    "ukulele", "cajon", "trong", "bass", "thanh nhac", "luyen hoi", "cao do",
    "quang giong", "hat be", "khan giong", "dau hong", "nhac ly", "gam", "nhip",
    "tiet tau", "cam am", "doc ban nhac", "hoa am", "phoi khi", "sang tac",
    "soundcheck", "mixer", "micro", "loa kiem am", "setlist", "tap band",
    "lo trinh hoc nhac", "lo trinh 7 ngay", "lo trinh 30 ngay", "ke hoach luyen tap",
    "nhat ky luyen tap", "hoc dan", "choi dan", "dem hat", "tab",
)

_STUDENT_COMPANION_CUES = (
    "khong co nang khieu", "so casting truot", "chua co nhac cu", "chua than voi ai",
    "moi nguoi gioi hon", "hoc dan mai khong tien bo", "ngai hoi anh chi",
    "sap thi", "lich thi", "muon nghi clb", "mat tu tin", "khong muon bieu dien",
    "muon doi nhac cu", "tim ban cung tap", "mau thuan voi thanh vien",
    "ap luc", "nan qua", "bo cuoc", "tu ti", "ngai giao tiep",
)

_PRACTICE_CUES = (
    "lich tap", "buoi tap", "rehearsal", "toi nay tap", "hom nay co tap",
    "lich tap band", "lịch tập",
)
