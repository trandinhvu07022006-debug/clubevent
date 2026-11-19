from django.urls import path

from . import views

app_name = "programs"

urlpatterns = [
    path("tai-lieu/", views.document_vault, name="document_vault"),
    path("tai-lieu/<int:pk>/", views.document_detail, name="document_detail"),
    path("tai-lieu/<int:pk>/tai-xuong/", views.document_download, name="document_download"),
    path("de-xuat/", views.proposal_hub, name="proposal_hub"),
    path("de-xuat/<int:pk>/", views.proposal_detail, name="proposal_detail"),
    path("dao-tao/", views.training_practice_hub, name="training_practice_hub"),
    path(
        "ban/<slug:slug>/showcase/them/",
        views.department_add_showcase,
        name="department_add_showcase",
    ),
]
