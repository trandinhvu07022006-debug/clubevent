"""Chạy local bằng dữ liệu riêng; email/SMS in trong terminal, không gửi ra ngoài."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Nạp các persona mẫu KMG trong DB local riêng")
    parser.add_argument("--prepare-only", action="store_true", help="Khởi tạo và kiểm tra, không chạy server")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port cần từ 1024 đến 65535")
    if sys.version_info < (3, 12):
        parser.error("Dùng Python 3.12 hoặc mới hơn")
    environment = dict(os.environ, PYTHONUTF8="1", KMG_LOCAL_SITE_URL=f"http://127.0.0.1:{args.port}")

    def manage(*arguments):
        subprocess.run(
            [sys.executable, str(ROOT / "manage.py"), *arguments, "--settings=config.settings_local"],
            cwd=ROOT, env=environment, check=True,
        )

    try:
        manage("migrate", "--noinput")
        manage("bootstrap_kmg")
        if args.demo:
            manage("seed_kmg")
        manage("collectstatic", "--noinput", "--verbosity=0")
        manage("check")
        print(f"Local KMG: http://127.0.0.1:{args.port} | Data: {ROOT / '.local-pilot'}", flush=True)
        if args.demo:
            print("Demo users: admin, chunhiem, truongban_cm, covan, thanhvien_daban | Password: Kmg@2026!", flush=True)
        else:
            print("If no admin exists yet: python manage.py createsuperuser --settings=config.settings_local", flush=True)
        print("Email/SMS are printed here. This launcher does not run a background scheduler.", flush=True)
        if not args.prepare_only:
            manage("runserver", f"127.0.0.1:{args.port}", "--noreload")
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
