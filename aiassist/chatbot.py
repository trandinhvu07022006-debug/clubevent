"""
Trợ lý tra cứu: HỎI ĐÁP THEO Ý ĐỊNH, KẾT HỢP AI CÓ DỮ LIỆU NỀN (hybrid).

QUAN TRỌNG khi viết báo cáo và khi bảo vệ - mô tả đúng kiến trúc 2 tầng:

TẦNG 1 - LUẬT (lõi, luôn chạy trước):
  Nhận diện ý định bằng so khớp từ khoá, truy vấn CSDL, trả lời theo mẫu câu.
  Mọi câu hỏi về sự kiện sắp tới, số chỗ, vé của tôi, việc của tôi, cách đăng
  ký/check-in/huỷ vé đều đi tầng này. Ưu điểm giữ nguyên:
    - Kết quả xác định, viết unit test được cho từng ý định.
    - Không bịa thông tin (không hallucination), không tốn quota.
    - Dữ liệu cá nhân (vé, công việc) CHỈ đi tầng này, không bao giờ gửi cho AI.

TẦNG 2 - AI (chỉ khi tầng 1 không nhận ra ý định):
  Gửi câu hỏi cho LLM KÈM dữ liệu công khai lấy từ CSDL (sự kiện, loại vé, quy
  định) và lệnh chỉ được trả lời theo dữ liệu đó - kỹ thuật "grounding".
  Câu trả lời được gắn nhãn "AI" trên giao diện. Link do server tạo từ mã sự
  kiện đã kiểm tra, AI không tự viết URL. Xem aiassist/services.py::ask_assistant.

KHÔNG CÓ AI (chưa cấu hình key, mất mạng, hết lượt, lỗi...) thì hệ thống hoạt
động y như bản chỉ có luật: câu hỏi lạ nhận lời gợi ý các chủ đề hỗ trợ.

Cách nhận diện ý định:
  1. Chuẩn hoá câu hỏi: hạ chữ thường và BỎ DẤU tiếng Việt, để "còn vé không"
     và "con ve khong" đều khớp - người dùng gõ nhanh hay không bỏ dấu đều được.
  2. Mỗi ý định có một bộ từ khoá. Ý định nào khớp nhiều từ khoá nhất thì thắng.
  3. Không ý định nào khớp thì chuyển sang tầng AI (nếu dùng được).
"""
import re
import unicodedata

from django.urls import reverse
from django.utils import timezone


def normalize(text):
    """
    Hạ chữ thường và bỏ dấu tiếng Việt.

    Cách làm: tách ký tự có dấu thành chữ gốc + dấu (dạng NFD), rồi bỏ hết
    các ký tự dấu đi. Riêng chữ 'đ' không tách được bằng cách này nên phải
    thay thủ công.
    """
    text = (text or "").lower().strip()
    text = text.replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


