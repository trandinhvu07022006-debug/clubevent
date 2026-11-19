from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("cai-dat/", views.notification_update_preferences, name="update_preferences"),
    path("<int:pk>/mo/", views.notification_open, name="open"),
    path("doc-het/", views.notification_read_all, name="read_all"),
]
