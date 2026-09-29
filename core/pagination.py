"""
Tiện ích phân trang dùng chung cho các danh sách dài.

Yêu cầu phi chức năng ghi hệ thống phục vụ khoảng 500 người dùng. Đổ hết
mấy trăm dòng ra một trang thì vừa chậm vừa khó đọc, nên các danh sách đều
phân trang.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.paginator import Paginator

if TYPE_CHECKING:
    from django.core.paginator import Page
    from django.db.models import QuerySet
    from django.http import HttpRequest


def paginate(request: HttpRequest, queryset: QuerySet,
             per_page: int = 12) -> tuple[Page, str]:
    """
    Cắt queryset thành từng trang.

    Trả về (page_obj, querystring) trong đó `querystring` là chuỗi các tham
    số lọc hiện tại (đã bỏ `page`), để link sang trang khác không làm mất
    bộ lọc người dùng đang chọn. Đây là lỗi rất hay gặp: bấm sang trang 2
    là bộ lọc bay sạch.
    """
    page_obj = Paginator(queryset, per_page).get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    querystring = f"&{params.urlencode()}" if params else ""

    return page_obj, querystring
