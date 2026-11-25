"""Định tuyến gốc. Mỗi app có file urls.py riêng."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.throttle import throttle_login
from core.health import health
from notifications import views as notification_views

urlpatterns = [
    path("health/", health, name="health"),
    path("manifest.webmanifest", notification_views.pwa_manifest_view, name="pwa_manifest"),
    path("sw.js", notification_views.pwa_service_worker_view, name="pwa_service_worker"),
    # Phải đứng TRƯỚC admin.site.urls để mọi lượt đăng nhập admin bị giới hạn
    path("admin/login/", throttle_login(admin.site.login)),
    path("admin/", admin.site.urls),
    path("", include("pages.urls")),
    path("", include("events.urls")),
    path("portal/", include("public_portal.urls")),
    # KMG Enterprise Workspace
    path("workspace/", include("evaluations.urls")),
    path("workspace/", include("finance.urls")),
    path("workspace/", include("social.urls")),
    path("workspace/", include("programs.urls")),
    path("workspace/", include("operations.urls")),
    path("workspace/", include("organization.urls")),
    path("api/v1/", include("organization.api_urls")),
    path("taikhoan/", include("accounts.urls")),
    path("congviec/", include("organizing.urls")),
    path("ve/", include("registrations.urls")),
    path("phanhoi/", include("feedback.urls")),
    path("troly/", include("aiassist.urls")),
    path("thongbao/", include("notifications.urls")),
    path("tuyen-thanh-vien/", include("recruitment.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
