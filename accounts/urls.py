from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("dangnhap/", views.AppLoginView.as_view(), name="login"),
    path("dangxuat/", views.AppLogoutView.as_view(), name="logout"),
    path("dangky/", views.register, name="register"),
    path("xacminh/", views.verify_email, name="verify_email"),
    path("xacminh-otp/", views.verify_otp_view, name="verify_otp"),
    path("xacminh-otp/gui-lai/", views.resend_otp_view, name="resend_otp"),
    path("xacminh-email/<str:token>/", views.verify_email, name="verify_email"),
    path("xacminh-email-lai/", views.resend_verification_email, name="resend_verify_email"),
    path("hoso/", views.profile, name="profile"),
    path("thietbi/", views.session_list, name="sessions"),
    path("thietbi/<int:pk>/thuhoi/", views.session_revoke, name="session_revoke"),
    path("thietbi/thuhoi-khac/", views.session_revoke_others, name="session_revoke_others"),
    path("trang-thai/", views.membership_status_portal, name="membership_status"),
    path("doimatkhau/", views.AppPasswordChangeView.as_view(), name="password_change"),
    path("quenmatkhau/", views.AppPasswordResetView.as_view(), name="password_reset"),
    path(
        "quenmatkhau/dagui/",
        views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "datlai/<uidb64>/<token>/",
        views.AppPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "datlai/xong/",
        views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("quanly/", views.user_list, name="user_list"),
    path("quanly/<int:pk>/role/", views.user_set_role, name="user_role"),
    path(
        "quanly/<int:pk>/lanh-dao/",
        views.user_assign_leadership,
        name="user_assign_leadership",
    ),
    path(
        "quanly/<int:pk>/nhiem-ky/<int:appt_pk>/ket-thuc/",
        views.user_end_leadership,
        name="user_end_leadership",
    ),
    path("quanly/<int:pk>/khoa/", views.user_toggle_lock, name="user_lock"),
    path("nhatky/", views.audit_log, name="audit_log"),
]
