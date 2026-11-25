"""DEBUG=False thì phải có đủ khoá bí mật riêng, không được dùng khoá mặc định."""
import os
import subprocess
import sys
import tempfile

from django.conf import settings
from django.test import SimpleTestCase

KEY_NAMES = ("SECRET_KEY", "CERT_SIGNING_KEY", "CHAT_MASTER_KEK")
# Nạp config.settings trong tiến trình riêng, giả như máy không có file .env
BOOT = """
import pathlib
original = pathlib.Path.exists
pathlib.Path.exists = lambda p, *a, **k: p.name != ".env" and original(p, *a, **k)
import config.settings
"""


class SecretGuardTests(SimpleTestCase):
    def _boot(self, debug, **overrides):
        """Giá trị None nghĩa là không đặt biến môi trường đó."""
        values = {name: f"khoa-rieng-{name}-" + "x" * 32 for name in KEY_NAMES}
        values.update(overrides)
        env = {k: v for k, v in os.environ.items() if k not in KEY_NAMES}
        env.update({k: v for k, v in values.items() if v is not None})
        with tempfile.TemporaryDirectory() as logs:
            env.update({"DEBUG": debug, "DB_ENGINE": "sqlite", "DATABASE_URL": "",
                        "CACHE_URL": "", "LOG_ROOT": logs, "PYTHONIOENCODING": "utf-8"})
            return subprocess.run(
                [sys.executable, "-c", BOOT], cwd=settings.BASE_DIR, env=env,
                capture_output=True, encoding="utf-8", timeout=60)

    def assertRefused(self, result, name):
        self.assertNotEqual(result.returncode, 0, f"Vẫn khởi động dù {name} yếu")
        self.assertIn("ImproperlyConfigured", result.stderr)
        self.assertIn(name, result.stderr)

    def test_production_refuses_missing_key(self):
        for name in KEY_NAMES:
            with self.subTest(name=name):
                self.assertRefused(self._boot("False", **{name: None}), name)

    def test_production_refuses_empty_key(self):
        for name in KEY_NAMES:
            with self.subTest(name=name):
                self.assertRefused(self._boot("False", **{name: "  "}), name)

    def test_production_boots_with_all_keys(self):
        result = self._boot("False")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_development_still_boots_without_keys(self):
        result = self._boot("True", **{name: None for name in KEY_NAMES})
        self.assertEqual(result.returncode, 0, result.stderr)
