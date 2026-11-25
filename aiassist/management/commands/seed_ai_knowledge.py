"""Nạp dữ liệu mẫu cho Kho tri thức CLB (RAG) và Cấu hình Prompt mặc định."""
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
]


class Command(BaseCommand):
    help = "Nạp dữ liệu tri thức nền tảng CLB (RAG) và cấu hình Prompt mặc định."

    def handle(self, *args, **options):
        created_kb = 0
        for item in DEFAULT_KNOWLEDGE:
            _, created = ClubKnowledge.objects.get_or_create(
                title=item["title"],
                defaults=item,
            )
            if created:
                created_kb += 1

        _, created_profile = AIPromptProfile.objects.get_or_create(
            task_key=AITaskKey.CHATBOT,
            defaults={
                "brand_voice": "Thân thiện, gần gũi kiểu sinh viên, chính xác, súc tích và luôn hỗ trợ nhiệt tình.",
                "extra_instructions": "Luôn ưu tiên hướng dẫn người dùng bấm đúng mục trên website khi cần thao tác.",
                "few_shot_examples": [
                    {
                        "input": "Mình muốn vào CLB thì làm thế nào?",
                        "output": "Bạn có thể vào mục Tuyển thành viên trên thanh menu để xem đợt tuyển đang mở, chọn Ban phù hợp và nộp đơn trực tuyến nhé!",
                    }
                ],
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(
            f"Đã nạp {created_kb} mục Kho tri thức mới và {'tạo' if created_profile else 'giữ nguyên'} cấu hình Prompt Chatbot."
        ))
