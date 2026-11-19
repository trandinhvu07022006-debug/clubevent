"""
Cổng Admin Django của phân hệ Mạng xã hội Nội bộ & Nhắn tin (`social`).

QUY TẮC BẢO MẬT `R03` & BẤT BIẾN `INV-05` (`Zero-Admin-Read`):
TUYỆT ĐỐI KHÔNG đăng ký `Conversation`, `ConversationMember`, `ChatMessage`,
`ChatAttachment`, `ChatReaction`, `SocialPost` (`PERSONAL`), hoặc `MusicPlaylist`
vào Django Admin để ngay cả Superuser / Staff cũng không thể đọc lén tin nhắn riêng
hay playlist cá nhân của thành viên từ `/admin/`.
"""
