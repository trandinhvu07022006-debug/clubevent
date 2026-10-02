"""Định tuyến gốc. Mỗi app có file urls.py riêng."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("pages.urls")),
    path("", include("events.urls")),
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
