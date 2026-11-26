"""Lệnh sinh dữ liệu Staging quy mô lớn, có seed tái lập và chặn tuyệt đối trên Production."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from organization.staging_seeder import SCALE_PRESETS, generate_staging_dataset


class Command(BaseCommand):
    help = "Sinh dữ liệu staging KMG có tham số quy mô (--scale) và random seed (--seed)."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument("--scale", choices=tuple(SCALE_PRESETS.keys()), default="smoke")
        parser.add_argument("--members", type=int, default=None)
        parser.add_argument("--guests", type=int, default=None)
        parser.add_argument("--events", type=int, default=None)
        parser.add_argument("--tickets", type=int, default=None)
        parser.add_argument("--tasks", type=int, default=None)
        parser.add_argument("--messages", type=int, default=None)
        parser.add_argument("--notifications", type=int, default=None)
        parser.add_argument("--logs", type=int, default=None)

    def handle(self, *args, **options):
        overrides = {
            k: options[k]
            for k in ("members", "guests", "events", "tickets", "tasks", "messages", "notifications", "logs")
        }
        summary = generate_staging_dataset(
            seed=options["seed"],
            scale=options["scale"],
            overrides=overrides,
        )
        self.stdout.write(json.dumps({"seed": options["seed"], "scale": options["scale"], "counts": summary}, ensure_ascii=False))
