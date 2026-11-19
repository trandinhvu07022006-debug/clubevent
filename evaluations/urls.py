from django.urls import path

from . import views

app_name = "evaluations"

urlpatterns = [
    path("danh-gia/", views.evaluation_hub, name="hub"),
    path("danh-gia/soan-moi/", views.evaluation_draft_new, name="draft_new"),
    path("danh-gia/<int:pk>/", views.evaluation_detail, name="detail"),
    path("phan-tich/", views.analytics_dashboard, name="analytics"),
    path("phan-tich/bao-cao.csv", views.analytics_csv, name="analytics_csv"),
]
