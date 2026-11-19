"""
Mã hóa Phong bì AES-256-GCM & Chữ ký Bằng chứng HMAC cho Nhắn tin Nội bộ (`WF21`, `INV-05`, `BE-07`, `SEC-07`):

- Mỗi `Conversation` sở hữu một Khóa dữ liệu ngẫu nhiên 256-bit (DEK).
- DEK được bọc (wrap) bằng Khóa chủ `CHAT_MASTER_KEK` (tách biệt với `SECRET_KEY` theo `SEC-07`)
  dùng `AESGCM` (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`).
- Mỗi `ChatMessage` mã hóa bằng DEK + nonce ngẫu nhiên CSPRNG 12 byte + Associated Authenticated Data (AAD)
  gắn cứng `(conversation_id, sender_id)` để chống tráo đổi bản mã giữa các phòng/người gửi.
- Không bao giờ lưu bản rõ `plaintext` tin nhắn trong CSDL hay `AuditLog` (`WF21`).
- `MessageAbuseReport` (`BE-07`) dùng chữ ký `HMAC-SHA256` độc lập để chứng thực nguyên văn
  nội dung bị báo cáo tại thời điểm nạn nhân gửi tố cáo, không mở cửa sau đọc các tin nhắn khác.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

_DEK_TOKEN_PREFIX = "v1:"
_DEK_AAD = b"kmg-chat-dek-wrap-v1"


def _derive_master_kek() -> bytes:
    """
    Rút xuất khóa KEK 256-bit từ `settings.CHAT_MASTER_KEK` (tách khỏi `SECRET_KEY`).
    Nếu môi trường dev chưa cấu hình `CHAT_MASTER_KEK`, rút xuất tất định từ khóa riêng
    với salt tách biệt qua HKDF-SHA256 để hệ thống vẫn vận hành đồng nhất.
    """
    raw_secret = (getattr(settings, "CHAT_MASTER_KEK", "") or "").strip()
    if not raw_secret:
        fallback = (
            getattr(settings, "CERT_SIGNING_KEY", "")
            or getattr(settings, "SECRET_KEY", "kmg-dev-chat-kek")
        ).strip()
        raw_secret = f"fallback-kek:{fallback}"
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"kmg-platform-chat-kek-salt-v1",
        info=b"aes-256-gcm-envelope-kek",
    )
    return hkdf.derive(raw_secret.encode("utf-8"))


def _derive_abuse_hmac_key() -> bytes:
    raw_secret = (
        getattr(settings, "CHAT_MASTER_KEK", "")
        or getattr(settings, "CERT_SIGNING_KEY", "")
        or getattr(settings, "SECRET_KEY", "kmg-dev-abuse-hmac")
    ).strip()
    return hashlib.sha256(f"kmg-abuse-report-hmac-v1|{raw_secret}".encode("utf-8")).digest()


def generate_wrapped_dek() -> str:
    """Sinh mới DEK 256-bit ngẫu nhiên và bọc bằng AES-256-GCM Master KEK."""
    dek = AESGCM.generate_key(bit_length=256)
    kek = _derive_master_kek()
    nonce = os.urandom(12)
    wrapped = AESGCM(kek).encrypt(nonce, dek, _DEK_AAD)
    token = base64.urlsafe_b64encode(nonce + wrapped).decode("ascii")
    return f"{_DEK_TOKEN_PREFIX}{token}"


def unwrap_dek(wrapped_token: str) -> bytes:
    """Giải bọc DEK 256-bit chỉ trong bộ nhớ RAM (không bao giờ lưu DEK trần ra DB)."""
    if not wrapped_token or not wrapped_token.startswith(_DEK_TOKEN_PREFIX):
        raise ValueError("Định dạng khóa hội thoại được bọc không hợp lệ.")
    payload = base64.urlsafe_b64decode(wrapped_token[len(_DEK_TOKEN_PREFIX):].encode("ascii"))
    if len(payload) < 28:  # 12 byte nonce + >=16 byte GCM tag
        raise ValueError("Payload khóa hội thoại bị hỏng.")
    nonce, wrapped = payload[:12], payload[12:]
    kek = _derive_master_kek()
    return AESGCM(kek).decrypt(nonce, wrapped, _DEK_AAD)


def build_message_aad(conversation_id: int, sender_id: int) -> bytes:
    return f"kmg:conv:{conversation_id}:sender:{sender_id}".encode("utf-8")


def encrypt_message_text(
    *,
    dek: bytes,
    plaintext: str,
    conversation_id: int,
    sender_id: int,
) -> tuple[bytes, bytes]:
    """
    Mã hóa nội dung tin nhắn bằng AES-256-GCM với nonce 96-bit ngẫu nhiên mỗi tin nhắn.
    Trả về `(iv_nonce, ciphertext_with_tag)`.
    """
    iv_nonce = os.urandom(12)
    aad = build_message_aad(conversation_id, sender_id)
    ct = AESGCM(dek).encrypt(iv_nonce, plaintext.encode("utf-8"), aad)
    return iv_nonce, ct


def decrypt_message_text(
    *,
    dek: bytes,
    iv_nonce: bytes,
    ciphertext: bytes,
    conversation_id: int,
    sender_id: int,
) -> str:
    """Giải mã tin nhắn chỉ trên RAM sau khi đã kiểm tra `ConversationMember(left_at IS NULL)`."""
    aad = build_message_aad(conversation_id, sender_id)
    pt_bytes = AESGCM(dek).decrypt(bytes(iv_nonce), bytes(ciphertext), aad)
    return pt_bytes.decode("utf-8")


def sign_abuse_report_snapshot(
    *,
    message_id: int,
    conversation_id: int,
    sender_id: int,
    created_at_iso: str,
    plaintext_snapshot: str,
) -> str:
    """Tạo chữ ký HMAC-SHA256 chống giả mạo bằng chứng tố cáo tin nhắn (`BE-07`)."""
    canonical = (
        f"v1|{message_id}|{conversation_id}|{sender_id}|{created_at_iso}|"
        f"{hashlib.sha256(plaintext_snapshot.encode('utf-8')).hexdigest()}"
    )
    key = _derive_abuse_hmac_key()
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_abuse_report_snapshot(
    *,
    message_id: int,
    conversation_id: int,
    sender_id: int,
    created_at_iso: str,
    plaintext_snapshot: str,
    hmac_proof: str,
) -> bool:
    expected = sign_abuse_report_snapshot(
        message_id=message_id,
        conversation_id=conversation_id,
        sender_id=sender_id,
        created_at_iso=created_at_iso,
        plaintext_snapshot=plaintext_snapshot,
    )
    return hmac.compare_digest(expected, hmac_proof or "")