# Mỗi ý định gồm: mã, danh sách từ khoá, và có cần đăng nhập hay không.
# Từ khoá viết ở dạng ĐÃ BỎ DẤU vì câu hỏi cũng được chuẩn hoá trước khi so.
INTENTS = [
    {
        "code": "upcoming_events",
        "keywords": [
            "su kien", "sap toi", "sap dien ra", "co gi", "lich",
            "chuong trinh", "hoat dong", "sap co", "event", "to chuc event",
            "dem nhac tiep theo", "bao gio co dem nhac",
        ],
        "login_required": False,
    },
    {
        "code": "seats_left",
        "keywords": [
            "con ve", "con cho", "het ve", "het cho", "bao nhieu ve",
            "bao nhieu cho", "so luong ve", "con khong", "dat duoc",
            "sold out", "con slot", "het slot",
        ],
        "login_required": False,
    },
    {
        "code": "my_tickets",
        "keywords": [
            "ve cua toi", "ve toi", "ve cua minh", "ve cua em",
            "xem lai ve", "ve minh da dat", "nhung ve nao",
            "ma ve", "ma qr cua minh", "ma qr cua toi", "qr",
            "check in cua toi", "toi dat", "toi dang ky", "ve da dat",
        ],
        "login_required": True,
    },
    {
        "code": "my_tasks",
        "keywords": [
            "viec cua toi", "viec cua minh", "viec cua em", "cong viec",
            "task", "task nao", "deadline", "han chot", "sap toi han",
            "han bao gio", "toi phai lam", "phai lam gi", "duoc giao",
            "duoc phan cong", "viec gi cho toi", "viec gi cho minh",
        ],
        "login_required": True,
    },
    {
        "code": "how_to_register",
        "keywords": [
            "dang ky the nao", "dang ky ve", "lam sao de dang ky", "cach dang ky",
            "huong dan", "dang ky nhu the nao", "mua ve", "mua ve the nao",
            "dat ve online", "dat ve", "chuyen khoan", "momo", "tra tien mat",
            "thanh toan",
        ],
        "login_required": False,
    },
    {
        "code": "how_to_checkin",
        "keywords": [
            "check in the nao", "check in nhu nao", "cach check in",
            "quy trinh check in", "check in", "vao cua", "cua soat ve",
            "soat ve", "quet ma", "diem danh", "in ve giay", "ma qr trong dt",
        ],
        "login_required": False,
    },
    {
        "code": "cancel_ticket",
        "keywords": [
            "huy ve", "tra ve", "tra lai ve", "khong di duoc", "bo ve",
            "huy dang ky", "dang ky nham", "nham su kien", "cancel",
        ],
        "login_required": False,
    },
    {
        "code": "club_departments",
        # KHÔNG dùng "cac ban" / "ban nao" đứng riêng: trùng "các bạn", "bạn nào"
        # khi người dùng gõ không dấu.
        "keywords": [
            "ban chuyen mon", "nhung ban nao", "clb co ban nao",
            "clb chia thanh may ban", "may ban", "cac ban trong clb",
            "cac ban cua clb", "ban hau can", "ban truyen thong",
            "khac nhau cho nao",
        ],
        "login_required": False,
    },
    {
        "code": "recruitment_info",
        "keywords": [
            "tuyen thanh vien", "tuyen quan", "tuyen ctv", "dot tuyen",
            "ung tuyen", "tham gia clb", "vao clb", "casting", "phong van",
        ],
        "login_required": False,
    },
    {
        "code": "greeting",
        "keywords": ["xin chao", "chao", "hello", "hi", "alo"],
        "login_required": False,
    },
]

# Không đưa câu trả lời chứa dữ liệu riêng/nội bộ vào lịch sử gửi AI hoặc log.
# Hai ý định sự kiện có thể trả dữ liệu INTERNAL cho thành viên có quyền;
# loại trừ toàn bộ hai ý định để không phụ thuộc vào quyền tại lượt chat sau.
PRIVATE_INTENTS = frozenset({
    "my_tickets", "my_tasks", "greeting", "upcoming_events", "seats_left",
})

# Câu gợi ý hiện sẵn dưới ô chat để người dùng biết hỏi được gì
SUGGESTIONS = [
    "Sắp tới có sự kiện gì?",
    "Còn vé không?",
    "Vé của tôi thế nào?",
    "Việc của tôi có gì?",
    "Đăng ký thế nào?",
]


def prepare_query(question):
    """
    Chuẩn hoá câu hỏi để so khớp từ khoá, phân biệt "bạn" (người) với "ban".

    Bỏ dấu làm "bạn" và "ban" giống hệt nhau, nên:
      - "bạn" có dấu được đổi thành ký hiệu riêng TRƯỚC khi bỏ dấu.
      - Lời gọi "các bạn ơi", "ban oi" bị cắt vì không mang ý định.
      - Chuẩn hoá biến thể thường gặp ("checkin" -> "check in", chữ kéo dài).
    """
    text = unicodedata.normalize("NFC", (question or "").lower())
    text = re.sub(r"\bbạn\b", " _nguoi_ ", text)
    text = " ".join(normalize(text).split())
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"([a-z])\1{2,}", r"\1", text)
    text = re.sub(r"\bcheck[\s\-_]*in\b", "check in", text)
    text = re.sub(r"\b(?:(?:cac|moi) )?(?:_nguoi_|ban) oi\b", " ", text)
    return " ".join(text.split())


