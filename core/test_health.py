"""Health check phải phát hiện lỗi phụ thuộc và không lộ bí mật khi thất bại."""
from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase


class HealthTests(TestCase):
    def test_ready_without_authentication_and_never_cached(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertIn("no-store", response["Cache-Control"])

    @patch("core.health.connection.cursor", side_effect=OperationalError("secret-db-password"))
    def test_database_failure_is_generic_503(self, cursor):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"ok": False})
        self.assertNotIn(b"secret-db-password", response.content)

    @patch("core.health.cache.set", side_effect=ConnectionError("secret-cache-url"))
    def test_cache_unavailable_is_503(self, cache_set):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"ok": False})

    @patch("core.health.cache.get", return_value=None)
    def test_cache_silent_write_loss_is_503(self, cache_get):
        self.assertEqual(self.client.get("/health/").status_code, 503)

    def test_only_safe_methods(self):
        self.assertEqual(self.client.post("/health/").status_code, 405)
        response = self.client.head("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
