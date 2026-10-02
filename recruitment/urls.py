from django.urls import path

from . import views

app_name = "recruitment"

urlpatterns = [
    path("", views.recruit_home, name="home"),
    path("nop-don/", views.apply, name="apply"),
    path("don-cua-toi/", views.my_application, name="my_application"),
    path("don/<int:pk>/rut/", views.withdraw, name="withdraw"),
    path("duyet/", views.review_list, name="review_list"),
    path("duyet/<int:pk>/", views.review_detail, name="review_detail"),
    path("dot/tao/", views.round_form, name="round_create"),
    path("dot/<int:pk>/sua/", views.round_form, name="round_update"),
]
