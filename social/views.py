"""
Giao diện Web Phase 4 (`social.views`):
- Mạng xã hội Nội bộ (`/workspace/mang-xa-hoi/`, `/workspace/mang-xa-hoi/bai/<pk>/`, tải tệp bảo mật `SEC-01`).
- Nhắn tin Nội bộ Bảo mật AES-256-GCM (`/workspace/tin-nhan/`, `/workspace/tin-nhan/<pk>/`, tố cáo `BE-07` `/workspace/tin-nhan/bao-cao/`).
- Playlist Âm nhạc Cá nhân & Tặng nhạc (`/workspace/nhac/`, `/workspace/nhac/playlist/<pk>/`).
"""
from __future__ import annotations

import os

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from operations.models import ClubEventProfile, ClubTask, ClubTaskAssignee, EventAttendance
from organization.models import (
    ClubMembershipStatus,
    Department,
    DeptMembershipStatus,
)
from organization.permissions import PermissionEngine, club_member_required
from organization.services import GovernanceError
from programs.services import _is_active_club_actor, _is_pure_advisor

from .models import (
    AbuseReportStatus,
    ChatAttachment,
    ChatMessage,
    ChatReactionEmoji,
    Conversation,
    ConversationMember,
    ConversationType,
    MessageAbuseReport,
    MusicPlaylist,
    MusicShare,
    PlaylistItem,
    PlaylistVisibility,
    SocialAttachmentType,
    SocialComment,
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
    build_safe_embed_info,
    can_access_conversation,
    can_review_abuse_reports,
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
    send_chat_message,
    send_music_share,
    serialize_post_for_viewer,
    soft_delete_social_post,
    toggle_chat_reaction,
    toggle_social_reaction,
    update_playlist,
)


def _active_non_advisor_peers(actor: User) -> list[User]:
    candidates = (
        User.objects.select_related("club_membership")
        .filter(club_membership__status=ClubMembershipStatus.ACTIVE, is_locked=False)
        .exclude(pk=actor.pk)
        .order_by("full_name", "username")
    )
    return [u for u in candidates if _is_active_club_actor(u) and not _is_pure_advisor(u)]


