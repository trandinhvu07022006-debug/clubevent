"""
Music Knowledge System, Personalized Music Tutor & Student Companion for KMG AI.

Safety invariants:
  - Never encourage vocal practice when experiencing throat pain or hoarseness; never diagnose.
  - Never instruct dangerous electrical/high-voltage equipment repair.
  - Never copy copyrighted song lyrics or paid textbooks.
  - Progress metrics are computed strictly from real logs/skills/enrollments (never fabricated).
"""
from __future__ import annotations

import re
from typing import Any

from .router import prepare_query


# Structured topic guides (concise, practical, student-friendly, safety-checked)
_MUSIC_TOPICS: list[dict[str, Any]] = [
    {
        "keys": ("bam f", "hop am chan", "barre", "f truong"),
        "title": "Kỹ thuật bấm hợp âm chặn (F trưởng) trên Guitar",
        "answer": (
            "Hợp âm F là thử thách quen thuộc khi mới tập guitar. Bạn thử 3 bước này nhé:\n"
            "1. Dùng cạnh ngoài (hơi nghiêng về phía ngón cái) của ngón trỏ ép sát ngay sát thanh phím ngăn 1 thay vì đặt chính giữa phím.\n"
            "2. Hạ nhẹ ngón cái xuống giữa mặt sau cần đàn để tạo lực đòn bẩy, giữ khuỷu tay thả lỏng.\n"
            "3. Nếu còn rè, tập trước thế Fmaj7 hoặc F chặn 4 dây dưới trong 5 phút/ngày rồi nâng dần lên chặn 6 dây."
        ),
    },
    {
        "keys": ("hop am co ban", "chuyen hop am", "dem hat", "quat cha", "rai ngon", "capo", "fingerstyle"),
        "title": "Đệm hát Guitar cơ bản & chuyển hợp âm",
        "answer": (
            "Để chuyển hợp âm mượt khi đệm hát:\n"
            "1. Tập vòng hợp âm C - G - Am - F (hoặc G - D - Em - C) thật chậm với metronome ở 60 BPM.\n"
            "2. Giữ nhịp tay phải đều (Down-Down-Up-Up-Down-Up) — đừng dừng tay phải khi tay trái đang đổi thế.\n"
            "3. Dùng Capo kẹp lên ngăn phù hợp để giữ tông hát thoải mái mà vẫn dùng thế bấm quen thuộc."
        ),
    },
    {
        "keys": ("len day", "tieng re", "chon dan", "bao quan", "guitar", "tab", "tu the cam dan"),
        "title": "Làm quen & bảo quản đàn Guitar",
        "answer": (
            "Với người mới tập guitar: ưu tiên đàn action vừa phải (dây không quá cao ở ngăn 12), lên dây chuẩn E-A-D-G-B-E trước mỗi buổi tập bằng app tuner.\n"
            "Nếu bị rè dây: kiểm tra xem ngón tay có đặt sát thanh phím chưa; nếu rè cả khi buông dây thì có thể mang tới Ban Kỹ thuật CLB kiểm tra cong cần hoặc độ cao lược đàn. "
            "Cất đàn nơi khô thoáng, tránh nắng gắt hoặc cốp xe nóng."
        ),
    },
    {
        "keys": ("dau hong", "khan giong", "rat hong", "mat giong", "ep giong"),
        "title": "An toàn giọng hát",
        "answer": (
            "Nếu bạn đang đau rát họng hoặc khàn tiếng, hãy **dừng luyện thanh ngay** để tránh tổn thương dây thanh quản. "
            "Uống nước ấm, nghỉ nói chuyện nhiều và không cố ép lên nốt cao. "
            "Mình không thể thay thế bác sĩ — nếu khàn tiếng kéo dài trên 1–2 tuần, bạn nên đi khám chuyên khoa Tai Mũi Họng nhé."
        ),
    },
    {
        "keys": ("thanh nhac", "luyen hoi", "cao do", "truong do", "quang giong", "chon tong", "luyen nghe", "phat am", "hat be"),
        "title": "Luyện thanh nhạc & hơi thở cơ bản",
        "answer": (
            "Nền tảng thanh nhạc gồm 3 phần: hơi thở bụng, giữ cao độ và mở khẩu hình tự nhiên.\n"
            "• Luyện hơi: hít sâu làm phồng nhẹ bụng dưới, xì hơi 'sss' đều 15–20 giây không giật.\n"
            "• Khởi động giọng: lip trill (rung môi) từ quãng trung lên nhẹ nhàng 5 phút trước khi hát.\n"
            "• Chọn tông: hát thử đoạn điệp khúc; nếu phải gồng cổ hoặc hụt hơi, hãy hạ 1–2 nửa cung cho vừa quãng giọng thoải mái."
        ),
    },
    {
        "keys": ("nhac ly", "not nhac", "quang", "gam", "tong", "nhip", "tiet tau", "vong hoa am", "chuyen tong", "cam am", "doc ban nhac", "hoa am"),
        "title": "Nhạc lý ứng dụng cho sinh viên",
        "answer": (
            "Bạn nên học nhạc lý gắn liền với nhạc cụ thay vì học thuộc lòng:\n"
            "1. Nắm 7 nốt tự nhiên (C-D-E-F-G-A-B) và quy luật cung - nửa cung (E-F và B-C cách nhau nửa cung).\n"
            "2. Học cấu tạo hợp âm trưởng/thứ cơ bản và vòng bậc I - V - vi - IV (vd ở giọng C: C - G - Am - F).\n"
            "3. Tập gõ nhịp 4/4 và 3/4 với metronome 10 phút/ngày để vững tiết tấu và dễ cảm âm khi chơi cùng band."
        ),
    },
    {
        "keys": ("piano", "keyboard", "bass", "trong", "ukulele", "cajon"),
        "title": "Hướng dẫn làm quen các nhạc cụ khác",
        "answer": (
            "Mỗi nhạc cụ có điểm khởi đầu riêng:\n"
            "• Ukulele / Cajon: dễ tiếp cận nhất cho người mới, chỉ 1–2 tuần là đệm được bài đơn giản.\n"
            "• Piano / Keyboard: tập tay phải giai điệu + tay trái hợp âm gốc trước khi chạy arpeggio.\n"
            "• Bass / Trống: ưu tiên giữ chắc nhịp với metronome và lắng nghe kick-bass ăn khớp nhau khi vào band."
        ),
    },
    {
        "keys": ("tap band", "thanh lap band", "phan vai", "rehearsal", "can bang am luong", "gop y", "chon bai"),
        "title": "Kỹ năng tập luyện cùng Band",
        "answer": (
            "Để buổi tập band hiệu quả:\n"
            "1. Chốt trước tông bài hát, cấu trúc (Intro - Verse - Chorus - Bridge - Outro) và mỗi người tự tập phần mình ở nhà trước.\n"
            "2. Khi ghép band, đặt âm lượng vừa phải để nghe được nhau, bám chắc nhịp trống/cajon.\n"
            "3. Góp ý theo hướng xây dựng (chỉ rõ đoạn nào cần chỉnh nhịp/tông) để giữ tinh thần thoải mái cho cả nhóm."
        ),
    },
    {
        "keys": ("soundcheck", "san khau", "micro", "mixer", "loa", "thiet bi", "setlist", "tong duyet", "quen loi", "sai hop am", "su co thiet bi", "tam ly bieu dien", "chap dien", "su co dien"),
        "title": "Kỹ năng biểu diễn & Soundcheck an toàn",
        "answer": (
            "Khi chuẩn bị sân khấu và soundcheck:\n"
            "• Thử micro, monitor và cân bằng âm lượng từng nhạc cụ trước giờ diễn; giữ khoảng cách micro ổn định và tránh chĩa thẳng vào loa để hạn chế hú (feedback).\n"
            "• Nếu lỡ quên lời hoặc sai hợp âm trên sân khấu: giữ nhịp tiếp tục, mỉm cười hoặc ra hiệu nhẹ cho band — khán giả ít để ý nếu bạn không dừng lại.\n"
            "• Lưu ý an toàn: nếu có sự cố điện, chập cháy hoặc mùi khét từ thiết bị âm thanh, **ngắt nguồn và báo ngay Ban Kỹ thuật**, tuyệt đối không tự tháo sửa điện."
        ),
    },
    {
        "keys": ("sang tac", "cover", "phoi khi", "thu am", "phong cach bieu dien", "ban quyen"),
        "title": "Sáng tạo âm nhạc & Cover đúng bản quyền",
        "answer": (
            "Khi cover, phối khí hoặc sáng tác: hãy bắt đầu từ vòng hợp âm đơn giản, thử thay đổi tiết tấu hoặc chuyển tông phù hợp chất giọng để tạo dấu ấn riêng. "
            "Khi thu âm tại nhà, chọn phòng ít vang và kiểm tra mức gain tránh bị rè (clipping). "
            "Luôn tôn trọng bản quyền tác giả khi đăng tải sản phẩm và không sao chép trái phép giáo trình/bản nhạc có bản quyền."
        ),
    },
]

