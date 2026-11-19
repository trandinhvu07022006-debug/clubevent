"""
REST API `/api/v1/` — Phase 4 Internal Social, Encrypted Messaging & Music Playlists:
- Mạng xã hội Nội bộ (`/api/v1/social/posts/`, `react`, `comments`, `report`, `moderate`, `moderation/queue`, `attachments/download`).
- Nhắn tin Nội bộ Mã hóa AES-256-GCM (`/api/v1/messages/conversations/`, `messages`, `leave`, `recall`, `react`, `report`, `abuse-reports`).
- Playlist & Tặng nhạc (`/api/v1/music/playlists/`, `recipients/search/` [`BE-05`, `SEC-04`, `SEC-06`], `shares/`).
"""
from __future__ import annotations

from functools import wraps
import os

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.models import User
from operations.models import ClubEventProfile, ClubTask
from organization.api_views import _parse_json_body, api_error, api_ok
from organization.models import Department
from organization.permissions import PermissionEngine, api_login_required
from organization.services import GovernanceError
from programs.services import _is_active_club_actor, _is_pure_advisor

from .models import (
    AbuseReportStatus,
    ChatAttachment,
    ChatMessage,
    ChatReactionEmoji,
    Conversation,
    ConversationMember,
    MessageAbuseReport,
    MusicPlaylist,
    MusicShare,
    PlaylistItem,
    PlaylistVisibility,
    SocialModerationAction,
    SocialPost,
    SocialPostAttachment,
    SocialPostVisibility,
    SocialReactionType,
    SocialReport,
)
from .services import (
    add_social_comment,
    add_track_to_playlist,
    can_access_conversation,
    can_view_playlist,
    can_view_post,
    create_custom_conversation,
    create_playlist,
    create_social_post,
    ensure_club_conversation,
    ensure_department_conversation,
    ensure_event_conversation,
    ensure_task_conversation,
    get_moderation_queue,
    get_or_create_direct_conversation,
    leave_conversation,
    list_abuse_reports_for_reviewer,
    list_conversations_for_user,
    list_decrypted_messages,
    list_visible_posts,
    moderate_social_post,
    recall_chat_message,
    remove_track_from_playlist,
    report_message_abuse,
    report_social_post,
    review_message_abuse_report,
    save_shared_track_to_playlist,
    search_recipients_for_share,
    send_chat_message,
    send_music_share,
    serialize_post_for_viewer,
    soft_delete_social_post,
    toggle_chat_reaction,
    toggle_social_reaction,
    update_playlist,
)


