from django.urls import path

from . import views

app_name = "pages"

urlpatterns = [
    path("", views.home, name="home"),
    path("danh-cho-thanh-vien/", views.for_members, name="for_members"),
    path("danh-cho-ban-to-chuc/", views.for_organizers, name="for_organizers"),
    path("gioi-thieu/", views.about, name="about"),
    path("tong-quan/", views.dashboard, name="dashboard"),
]