_QUESTION_CUES = frozenset({
    "hoi", "lien he", "bao nhieu", "bao gio", "khi nao", "o dau", "the nao",
    "nhu nao", "kieu gi", "lam sao", "co nhan", "duoc khong", "duoc ko",
    "tai tro", "gui xe", "mac gi", "giai giup",
})


def _is_pure_greeting(raw_question: str, norm_text: str) -> bool:
    """Tránh để lời chào đầu câu ("chào ad, cho mình hỏi...") nuốt mất câu hỏi thật."""
    if "?" in (raw_question or ""):
        return False
    if any(_has_phrase(norm_text, cue) for cue in _QUESTION_CUES):
        return False
    return len(norm_text.split()) <= 8


def detect_intent(question):
    """
    Tìm ý định khớp nhất với câu hỏi.

    Cách chấm điểm: cộng ĐỘ DÀI của các từ khoá khớp được, chứ không đếm số
    từ khoá. Lý do là từ khoá dài thì cụ thể hơn nên đáng tin hơn.
    Không khớp gì thì trả về None.
    """
    text = prepare_query(question)
    if not text:
        return None

    best, best_score = None, 0
    for intent in INTENTS:
        if intent["code"] == "greeting" and not _is_pure_greeting(question, text):
            continue
        score = sum(len(kw.strip()) for kw in intent["keywords"]
                    if _has_phrase(text, kw))
        if score > best_score:
            best, best_score = intent, score
    return best


_PHRASE_CACHE = {}


def _has_phrase(text, keyword):
    """
    Từ khoá phải xuất hiện như NGUYÊN TỪ, không được khớp vào giữa từ khác.

    Trước đây so khớp kiểu chuỗi con (`kw in text`), nên từ khoá chào hỏi
    "hi" khớp nhầm vào giữa "phi", "thi", "chi" sau khi bỏ dấu: câu "Phí gửi xe
    bao nhiêu" bị hiểu là lời chào. Ở đây dùng ranh giới từ (\\b) của regex.
    """
    pattern = _PHRASE_CACHE.get(keyword)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(keyword.strip()) + r"\b")
        _PHRASE_CACHE[keyword] = pattern
    return pattern.search(text) is not None


UNKNOWN_TEXT = ("Mình chưa hiểu câu hỏi này. Mình trả lời được về: "
                "sự kiện sắp tới, số chỗ còn lại, vé của bạn, "
                "công việc được giao, và cách đăng ký hoặc check-in.")


def _can_use_ai(question, allow_ai):
    """Chỉ giữ lượt AI khi thực sự đi vào nhánh AI; vẫn hỗ trợ bool cũ."""
    if not normalize(question):
        return False
    return bool(allow_ai() if callable(allow_ai) else allow_ai)


def answer(question, user=None, allow_ai=True, history=None):
    """
    Trả lời một câu hỏi.
    Nhận thêm `history` để duy trì mạch hội thoại đa lượt cho tầng AI.

    Trả về dict: {"text", "intent", "links": [...], "source": "rules" | "ai"}
    Phần `links` là các đường dẫn gợi ý để người dùng bấm sang trang tương ứng.
    `source` cho giao diện biết câu trả lời đến từ luật (chính xác) hay từ AI
    (có thể chưa chính xác) để gắn nhãn tương ứng.

    `allow_ai` là bool hoặc callback giữ lượt nguyên tử trước khi gọi AI.
    """
    intent = detect_intent(question)

    if intent is None:
        # Chỉ tới đây mới gọi AI - 8 ý định có sẵn LUÔN đi nhánh luật.
        if _can_use_ai(question, allow_ai):
            ai_result = _answer_with_ai(question, history=history, user=user)
            if ai_result is not None:
                return ai_result
        return {"intent": "unknown", "source": "rules",
                "text": UNKNOWN_TEXT, "links": []}

    is_logged_in = bool(user and user.is_authenticated)
    if intent["login_required"] and not is_logged_in:
        return {
            "intent": intent["code"],
            "source": "rules",
            "text": "Bạn cần đăng nhập thì mình mới tra được thông tin cá nhân.",
            "links": [{"label": "Đăng nhập", "url": reverse("accounts:login")}],
        }

    handler = HANDLERS[intent["code"]]
    result = handler(user)
    result["intent"] = intent["code"]
    result["source"] = "rules"
    return result


