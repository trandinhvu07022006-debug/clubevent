from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="list"),
    path("sukien/<int:pk>/", views.event_detail, name="detail"),
    path("sukien/tao/", views.event_create, name="create"),
    path("sukien/<int:pk>/sua/", views.event_update, name="update"),
    path("sukien/<int:pk>/trangthai/", views.event_set_status, name="set_status"),
    path("sukien/<int:pk>/loaive/them/", views.ticket_type_create, name="tt_create"),
    path("loaive/<int:pk>/xoa/", views.ticket_type_delete, name="tt_delete"),
    path("thongke/", views.dashboard, name="dashboard"),
]
