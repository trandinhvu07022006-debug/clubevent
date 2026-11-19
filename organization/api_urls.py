from django.urls import path

from evaluations import api_views as eval_api
from finance import api_views as fin_api
from operations import api_views as ops_api
from programs import api_views as prog_api
from public_portal import views as public_views
from social import api_views as social_api

from . import api_views

app_name = "api_v1"

urlpatterns = [
    path("auth/me/", api_views.api_auth_me, name="auth_me"),
    path("auth/register/", api_views.api_auth_register, name="auth_register"),
    path("auth/otp/send/", api_views.api_auth_otp_send, name="auth_otp_send"),
    path("auth/otp/verify/", api_views.api_auth_otp_verify, name="auth_otp_verify"),
    path("auth/sessions/", api_views.api_auth_sessions, name="auth_sessions"),
    path(
        "auth/sessions/<int:pk>/revoke/",
        api_views.api_auth_session_revoke,
        name="auth_session_revoke",
    ),
    path("departments/", api_views.api_departments_list, name="departments_list"),
    path(
        "departments/<slug:slug>/",
        api_views.api_department_detail,
        name="department_detail",
    ),
    path(
        "departments/<slug:slug>/members/",
        api_views.api_department_members,
        name="department_members",
    ),
    path(
        "appointments/",
        api_views.api_appointments_create,
        name="appointments_create",
    ),
    path(
        "appointments/<int:pk>/end/",
        api_views.api_appointment_end,
        name="appointment_end",
    ),
    path(
        "permission-grants/",
        api_views.api_permission_grants,
        name="permission_grants",
    ),
    path(
        "permission-grants/<int:pk>/revoke/",
        api_views.api_permission_grant_revoke,
        name="permission_grant_revoke",
    ),
    path("skills/me/", api_views.api_my_skills, name="my_skills"),
    path(
        "skills/user-skills/<int:pk>/verify/",
        api_views.api_verify_user_skill,
        name="verify_user_skill",
    ),
    path(
        "members/promote/",
        api_views.api_members_promote,
        name="members_promote",
    ),
    path(
        "members/<int:user_id>/lifecycle/",
        api_views.api_member_lifecycle,
        name="member_lifecycle",
    ),
    path(
        "admin/leadership/",
        api_views.api_admin_assign_leadership,
        name="admin_assign_leadership",
    ),
    path(
        "resources/<str:resource_code>/access-check/",
        api_views.api_resource_access_check,
        name="resource_access_check",
    ),
    path(
        "public/contact/",
        public_views.api_public_contact,
        name="public_contact",
    ),
    # --- Phase 2: Core Management ---
    path("tasks/", ops_api.api_tasks, name="tasks"),
    path("tasks/<int:pk>/", ops_api.api_task_detail, name="task_detail"),
    path("tasks/<int:pk>/progress/", ops_api.api_task_progress, name="task_progress"),
    path("tasks/<int:pk>/submit/", ops_api.api_task_submit, name="task_submit"),
    path("tasks/<int:pk>/review/", ops_api.api_task_review, name="task_review"),
    path("club-events/", ops_api.api_club_events, name="club_events"),
    path("club-events/<int:pk>/rsvp/", ops_api.api_club_event_rsvp, name="club_event_rsvp"),
    path("club-events/<int:pk>/review/", ops_api.api_club_event_review, name="club_event_review"),
    path("discipline-cases/", ops_api.api_discipline_cases, name="discipline_cases"),
    path(
        "discipline-cases/<int:pk>/resolve/",
        ops_api.api_discipline_case_resolve,
        name="discipline_case_resolve",
    ),
    path("appeals/", ops_api.api_appeals, name="appeals"),
    path("appeals/<int:pk>/adjudicate/", ops_api.api_appeal_adjudicate, name="appeal_adjudicate"),
    path("announcements/", ops_api.api_announcements, name="announcements"),
    path(
        "notifications/preferences/",
        ops_api.api_notification_preferences,
        name="notification_preferences",
    ),
    path("notifications/push-subscribe/", ops_api.api_push_subscribe, name="push_subscribe"),
    # --- Phase 3: Department Management, Vault ACL, Proposals & Training/Practice ---
    path("documents/", prog_api.api_documents, name="documents"),
    path("documents/<int:pk>/", prog_api.api_document_detail, name="document_detail"),
    path("documents/<int:pk>/download/", prog_api.api_document_download, name="document_download"),
    path("documents/<int:pk>/acl/", prog_api.api_document_acl, name="document_acl"),
    path("documents/<int:pk>/break-glass/", prog_api.api_document_break_glass, name="document_break_glass"),
    path("proposals/", prog_api.api_proposals, name="proposals"),
    path("proposals/<int:pk>/", prog_api.api_proposal_detail, name="proposal_detail"),
    path("proposals/<int:pk>/review/", prog_api.api_proposal_review, name="proposal_review"),
    path("proposals/<int:pk>/convert/", prog_api.api_proposal_convert, name="proposal_convert"),
    path("training-courses/", prog_api.api_training_courses, name="training_courses"),
    path("training-courses/<int:pk>/enroll/", prog_api.api_training_enroll, name="training_enroll"),
    path("practice-sessions/", prog_api.api_practice_sessions, name="practice_sessions"),
    path("practice-sessions/<int:pk>/attendance/", prog_api.api_practice_attendance, name="practice_attendance"),
    # --- Phase 4: Internal Social, Encrypted AES-256-GCM Messaging & Music Playlists ---
    path("social/posts/", social_api.api_social_posts, name="social_posts"),
    path("social/posts/<int:pk>/", social_api.api_social_post_detail, name="social_post_detail"),
    path("social/posts/<int:pk>/react/", social_api.api_social_post_react, name="social_post_react"),
    path("social/posts/<int:pk>/comments/", social_api.api_social_post_comments, name="social_post_comments"),
    path("social/posts/<int:pk>/report/", social_api.api_social_post_report, name="social_post_report"),
    path("social/posts/<int:pk>/moderate/", social_api.api_social_post_moderate, name="social_post_moderate"),
    path("social/moderation/queue/", social_api.api_social_moderation_queue, name="social_moderation_queue"),
    path("social/attachments/<int:pk>/download/", social_api.api_social_attachment_download, name="social_attachment_download"),
    path("messages/conversations/", social_api.api_conversations, name="conversations"),
    path("messages/conversations/<int:pk>/messages/", social_api.api_conversation_messages, name="conversation_messages"),
    path("messages/conversations/<int:pk>/leave/", social_api.api_conversation_leave, name="conversation_leave"),
    path("messages/<int:pk>/recall/", social_api.api_message_recall, name="message_recall"),
    path("messages/<int:pk>/react/", social_api.api_message_react, name="message_react"),
    path("messages/<int:pk>/report/", social_api.api_message_report, name="message_report"),
    path("messages/abuse-reports/", social_api.api_abuse_reports, name="message_abuse_reports"),
    path("messages/abuse-reports/<int:pk>/review/", social_api.api_abuse_report_review, name="message_abuse_report_review"),
    path("messages/attachments/<int:pk>/download/", social_api.api_chat_attachment_download, name="chat_attachment_download"),
    path("music/playlists/", social_api.api_playlists, name="music_playlists"),
    path("music/playlists/<int:pk>/", social_api.api_playlist_detail, name="music_playlist_detail"),
    path("music/playlists/<int:pk>/items/", social_api.api_playlist_add_item, name="music_playlist_add_item"),
    path("music/items/<int:pk>/", social_api.api_playlist_remove_item, name="music_playlist_remove_item"),
    path("music/recipients/search/", social_api.api_music_recipients_search, name="music_recipients_search"),
    path("music/shares/", social_api.api_music_shares, name="music_shares"),
    path("music/shares/<int:pk>/save/", social_api.api_music_share_save, name="music_share_save"),
    # --- Phase 5: Sổ cái Quỹ Bất biến, Maker-Checker, Đánh giá 7 Tiêu chí, Vinh danh & Phân tích ---
    path("finance/summary/", fin_api.api_finance_summary, name="finance_summary"),
    path("finance/transactions/", fin_api.api_finance_transactions, name="finance_transactions"),
    path("finance/transactions/<int:pk>/", fin_api.api_finance_transaction_detail, name="finance_transaction_detail"),
    path("finance/transactions/<int:pk>/review/", fin_api.api_finance_transaction_review, name="finance_transaction_review"),
    path("finance/transactions/<int:pk>/adjust/", fin_api.api_finance_transaction_adjust, name="finance_transaction_adjust"),
    path("finance/contributions/", fin_api.api_finance_contributions, name="finance_contributions"),
    path("finance/my-contributions/", fin_api.api_finance_my_contributions, name="finance_my_contributions"),
    path("finance/export/", fin_api.api_finance_ledger_export, name="finance_ledger_export"),
    path("evaluations/my/", eval_api.api_evaluations_my, name="evaluations_my"),
    path("evaluations/", eval_api.api_evaluations_list, name="evaluations_list"),
    path("evaluations/<int:pk>/", eval_api.api_evaluation_detail, name="evaluations_detail"),
    path("evaluations/<int:pk>/finalize/", eval_api.api_evaluation_finalize, name="evaluations_finalize"),
    path("evaluations/<int:pk>/response/", eval_api.api_evaluation_response, name="evaluations_response"),
    path("recognitions/", eval_api.api_recognitions, name="recognitions"),
    path("recognitions/<int:pk>/verify/", eval_api.api_recognition_verify, name="recognition_verify"),
    path("analytics/summary/", eval_api.api_analytics_summary, name="analytics_summary"),
    path("analytics/export/", eval_api.api_analytics_export_csv, name="analytics_export_csv"),
]
