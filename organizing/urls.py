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
    path("<int:pk>/nhan/", views.task_claim, name="claim"),
    path("viec-cua-toi/", views.my_tasks, name="my_tasks"),
    path("giao-viec/", views.task_assign, name="assign"),
    path("ban/", views.department_list, name="department_list"),
    path("ban/tao/", views.department_create, name="department_create"),
    path("ban/<slug:slug>/", views.department_detail, name="department_detail"),
    path("ban/<slug:slug>/sua/", views.department_update, name="department_update"),
    path("ban/<slug:slug>/xoa/", views.department_delete, name="department_delete"),
    path("sukien/<int:event_id>/ngansach/", views.budget, name="budget"),
    path("sukien/<int:event_id>/ngansach/them/", views.expense_create,
         name="expense_create"),
    path("sukien/<int:event_id>/ngansach/csv/", views.budget_csv, name="budget_csv"),
    path("khoanchi/<int:pk>/sua/", views.expense_update, name="expense_update"),
    path("khoanchi/<int:pk>/xoa/", views.expense_delete, name="expense_delete"),
]