_STUDENT_COMPANION_CASES: list[tuple[tuple[str, ...], str]] = [
    (
        ("khong co nang khieu", "mat tu tin", "moi nguoi gioi hon", "tu ti", "mai khong tien bo"),
        "Đừng quá áp lực nhé — gần như ai mới bắt đầu ở KMG cũng từng thấy ngợp khi nhìn các anh chị chơi mượt. "
        "Âm nhạc phần lớn đến từ thói quen tập đều 15–20 phút mỗi ngày chứ không phải năng khiếu bẩm sinh. "
        "Bạn có thể chọn một mục tiêu nhỏ trong 7 ngày (ví dụ chuyển mượt 3 hợp âm) và tập cùng bạn hoặc mentor Ban Chuyên môn để thấy tiến bộ rõ hơn.",
    ),
    (
        ("so casting truot", "casting", "chua biet dan", "chua biet gi"),
        "Không sao cả! KMG đón nhận cả các bạn chưa biết chơi nhạc cụ nhưng có đam mê âm nhạc hoặc muốn đóng góp ở mảng Truyền thông – Sự kiện, Kỹ thuật hậu cần. "
        "Khi đi casting, CLB đánh giá cao sự chân thành, tinh thần học hỏi và khả năng phối hợp hơn là kỹ thuật quá cao siêu. Bạn cứ tự tin chuẩn bị phần thể hiện vừa sức nhất nhé!",
    ),
    (
        ("chua co nhac cu", "khong co dan", "muon dan"),
        "Nếu chưa có nhạc cụ riêng, bạn vẫn có thể tham gia sinh hoạt CLB và mượn/tập chung nhạc cụ tại các buổi tập hoặc phòng tập của CLB (tùy lịch sắp xếp của Ban Chuyên môn). "
        "Khi nào muốn mua đàn đầu tiên, bạn có thể nhắn các anh chị Ban Chuyên môn tư vấn mẫu vừa túi tiền sinh viên để tránh mua nhầm đàn khó bấm.",
    ),
    (
        ("chua than voi ai", "ngai hoi anh chi", "ngai giao tiep", "tim ban cung tap"),
        "Mới vào CLB ai cũng hơi ngại lúc đầu hết. Cách nhanh nhất để làm quen là đi đều các buổi sinh hoạt/tập chung của Ban hoặc rủ 1–2 bạn mới khác cùng tập một bài đơn giản. "
        "Các anh chị ở KMG rất thoải mái, bạn cứ mạnh dạn hỏi trực tiếp hoặc nhắn trong nhóm Ban nhé!",
    ),
    (
        ("sap thi", "mai thi", "lich thi", "ban hoc", "muon nghi clb", "khong muon bieu dien", "trung lich"),
        "Việc học và thi cử của sinh viên luôn là ưu tiên hàng đầu. Nếu trùng lịch thi, bạn chỉ cần báo sớm cho Trưởng ban hoặc người phụ trách buổi tập để xin phép nghỉ/dời lịch hoặc điều chỉnh lộ trình tập nhẹ xuống 10 phút/ngày. "
        "Nếu chưa sẵn sàng lên sân khấu, bạn hoàn toàn có thể sinh hoạt, tập luyện và hỗ trợ hậu trường trước — CLB không ép buộc biểu diễn đâu nhé.",
    ),
    (
        ("doi nhac cu", "chuyen ban"),
        "Nếu bạn muốn thử đổi nhạc cụ hoặc chuyển Ban cho phù hợp hơn với sở thích hiện tại, hãy trao đổi thẳng thắn với Trưởng ban hiện tại và Ban Chủ nhiệm để được hỗ trợ chuyển tiếp thuận lợi nhé.",
    ),
    (
        ("mau thuan", "bi gop y"),
        "Khi tập nhóm khó tránh khỏi lúc bất đồng quan điểm. Bạn nên giữ bình tĩnh, tách riêng góp ý về kỹ thuật/bài nhạc với cảm xúc cá nhân, và nếu khó tự giải quyết thì nhờ Trưởng ban hoặc Cố vấn đứng ra điều phối giúp hai bên hiểu nhau hơn.",
    ),
]


