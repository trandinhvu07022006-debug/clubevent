"""F7.3 & Chỉ thị 3.5 - Trung tâm Thông báo, Tuỳ chọn Kênh nhắc việc & Nền tảng PWA."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from core.pagination import paginate

from .models import Notification
from .services import get_or_create_notification_preference


@login_required
def notification_list(request):
    """Danh sách thông báo của chính mình, phân trang 20, lọc chưa đọc & cài đặt kênh nhận."""
    qs = request.user.notifications.all()
    only_unread = request.GET.get("chua-doc") == "1"
    if only_unread:
        qs = qs.filter(is_read=False)
    page_obj, querystring = paginate(request, qs, per_page=20)
    preference = get_or_create_notification_preference(request.user)
    push_count = request.user.push_subscriptions.filter(is_active=True).count()
    return render(
        request,
        "notifications/list.html",
        {
            "items": page_obj,
            "page_obj": page_obj,
            "querystring": querystring,
            "only_unread": only_unread,
            "preference": preference,
            "push_count": push_count,
        },
    )


@require_POST
@login_required
def notification_open(request, pk):
    """
    Đánh dấu đã đọc rồi chuyển tới trang liên quan.

    - Lấy theo (pk, user) để không ai mở được thông báo của người khác (IDOR).
    - url do code sinh ra nhưng vẫn kiểm tra chống open redirect.
    """
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    if n.url and url_has_allowed_host_and_scheme(
        n.url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(n.url)
    return redirect("notifications:list")


@require_POST
@login_required
def notification_read_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    nxt = request.POST.get("next", "")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("notifications:list")


@require_POST
@login_required
def notification_update_preferences(request):
    """Cập nhật cài đặt nhận Email thông báo quan trọng / nhắc việc / Push PWA."""
    pref = get_or_create_notification_preference(request.user)
    pref.email_important = request.POST.get("email_important") == "1"
    pref.email_task_deadline = request.POST.get("email_task_deadline") == "1"
    pref.email_event_rsvp = request.POST.get("email_event_rsvp") == "1"
    pref.web_push_enabled = request.POST.get("web_push_enabled") == "1"
    pref.save()
    messages.success(request, "Đã lưu cài đặt kênh nhận thông báo & nhắc việc của bạn.")
    return redirect("notifications:list")


@require_GET
def pwa_manifest_view(request):
    """`/manifest.webmanifest` — Khai báo ứng dụng PWA cho điện thoại Android / iOS 16.4+."""
    manifest = {
        "name": "KMG Club Management Platform",
        "short_name": "KMG Club",
        "description": "Nền tảng quản trị nội bộ, công việc, sự kiện và âm nhạc của CLB KMG.",
        "start_url": "/workspace/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f7f6f3",
        "theme_color": "#34477d",
        "lang": "vi",
        "icons": [
            {
                "src": static("img/favicon.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": static("img/logo.jpg"),
                "sizes": "512x512",
                "type": "image/jpeg",
            },
        ],
    }
    return JsonResponse(
        manifest,
        content_type="application/manifest+json; charset=utf-8",
    )


@require_GET
def pwa_service_worker_view(request):
    """`/sw.js` — Service Worker hỗ trợ cài đặt PWA và xử lý Web Push Notification."""
    sw_script = """'use strict';
const CACHE_NAME = 'kmg-platform-shell-v1.2';
const PRECACHE_URLS = [
  '/',
  '/static/css/app.css',
  '/static/css/kmg_editorial.css',
  '/static/img/favicon.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      const results = await Promise.allSettled(
        PRECACHE_URLS.map(async (url) => {
          const response = await fetch(url, { cache: 'no-cache' });
          if (!response.ok) {
            throw new Error(`HTTP ${response.status} for ${url}`);
          }
          await cache.put(url, response);
          return url;
        })
      );
      const failed = results.filter((r) => r.status === 'rejected');
      if (failed.length) {
        console.warn('[KMG SW] Một số tài nguyên precache thất bại:', failed.map((f) => String(f.reason)));
      }
      if (failed.length === PRECACHE_URLS.length) {
        throw new Error('Toàn bộ tài nguyên precache đều thất bại');
      }
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('push', (event) => {
  let payload = { title: 'CLB KMG', body: 'Bạn có thông báo mới từ CLB KMG.', url: '/thongbao/' };
  if (event.data) {
    try {
      payload = Object.assign(payload, event.data.json());
    } catch (e) {
      payload.body = event.data.text();
    }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: '/static/img/favicon.png',
      data: { url: payload.url || '/thongbao/' }
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || '/thongbao/';
  event.waitUntil(clients.openWindow(targetUrl));
});
"""
    resp = HttpResponse(sw_script, content_type="application/javascript; charset=utf-8")
    resp["Service-Worker-Allowed"] = "/"
    resp["Cache-Control"] = "no-cache"
    return resp
