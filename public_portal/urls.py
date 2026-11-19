from django.urls import path

from . import views

app_name = "public_portal"

urlpatterns = [
    path("", views.home, name="home"),
]