def stream_answer(question, user=None, allow_ai=True, history=None):
    """
    Generator SSE: ưu tiên stream token thật từ AI provider (Gemini/OpenAI/Local LLM)
    khi cấu hình chạy trực tiếp; tự động fallback về câu trả lời quy tắc hoặc
    chia đoạn an toàn khi chạy test/mock hoặc Foundation Agent.
    """
    from django.conf import settings
    from events.models import Event, EventVisibility
    from . import providers, services
    from .privacy import known_names

    intent = detect_intent(question)

    if intent is None:
        if _can_use_ai(question, allow_ai):
            use_live_stream = (
                _answer_with_ai is _ORIGINAL_ANSWER_WITH_AI
                and services._ask_ai is services._ORIGINAL_ASK_AI
                and providers.is_live_streaming_ready()
                and not getattr(settings, "AI_FOUNDATION_AGENT", False)
            )
            if use_live_stream:
                emitted_any = False
                try:
                    final_evt = None
                    for item in services.stream_assistant_reply(
                        question, history=history, names=known_names(user)
                    ):
                        if item.get("done"):
                            final_evt = item
                        else:
                            emitted_any = True
                            yield {"token": item["token"], "done": False}
                    if final_evt:
                        ev_names = dict(
                            Event.objects.filter(
                                pk__in=final_evt["event_ids"],
                                visibility=EventVisibility.PUBLIC,
                            ).values_list("pk", "name")
                        )
                        links = [
                            {"label": ev_names[pk], "url": reverse("events:detail", args=[pk])}
                            for pk in final_evt["event_ids"] if pk in ev_names
                        ]
                        yield {
                            "done": True,
                            "text": final_evt["text"],
                            "links": links,
                            "sources": final_evt.get("sources", []),
                            "intent": "ai",
                            "source": "ai",
                            "meta": {
                                "model_name": final_evt["model"],
                                "prompt_version": final_evt["prompt_version"],
                            },
                        }
                        return
                except services.AIError:
                    if emitted_any or not getattr(settings, "AI_FALLBACK_PROVIDER", ""):
                        if not emitted_any:
                            yield {"token": UNKNOWN_TEXT, "done": False}
                        yield {
                            "done": True,
                            "text": UNKNOWN_TEXT,
                            "links": [],
                            "intent": "unknown",
                            "source": "rules",
                        }
                        return

            ai_result = _answer_with_ai(question, history=history, user=user)
            if ai_result is not None:
                text = ai_result["text"]
                words = re.findall(r"\S+|\s+", text)
                chunk = []
                for w in words:
                    chunk.append(w)
                    if len(chunk) >= 2 or "\n" in w:
                        yield {"token": "".join(chunk), "done": False}
                        chunk = []
                if chunk:
                    yield {"token": "".join(chunk), "done": False}
                yield {
                    "done": True,
                    "text": text,
                    "links": ai_result.get("links", []),
                    "sources": ai_result.get("sources", []),
                    "intent": "ai",
                    "source": "ai",
                    "meta": ai_result.get("meta", {}),
                }
                return

        # Fallback câu chưa hiểu
        words = re.findall(r"\S+|\s+", UNKNOWN_TEXT)
        for w in words:
            yield {"token": w, "done": False}
        yield {
            "done": True,
            "text": UNKNOWN_TEXT,
            "links": [],
            "intent": "unknown",
            "source": "rules",
        }
        return

    is_logged_in = bool(user and user.is_authenticated)
    if intent["login_required"] and not is_logged_in:
        msg = "Bạn cần đăng nhập thì mình mới tra được thông tin cá nhân."
        links = [{"label": "Đăng nhập", "url": reverse("accounts:login")}]
        yield {"token": msg, "done": False}
        yield {
            "done": True,
            "text": msg,
            "links": links,
            "intent": intent["code"],
            "source": "rules",
        }
        return

    handler = HANDLERS[intent["code"]]
    result = handler(user)
    text = result["text"]
    words = re.findall(r"\S+|\s+", text)
    chunk = []
    for w in words:
        chunk.append(w)
        if len(chunk) >= 2 or "\n" in w:
            yield {"token": "".join(chunk), "done": False}
            chunk = []
    if chunk:
        yield {"token": "".join(chunk), "done": False}
    yield {
        "done": True,
        "text": text,
        "links": result.get("links", []),
        "intent": intent["code"],
        "source": "rules",
    }


