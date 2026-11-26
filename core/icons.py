"""
Single Source of Truth cho hệ thống KMG Soft Icons 1.0.

Mỗi biểu tượng dùng viewBox 24x24, nét vẽ 1.65px, đầu/góc bo tròn mềm mại,
màu currentColor để tự động thích ứng Light / Dark mode và tránh phụ thuộc CSS font.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SoftIconSpec:
    key: str
    category: str
    label_vi: str
    legacy_bi: str
    svg_inner: str


KMG_SOFT_ICONS: dict[str, SoftIconSpec] = {
    # 1. Điều hướng
    "home": SoftIconSpec(
        key="home",
        category="Điều hướng",
        label_vi="Tổng quan / Trang chủ",
        legacy_bi="bi-house-heart",
        svg_inner=(
            '<path d="M3.75 10.5 12 4l8.25 6.5v8.25a1.75 1.75 0 0 1-1.75 1.75H5.5a1.75 1.75 0 0 1-1.75-1.75Z"/>'
            '<path d="M9.5 20.5v-5.25a1.5 1.5 0 0 1 1.5-1.5h2a1.5 1.5 0 0 1 1.5 1.5v5.25"/>'
        ),
    ),
    "compass": SoftIconSpec(
        key="compass",
        category="Điều hướng",
        label_vi="Khám phá / Cổng thông tin",
        legacy_bi="bi-globe2",
        svg_inner=(
            '<circle cx="12" cy="12" r="8.5"/>'
            '<path d="m14.8 9.2-1.8 4.6-4.6 1.8 1.8-4.6Z"/>'
        ),
    ),
    "grid": SoftIconSpec(
        key="grid",
        category="Điều hướng",
        label_vi="Không gian CLB",
        legacy_bi="bi-grid-1x2-fill",
        svg_inner=(
            '<rect x="3.75" y="4" width="7" height="7" rx="1.8"/>'
            '<rect x="13.25" y="4" width="7" height="7" rx="1.8"/>'
            '<rect x="3.75" y="13.25" width="7" height="6.75" rx="1.8"/>'
            '<rect x="13.25" y="13.25" width="7" height="6.75" rx="1.8"/>'
        ),
    ),
    "layers": SoftIconSpec(
        key="layers",
        category="Điều hướng",
        label_vi="Các Ban & Cơ cấu",
        legacy_bi="bi-diagram-3",
        svg_inner=(
            '<path d="m12 4.25 8 4.25-8 4.25-8-4.25Z"/>'
            '<path d="m4 12.25 8 4.25 8-4.25"/>'
            '<path d="m4 16 8 4.25L20 16"/>'
        ),
    ),
    "search": SoftIconSpec(
        key="search",
        category="Điều hướng",
        label_vi="Tìm kiếm",
        legacy_bi="bi-search",
        svg_inner=(
            '<circle cx="10.75" cy="10.75" r="6.25"/>'
            '<path d="m15.5 15.5 4.5 4.5"/>'
        ),
    ),
    "sliders": SoftIconSpec(
        key="sliders",
        category="Điều hướng",
        label_vi="Bộ lọc / Tuỳ chỉnh",
        legacy_bi="bi-sliders",
        svg_inner=(
            '<path d="M4.5 7h15M4.5 17h15"/>'
            '<circle cx="9" cy="7" r="2.1" fill="var(--app-surface, #fff)"/>'
            '<circle cx="15" cy="17" r="2.1" fill="var(--app-surface, #fff)"/>'
            '<path d="M4.5 12h15"/>'
            '<circle cx="13.5" cy="12" r="2.1" fill="var(--app-surface, #fff)"/>'
        ),
    ),

    # 2. Âm nhạc & Bản sắc KMG
    "guitar": SoftIconSpec(
        key="guitar",
        category="Âm nhạc & KMG",
        label_vi="Guitar KMG / Âm nhạc",
        legacy_bi="bi-music-note-beamed",
        svg_inner=(
            '<path d="m15.8 4.2 4 4"/>'
            '<path d="m17.5 6.5-5.6 5.6"/>'
            '<path d="M7.2 12.4a3.6 3.6 0 0 1 4.4 4.4c-.6 1.7-2.4 3.4-4.7 3.4A3.1 3.1 0 0 1 3.8 17c0-2.3 1.7-4 3.4-4.6Z"/>'
            '<circle cx="8.8" cy="15.2" r="1.2"/>'
        ),
    ),
    "music": SoftIconSpec(
        key="music",
        category="Âm nhạc & KMG",
        label_vi="Kho nhạc & Hợp âm",
        legacy_bi="bi-vinyl",
        svg_inner=(
            '<path d="M9.5 17.5V7l9-1.75v10.5"/>'
            '<circle cx="7" cy="17.5" r="2.5"/>'
            '<circle cx="16" cy="15.75" r="2.5"/>'
        ),
    ),
    "mic": SoftIconSpec(
        key="mic",
        category="Âm nhạc & KMG",
        label_vi="Sân khấu & Biểu diễn",
        legacy_bi="bi-mic",
        svg_inner=(
            '<rect x="9" y="3.75" width="6" height="9.5" rx="3"/>'
            '<path d="M6.25 11.25a5.75 5.75 0 0 0 11.5 0"/>'
            '<path d="M12 17v3.25M9 20.25h6"/>'
        ),
    ),
    "headphones": SoftIconSpec(
        key="headphones",
        category="Âm nhạc & KMG",
        label_vi="Luyện tập & Hoà tấu",
        legacy_bi="bi-headphones",
        svg_inner=(
            '<path d="M4.5 14v-2a7.5 7.5 0 0 1 15 0v2"/>'
            '<rect x="4" y="13.5" width="3.5" height="5.5" rx="1.6"/>'
            '<rect x="16.5" y="13.5" width="3.5" height="5.5" rx="1.6"/>'
        ),
    ),

    # 3. Sự kiện & Vé
    "calendar": SoftIconSpec(
        key="calendar",
        category="Sự kiện & Vé",
        label_vi="Sự kiện & Lịch",
        legacy_bi="bi-calendar2-heart",
        svg_inner=(
            '<rect x="3.75" y="5.5" width="16.5" height="14.75" rx="2.4"/>'
            '<path d="M8 3.75V7M16 3.75V7M4 10h16"/>'
            '<circle cx="12" cy="14.75" r="1.2"/>'
        ),
    ),
    "ticket": SoftIconSpec(
        key="ticket",
        category="Sự kiện & Vé",
        label_vi="Vé tham dự",
        legacy_bi="bi-ticket-perforated",
        svg_inner=(
            '<path d="M4 8.5A1.75 1.75 0 0 1 5.75 6.75h12.5A1.75 1.75 0 0 1 20 8.5v1.9a1.85 1.85 0 0 0 0 3.2v1.9a1.75 1.75 0 0 1-1.75 1.75H5.75A1.75 1.75 0 0 1 4 15.5v-1.9a1.85 1.85 0 0 0 0-3.2Z"/>'
            '<path d="M14.25 7.25v9.5" stroke-dasharray="2 2"/>'
        ),
    ),
    "qr": SoftIconSpec(
        key="qr",
        category="Sự kiện & Vé",
        label_vi="Mã QR / Điểm danh",
        legacy_bi="bi-qr-code-scan",
        svg_inner=(
            '<rect x="4.5" y="4.5" width="5.5" height="5.5" rx="1.2"/>'
            '<rect x="14" y="4.5" width="5.5" height="5.5" rx="1.2"/>'
            '<rect x="4.5" y="14" width="5.5" height="5.5" rx="1.2"/>'
            '<path d="M14 14h2.5v2.5M19.5 14v5.5H14"/>'
        ),
    ),
    "map-pin": SoftIconSpec(
        key="map-pin",
        category="Sự kiện & Vé",
        label_vi="Địa điểm",
        legacy_bi="bi-geo-alt",
        svg_inner=(
            '<path d="M12 20.5s6-5.25 6-10.25a6 6 0 1 0-12 0c0 5 6 10.25 6 10.25Z"/>'
            '<circle cx="12" cy="10.25" r="2.1"/>'
        ),
    ),
    "clock": SoftIconSpec(
        key="clock",
        category="Sự kiện & Vé",
        label_vi="Thời gian / Hạn chót",
        legacy_bi="bi-clock",
        svg_inner=(
            '<circle cx="12" cy="12" r="8.25"/>'
            '<path d="M12 7.75V12l3 1.75"/>'
        ),
    ),

    # 4. Công việc & Tổ chức
    "check-circle": SoftIconSpec(
        key="check-circle",
        category="Công việc & Tổ chức",
        label_vi="Hoàn thành / Xác nhận",
        legacy_bi="bi-check-circle-fill",
        svg_inner=(
            '<circle cx="12" cy="12" r="8.25"/>'
            '<path d="m8.75 12.25 2.25 2.25 4.5-4.75"/>'
        ),
    ),
    "clipboard-list": SoftIconSpec(
        key="clipboard-list",
        category="Công việc & Tổ chức",
        label_vi="Công việc & Đánh giá",
        legacy_bi="bi-kanban",
        svg_inner=(
            '<rect x="5" y="5" width="14" height="15.25" rx="2.2"/>'
            '<path d="M9 3.75h6v2.5H9zM9 11h6M9 15h4"/>'
        ),
    ),
    "users": SoftIconSpec(
        key="users",
        category="Công việc & Tổ chức",
        label_vi="Thành viên & Tuyển quân",
        legacy_bi="bi-people",
        svg_inner=(
            '<circle cx="9.25" cy="8.75" r="3"/>'
            '<path d="M4.25 18.5a5 5 0 0 1 10 0"/>'
            '<path d="M15.75 6.5a2.6 2.6 0 0 1 0 5"/>'
            '<path d="M16.5 13.75a4.2 4.2 0 0 1 3.5 4.5"/>'
        ),
    ),
    "shield": SoftIconSpec(
        key="shield",
        category="Công việc & Tổ chức",
        label_vi="Quản trị & An toàn",
        legacy_bi="bi-shield-lock-fill",
        svg_inner=(
            '<path d="M12 3.75 19 6.5v5.25c0 4.4-3 7.35-7 8.5-4-1.15-7-4.1-7-8.5V6.5Z"/>'
            '<path d="m9.5 12 1.75 1.75 3.5-3.75"/>'
        ),
    ),
    "award": SoftIconSpec(
        key="award",
        category="Công việc & Tổ chức",
        label_vi="Chứng nhận & Vinh danh",
        legacy_bi="bi-award",
        svg_inner=(
            '<circle cx="12" cy="9.5" r="5"/>'
            '<path d="M9.5 14v6l2.5-1.5L14.5 20v-6"/>'
        ),
    ),

    # 5. Tài chính & Tài liệu
    "wallet": SoftIconSpec(
        key="wallet",
        category="Tài chính & Tài liệu",
        label_vi="Quỹ & Tài chính CLB",
        legacy_bi="bi-cash-coin",
        svg_inner=(
            '<rect x="3.75" y="6" width="16.5" height="12.5" rx="2.3"/>'
            '<path d="M15.5 12.25h4.75M4 9.5h16"/>'
            '<circle cx="16.25" cy="12.25" r="0.8"/>'
        ),
    ),
    "file-text": SoftIconSpec(
        key="file-text",
        category="Tài chính & Tài liệu",
        label_vi="Kho tài liệu & Biên bản",
        legacy_bi="bi-journal-text",
        svg_inner=(
            '<path d="M7 3.75h6.75L18 8v12.25A1.5 1.5 0 0 1 16.5 21.75h-9.5a1.5 1.5 0 0 1-1.5-1.5V5.25A1.5 1.5 0 0 1 7 3.75Z"/>'
            '<path d="M13.5 4v4.25h4.25M9 12.5h6M9 16h4.5"/>'
        ),
    ),

    # 6. Trợ lý AI & Giao tiếp
    "sparkles": SoftIconSpec(
        key="sparkles",
        category="Trợ lý AI & Giao tiếp",
        label_vi="Trợ lý AI KMG",
        legacy_bi="bi-robot",
        svg_inner=(
            '<path d="m12 3.75 1.55 4.45 4.45 1.55-4.45 1.55L12 15.75l-1.55-4.45L6 9.75l4.45-1.55Z"/>'
            '<path d="m18 15.25.65 1.85 1.85.65-1.85.65L18 20.25l-.65-1.85-1.85-.65 1.85-.65Z"/>'
        ),
    ),
    "message": SoftIconSpec(
        key="message",
        category="Trợ lý AI & Giao tiếp",
        label_vi="Nhắn tin & Thảo luận",
        legacy_bi="bi-chat-dots",
        svg_inner=(
            '<path d="M5 6.5h14a1.75 1.75 0 0 1 1.75 1.75v7.5A1.75 1.75 0 0 1 19 17.5H9.5l-4 3v-3H5a1.75 1.75 0 0 1-1.75-1.75v-7.5A1.75 1.75 0 0 1 5 6.5Z"/>'
            '<path d="M8.5 12h7"/>'
        ),
    ),
    "bell": SoftIconSpec(
        key="bell",
        category="Trợ lý AI & Giao tiếp",
        label_vi="Thông báo",
        legacy_bi="bi-bell",
        svg_inner=(
            '<path d="M17.5 15.25H6.5c1.1-1.2 1.75-2.6 1.75-5.25a3.75 3.75 0 1 1 7.5 0c0 2.65.65 4.05 1.75 5.25Z"/>'
            '<path d="M10.25 18.25a2 2 0 0 0 3.5 0"/>'
        ),
    ),

    # 7. Hành động chung
    "sun": SoftIconSpec(
        key="sun",
        category="Hành động chung",
        label_vi="Chế độ Sáng",
        legacy_bi="bi-sun-fill",
        svg_inner=(
            '<circle cx="12" cy="12" r="4"/>'
            '<path d="M12 3.5v2M12 18.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M3.5 12h2M18.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'
        ),
    ),
    "moon": SoftIconSpec(
        key="moon",
        category="Hành động chung",
        label_vi="Chế độ Tối",
        legacy_bi="bi-moon-stars-fill",
        svg_inner=(
            '<path d="M19.2 14.3A7.5 7.5 0 0 1 9.7 4.8a7.5 7.5 0 1 0 9.5 9.5Z"/>'
        ),
    ),
    "plus": SoftIconSpec(
        key="plus",
        category="Hành động chung",
        label_vi="Tạo mới / Thêm",
        legacy_bi="bi-plus-lg",
        svg_inner='<path d="M12 5v14M5 12h14"/>',
    ),
    "send": SoftIconSpec(
        key="send",
        category="Hành động chung",
        label_vi="Gửi / Giao việc",
        legacy_bi="bi-send",
        svg_inner=(
            '<path d="m20 4-9.5 9.5"/>'
            '<path d="M20 4 13.75 20l-3.25-6.5L4 10.25Z"/>'
        ),
    ),
    "download": SoftIconSpec(
        key="download",
        category="Hành động chung",
        label_vi="Tải xuống / Xuất tệp",
        legacy_bi="bi-download",
        svg_inner=(
            '<path d="M12 4.5v10.75M8.25 11.75 12 15.5l3.75-3.75"/>'
            '<path d="M5 17.5v1.25A1.5 1.5 0 0 0 6.5 20.25h11a1.5 1.5 0 0 0 1.5-1.5V17.5"/>'
        ),
    ),
}


def grouped_soft_icons() -> list[tuple[str, list[SoftIconSpec]]]:
    """Nhóm danh sách biểu tượng theo danh mục để hiển thị tại Design System Showcase."""
    groups: dict[str, list[SoftIconSpec]] = {}
    for spec in KMG_SOFT_ICONS.values():
        groups.setdefault(spec.category, []).append(spec)
    return list(groups.items())
