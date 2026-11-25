"""Nạp dữ liệu mẫu cho Kho tri thức CLB (RAG) và Cấu hình Prompt cho cả 5 modun AI."""
from django.core.management.base import BaseCommand

from aiassist.models import AIPromptProfile, AITaskKey, ClubKnowledge, KnowledgeCategory

DEFAULT_KNOWLEDGE = [
    {
        "title": "Giới thiệu chung về KMG Club",
        "category": KnowledgeCategory.GENERAL,
        "keywords": "kmg, cau lac bo, clb, gioi thieu, am nhac, hoat dong",
        "content": (
            "KMG Club là câu lạc bộ âm nhạc và tổ chức sự kiện dành cho sinh viên. "
            "CLB thường xuyên tổ chức các đêm nhạc Acoustic, workshop kỹ năng, sự kiện giao lưu "
            "và các đợt tuyển thành viên theo học kỳ."
        ),
        "priority": 1,
    },
    {
        "title": "Quy trình tham gia và check-in sự kiện",
        "category": KnowledgeCategory.EVENT,
        "keywords": "tham gia, check in, ma qr, ve dien tu, chuyen nhuong ve",
        "content": (
            "Sinh viên đăng ký vé trực tuyến trên hệ thống. Với vé có phí cần thanh toán qua VietQR "
            "trong thời hạn quy định. Khi đến sự kiện, mở mục 'Vé của tôi' để xuất trình mã QR "
            "cho BTC quét check-in. Hệ thống cũng hỗ trợ chuyển nhượng vé hợp lệ trước giờ diễn ra."
        ),
        "priority": 2,
    },
    {
        "title": "Quy trình tuyển thành viên và phỏng vấn/casting",
        "category": KnowledgeCategory.RECRUITMENT,
        "keywords": "tuyen thanh vien, tuyen quan, casting, phong van, nop don, ban",
        "content": (
            "CLB mở đơn tuyển theo từng đợt trong mục Tuyển thành viên. Ứng viên chọn Ban mong muốn, "
            "điền thế mạnh/kỹ năng, động lực và có thể đính kèm link portfolio/video. Sau vòng duyệt đơn, "
            "Trưởng ban sẽ hẹn lịch phỏng vấn hoặc casting trực tiếp."
        ),
        "priority": 3,
    },
    {
        "title": "Cơ cấu các Ban và hoạt động nội bộ",
        "category": KnowledgeCategory.RULE,
        "keywords": "co cau, ban chuyen mon, noi quy, workspace, nhiem vu",
        "content": (
            "Thành viên chính thức được cấp quyền truy cập Không gian nội bộ (/workspace/) để nhận "
            "nhiệm vụ, tham gia lịch tập, đề xuất chương trình, bảng tin nội bộ và đánh giá định kỳ."
        ),
        "priority": 4,
    },
    {
        "title": "Thanh toán VietQR và hoàn/hủy vé",
        "category": KnowledgeCategory.FINANCE,
        "keywords": "thanh toan, vietqr, chuyen khoan, hoan ve, huy ve",
        "content": (
            "Vé có phí sử dụng mã chuyển khoản VietQR tự động kèm nội dung giao dịch riêng. "
            "Nếu chưa check-in và còn trong thời hạn cho phép, người dùng có thể tự hủy vé ở mục "
            "'Vé của tôi' để nhường suất cho danh sách chờ."
        ),
        "priority": 5,
    },
]