def _answer_with_ai(question, history=None, user=None):
    """
    Nhánh AI. Trả về dict trả lời, hoặc None nếu AI không dùng được (chưa có
    key, lỗi mạng, quá tải...) - khi đó answer() quay về câu "chưa hiểu".

    Link do SERVER tạo từ mã sự kiện đã được kiểm tra, AI không tự viết URL.
    """
    from django.conf import settings
    from .privacy import known_names
    from .services import AIError, ask_assistant

    if getattr(settings, "AI_FOUNDATION_AGENT", False) and not history:
        from .adapters import ask_with_foundation
        foundation_result = ask_with_foundation(question, user=user)
        if foundation_result is not None:
            return foundation_result

    try:
        data = ask_assistant(question, history=history, names=known_names(user))
    except AIError:
        return None

    from events.models import Event, EventVisibility
    names = dict(
        Event.objects.filter(
            pk__in=data["event_ids"],
            visibility=EventVisibility.PUBLIC,
        ).values_list("pk", "name")
    )
    links = [{"label": names[pk], "url": reverse("events:detail", args=[pk])}
             for pk in data["event_ids"] if pk in names]
    return {"intent": "ai", "source": "ai", "text": data["answer"], "links": links,
            "sources": data.get("sources", []),
            # Chỉ dùng để ghi log; view gỡ ra trước khi trả cho trình duyệt
            "meta": {"model_name": data["model"],
                     "prompt_version": data["prompt_version"]}}


_ORIGINAL_ANSWER_WITH_AI = _answer_with_ai


# --------------------------------------------------------------------------
# Các hàm trả lời cho từng ý định. Mỗi hàm tự truy vấn DB.
# --------------------------------------------------------------------------
def _upcoming_events(user):
    from events.models import Event, EventStatus, EventVisibility, can_view_internal_events

    events = (Event.objects
              .filter(status=EventStatus.OPEN, starts_at__gte=timezone.now()))
    if not can_view_internal_events(user):
        events = events.filter(visibility=EventVisibility.PUBLIC)
    events = events.order_by("starts_at")[:5]
    if not events:
        return {"text": "Hiện chưa có sự kiện nào đang mở đăng ký.", "links": []}

    lines = ["Các sự kiện đang mở đăng ký:"]
    links = []
    for e in events:
        lines.append(f"• {e.name} - {timezone.localtime(e.starts_at):%H:%M %d/%m} "
                     f"tại {e.location}")
        links.append({"label": e.name, "url": reverse("events:detail", args=[e.pk])})
    return {"text": "\n".join(lines), "links": links}


