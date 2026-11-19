"""Một tiến trình định kỳ cho mỗi deployment; dừng gọn khi nhận SIGTERM."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


def write_status(path, *, ok, results, now=None):
    """Only command names and exit codes are persisted; never command output."""
    payload = {"ok": ok, "finished_at": time.time() if now is None else now, "results": results}
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)
    print(json.dumps({"event": "scheduler_cycle", **payload}), flush=True)


def main():
    interval = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "900"))
    if interval < 30:
        raise SystemExit("SCHEDULER_INTERVAL_SECONDS must be >= 30")
    timeout = int(os.environ.get("SCHEDULER_COMMAND_TIMEOUT_SECONDS", "300"))
    if timeout < 10:
        raise SystemExit("SCHEDULER_COMMAND_TIMEOUT_SECONDS must be >= 10")
    status_path = Path(os.environ.get("SCHEDULER_STATUS_PATH", "/tmp/kmg-scheduler.json"))
    status_path.unlink(missing_ok=True)
    stopped = threading.Event()
    child = None

    def stop(signum, frame):
        stopped.set()
        if child is not None and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    root = Path(__file__).resolve().parent.parent
    while not stopped.is_set():
        results = {}
        for command in ("run_periodic", "run_kmg_operations"):
            if stopped.is_set():
                break
            child = subprocess.Popen([sys.executable, "manage.py", command], cwd=root)
            try:
                result = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                result = 124
            child = None
            results[command] = result
            if result:
                print(f"Scheduler: {command} failed with exit {result}", file=sys.stderr, flush=True)
        if not stopped.is_set():
            write_status(status_path, ok=len(results) == 2 and not any(results.values()), results=results)
        stopped.wait(interval)


if __name__ == "__main__":
    main()
