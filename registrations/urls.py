from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path("dangky/<int:event_id>/", views.book, name="book"),
    path("cua-toi/", views.my_tickets, name="my_tickets"),
    path("<int:pk>/in/", views.ticket_print, name="print"),
    path("cho/<int:ticket_type_id>/", views.waitlist_join, name="waitlist_join"),
    path("cho/<int:pk>/roi/", views.waitlist_leave, name="waitlist_leave"),
    path("<int:pk>/huy/", views.cancel, name="cancel"),
    path("thanhtoan/", views.payment_list, name="payment_list"),
    path("thanhtoan/<int:pk>/xacnhan/", views.payment_confirm, name="payment_confirm"),
    path("thanhtoan/nhom/<str:ref>/xacnhan/", views.payment_confirm_booking,
         name="payment_confirm_booking"),
    path("checkin/<int:event_id>/", views.checkin, name="checkin"),
    path("checkin/<int:event_id>/quet/", views.checkin_scan, name="checkin_scan"),
    path("checkin/<int:event_id>/tiendo/", views.checkin_progress, name="checkin_progress"),
    path("thamgia/<int:event_id>/", views.participant_list, name="participants"),
    path("thamgia/<int:event_id>/csv/", views.participant_csv, name="participants_csv"),
]
