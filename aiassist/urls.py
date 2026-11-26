from django.urls import path

from . import views

app_name = "aiassist"

urlpatterns = [
    path("", views.chat_page, name="chat"),
    path("hoi/", views.chat_api, name="chat_api"),
    path("stream/", views.chat_stream_api, name="chat_stream_api"),
    path("danh-gia/", views.chat_feedback_api, name="chat_feedback_api"),
    path("ho-so-nhac/", views.music_profile_api, name="music_profile_api"),
    path("huan-luyen/", views.ai_studio, name="studio"),
    path("huan-luyen/kiem-dinh/", views.ai_studio_eval, name="studio_eval"),
    path("huan-luyen/chay-pipeline/", views.ai_studio_run_pipeline, name="studio_run_pipeline"),
    path("huan-luyen/xuat-eval/", views.ai_studio_eval_export, name="studio_eval_export"),
    path("huan-luyen/xuat-jsonl/", views.ai_studio_export, name="studio_export"),
]
