from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path("gui/<int:event_id>/", views.send_feedback, name="send"),
    path("sukien/<int:event_id>/", views.feedback_list, name="list"),
    path("sukien/<int:event_id>/ai/", views.ai_summarize, name="ai_summarize"),
]
