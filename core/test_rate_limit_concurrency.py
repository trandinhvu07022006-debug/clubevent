"""Chống vượt hạn mức bằng request đồng thời và kiểm tra cửa sổ trượt."""
from concurrent.futures import ThreadPoolExecutor
import os
import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from core.security import is_rate_limited, record_rate_event


class RateLimitConcurrencyTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.10")
        self.scope = uuid.uuid4().hex

    def test_parallel_requests_cannot_exceed_limit(self):
        with ThreadPoolExecutor(max_workers=20) as workers:
            results = list(workers.map(
                lambda _: is_rate_limited(self.request, self.scope, 5, 60), range(60)
            ))
        self.assertEqual(results.count(False), 5)

    def test_check_only_does_not_consume_budget_and_window_expires(self):
        with patch("core.security.time.time", return_value=1000):
            for _ in range(4):
                self.assertFalse(is_rate_limited(self.request, self.scope, 1, 60, record=False))
            record_rate_event(self.request, self.scope, 60)
            self.assertTrue(is_rate_limited(self.request, self.scope, 1, 60))
        with patch("core.security.time.time", return_value=1060):
            self.assertFalse(is_rate_limited(self.request, self.scope, 1, 60))

    def test_cache_outage_fails_closed_without_logging_secrets(self):
        with patch("core.security._rate_event", side_effect=ConnectionError("private-redis-password")):
            with self.assertLogs("core.security", level="WARNING") as logs:
                self.assertTrue(is_rate_limited(self.request, self.scope, 5, 60))
            self.assertNotIn("private-redis-password", " ".join(logs.output))


@skipUnless(os.environ.get("KMG_TEST_REDIS_URL"), "Redis integration runs in CI with a dedicated Redis service")
class RedisRateLimitTests(SimpleTestCase):
    def test_atomic_limit_across_independent_thread_connections(self):
        config = {"default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": os.environ.get("KMG_TEST_REDIS_URL"),
            "KEY_PREFIX": "kmg-test-" + uuid.uuid4().hex,
        }}
        request = RequestFactory().get("/", REMOTE_ADDR="192.0.2.20")
        with override_settings(CACHES=config):
            with ThreadPoolExecutor(max_workers=20) as workers:
                results = list(workers.map(
                    lambda _: is_rate_limited(request, "parallel", 7, 30), range(60)
                ))
            self.assertEqual(results.count(False), 7)
            self.assertTrue(is_rate_limited(request, "parallel", 7, 30, record=False))
            self.assertFalse(is_rate_limited(request, "separate", 7, 30))