DEFAULT_PROFILES = [
    {
        "task_key": AITaskKey.CHATBOT,
        "brand_voice": "Thân thiện, gần gũi kiểu sinh viên, chính xác, súc tích và luôn hỗ trợ nhiệt tình.",
        "extra_instructions": "Luôn ưu tiên hướng dẫn người dùng bấm đúng mục trên website khi cần thao tác.",
        "few_shot_examples": [
            {
                "input": "Mình muốn vào CLB thì làm thế nào?",
                "output": "Bạn có thể vào mục Tuyển thành viên trên thanh menu để xem đợt tuyển đang mở, chọn Ban phù hợp và nộp đơn trực tuyến nhé!",
            }
        ],
    },
    {
        "task_key": AITaskKey.SUGGEST_TASKS,
        "brand_voice": "Thực tế, chi tiết, rõ đầu việc theo quy trình tổ chức sự kiện CLB sinh viên.",
        "extra_instructions": "Phân bổ công việc cân đối giữa Ban Nội dung, Ban Truyền thông, Ban Hậu cần và Ban Kỹ thuật.",
        "few_shot_examples": [
            {
                "input": "Đêm nhạc Acoustic 150 người, còn 14 ngày",
                "output": '{"title": "Khảo sát âm thanh và test micro tại hội trường", "days_before": 3, "note": "Kiểm tra mixer, loa kiểm âm và dây kết nối nhạc cụ", "department": "Ban Kỹ thuật", "priority": "HIGH"}',
            }
        ],
    },
    {
        "task_key": AITaskKey.EVENT_MARKETING,
        "brand_voice": "Trẻ trung, giàu năng lượng sinh viên, truyền cảm hứng âm nhạc & gắn kết cộng đồng.",
        "extra_instructions": "Bài đăng Fanpage phải mở đầu bằng tiêu đề thu hút, nêu rõ Thời gian - Địa điểm và Call-to-Action đặt vé trên KMG Club Event.",
        "few_shot_examples": [
            {
                "input": "Đêm nhạc Acoustic Dưới Ánh Đèn",
                "output": "🎸 ĐÊM NHẠC ACOUSTIC: DƯỚI ÁNH ĐÈN 🎶 — Gác lại deadline, cùng KMG hòa mình vào những giai điệu mộc mạc và ấm áp nhất học kỳ này! 🎟 Đặt vé ngay trên hệ thống!",
            }
        ],
    },
    {
        "task_key": AITaskKey.SCREEN_APPLICATION,
        "brand_voice": "Khách quan, khích lệ tinh thần học hỏi, đánh giá đúng thế mạnh ứng viên.",
        "extra_instructions": "Câu hỏi phỏng vấn/casting cần gắn trực tiếp với tình huống thực tế của Ban ứng tuyển.",
        "few_shot_examples": [
            {
                "input": "Ứng tuyển Ban Truyền thông, biết chụp ảnh & Canva, chưa có kinh nghiệm chạy event",
                "output": "Điểm 8/10. Ứng viên có nền tảng hình ảnh tốt và tinh thần cầu tiến. Câu hỏi gợi ý: Nếu sự kiện diễn ra vào buổi tối thiếu sáng, bạn xử lý bố cục và hậu kỳ ảnh thế nào để kịp đăng recap trong 24h?",
            }
        ],
    },
    {
        "task_key": AITaskKey.POSTMORTEM,
        "brand_voice": "Chuyên nghiệp, súc tích, định hướng hành động rõ ràng cho Ban Chủ nhiệm.",
        "extra_instructions": "Đối chiếu chặt chẽ tỷ lệ check-in, cân đối thu-chi và phản hồi khán giả để đề xuất cải tiến thực tế.",
        "few_shot_examples": [
            {
                "input": "Check-in 75%, thặng dư 500.000đ, đánh giá 4.6/5",
                "output": "Sự kiện vận hành hiệu quả và cân đối tài chính dương (+500.000đ). Cần bổ sung tin nhắn nhắc lịch trước 12h để nâng tỷ lệ check-in vượt mốc 85%.",
            }
        ],
    },
]


class Command(BaseCommand):
    help = "Nạp dữ liệu tri thức nền tảng CLB (RAG) và cấu hình Prompt cho 5 modun AI."

    def handle(self, *args, **options):
        created_kb = 0
        for item in DEFAULT_KNOWLEDGE:
            _, created = ClubKnowledge.objects.get_or_create(
                title=item["title"],
                defaults=item,
            )
            if created:
                created_kb += 1

        created_profiles = 0
        for prof in DEFAULT_PROFILES:
            _, created = AIPromptProfile.objects.get_or_create(
                task_key=prof["task_key"],
                defaults={
                    "brand_voice": prof["brand_voice"],
                    "extra_instructions": prof["extra_instructions"],
                    "few_shot_examples": prof["few_shot_examples"],
                    "is_active": True,
                },
            )
            if created:
                created_profiles += 1

        self.stdout.write(self.style.SUCCESS(
            f"Đã nạp {created_kb} mục Kho tri thức mới và {created_profiles} cấu hình Prompt modun AI mới."
        ))
