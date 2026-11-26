"""Cổng bảo vệ tuyệt đối chống chạy seed / reset dữ liệu mẫu trên Production."""
from __future__ import annotations

import os

from django.conf import settings
from django.core.management.base import CommandError


def assert_non_production_seed_allowed(command_name: str) -> None:
    """Chặn cứng mọi lệnh seed dữ liệu giả / reset khi đang ở Production."""
    env_name = (getattr(settings, "KMG_ENV", "") or os.environ.get("KMG_ENV", "")).strip().lower()
    if env_name == "prod":
        raise CommandError(
            f"Từ chối chạy `{command_name}` vì KMG_ENV=prod (chặn tuyệt đối trên Production)."
        )
    if not getattr(settings, "ALLOW_DEMO_SEED", False):
        raise CommandError(
            f"Từ chối chạy `{command_name}` vì ALLOW_DEMO_SEED=False."
        )