def _seats_left(user):
    from events.models import Event, EventStatus, EventVisibility, can_view_internal_events

    events = (Event.objects
              .filter(status=EventStatus.OPEN, starts_at__gte=timezone.now())
              .prefetch_related("ticket_types"))
    if not can_view_internal_events(user):
        events = events.filter(visibility=EventVisibility.PUBLIC)
    events = events.order_by("starts_at")[:5]
    if not events:
        return {"text": "Hiện chưa có sự kiện nào đang mở đăng ký.", "links": []}

    lines = []
    links = []
    for e in events:
        types = list(e.ticket_types.all())
        if not types:
            continue
        detail = ", ".join(
            f"{t.name}: {'hết chỗ' if t.is_sold_out else str(t.remaining) + ' chỗ'}"
            for t in types)
        lines.append(f"• {e.name} - {detail}")
        links.append({"label": f"Đăng ký {e.name}", "url": reverse("events:detail", args=[e.pk])})

    if not lines:
        return {"text": "Các sự kiện đang mở chưa cấu hình loại vé.", "links": []}
    return {"text": "Số chỗ còn lại:\n" + "\n".join(lines), "links": links}


def _my_tickets(user):
    from registrations.models import Ticket, TicketStatus

    tickets = (Ticket.objects
               .filter(user=user)
               .exclude(status=TicketStatus.CANCELLED)
               .select_related("event", "ticket_type")
               .order_by("event__starts_at"))
    if not tickets:
        return {
            "text": "Bạn chưa đăng ký sự kiện nào.",
            "links": [{"label": "Xem sự kiện đang mở", "url": reverse("events:list")}],
        }

    lines = [f"Bạn đang có {len(tickets)} vé:"]
    for t in tickets:
        lines.append(f"• {t.event.name} - mã {t.code} - {t.get_status_display()}")
    pending = sum(1 for t in tickets if t.status == TicketStatus.PENDING)
    if pending:
        lines.append(f"\nCó {pending} vé chờ thanh toán. Thanh toán xong báo BTC "
                     f"xác nhận, quá 24h vé sẽ tự huỷ.")
    return {"text": "\n".join(lines),
            "links": [{"label": "Mở trang vé của tôi", "url": reverse("registrations:my_tickets")}]}


def _my_tasks(user):
    from organizing.models import Task, TaskStatus

    if not user.is_staff_btc:
        return {"text": "Chức năng công việc chỉ dành cho ban tổ chức.",
                "links": []}

    tasks = (Task.objects
             .filter(assignee=user)
             .exclude(status=TaskStatus.DONE)
             .exclude(event__status="CANCELLED")
             .select_related("event")
             .order_by("deadline"))
    if not tasks:
        return {"text": "Bạn không còn việc nào chưa xong. Tốt lắm.",
                "links": [{"label": "Xem tất cả việc", "url": reverse("organizing:my_tasks")}]}

    lines = [f"Bạn còn {len(tasks)} việc chưa xong:"]
    overdue = 0
    for t in tasks:
        when = (f" - hạn {timezone.localtime(t.deadline):%H:%M %d/%m}"
                if t.deadline else "")
        late = ""
        if t.is_overdue:
            overdue += 1
            late = " (QUÁ HẠN)"
        lines.append(f"• {t.title}{when}{late} - {t.scope_label}")
    if overdue:
        lines.append(f"\nTrong đó {overdue} việc đã quá hạn.")
    return {"text": "\n".join(lines),
            "links": [{"label": "Mở trang việc của tôi",
                       "url": reverse("organizing:my_tasks")}]}


def _how_to_register(user):
    from django.conf import settings

    return {
        "text": (
            "Cách đăng ký:\n"
            "1. Đăng nhập, vào trang sự kiện bạn muốn tham gia.\n"
            "2. Chọn loại vé và số lượng rồi bấm Đăng ký.\n"
            f"3. Mỗi người đăng ký tối đa "
            f"{settings.MAX_TICKETS_PER_USER_PER_EVENT} vé cho một sự kiện.\n"
            "4. Vé miễn phí có hiệu lực ngay. Vé có phí thì chuyển khoản rồi "
            f"báo ban tổ chức xác nhận, quá "
            f"{settings.PAYMENT_DEADLINE_HOURS}h chưa xác nhận là vé tự huỷ.\n"
            "5. Vé và mã QR nằm ở mục Vé của tôi."
        ),
        "links": [{"label": "Xem sự kiện đang mở", "url": reverse("events:list")}],
    }


