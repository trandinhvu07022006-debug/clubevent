from django.urls import path

from . import views

app_name = "organization"

urlpatterns = [
    path("", views.workspace_home, name="workspace_home"),
    path("ung-tuyen/", views.apply_membership, name="apply_membership"),
    path("quan-tri/", views.governance_center, name="governance_center"),
    path("giam-sat/", views.advisor_overview, name="advisor_overview"),
    path(
        "thanh-vien/<int:user_id>/lich-su/",
        views.member_lifecycle_view,
        name="member_lifecycle",
    ),
    path("ban/<slug:slug>/", views.department_detail, name="department_detail"),
    path(
        "ban/<slug:slug>/xac-minh-skill/<int:pk>/",
        views.department_verify_skill_view,
        name="department_verify_skill",
    ),
    path(
        "ban/<slug:slug>/so-duyet-don/<int:pk>/",
        views.department_screen_application_view,
        name="department_screen_application",
    ),
    path(
        "ban/<slug:slug>/bo-nhiem-pho-ban/",
        views.department_appoint_deputy_view,
        name="department_appoint_deputy",
    ),
    path(
        "ban/<slug:slug>/uy-quyen/",
        views.department_grant_bundle_view,
        name="department_grant_bundle",
    ),
]