def _handle_social_post_action(request, actor: User, redirect_to: str):
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được tương tác hoặc chỉnh sửa.")
    action = request.POST.get("action", "")
    if action == "create_post":
        vis = request.POST.get("visibility", SocialPostVisibility.CLUB)
        dept_id = (request.POST.get("department_id") or "").strip()
        dept = (
            Department.objects.filter(pk=dept_id, is_active=True).first()
            if dept_id.isdigit()
            else None
        )
        aud_ids = [int(x) for x in request.POST.getlist("audience_user_ids") if x.isdigit()]
        audience_users = list(User.objects.filter(pk__in=aud_ids)) if aud_ids else []
        post = create_social_post(
            actor,
            content=request.POST.get("content", ""),
            visibility=vis,
            department=dept,
            audience_users=audience_users,
            link_url=request.POST.get("link_url", ""),
            attachments=request.FILES.getlist("attachments"),
        )
        messages.success(request, f"Đã đăng bài viết #{post.id} ({post.get_visibility_display()}).")
        return redirect(redirect_to)

    if action == "share_post":
        orig = get_object_or_404(SocialPost, pk=request.POST.get("shared_post_id"))
        vis = request.POST.get("visibility", SocialPostVisibility.CLUB)
        dept_id = (request.POST.get("department_id") or "").strip()
        dept = (
            Department.objects.filter(pk=dept_id, is_active=True).first()
            if dept_id.isdigit()
            else None
        )
        aud_ids = [int(x) for x in request.POST.getlist("audience_user_ids") if x.isdigit()]
        audience_users = list(User.objects.filter(pk__in=aud_ids)) if aud_ids else []
        repost = create_social_post(
            actor,
            content=request.POST.get("content", ""),
            visibility=vis,
            department=dept,
            audience_users=audience_users,
            shared_post=orig,
        )
        messages.success(request, f"Đã chia sẻ bài viết thành bài mới #{repost.id}.")
        return redirect("social:post_detail", pk=repost.pk)

    if action == "delete_post":
        post = get_object_or_404(SocialPost, pk=request.POST.get("post_id"))
        soft_delete_social_post(actor, post)
        messages.success(request, f"Đã xoá bài viết #{post.id}.")
        return redirect("social:feed")

    if action == "add_comment":
        post = get_object_or_404(SocialPost, pk=request.POST.get("post_id"))
        parent_id = (request.POST.get("parent_id") or "").strip()
        parent = (
            get_object_or_404(SocialComment, pk=parent_id, post=post)
            if parent_id.isdigit()
            else None
        )
        add_social_comment(
            actor,
            post,
            content=request.POST.get("content", ""),
            parent_comment=parent,
        )
        messages.success(request, "Đã gửi bình luận.")
        return redirect(redirect_to)

    if action == "react_post":
        post = get_object_or_404(SocialPost, pk=request.POST.get("post_id"))
        rtype = request.POST.get("reaction_type", SocialReactionType.LIKE)
        toggle_social_reaction(actor, reaction_type=rtype, post=post)
        return redirect(redirect_to)

    if action == "react_comment":
        cmt = get_object_or_404(SocialComment, pk=request.POST.get("comment_id"))
        rtype = request.POST.get("reaction_type", SocialReactionType.LIKE)
        toggle_social_reaction(actor, reaction_type=rtype, comment=cmt)
        return redirect(redirect_to)

    if action == "report_post":
        post = get_object_or_404(SocialPost, pk=request.POST.get("post_id"))
        report_social_post(actor, post, request.POST.get("reason", ""))
        messages.info(request, "Đã gửi báo cáo vi phạm tới cán bộ kiểm duyệt phạm vi phù hợp.")
        return redirect(redirect_to)

    if action == "moderate_post":
        post = get_object_or_404(SocialPost, pk=request.POST.get("post_id"))
        rep_id = (request.POST.get("report_id") or "").strip()
        rep = (
            SocialReport.objects.filter(pk=rep_id, post=post).first()
            if rep_id.isdigit()
            else None
        )
        mod_log = moderate_social_post(
            actor,
            post,
            action=request.POST.get("mod_action", SocialModerationAction.HIDE),
            note=request.POST.get("note", ""),
            report=rep,
        )
        messages.success(request, f"Đã cập nhật kiểm duyệt: {mod_log.get_action_display()}.")
        return redirect(redirect_to)

    return None


