from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("cong-viec/", views.task_list, name="task_list"),
    path("cong-viec/<int:pk>/", views.task_detail, name="task_detail"),
    path(
        "cong-viec/tep-nop/<int:submission_id>/",
        views.download_task_submission_file,
        name="download_submission",
    ),
    path("su-kien/", views.event_hub, name="event_hub"),
    path("su-kien/<int:pk>/", views.event_detail, name="event_detail"),
    path("ky-luat/", views.discipline_center, name="discipline_center"),
]
