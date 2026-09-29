from django.urls import path

from . import views

app_name = "organizing"

urlpatterns = [
    path("sukien/<int:event_id>/", views.task_board, name="board"),
    path("sukien/<int:event_id>/tao/", views.task_create, name="create"),
    path("sukien/<int:event_id>/ai/", views.ai_suggest, name="ai_suggest"),
    path("<int:pk>/sua/", views.task_update, name="update"),
    path("<int:pk>/xoa/", views.task_delete, name="delete"),
    path("<int:pk>/trangthai/", views.task_set_status, name="set_status"),
    path("viec-cua-toi/", views.my_tasks, name="my_tasks"),
]