# ---------------------------------------------------------------------------
# 1. MẠNG XÃ HỘI NỘI BỘ
# ---------------------------------------------------------------------------
@club_member_required
def social_feed(request):
    actor = request.user
    is_advisor = _is_pure_advisor(actor)
    scope = (request.GET.get("scope") or "ALL").strip().upper()
    dept_slug = (request.GET.get("dept") or "").strip()
    selected_dept = (
        Department.objects.filter(slug=dept_slug, is_active=True).first()
        if dept_slug
        else None
    )

    if request.method == "POST":
        try:
            resp = _handle_social_post_action(request, actor, request.get_full_path())
            if resp is not None:
                return resp
        except GovernanceError as exc:
            messages.error(request, str(exc))

    all_depts = list(Department.objects.filter(is_active=True))
    my_dept_ids = PermissionEngine.get_active_department_ids(actor)
    postable_depts = [
        d
        for d in all_depts
        if (d.id in my_dept_ids)
        or PermissionEngine.authorize(actor, "dept.post.moderate", department=d)
    ]

    can_moderate_any = (not is_advisor) and (
        PermissionEngine.authorize(actor, "club.social.moderate")
        or any(
            PermissionEngine.authorize(actor, "dept.post.moderate", department=d)
            for d in all_depts
        )
    )
    moderation_queue = []
    if can_moderate_any:
        try:
            moderation_queue = get_moderation_queue(actor)
        except PermissionDenied:
            moderation_queue = []

    if scope == "MODERATION" and not can_moderate_any:
        raise PermissionDenied("Bạn không có quyền xem hàng đợi kiểm duyệt MXH.")

    posts = [] if scope == "MODERATION" else list_visible_posts(
        actor, scope=scope, department=selected_dept
    )

    ai_digest, ai_digest_used = None, False
    if request.GET.get("digest") == "1" and scope != "MODERATION":
        from aiassist.services import summarize_social_feed
        from core.security import is_rate_limited
        if not is_rate_limited(request, scope="kmg_ai_assist", limit=20, window_seconds=300):
            ai_digest, ai_digest_used, _ = summarize_social_feed(
                [getattr(p, "content", "") for p in posts[:12]],
                names=tuple(p.author.full_name for p in posts[:12]),
            )

    return render(
        request,
        "social/feed.html",
        {
            "posts": posts,
            "ai_digest": ai_digest,
            "ai_digest_used": ai_digest_used,
            "scope": scope,
            "selected_dept": selected_dept,
            "postable_depts": postable_depts,
            "all_depts": all_depts,
            "peer_members": _active_non_advisor_peers(actor) if not is_advisor else [],
            "is_advisor": is_advisor,
            "can_moderate_any": can_moderate_any,
            "moderation_queue": moderation_queue,
            "visibility_choices": SocialPostVisibility.choices,
            "reaction_choices": SocialReactionType.choices,
            "mod_action_choices": SocialModerationAction.choices,
        },
    )


@club_member_required
def social_post_detail(request, pk: int):
    actor = request.user
    post = get_object_or_404(
        SocialPost.objects.select_related(
            "author", "department", "shared_post__author", "shared_post__department"
        ),
        pk=pk,
    )
    if not can_view_post(actor, post):
        raise PermissionDenied("Bạn không có quyền xem bài viết này (`PA-05`).")

    if request.method == "POST":
        try:
            resp = _handle_social_post_action(
                request, actor, request.get_full_path()
            )
            if resp is not None:
                return resp
        except GovernanceError as exc:
            messages.error(request, str(exc))
        post.refresh_from_db()
        if not can_view_post(actor, post):
            return redirect("social:feed")

    my_dept_ids = PermissionEngine.get_active_department_ids(actor)
    postable_depts = [
        d
        for d in Department.objects.filter(is_active=True)
        if (d.id in my_dept_ids)
        or PermissionEngine.authorize(actor, "dept.post.moderate", department=d)
    ]
    return render(
        request,
        "social/post_detail.html",
        {
            "item": serialize_post_for_viewer(actor, post),
            "postable_depts": postable_depts,
            "peer_members": _active_non_advisor_peers(actor)
            if not _is_pure_advisor(actor)
            else [],
            "is_advisor": _is_pure_advisor(actor),
            "visibility_choices": SocialPostVisibility.choices,
            "reaction_choices": SocialReactionType.choices,
            "mod_action_choices": SocialModerationAction.choices,
        },
    )


@club_member_required
def social_attachment_download(request, pk: int):
    """Tải / xem tệp đính kèm MXH từ PrivateVaultStorage — kiểm tra `can_view_post` (`SEC-01`, `PA-05`)."""
    att = get_object_or_404(SocialPostAttachment.objects.select_related("post"), pk=pk)
    if not can_view_post(request.user, att.post):
        raise PermissionDenied("Bạn không có quyền truy cập tệp đính kèm này.")
    if not att.file:
        raise Http404("Tệp đính kèm không tồn tại.")

    as_attach = att.attachment_type != SocialAttachmentType.IMAGE
    resp = FileResponse(
        att.file.open("rb"),
        as_attachment=as_attach,
        filename=os.path.basename(att.original_filename or f"social_{att.pk}.bin"),
        content_type=att.content_type or "application/octet-stream",
    )
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    return resp


