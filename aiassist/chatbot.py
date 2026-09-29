"""
Trợ lý tra cứu dựa trên luật (rule-based assistant).

QUAN TRỌNG khi viết báo cáo và khi bảo vệ: đây KHÔNG phải AI sinh ngôn ngữ.
Nó nhận diện ý định người dùng bằng cách so khớp từ khoá, rồi truy vấn cơ sở
dữ liệu và trả lời theo mẫu câu có sẵn. Gọi đúng tên là "hỏi đáp theo ý định"
(intent-based QA). Ghi là "tích hợp AI" thì sai và dễ bị hỏi vặn.

Đổi lại, nó có những ưu điểm mà chatbot dùng LLM không có:
  - Không gọi API ra ngoài, nên chạy được cả trên host chặn kết nối ngoài.
  - Không tốn quota, không cần API key.
  - Kết quả xác định, nên viết unit test được cho từng ý định.
  - Không bao giờ bịa thông tin sai về sự kiện (không bị hallucination).

Cách nhận diện ý định:
  1. Chuẩn hoá câu hỏi: hạ chữ thường và BỎ DẤU tiếng Việt, để "còn vé không"
     và "con ve khong" đều khớp — người dùng gõ nhanh hay không bỏ dấu đều được.
  2. Mỗi ý định có một bộ từ khoá. Ý định nào khớp nhiều từ khoá nhất thì thắng.
  3. Không ý định nào khớp thì trả lời gợi ý các câu hỏi biết trả lời.
"""
import unicodedata

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
        score = sum(len(kw) for kw in intent["keywords"] if kw in text)
        if score > best_score:
            best, best_score = intent, score
    return best


def answer(question, user=None):
    """
    Trả lời một câu hỏi.

    Trả về dict: {"text": câu trả lời, "intent": mã ý định, "links": [...]}
    Phần `links` là các đường dẫn gợi ý để người dùng bấm sang trang tương ứng.
    """
    intent = detect_intent(question)

    if intent is None:
        return {
            "intent": "unknown",
            "text": ("Mình chưa hiểu câu hỏi này. Mình trả lời được về: "
                     "sự kiện sắp tới, số chỗ còn lại, vé của bạn, "
                     "công việc được giao, và cách đăng ký hoặc check-in."),
            "links": [],
        }

    is_logged_in = bool(user and user.is_authenticated)
    if intent["login_required"] and not is_logged_in:
        return {
            "intent": intent["code"],
            "text": "Bạn cần đăng nhập thì mình mới tra được thông tin cá nhân.",
            "links": [{"label": "Đăng nhập", "url": "/taikhoan/dangnhap/"}],
        }

    handler = HANDLERS[intent["code"]]
    result = handler(user)
    result["intent"] = intent["code"]
    return result


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
        lines.append(f"• {e.name} — {timezone.localtime(e.starts_at):%H:%M %d/%m} "
                     f"tại {e.location}")
        links.append({"label": e.name, "url": f"/sukien/{e.pk}/"})
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
        lines.append(f"• {e.name} — {detail}")
        links.append({"label": f"Đăng ký {e.name}", "url": f"/sukien/{e.pk}/"})

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
            "links": [{"label": "Xem sự kiện đang mở", "url": "/"}],
        }

    lines = [f"Bạn đang có {len(tickets)} vé:"]
    for t in tickets:
        lines.append(f"• {t.event.name} — mã {t.code} — {t.get_status_display()}")
    pending = sum(1 for t in tickets if t.status == TicketStatus.PENDING)
    if pending:
        lines.append(f"\nCó {pending} vé chờ thanh toán. Thanh toán xong báo BTC "
                     f"xác nhận, quá 24h vé sẽ tự huỷ.")
    return {"text": "\n".join(lines),
            "links": [{"label": "Mở trang vé của tôi", "url": "/ve/cua-toi/"}]}


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
                "links": [{"label": "Xem tất cả việc", "url": "/congviec/viec-cua-toi/"}]}

    lines = [f"Bạn còn {len(tasks)} việc chưa xong:"]
    overdue = 0
    for t in tasks:
        when = (f" — hạn {timezone.localtime(t.deadline):%H:%M %d/%m}"
                if t.deadline else "")
        late = ""
        if t.is_overdue:
            overdue += 1
            late = " (QUÁ HẠN)"
        lines.append(f"• {t.title}{when}{late} — {t.event.name}")
    if overdue:
        lines.append(f"\nTrong đó {overdue} việc đã quá hạn.")
    return {"text": "\n".join(lines),
            "links": [{"label": "Mở trang việc của tôi",
                       "url": "/congviec/viec-cua-toi/"}]}


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
        "links": [{"label": "Xem sự kiện đang mở", "url": "/"}],
    }


def _how_to_checkin(user):
    return {
        "text": ("Hôm diễn ra sự kiện, bạn mở mục Vé của tôi và đưa mã QR "
                 "cho ban tổ chức quét. Không quét được thì đọc mã 12 ký tự "
                 "để ban tổ chức nhập tay. Mỗi vé chỉ check-in được một lần."),
        "links": [{"label": "Mở trang vé của tôi", "url": "/ve/cua-toi/"}],
    }


def _cancel_ticket(user):
    from django.conf import settings

    return {
        "text": (f"Bạn huỷ vé được ở mục Vé của tôi, miễn là còn hơn "
                 f"{settings.CANCEL_BEFORE_HOURS} giờ nữa mới tới giờ diễn ra "
                 f"và vé chưa check-in. Huỷ xong chỗ đó được trả lại cho "
                 f"người khác đăng ký."),
        "links": [{"label": "Mở trang vé của tôi", "url": "/ve/cua-toi/"}],
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
