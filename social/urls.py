from django.urls import path

from . import views

app_name = "social"

urlpatterns = [
    path("mang-xa-hoi/", views.social_feed, name="feed"),
    path("mang-xa-hoi/bai/<int:pk>/", views.social_post_detail, name="post_detail"),
    path(
        "mang-xa-hoi/tep/<int:pk>/",
        views.social_attachment_download,
        name="attachment_download",
    ),
    path("tin-nhan/", views.messaging_inbox, name="messaging_inbox"),
    path("tin-nhan/bao-cao/", views.message_abuse_reports_view, name="abuse_reports"),
    path("tin-nhan/<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path(
        "tin-nhan/tep/<int:pk>/",
        views.chat_attachment_download,
        name="chat_attachment_download",
    ),
    path("nhac/", views.music_hub, name="music_hub"),
    path("nhac/playlist/<int:pk>/", views.playlist_detail, name="playlist_detail"),
]