# ---------------------------------------------------------------------------
# 2. NHẮN TIN NỘI BỘ BẢO MẬT AES-256-GCM
# ---------------------------------------------------------------------------
def _handle_messaging_action(request, actor: User, active_conv: Conversation | None):
    if _is_pure_advisor(actor):
        raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không thể nhắn tin hoặc tạo hội thoại.")
    action = request.POST.get("action", "")
    if action == "start_direct":
        peer = get_object_or_404(User, pk=request.POST.get("peer_user_id"))
        conv = get_or_create_direct_conversation(actor, peer)
        return redirect("social:conversation_detail", pk=conv.pk)

    if action == "create_group":
        m_ids = [int(x) for x in request.POST.getlist("member_user_ids") if x.isdigit()]
        members = list(User.objects.filter(pk__in=m_ids))
        conv = create_custom_conversation(
            actor,
            title=request.POST.get("title", ""),
            member_users=members,
        )
        messages.success(request, f"Đã tạo nhóm trò chuyện '{conv.title}'.")
        return redirect("social:conversation_detail", pk=conv.pk)

    if action == "open_club_room":
        if _is_pure_advisor(actor):
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
        if not _is_active_club_actor(actor):
            raise PermissionDenied("Chỉ thành viên CLB mới được vào phòng chat chung.")
        conv = ensure_club_conversation(created_by=actor)
        ConversationMember.objects.update_or_create(
            conversation=conv, user=actor, defaults={"left_at": None}
        )
        return redirect("social:conversation_detail", pk=conv.pk)

    if action == "open_dept_room":
        if _is_pure_advisor(actor):
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`).")
        dept = get_object_or_404(
            Department, pk=request.POST.get("department_id"), is_active=True
        )
        if dept.id not in PermissionEngine.get_active_department_ids(actor):
            raise PermissionDenied(f"Bạn phải đang là thành viên của {dept.name} mới được vào phòng chat Ban.")
        conv = ensure_department_conversation(dept, created_by=actor)
        return redirect("social:conversation_detail", pk=conv.pk)

    if action == "open_event_room":
        ce = get_object_or_404(ClubEventProfile, pk=request.POST.get("club_event_id"))
        conv = ensure_event_conversation(actor, ce)
        return redirect("social:conversation_detail", pk=conv.pk)

    if action == "open_task_room":
        task = get_object_or_404(ClubTask, pk=request.POST.get("task_id"))
        conv = ensure_task_conversation(actor, task)
        return redirect("social:conversation_detail", pk=conv.pk)

    if active_conv is None:
        return None

    if action == "send_message":
        reply_id = (request.POST.get("reply_to_id") or "").strip()
        reply_to = (
            ChatMessage.objects.filter(pk=reply_id, conversation=active_conv).first()
            if reply_id.isdigit()
            else None
        )
        send_chat_message(
            actor,
            active_conv,
            plaintext=request.POST.get("plaintext", ""),
            attachment_file=request.FILES.get("attachment"),
            reply_to=reply_to,
        )
        return redirect("social:conversation_detail", pk=active_conv.pk)

    if action == "recall_message":
        msg = get_object_or_404(
            ChatMessage, pk=request.POST.get("message_id"), conversation=active_conv
        )
        recall_chat_message(actor, msg)
        messages.info(request, "Đã thu hồi và xoá mật mã nội dung tin nhắn.")
        return redirect("social:conversation_detail", pk=active_conv.pk)

    if action == "react_message":
        msg = get_object_or_404(
            ChatMessage, pk=request.POST.get("message_id"), conversation=active_conv
        )
        toggle_chat_reaction(
            actor, msg, emoji=request.POST.get("emoji", ChatReactionEmoji.LIKE)
        )
        return redirect("social:conversation_detail", pk=active_conv.pk)

    if action == "report_abuse":
        msg = get_object_or_404(
            ChatMessage, pk=request.POST.get("message_id"), conversation=active_conv
        )
        rep = report_message_abuse(
            actor, msg, reason=request.POST.get("reason", "")
        )
        messages.success(
            request,
            f"Đã gửi tố cáo #{rep.id} kèm bằng chứng HMAC tới Ban Chủ nhiệm Nhân sự (vẫn giữ bí mật các tin nhắn khác).",
        )
        return redirect("social:conversation_detail", pk=active_conv.pk)

    if action == "leave_room":
        leave_conversation(actor, active_conv)
        messages.info(request, "Bạn đã rời khỏi hội thoại này.")
        return redirect("social:messaging_inbox")

    return None


def _messaging_sidebar_context(actor: User) -> dict:
    my_dept_ids = PermissionEngine.get_active_department_ids(actor)
    my_depts = list(Department.objects.filter(pk__in=my_dept_ids, is_active=True))
    my_events = list(
        ClubEventProfile.objects.select_related("event")
        .filter(
            Q(attendances__user=actor) | Q(lead_department_id__in=my_dept_ids)
        )
        .distinct()
        .order_by("-id")[:10]
    )
    my_tasks = list(
        ClubTask.objects.select_related("department")
        .filter(
            Q(assignees__user=actor, assignees__is_active=True)
            | Q(created_by=actor)
        )
        .distinct()
        .order_by("-id")[:10]
    )
    return {
        "conversations": list_conversations_for_user(actor),
        "peer_members": _active_non_advisor_peers(actor) if not _is_pure_advisor(actor) else [],
        "my_depts": my_depts,
        "my_events": my_events,
        "my_tasks": my_tasks,
        "is_advisor": _is_pure_advisor(actor),
        "can_review_abuse": can_review_abuse_reports(actor),
        "emoji_choices": ChatReactionEmoji.choices,
    }


@club_member_required
def messaging_inbox(request):
    actor = request.user
    if request.method == "POST":
        try:
            resp = _handle_messaging_action(request, actor, None)
            if resp is not None:
                return resp
        except GovernanceError as exc:
            messages.error(request, str(exc))

    ctx = _messaging_sidebar_context(actor)
    active_conv = ctx["conversations"][0]["conversation"] if ctx["conversations"] else None
    decrypted_msgs = (
        list_decrypted_messages(actor, active_conv) if active_conv is not None else []
    )
    room_members = (
        list(
            ConversationMember.objects.select_related("user")
            .filter(conversation=active_conv, left_at__isnull=True)
            .order_by("joined_at")
        )
        if active_conv is not None
        else []
    )
    ctx.update(
        {
            "active_conv": active_conv,
            "decrypted_messages": decrypted_msgs,
            "room_members": room_members,
            "search_query": "",
            "last_message_id": decrypted_msgs[-1]["id"] if decrypted_msgs else 0,
        }
    )
    return render(request, "social/messaging.html", ctx)


@club_member_required
def conversation_detail(request, pk: int):
    actor = request.user
    conv = get_object_or_404(Conversation, pk=pk)
    if not can_access_conversation(actor, conv):
        raise PermissionDenied("Bạn không phải thành viên hoạt động của hội thoại này (`INV-05`).")

    if request.method == "POST":
        try:
            resp = _handle_messaging_action(request, actor, conv)
            if resp is not None:
                return resp
        except GovernanceError as exc:
            messages.error(request, str(exc))

    q = (request.GET.get("q") or "").strip()
    ctx = _messaging_sidebar_context(actor)
    decrypted_msgs = list_decrypted_messages(actor, conv, search_query=q)
    room_members = list(
        ConversationMember.objects.select_related("user")
        .filter(conversation=conv, left_at__isnull=True)
        .order_by("joined_at")
    )
    ctx.update(
        {
            "active_conv": conv,
            "decrypted_messages": decrypted_msgs,
            "room_members": room_members,
            "search_query": q,
            "last_message_id": decrypted_msgs[-1]["id"] if decrypted_msgs else 0,
        }
    )
    return render(request, "social/messaging.html", ctx)


@club_member_required
def chat_attachment_download(request, pk: int):
    att = get_object_or_404(
        ChatAttachment.objects.select_related("message__conversation"), pk=pk
    )
    if not can_access_conversation(request.user, att.message.conversation):
        raise PermissionDenied("Bạn không có quyền tải tệp đính kèm tin nhắn này (`INV-05`).")
    if att.message.is_recalled or not att.file:
        raise Http404("Tệp không còn khả dụng.")

    as_attach = not (att.content_type or "").startswith("image/")
    resp = FileResponse(
        att.file.open("rb"),
        as_attachment=as_attach,
        filename=os.path.basename(att.original_filename or f"chat_{att.pk}.bin"),
        content_type=att.content_type or "application/octet-stream",
    )
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, no-store"
    return resp


@club_member_required
def message_abuse_reports_view(request):
    actor = request.user
    if request.method == "POST":
        rep = get_object_or_404(MessageAbuseReport, pk=request.POST.get("report_id"))
        try:
            review_message_abuse_report(
                actor,
                rep,
                status=request.POST.get("status", AbuseReportStatus.ACTION_TAKEN),
                resolution_note=request.POST.get("resolution_note", ""),
            )
            messages.success(request, f"Đã xử lý báo cáo vi phạm #{rep.id}.")
            return redirect("social:abuse_reports")
        except GovernanceError as exc:
            messages.error(request, str(exc))

    reports = list_abuse_reports_for_reviewer(actor)
    return render(
        request,
        "social/abuse_reports.html",
        {
            "reports": reports,
            "status_choices": [
                (AbuseReportStatus.UNDER_REVIEW, "Đang xác minh"),
                (AbuseReportStatus.ACTION_TAKEN, "Đã xử lý kỷ luật"),
                (AbuseReportStatus.DISMISSED, "Bác bỏ tố cáo"),
            ],
        },
    )


# ---------------------------------------------------------------------------
# 3. PLAYLIST ÂM NHẠC CÁ NHÂN & TẶNG NHẠC
# ---------------------------------------------------------------------------
@club_member_required
def music_hub(request):
    actor = request.user
    is_advisor = _is_pure_advisor(actor)

    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được tạo playlist hoặc tặng nhạc.")
        action = request.POST.get("action", "")
        try:
            if action == "create_playlist":
                pl = create_playlist(
                    actor,
                    title=request.POST.get("title", ""),
                    description=request.POST.get("description", ""),
                    visibility=request.POST.get("visibility", PlaylistVisibility.PRIVATE),
                )
                messages.success(request, f"Đã tạo playlist '{pl.title}'.")
                return redirect("social:playlist_detail", pk=pl.pk)
            if action == "send_share":
                recipient = get_object_or_404(
                    User, pk=request.POST.get("recipient_user_id")
                )
                src_id = (request.POST.get("source_item_id") or "").strip()
                src_item = (
                    get_object_or_404(PlaylistItem, pk=src_id)
                    if src_id.isdigit()
                    else None
                )
                sh = send_music_share(
                    actor,
                    recipient=recipient,
                    track_url=request.POST.get("track_url", ""),
                    title=request.POST.get("title", ""),
                    artist_name=request.POST.get("artist_name", ""),
                    personal_message=request.POST.get("personal_message", ""),
                    source_item=src_item,
                )
                messages.success(
                    request, f"Đã gửi tặng '{sh.title}' tới {recipient.public_name}."
                )
                return redirect("social:music_hub")
            if action == "save_share":
                sh = get_object_or_404(MusicShare, pk=request.POST.get("share_id"))
                pl_id = (request.POST.get("target_playlist_id") or "").strip()
                pl = (
                    MusicPlaylist.objects.filter(pk=pl_id, owner=actor).first()
                    if pl_id.isdigit()
                    else None
                )
                saved = save_shared_track_to_playlist(actor, sh, target_playlist=pl)
                messages.success(
                    request,
                    f"Đã lưu '{saved.title}' vào playlist '{saved.playlist.title}'.",
                )
                return redirect("social:music_hub")
        except GovernanceError as exc:
            messages.error(request, str(exc))

    my_playlists = list(
        MusicPlaylist.objects.filter(owner=actor).prefetch_related("items")
    )
    club_shared_playlists = list(
        MusicPlaylist.objects.filter(visibility=PlaylistVisibility.CLUB_SHARED)
        .exclude(owner=actor)
        .select_related("owner")
        .prefetch_related("items")[:24]
    )
    received_shares = list(
        MusicShare.objects.filter(recipient=actor).select_related("sender", "saved_item")[:20]
    )
    sent_shares = list(
        MusicShare.objects.filter(sender=actor).select_related("recipient")[:20]
    )
    return render(
        request,
        "social/music_hub.html",
        {
            "my_playlists": my_playlists,
            "club_shared_playlists": club_shared_playlists,
            "received_shares": received_shares,
            "sent_shares": sent_shares,
            "visibility_choices": PlaylistVisibility.choices,
            "is_advisor": is_advisor,
        },
    )


@club_member_required
def playlist_detail(request, pk: int):
    actor = request.user
    playlist = get_object_or_404(
        MusicPlaylist.objects.select_related("owner").prefetch_related("items"), pk=pk
    )
    if not can_view_playlist(actor, playlist):
        raise PermissionDenied("Bạn không có quyền xem Playlist riêng tư này (`INV-05`).")

    is_advisor = _is_pure_advisor(actor)
    is_owner = (playlist.owner_id == actor.id) and (not is_advisor)
    if request.method == "POST":
        if is_advisor:
            raise PermissionDenied("Cố vấn ở chế độ Hard Read-Only (`INV-04`), không được tạo playlist hoặc tặng nhạc.")
        action = request.POST.get("action", "")
        try:
            if action == "add_track":
                dur_raw = (request.POST.get("duration_seconds") or "").strip()
                add_track_to_playlist(
                    actor,
                    playlist,
                    track_url=request.POST.get("track_url", ""),
                    title=request.POST.get("title", ""),
                    artist_name=request.POST.get("artist_name", ""),
                    duration_seconds=int(dur_raw) if dur_raw.isdigit() else None,
                )
                messages.success(request, "Đã thêm bài hát vào playlist.")
                return redirect("social:playlist_detail", pk=playlist.pk)
            if action == "remove_track":
                item = get_object_or_404(
                    PlaylistItem, pk=request.POST.get("item_id"), playlist=playlist
                )
                remove_track_from_playlist(actor, item)
                messages.info(request, "Đã gỡ bài hát khỏi playlist.")
                return redirect("social:playlist_detail", pk=playlist.pk)
            if action == "update_playlist":
                update_playlist(
                    actor,
                    playlist,
                    title=request.POST.get("title"),
                    description=request.POST.get("description"),
                    visibility=request.POST.get("visibility"),
                )
                messages.success(request, "Đã cập nhật thông tin playlist.")
                return redirect("social:playlist_detail", pk=playlist.pk)
        except GovernanceError as exc:
            messages.error(request, str(exc))

    tracks = [
        {
            "item": it,
            "embed": build_safe_embed_info(it.source_provider, it.external_track_id),
        }
        for it in playlist.items.all()
    ]
    return render(
        request,
        "social/playlist_detail.html",
        {
            "playlist": playlist,
            "tracks": tracks,
            "is_owner": is_owner,
            "is_advisor": is_advisor,
            "visibility_choices": PlaylistVisibility.choices,
        },
    )