def answer_music_or_companion(question: str, user=None) -> dict | None:
    """
    Answer music knowledge, personalized tutor plan, or student companion queries.
    Returns None if no topic matches so caller can fall through to Hybrid RAG / LLM.
    """
    norm = prepare_query(question)
    if not norm:
        return None

    # 1. Personalized 7-day / 30-day learning plan request
    if any(k in norm for k in ("lo trinh 7 ngay", "lo trinh 30 ngay", "lo trinh hoc", "ke hoach luyen tap", "goi y bai tap")):
        days = 30 if "30" in norm else 7
        return build_adaptive_plan_response(question, user=user, days=days)

    # 2. Personal practice progress summary
    if any(k in norm for k in ("tien do hoc nhac", "nhat ky luyen tap", "ho so hoc nhac")):
        return get_music_progress_response(user)

    # 3. Student companion (check before general music so emotional/study-life issues get empathy)
    for cues, reply in _STUDENT_COMPANION_CASES:
        if any(c in norm for c in cues):
            return {
                "intent": "student_companion",
                "source": "rules",
                "text": reply,
                "links": [],
                "meta": {"classification": "PUBLIC"},
            }

    # 4. Structured music knowledge topics
    for topic in _MUSIC_TOPICS:
        if any(k in norm for k in topic["keys"]):
            return {
                "intent": "music_tutor",
                "source": "rules",
                "text": topic["answer"],
                "links": [],
                "sources": [{"title": topic["title"], "category": "Kiến thức âm nhạc"}],
                "meta": {"classification": "PUBLIC"},
            }

    return None