def _api_guard(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except PermissionDenied as exc:
            return api_error("PERMISSION_DENIED", str(exc) or "Không đủ quyền.", status=403)
        except Http404:
            return api_error("NOT_FOUND", "Không tìm thấy tài nguyên.", status=404)
        except ValidationError as exc:
            return api_error("VALIDATION_ERROR", "; ".join(exc.messages), status=400)
        except GovernanceError as exc:
            http_status = 429 if exc.code == "RATE_LIMITED" else 400
            return api_error(exc.code, str(exc), status=http_status)

    return wrapper


def _post_to_json(serialized: dict) -> dict:
    def _cmt_to_json(c: dict) -> dict:
        return {
            "id": c["id"],
            "author_id": c["author_id"],
            "author_name": c["author_name"],
            "content": c["content"],
            "parent_id": c["parent_id"],
            "mentioned_usernames": c["mentioned_usernames"],
            "reaction_counts": c["reaction_counts"],
            "my_reaction": c["my_reaction"],
            "created_at": c["created_at"].isoformat(),
            "replies": [_cmt_to_json(r) for r in c["replies"]],
        }

    sp = serialized["shared_post_data"]
    if sp is not None:
        sp_json = {
            "id": sp["id"],
            "author_id": sp["author_id"],
            "author_name": sp["author_name"],
            "visibility": sp["visibility"],
            "department_name": sp["department_name"],
            "content": sp["content"],
            "link_url": sp["link_url"],
            "attachments": sp["attachments"],
            "created_at": sp["created_at"].isoformat(),
        }
    else:
        sp_json = None

    return {
        "id": serialized["id"],
        "author_id": serialized["author_id"],
        "author_name": serialized["author_name"],
        "visibility": serialized["visibility"],
        "department": serialized["department"],
        "content": serialized["content"],
        "link_url": serialized["link_url"],
        "moderation_status": serialized["moderation_status"],
        "attachments": serialized["attachments"],
        "reaction_counts": serialized["reaction_counts"],
        "reaction_total": serialized["reaction_total"],
        "my_reaction": serialized["my_reaction"],
        "comment_count": serialized["comment_count"],
        "comments": [_cmt_to_json(c) for c in serialized["comments"]],
        "shared_post_id": serialized["shared_post_id"],
        "shared_post_restricted": serialized["shared_post_restricted"],
        "shared_post_placeholder": serialized["shared_post_placeholder"],
        "shared_post_data": sp_json,
        "can_delete": serialized["can_delete"],
        "can_moderate": serialized["can_moderate"],
        "created_at": serialized["created_at"].isoformat(),
    }


def _playlist_to_json(pl: MusicPlaylist) -> dict:
    return {
        "id": pl.id,
        "owner_id": pl.owner_id,
        "owner_name": pl.owner.public_name,
        "title": pl.title,
        "description": pl.description,
        "visibility": pl.visibility,
        "items": [
            {
                "id": it.id,
                "source_provider": it.source_provider,
                "external_track_id": it.external_track_id,
                "track_url": it.track_url,
                "title": it.title,
                "artist_name": it.artist_name,
                "duration_seconds": it.duration_seconds,
            }
            for it in pl.items.all()
        ],
        "updated_at": pl.updated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# 1. INTERNAL SOCIAL API (`/api/v1/social/...`)
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_social_posts(request):
    if request.method == "GET":
        scope = (request.GET.get("scope") or "ALL").strip().upper()
        dept_slug = (request.GET.get("dept") or "").strip()
        dept = Department.objects.filter(slug=dept_slug, is_active=True).first() if dept_slug else None
        items = list_visible_posts(request.user, scope=scope, department=dept)
        return api_ok([_post_to_json(it) for it in items])

    if request.FILES:
        data = request.POST
        files = request.FILES.getlist("attachments")
        aud_ids = [int(x) for x in request.POST.getlist("audience_user_ids") if x.isdigit()]
    else:
        data = _parse_json_body(request)
        files = []
        aud_ids = [int(x) for x in (data.get("audience_user_ids") or []) if str(x).isdigit()]

    dept_id = data.get("department_id")
    dept = (
        Department.objects.filter(pk=dept_id, is_active=True).first()
        if str(dept_id or "").isdigit()
        else None
    )
    shared_id = data.get("shared_post_id")
    shared_post = (
        get_object_or_404(SocialPost, pk=shared_id)
        if str(shared_id or "").isdigit()
        else None
    )
    aud_users = list(User.objects.filter(pk__in=aud_ids)) if aud_ids else []
    post = create_social_post(
        request.user,
        content=data.get("content", ""),
        visibility=data.get("visibility", SocialPostVisibility.CLUB),
        department=dept,
        audience_users=aud_users,
        shared_post=shared_post,
        link_url=data.get("link_url", ""),
        attachments=files,
    )
    return api_ok(_post_to_json(serialize_post_for_viewer(request.user, post)), status=201)


@require_http_methods(["GET", "DELETE"])
@api_login_required
@_api_guard
def api_social_post_detail(request, pk: int):
    post = get_object_or_404(SocialPost, pk=pk)
    if request.method == "DELETE":
        soft_delete_social_post(request.user, post)
        return api_ok({"id": post.id, "is_deleted": True})
    if not can_view_post(request.user, post):
        raise PermissionDenied("Bạn không có quyền xem bài viết này (`PA-05`).")
    return api_ok(_post_to_json(serialize_post_for_viewer(request.user, post)))


@require_POST
@api_login_required
@_api_guard
def api_social_post_react(request, pk: int):
    post = get_object_or_404(SocialPost, pk=pk)
    data = _parse_json_body(request)
    res = toggle_social_reaction(
        request.user,
        reaction_type=data.get("reaction_type", SocialReactionType.LIKE),
        post=post,
    )
    return api_ok(res)


@require_POST
@api_login_required
@_api_guard
def api_social_post_comments(request, pk: int):
    post = get_object_or_404(SocialPost, pk=pk)
    data = _parse_json_body(request)
    parent_id = data.get("parent_id")
    parent = (
        get_object_or_404(post.comments.model, pk=parent_id, post=post)
        if str(parent_id or "").isdigit()
        else None
    )
    cmt = add_social_comment(
        request.user,
        post,
        content=data.get("content", ""),
        parent_comment=parent,
    )
    return api_ok(
        {
            "id": cmt.id,
            "post_id": post.id,
            "content": cmt.content,
            "mentioned_usernames": [u.username for u in cmt.mentioned_users.all()],
        },
        status=201,
    )


@require_POST
@api_login_required
@_api_guard
def api_social_post_report(request, pk: int):
    post = get_object_or_404(SocialPost, pk=pk)
    data = _parse_json_body(request)
    rep = report_social_post(request.user, post, reason=data.get("reason", ""))
    return api_ok({"id": rep.id, "status": rep.status}, status=201)


@require_POST
@api_login_required
@_api_guard
def api_social_post_moderate(request, pk: int):
    post = get_object_or_404(SocialPost, pk=pk)
    data = _parse_json_body(request)
    rep_id = data.get("report_id")
    rep = (
        SocialReport.objects.filter(pk=rep_id, post=post).first()
        if str(rep_id or "").isdigit()
        else None
    )
    log_entry = moderate_social_post(
        request.user,
        post,
        action=data.get("action", SocialModerationAction.HIDE),
        note=data.get("note", ""),
        report=rep,
    )
    return api_ok(
        {
            "log_id": log_entry.id,
            "post_id": post.id,
            "moderation_status": post.moderation_status,
            "action": log_entry.action,
        }
    )


@require_GET
@api_login_required
@_api_guard
def api_social_moderation_queue(request):
    reports = get_moderation_queue(request.user)
    return api_ok(
        [
            {
                "id": r.id,
                "post_id": r.post_id,
                "post_visibility": r.post.visibility,
                "department": r.post.department.name if r.post.department_id else None,
                "post_excerpt": r.post.content[:140],
                "reporter_name": r.reporter.public_name,
                "reason": r.reason,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in reports
        ]
    )


@require_GET
@api_login_required
@_api_guard
def api_social_attachment_download(request, pk: int):
    att = get_object_or_404(SocialPostAttachment.objects.select_related("post"), pk=pk)
    if not can_view_post(request.user, att.post):
        raise PermissionDenied("Bạn không có quyền tải tệp đính kèm này.")
    if not att.file:
        raise Http404("Tệp không tồn tại.")
    resp = FileResponse(
        att.file.open("rb"),
        as_attachment=True,
        filename=os.path.basename(att.original_filename or f"social_{att.pk}.bin"),
        content_type=att.content_type or "application/octet-stream",
    )
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    return resp


# ---------------------------------------------------------------------------
# 2. ENCRYPTED MESSAGING API (`/api/v1/messages/...`)
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_conversations(request):
    if request.method == "GET":
        items = list_conversations_for_user(request.user)
        return api_ok(
            [
                {
                    "id": it["id"],
                    "conv_type": it["conv_type"],
                    "display_title": it["display_title"],
                    "member_count": it["member_count"],
                    "has_unread": it["has_unread"],
                    "last_message_at": it["last_message_at"].isoformat()
                    if it["last_message_at"]
                    else None,
                }
                for it in items
            ]
        )

    data = _parse_json_body(request)
    kind = (data.get("conv_type") or "DIRECT_1ON1").upper()
    if kind == "DIRECT_1ON1":
        peer = get_object_or_404(User, pk=data.get("peer_user_id"))
        conv = get_or_create_direct_conversation(request.user, peer)
    elif kind == "CUSTOM_GROUP":
        m_ids = [int(x) for x in (data.get("member_user_ids") or []) if str(x).isdigit()]
        conv = create_custom_conversation(
            request.user,
            title=data.get("title", ""),
            member_users=list(User.objects.filter(pk__in=m_ids)),
        )
    elif kind == "CLUB_WIDE":
        if _is_pure_advisor(request.user):
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
        if not _is_active_club_actor(request.user):
            raise PermissionDenied("Chỉ thành viên CLB mới được vào phòng chat chung.")
        conv = ensure_club_conversation(created_by=request.user)
        ConversationMember.objects.update_or_create(
            conversation=conv, user=request.user, defaults={"left_at": None}
        )
    elif kind == "DEPARTMENT":
        if _is_pure_advisor(request.user):
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
        dept = get_object_or_404(Department, pk=data.get("department_id"), is_active=True)
        if dept.id not in PermissionEngine.get_active_department_ids(request.user):
            raise PermissionDenied("Bạn không thuộc Ban này.")
        conv = ensure_department_conversation(dept, created_by=request.user)
    elif kind == "EVENT":
        ce = get_object_or_404(ClubEventProfile, pk=data.get("club_event_id"))
        conv = ensure_event_conversation(request.user, ce)
    elif kind == "TASK":
        task = get_object_or_404(ClubTask, pk=data.get("task_id"))
        conv = ensure_task_conversation(request.user, task)
    else:
        raise GovernanceError("Loại hội thoại không hợp lệ.")
    return api_ok({"id": conv.id, "conv_type": conv.conv_type, "title": conv.title}, status=201)


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_conversation_messages(request, pk: int):
    conv = get_object_or_404(Conversation, pk=pk)
    if request.method == "GET":
        after_raw = (request.GET.get("after_id") or "").strip()
        after_id = int(after_raw) if after_raw.isdigit() else None
        q = (request.GET.get("q") or "").strip()
        msgs = list_decrypted_messages(
            request.user, conv, after_id=after_id, search_query=q
        )
        return api_ok(
            [
                {
                    "id": m["id"],
                    "sender_id": m["sender_id"],
                    "sender_name": m["sender_name"],
                    "is_mine": m["is_mine"],
                    "text": m["text"],
                    "is_recalled": m["is_recalled"],
                    "attachments": m["attachments"],
                    "reaction_counts": m["reaction_counts"],
                    "my_reaction": m["my_reaction"],
                    "can_recall": m["can_recall"],
                    "can_report": m["can_report"],
                    "created_at": m["created_at_iso"],
                }
                for m in msgs
            ]
        )

    if request.FILES:
        data = request.POST
        att_file = request.FILES.get("attachment")
    else:
        data = _parse_json_body(request)
        att_file = None

    reply_id = data.get("reply_to_id")
    reply_to = (
        ChatMessage.objects.filter(pk=reply_id, conversation=conv).first()
        if str(reply_id or "").isdigit()
        else None
    )
    msg = send_chat_message(
        request.user,
        conv,
        plaintext=data.get("plaintext", ""),
        attachment_file=att_file,
        reply_to=reply_to,
    )
    return api_ok({"id": msg.id, "conversation_id": conv.id}, status=201)


@require_POST
@api_login_required
@_api_guard
def api_conversation_leave(request, pk: int):
    conv = get_object_or_404(Conversation, pk=pk)
    cm = leave_conversation(request.user, conv)
    return api_ok({"conversation_id": conv.id, "left_at": cm.left_at.isoformat()})


@require_POST
@api_login_required
@_api_guard
def api_message_recall(request, pk: int):
    msg = get_object_or_404(ChatMessage, pk=pk)
    recall_chat_message(request.user, msg)
    return api_ok({"id": msg.id, "is_recalled": True})


@require_POST
@api_login_required
@_api_guard
def api_message_react(request, pk: int):
    msg = get_object_or_404(ChatMessage, pk=pk)
    data = _parse_json_body(request)
    res = toggle_chat_reaction(
        request.user, msg, emoji=data.get("emoji", ChatReactionEmoji.LIKE)
    )
    return api_ok(res)


@require_POST
@api_login_required
@_api_guard
def api_message_report(request, pk: int):
    msg = get_object_or_404(ChatMessage, pk=pk)
    data = _parse_json_body(request)
    rep = report_message_abuse(request.user, msg, reason=data.get("reason", ""))
    return api_ok(
        {
            "id": rep.id,
            "status": rep.status,
            "hmac_proof": rep.hmac_proof,
        },
        status=201,
    )


@require_GET
@api_login_required
@_api_guard
def api_abuse_reports(request):
    items = list_abuse_reports_for_reviewer(request.user)
    return api_ok(
        [
            {
                "id": it["report"].id,
                "reporter_id": it["report"].reporter_id,
                "reported_user_id": it["report"].reported_user_id,
                "reported_user_name": it["report"].reported_user.public_name,
                "conversation_id": it["report"].conversation_id,
                "message_id": it["report"].message_id,
                "reason": it["report"].reason,
                "verified_plaintext_snapshot": it["report"].verified_plaintext_snapshot,
                "hmac_valid": it["hmac_valid"],
                "status": it["report"].status,
                "can_adjudicate": it["can_adjudicate"],
            }
            for it in items
        ]
    )


@require_POST
@api_login_required
@_api_guard
def api_abuse_report_review(request, pk: int):
    rep = get_object_or_404(MessageAbuseReport, pk=pk)
    data = _parse_json_body(request)
    review_message_abuse_report(
        request.user,
        rep,
        status=data.get("status", AbuseReportStatus.ACTION_TAKEN),
        resolution_note=data.get("resolution_note", ""),
    )
    return api_ok({"id": rep.id, "status": rep.status})


@require_GET
@api_login_required
@_api_guard
def api_chat_attachment_download(request, pk: int):
    att = get_object_or_404(ChatAttachment.objects.select_related("message__conversation"), pk=pk)
    if not can_access_conversation(request.user, att.message.conversation):
        raise PermissionDenied("Bạn không có quyền tải tệp đính kèm tin nhắn này (`INV-05`).")
    if att.message.is_recalled or not att.file:
        raise Http404("Tệp không khả dụng.")
    resp = FileResponse(
        att.file.open("rb"),
        as_attachment=True,
        filename=os.path.basename(att.original_filename or f"chat_{att.pk}.bin"),
        content_type=att.content_type or "application/octet-stream",
    )
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    return resp


# ---------------------------------------------------------------------------
# 3. MUSIC PLAYLIST & GIFTING API (`/api/v1/music/...`)
# ---------------------------------------------------------------------------
@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_playlists(request):
    if request.method == "GET":
        if not _is_active_club_actor(request.user):
            raise PermissionDenied("Chỉ thành viên CLB mới có quyền xem playlist.")
        own = list(MusicPlaylist.objects.filter(owner=request.user).select_related("owner").prefetch_related("items"))
        shared = list(
            MusicPlaylist.objects.filter(visibility=PlaylistVisibility.CLUB_SHARED)
            .exclude(owner=request.user)
            .select_related("owner")
            .prefetch_related("items")
        )
        return api_ok(
            {
                "mine": [_playlist_to_json(p) for p in own],
                "club_shared": [_playlist_to_json(p) for p in shared],
            }
        )

    data = _parse_json_body(request)
    pl = create_playlist(
        request.user,
        title=data.get("title", ""),
        description=data.get("description", ""),
        visibility=data.get("visibility", PlaylistVisibility.PRIVATE),
    )
    return api_ok(_playlist_to_json(pl), status=201)


@require_http_methods(["GET", "PATCH"])
@api_login_required
@_api_guard
def api_playlist_detail(request, pk: int):
    pl = get_object_or_404(MusicPlaylist.objects.select_related("owner").prefetch_related("items"), pk=pk)
    if request.method == "GET":
        if not can_view_playlist(request.user, pl):
            raise PermissionDenied("Bạn không có quyền truy cập Playlist riêng tư này (`INV-05`).")
        return api_ok(_playlist_to_json(pl))

    data = _parse_json_body(request)
    pl = update_playlist(
        request.user,
        pl,
        title=data.get("title"),
        description=data.get("description"),
        visibility=data.get("visibility"),
    )
    return api_ok(_playlist_to_json(pl))


@require_POST
@api_login_required
@_api_guard
def api_playlist_add_item(request, pk: int):
    pl = get_object_or_404(MusicPlaylist, pk=pk)
    data = _parse_json_body(request)
    dur_raw = data.get("duration_seconds")
    dur = int(dur_raw) if str(dur_raw or "").isdigit() else None
    item = add_track_to_playlist(
        request.user,
        pl,
        track_url=data.get("track_url", ""),
        title=data.get("title", ""),
        artist_name=data.get("artist_name", ""),
        duration_seconds=dur,
    )
    return api_ok(
        {
            "id": item.id,
            "source_provider": item.source_provider,
            "external_track_id": item.external_track_id,
            "track_url": item.track_url,
            "title": item.title,
        },
        status=201,
    )


@require_http_methods(["DELETE"])
@api_login_required
@_api_guard
def api_playlist_remove_item(request, pk: int):
    item = get_object_or_404(PlaylistItem, pk=pk)
    remove_track_from_playlist(request.user, item)
    return api_ok({"deleted_id": pk})


@require_GET
@api_login_required
@_api_guard
def api_music_recipients_search(request):
    """Tìm thành viên nhận tặng nhạc (`BE-05` + `SEC-04` + `SEC-06`): ẩn Email/SĐT/MSSV, tối đa <= 10."""
    results = search_recipients_for_share(request, request.user, request.GET.get("q", ""))
    return api_ok(results)


@require_http_methods(["GET", "POST"])
@api_login_required
@_api_guard
def api_music_shares(request):
    if request.method == "GET":
        if not _is_active_club_actor(request.user):
            raise PermissionDenied("Bạn không có quyền truy cập hộp quà nhạc.")
        rec = MusicShare.objects.filter(recipient=request.user).select_related("sender")[:20]
        sent = MusicShare.objects.filter(sender=request.user).select_related("recipient")[:20]
        return api_ok(
            {
                "received": [
                    {
                        "id": s.id,
                        "sender_id": s.sender_id,
                        "sender_name": s.sender.public_name,
                        "title": s.title,
                        "artist_name": s.artist_name,
                        "track_url": s.track_url,
                        "personal_message": s.personal_message,
                        "is_saved_to_playlist": s.is_saved_to_playlist,
                    }
                    for s in rec
                ],
                "sent": [
                    {
                        "id": s.id,
                        "recipient_id": s.recipient_id,
                        "recipient_name": s.recipient.public_name,
                        "title": s.title,
                    }
                    for s in sent
                ],
            }
        )

    data = _parse_json_body(request)
    recipient = get_object_or_404(User, pk=data.get("recipient_user_id"))
    src_id = data.get("source_item_id")
    src_item = get_object_or_404(PlaylistItem, pk=src_id) if str(src_id or "").isdigit() else None
    sh = send_music_share(
        request.user,
        recipient=recipient,
        track_url=data.get("track_url", ""),
        title=data.get("title", ""),
        artist_name=data.get("artist_name", ""),
        personal_message=data.get("personal_message", ""),
        source_item=src_item,
    )
    return api_ok({"id": sh.id, "title": sh.title, "recipient_id": sh.recipient_id}, status=201)


@require_POST
@api_login_required
@_api_guard
def api_music_share_save(request, pk: int):
    sh = get_object_or_404(MusicShare, pk=pk)
    if request.content_type and "json" in request.content_type.lower():
        data = _parse_json_body(request)
    elif request.POST:
        data = request.POST
    else:
        data = {}
    pl_id = data.get("target_playlist_id")
    pl = get_object_or_404(MusicPlaylist, pk=pl_id) if str(pl_id or "").isdigit() else None
    item = save_shared_track_to_playlist(request.user, sh, target_playlist=pl)
    return api_ok({"saved_item_id": item.id, "playlist_id": item.playlist_id})
