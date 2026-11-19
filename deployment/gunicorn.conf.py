"""Cấu hình WSGI; tăng worker sau khi đo tải trên hạ tầng thật."""
import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
timeout = 60
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
# Django tự xử lý header đã được Nginx ghi đè; không tin header trực tiếp tại WSGI.
forwarded_allow_ips = ""