def build_adaptive_plan_response(question: str, user=None, days: int = 7) -> dict:
    """
    Build a realistic 7-day or 30-day music practice plan tailored to user's
    MusicLearningProfile (if logged in & personalization_enabled) or parsed from question.
    """
    norm = prepare_query(question)
    instrument = "Guitar"
    if any(k in norm for k in ("thanh nhac", "hat", "vocal")):
        instrument = "Thanh nhạc"
    elif "piano" in norm or "keyboard" in norm:
        instrument = "Piano / Keyboard"
    elif "ukulele" in norm:
        instrument = "Ukulele"
    elif "cajon" in norm or "trong" in norm:
        instrument = "Trống / Cajon"

    minutes = 15
    m = re.search(r"\b(\d{1,3})\s*(?:phut|p)\b", norm)
    if m:
        minutes = max(10, min(int(m.group(1)), 120))

    level_label = "Mới bắt đầu"
    goal = "Đệm hát cơ bản"
    known_skills: list[str] = []

    if user and getattr(user, "is_authenticated", False):
        from .models import MusicLearningProfile
        from organization.models import UserSkill

        prof = MusicLearningProfile.objects.filter(user=user).first()
        if prof and prof.personalization_enabled:
            instrument = prof.instrument or instrument
            level_label = prof.get_level_display()
            goal = prof.goal or goal
            minutes = prof.daily_minutes or minutes
        known_skills = list(
            UserSkill.objects.filter(user=user)
            .select_related("skill")
            .values_list("skill__name", flat=True)[:5]
        )

    skill_note = f" (kỹ năng đã có: {', '.join(known_skills)})" if known_skills else ""

    if days == 30:
        plan_text = (
            f"Lộ trình {days} ngày ({minutes} phút/ngày) cho {instrument} — {level_label}{skill_note}:\n"
            f"• Tuần 1: Tư thế chuẩn, làm quen nhạc cụ/hơi thở, giữ nhịp 60 BPM.\n"
            f"• Tuần 2: 3–4 hợp âm/kỹ thuật nền tảng và chuyển nhịp chậm đều.\n"
            f"• Tuần 3: Ghép 1 bài hát hoàn chỉnh theo mục tiêu '{goal}' (tốc độ 75–85%).\n"
            f"• Tuần 4: Hoàn thiện tốc độ chuẩn, tự thu âm kiểm tra lỗi và tập ghép cùng bạn/CLB.\n"
            f"Nếu tuần nào bận thi, giảm xuống 10 phút/ngày để giữ cảm giác tay/giọng mà không bị áp lực."
        )
    else:
        plan_text = (
            f"Lộ trình 7 ngày ({minutes} phút/ngày) cho {instrument} — {level_label}{skill_note}:\n"
            f"• Ngày 1–2: Khởi động 5 phút + làm quen tư thế/lên dây/luyện hơi ({minutes - 5} phút).\n"
            f"• Ngày 3–4: Tập 2–3 hợp âm hoặc bài tập cao độ cơ bản với metronome chậm.\n"
            f"• Ngày 5–6: Chuyển hợp âm / ghép câu ngắn cho mục tiêu '{goal}'.\n"
            f"• Ngày 7: Ghép một đoạn bài hát ngắn (30–60 giây) và ghi lại nhật ký luyện tập.\n"
            f"Lưu ý: không bắt đầu bằng kỹ thuật khó (như chặn hợp âm liên tục hoặc gằn giọng) khi mới làm quen."
        )

    return {
        "intent": "music_tutor",
        "source": "rules",
        "text": plan_text,
        "links": [],
        "meta": {"classification": "INTERNAL" if (user and getattr(user, "is_authenticated", False)) else "PUBLIC"},
    }


