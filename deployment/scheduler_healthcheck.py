"""Fail when a scheduler cycle fails, stalls or never completed."""
import json
import os
from pathlib import Path
import time


def healthy(status, *, now, max_age):
    finished_at = status.get("finished_at")
    return (
        status.get("ok") is True
        and isinstance(finished_at, (float, int))
        and 0 <= now - finished_at <= max_age
        and status.get("results") == {"run_periodic": 0, "run_kmg_operations": 0}
    )


def main():
    path = Path(os.environ.get("SCHEDULER_STATUS_PATH", "/tmp/kmg-scheduler.json"))
    max_age = (
        int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "900"))
        + 2 * int(os.environ.get("SCHEDULER_COMMAND_TIMEOUT_SECONDS", "300"))
        + 60
    )
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        ready = isinstance(status, dict) and healthy(status, now=time.time(), max_age=max_age)
    except (OSError, ValueError, TypeError):
        ready = False
    raise SystemExit(0 if ready else 1)


if __name__ == "__main__":
    main()
