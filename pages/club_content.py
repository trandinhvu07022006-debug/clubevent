"""
NỘI DUNG GIỚI THIỆU KMG - một chỗ duy nhất để sửa.

Nguồn: bài giới thiệu chính thức của CLB (thành tích, tiêu chí là thật).
Đã chắt lọc: bỏ emoji và câu kêu gọi kiểu bài đăng Facebook, giữ nguyên ý,
KHÔNG thêm số liệu/năm nào ngoài nguồn. Muốn thêm thành tích mới: thêm một
dòng vào ACHIEVEMENTS.

Ban Quản trị (tên, chức vụ, ảnh) lưu trong CSDL (pages.ClubOfficer) để
Admin đổi qua trang quản trị mỗi nhiệm kỳ, không phải sửa code.
"""

CLUB_PROFILE = {
    "short_name": "KMG",
    "official_name": "Ban Âm nhạc Hội Sinh viên Học viện Kỹ thuật Mật mã",
    "former_name": "CLB Guitar Học viện Kỹ thuật Mật mã (KMA Guitar Club)",
    "motto": "Nơi âm nhạc bắt đầu từ những trái tim đồng điệu",
    "summary": (
        "Tiền thân là CLB Guitar Học viện Kỹ thuật Mật mã, KMG là câu lạc bộ lâu đời "
        "nhất Học viện - sân chơi cho sinh viên đam mê âm nhạc nói chung và guitar "
        "nói riêng."
    ),
    # Tiêu chí hoạt động (nguyên văn ý của CLB)
    "mission": "Chia sẻ kiến thức, tạo ra sân chơi cho sinh viên đam mê âm nhạc nói "
               "chung và guitar nói riêng.",
    "board_message": (
        "Ban Quản trị không chỉ quản lý, điều phối hoạt động mà còn là những người anh, "
        "người bạn đồng hành cùng tiếng đàn của mỗi thành viên - giữ cho ngọn lửa đam "
        "mê luôn được thắp sáng qua từng thế hệ."
    ),
}

# Điều làm nên KMG - (icon Bootstrap, tiêu đề ngắn, mô tả)
HIGHLIGHTS = [
    ("bi-door-open", "Không cần biết chơi nhạc cụ",
     "Chưa có năng khiếu âm nhạc vẫn tham gia được: CLB có nhiều hoạt động khác "
     "ngoài âm nhạc, như truyền thông và tổ chức sự kiện."),
    ("bi-people", "Gắn kết như một gia đình",
     "Thành viên các thế hệ luôn gắn bó với nhau như anh em trong nhà."),
    ("bi-mortarboard", "Học và rèn luyện kỹ năng",
     "Chơi nhạc cụ, hát, giao tiếp, tổ chức sự kiện, làm việc nhóm, truyền thông."),
    ("bi-mic", "Biểu diễn trên sân khấu thật",
     "Trực tiếp biểu diễn tại các sự kiện do Học viện tổ chức và các show âm nhạc "
     "của CLB."),
    ("bi-arrow-left-right", "Giao lưu ngoài Học viện",
     "Giao lưu với các CLB Guitar khác và tham dự sự kiện âm nhạc cho sinh viên "
     "trên địa bàn Hà Nội."),
    ("bi-tree", "Dã ngoại, tình nguyện, cuộc thi",
     "Nhiều hoạt động giúp rèn luyện bản thân và có thêm trải nghiệm thời sinh viên."),
]

# Thành tích - (giải, cuộc thi, ghi chú đơn vị tổ chức nếu có)
ACHIEVEMENTS = [
    ("Quán quân", "The House Voice", ""),
    ("Á quân", "KMA Got Talent", ""),
    ("Giải Ba", "KMA Got Talent", ""),
    ("Á quân", "Sing To Learn", "Học viện Công nghệ Bưu chính Viễn thông tổ chức"),
]
