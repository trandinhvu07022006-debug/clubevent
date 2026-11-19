"""Readiness probe chỉ trả trạng thái chung, không tiết lộ cấu hình phụ thuộc."""
from uuid import uuid4

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


@never_cache
@require_safe
def health(request):
    key = f"health:{uuid4().hex}"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("Database probe failed")
        cache.set(key, "ready", timeout=15)
        if cache.get(key) != "ready":
            raise RuntimeError("Cache probe failed")
        cache.delete(key)
    except Exception:
        return JsonResponse({"ok": False}, status=503)
    return JsonResponse({"ok": True})
