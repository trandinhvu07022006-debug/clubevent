"""
Test runner tùy biến cho KMG Platform.

Đảm bảo `django.core.cache` được dọn sạch trước mỗi test method độc lập để
các bài kiểm thử Rate Limit (SEC-06) và cache huy hiệu không làm nhiễu lẫn nhau,
trong khi trong phạm vi một test method (gửi nhiều request liên tiếp hoặc tạo
nhiều Client không cookie) bộ đếm Cache vẫn hoạt động đúng như môi trường thật.
"""
import unittest

from django.core.cache import cache
from django.test.runner import DiscoverRunner


class _CacheClearingResultMixin:
    def startTest(self, test):
        cache.clear()
        try:
            from accounts.sms import clear_sms_outbox

            clear_sms_outbox()
        except Exception:
            pass
        super().startTest(test)


class CacheClearingTextTestResult(_CacheClearingResultMixin, unittest.TextTestResult):
    pass


class KMGTestRunner(DiscoverRunner):
    def get_resultclass(self):
        base = super().get_resultclass() or unittest.TextTestResult
        if issubclass(base, _CacheClearingResultMixin):
            return base
        return type("KMGCacheClearingResult", (_CacheClearingResultMixin, base), {})