def _how_to_checkin(user):
    return {
        "text": ("Hôm diễn ra sự kiện, bạn mở mục Vé của tôi và đưa mã QR "
                 "cho ban tổ chức quét. Không quét được thì đọc mã 12 ký tự "
                 "để ban tổ chức nhập tay. Mỗi vé chỉ check-in được một lần."),
        "links": [{"label": "Mở trang vé của tôi", "url": reverse("registrations:my_tickets")}],
    }


def _cancel_ticket(user):
    from django.conf import settings

    return {
        "text": (f"Bạn huỷ vé được ở mục Vé của tôi, miễn là còn hơn "
                 f"{settings.CANCEL_BEFORE_HOURS} giờ nữa mới tới giờ diễn ra "
                 f"và vé chưa check-in. Huỷ xong chỗ đó được trả lại cho "
                 f"người khác đăng ký."),
        "links": [{"label": "Mở trang vé của tôi", "url": reverse("registrations:my_tickets")}],
    }


def _greeting(user):
    name = ""
    if user and user.is_authenticated:
        name = f" {user.full_name.split()[-1]}" if user.full_name else ""
    return {
        "text": (f"Chào{name}! Mình là trợ lý tra cứu của CLB. Mình trả lời "
                 f"được về sự kiện sắp tới, số chỗ còn lại, vé của bạn, "
                 f"công việc được giao, và cách đăng ký hoặc check-in."),
        "links": [],
    }


def _club_departments(user):
    from organizing.models import Department

    depts = list(Department.objects.all()[:10])
    if not depts:
        return {
            "text": "Hiện CLB chưa cập nhật danh sách các Ban chuyên môn trên hệ thống.",
            "links": [],
        }
    lines = ["Các Ban chuyên môn trong CLB hiện gồm:"]
    for d in depts:
        desc = f" — {d.description}" if d.description else ""
        lines.append(f"• {d.name}{desc}")
    return {
        "text": "\n".join(lines),
        "links": [{"label": "Xem trang Tuyển thành viên", "url": reverse("recruitment:home")}],
    }


def _recruitment_info(user):
    from recruitment.models import RecruitmentRound

    current_round = RecruitmentRound.current()
    if current_round:
        closes = timezone.localtime(current_round.closes_at)
        depts = ", ".join(d.name for d in current_round.open_departments()[:6]) or "Tất cả các ban"
        return {
            "text": (f"CLB đang mở đợt '{current_round.name}' đến {closes:%H:%M ngày %d/%m/%Y}.\n"
                     f"Các ban nhận đơn: {depts}.\n"
                     f"Bạn có thể nộp đơn trực tuyến ngay tại mục Tuyển thành viên."),
            "links": [{"label": "Nộp đơn ứng tuyển", "url": reverse("recruitment:apply")}],
        }

    upcoming = RecruitmentRound.next_upcoming()
    if upcoming:
        opens = timezone.localtime(upcoming.opens_at)
        return {
            "text": f"Đợt tuyển sắp tới '{upcoming.name}' sẽ mở nhận đơn từ {opens:%H:%M ngày %d/%m/%Y}.",
            "links": [{"label": "Xem thông tin tuyển thành viên", "url": reverse("recruitment:home")}],
        }

    return {
        "text": "Hiện tại chưa có đợt tuyển thành viên nào đang mở. Bạn hãy theo dõi trang Tuyển thành viên để cập nhật lịch mới nhất nhé!",
        "links": [{"label": "Trang Tuyển thành viên", "url": reverse("recruitment:home")}],
    }


HANDLERS = {
    "upcoming_events": _upcoming_events,
    "seats_left": _seats_left,
    "my_tickets": _my_tickets,
    "my_tasks": _my_tasks,
    "how_to_register": _how_to_register,
    "how_to_checkin": _how_to_checkin,
    "cancel_ticket": _cancel_ticket,
    "club_departments": _club_departments,
    "recruitment_info": _recruitment_info,
    "greeting": _greeting,
}