def get_music_progress_response(user) -> dict:
    """Report real practice logs, enrollments, and verified skills (never fabricate progress %)."""
    if not user or not getattr(user, "is_authenticated", False):
        return {
            "intent": "music_tutor",
            "source": "rules",
            "text": "Bạn cần đăng nhập để xem hồ sơ học nhạc và nhật ký luyện tập cá nhân nhé.",
            "links": [],
            "meta": {"classification": "PUBLIC"},
        }

    from .models import MusicLearningProfile, MusicPracticeLog
    from organization.models import UserSkill

    prof = MusicLearningProfile.objects.filter(user=user).first()
    skills = list(
        UserSkill.objects.filter(user=user)
        .select_related("skill")
        .values_list("skill__name", "proficiency", "verification_status")[:6]
    )
    if not prof:
        skill_str = ", ".join(f"{name} ({prof_lv})" for name, prof_lv, _ in skills) if skills else "chưa ghi nhận"
        return {
            "intent": "music_tutor",
            "source": "rules",
            "text": (
                f"Bạn chưa thiết lập hồ sơ Gia sư Âm nhạc cá nhân. Kỹ năng CLB hiện có: {skill_str}. "
                f"Bạn có thể hỏi mình 'Lập lộ trình 7 ngày học guitar 15 phút mỗi ngày' để bắt đầu nhé!"
            ),
            "links": [],
            "meta": {"classification": "PRIVATE_PII"},
        }

    logs = list(MusicPracticeLog.objects.filter(profile=prof)[:10])
    total_mins = sum(l.duration_minutes for l in logs)
    completed = sum(1 for l in logs if l.completed_exercise)
    lines = [
        f"Hồ sơ học nhạc: {prof.instrument} ({prof.get_level_display()}) — Mục tiêu: {prof.goal or 'Chưa đặt'}.",
        f"Cá nhân hóa AI: {'Đang bật' if prof.personalization_enabled else 'Đang tắt'}.",
        f"Nhật ký gần đây: {len(logs)} buổi ({total_mins} phút, hoàn thành {completed} bài tập).",
    ]
    if prof.mentor_notes:
        lines.append(f"Nhận xét mentor: {prof.mentor_notes[:180]}")
    if skills:
        lines.append("Kỹ năng trên hệ thống CLB: " + ", ".join(f"{n} ({lv})" for n, lv, _ in skills))

    return {
        "intent": "music_tutor",
        "source": "rules",
        "text": "\n".join(lines),
        "links": [],
        "meta": {"classification": "PRIVATE_PII"},
    }
