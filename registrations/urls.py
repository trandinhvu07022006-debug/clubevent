from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path("dangky/<int:event_id>/", views.book, name="book"),
    path("cua-toi/", views.my_tickets, name="my_tickets"),
    path("<int:pk>/huy/", views.cancel, name="cancel"),
    path("thanhtoan/", views.payment_list, name="payment_list"),
    path("thanhtoan/<int:pk>/xacnhan/", views.payment_confirm, name="payment_confirm"),
    path("checkin/<int:event_id>/", views.checkin, name="checkin"),
    path("thamgia/<int:event_id>/", views.participant_list, name="participants"),
    path("thamgia/<int:event_id>/csv/", views.participant_csv, name="participants_csv"),
]
