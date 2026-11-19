from django.urls import path

from . import views

app_name = "aiassist"

urlpatterns = [
    path("", views.chat_page, name="chat"),
    path("hoi/", views.chat_api, name="chat_api"),
    path("stream/", views.chat_stream_api, name="chat_stream_api"),
]
