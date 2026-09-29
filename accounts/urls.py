from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("dangnhap/", views.AppLoginView.as_view(), name="login"),
    path("dangxuat/", views.AppLogoutView.as_view(), name="logout"),
    path("dangky/", views.register, name="register"),
    path("hoso/", views.profile, name="profile"),
    path("doimatkhau/", views.AppPasswordChangeView.as_view(),
         name="password_change"),
    path("quanly/", views.user_list, name="user_list"),
    path("quanly/<int:pk>/role/", views.user_set_role, name="user_role"),
    path("quanly/<int:pk>/khoa/", views.user_toggle_lock, name="user_lock"),
    path("nhatky/", views.audit_log, name="audit_log"),
]
