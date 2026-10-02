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
        "keywords": ["su kien", "sap toi", "sap dien ra", "co gi", "lich",
                     "chuong trinh", "hoat dong", "sap co"],
        "login_required": False,
    },
    {
        "code": "seats_left",
        "keywords": ["con ve", "con cho", "het ve", "het cho", "bao nhieu ve",
                     "bao nhieu cho", "so luong ve", "con khong", "dat duoc"],
        "login_required": False,
    },
    {
        "code": "my_tickets",
        "keywords": ["ve cua toi", "ve toi", "ma ve", "qr", "check in cua toi",
                     "toi dat", "toi dang ky", "ve da dat"],
        "login_required": True,
    },
    {
        "code": "my_tasks",
        "keywords": ["viec cua toi", "cong viec", "task", "deadline",
                     "han chot", "toi phai lam", "duoc giao"],
        "login_required": True,
    },
    {
        "code": "how_to_register",
        "keywords": ["dang ky the nao", "lam sao de dang ky", "cach dang ky",
                     "huong dan", "dang ky nhu the nao", "mua ve the nao",
                     "thanh toan"],
        "login_required": False,
    },
    {
        "code": "how_to_checkin",
        "keywords": ["check in the nao", "cach check in", "vao cua",
                     "quet ma", "diem danh"],
        "login_required": False,
    },
    {
        "code": "cancel_ticket",
        "keywords": ["huy ve", "tra ve", "khong di duoc", "bo ve", "huy dang ky"],
        "login_required": False,
    },
    {
        "code": "greeting",
        "keywords": ["xin chao", "chao", "hello", "hi ", "alo"],
        "login_required": False,
    },
]

# Câu gợi ý hiện sẵn dưới ô chat để người dùng biết hỏi được gì
SUGGESTIONS = [
    "Sắp tới có sự kiện gì?",
    "Còn vé không?",
    "Vé của tôi thế nào?",
    "Việc của tôi có gì?",
    "Đăng ký thế nào?",
]


def detect_intent(question):
    """
    Tìm ý định khớp nhất với câu hỏi.

    Cách chấm điểm: cộng ĐỘ DÀI của các từ khoá khớp được, chứ không đếm số
    từ khoá. Lý do là từ khoá dài thì cụ thể hơn nên đáng tin hơn.

    Ví dụ câu "Việc của tôi có gì?" khớp cả hai:
        - "co gi"        (5 ký tự)  -> ý định hỏi sự kiện sắp tới
        - "viec cua toi" (12 ký tự) -> ý định hỏi công việc
    Nếu chỉ đếm số từ khoá thì hai bên hoà 1-1 và máy chọn nhầm cái đứng
    trước. Cộng độ dài thì "viec cua toi" thắng, đúng ý người hỏi.

    Không khớp gì thì trả về None.
    """
    text = normalize(question)
    if not text:
        return None

    best, best_score = None, 0
    for intent in INTENTS:
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


def answer(question, user=None, allow_ai=True):
    """
    Trả lời một câu hỏi.

    Trả về dict: {"text", "intent", "links": [...], "source": "rules" | "ai"}
    Phần `links` là các đường dẫn gợi ý để người dùng bấm sang trang tương ứng.
    `source` cho giao diện biết câu trả lời đến từ luật (chính xác) hay từ AI
    (có thể chưa chính xác) để gắn nhãn tương ứng.

    `allow_ai=False` khi người dùng đã dùng hết lượt AI (view quyết định).
    """
    intent = detect_intent(question)

    if intent is None:
        # Chỉ tới đây mới gọi AI - 8 ý định có sẵn LUÔN đi nhánh luật.
        if allow_ai and normalize(question):
            ai_result = _answer_with_ai(question)
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


def _answer_with_ai(question):
    """
    Nhánh AI. Trả về dict trả lời, hoặc None nếu AI không dùng được (chưa có
    key, lỗi mạng, quá tải...) - khi đó answer() quay về câu "chưa hiểu".

    Link do SERVER tạo từ mã sự kiện đã được kiểm tra, AI không tự viết URL.
    """
    from .services import AIError, ask_assistant

    try:
        data = ask_assistant(question)
    except AIError:
        return None

    from events.models import Event
    names = dict(Event.objects.filter(pk__in=data["event_ids"]).values_list("pk", "name"))
    links = [{"label": names[pk], "url": reverse("events:detail", args=[pk])}
             for pk in data["event_ids"] if pk in names]
    return {"intent": "ai", "source": "ai", "text": data["answer"], "links": links}


# --------------------------------------------------------------------------
# Các hàm trả lời cho từng ý định. Mỗi hàm tự truy vấn DB.
# --------------------------------------------------------------------------
def _upcoming_events(user):
    from events.models import Event, EventStatus

    events = (Event.objects
              .filter(status=EventStatus.OPEN, starts_at__gte=timezone.now())
              .order_by("starts_at")[:5])
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
    from events.models import Event, EventStatus

    events = (Event.objects
              .filter(status=EventStatus.OPEN, starts_at__gte=timezone.now())
              .prefetch_related("ticket_types")
              .order_by("starts_at")[:5])
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


HANDLERS = {
    "upcoming_events": _upcoming_events,
    "seats_left": _seats_left,
    "my_tickets": _my_tickets,
    "my_tasks": _my_tasks,
    "how_to_register": _how_to_register,
    "how_to_checkin": _how_to_checkin,
    "cancel_ticket": _cancel_ticket,
    "greeting": _greeting,
}
