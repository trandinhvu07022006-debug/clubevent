"""Probe nội bộ, tránh gửi cookie hoặc header người dùng."""
import json
import os
from urllib.request import Request, urlopen


request = Request(
    "http://127.0.0.1:8000/health/",
    headers={"Host": os.environ.get("HEALTHCHECK_HOST", "localhost")},
)
with urlopen(request, timeout=8) as response:
    if response.status != 200 or json.load(response) != {"ok": True}:
        raise SystemExit(1)
