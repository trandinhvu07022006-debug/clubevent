# KMG AI — Thiết kế Hệ thống Gia sư Âm nhạc (Music Tutor Design)

## 1. Phạm vi tri thức (`aiassist/music_tutor.py`)
1. **Guitar:** Tư thế, lên dây, xử lý rè dây, bảo quản đàn, hợp âm cơ bản, hợp âm chặn (F), chuyển hợp âm, rải ngón, quạt chả, fingerstyle, đệm hát, capo, TAB.
2. **Thanh nhạc:** Luyện hơi bụng, cao độ, trường độ, quãng giọng, chọn tông phù hợp, luyện nghe, phát âm, hát bè, tâm lý biểu diễn.
3. **Nhạc lý:** Nốt, quãng, gam, tông, nhịp, tiết tấu, vòng hòa âm, chuyển tông, cảm âm, đọc bản nhạc.
4. **Nhạc cụ khác:** Piano, Keyboard, Bass, Trống, Ukulele, Cajon.
5. **Tập luyện cùng Band & Biểu diễn:** Phân vai, giữ nhịp, cân bằng âm lượng, soundcheck, micro/mixer/loa, xử lý quên lời/sai hợp âm.
6. **Sáng tạo âm nhạc & Đời sống sinh viên:** Sáng tác, cover, phối khí, thu âm, đồng hành tâm lý sinh viên (ngại giao tiếp, sợ casting trượt, bận thi, chưa có nhạc cụ).

## 2. Nguyên tắc An toàn (Safety Guardrails)
- **Thanh nhạc:** Dừng ngay nếu đau/rát họng hoặc khàn giọng; không chẩn đoán bệnh lý y tế.
- **Thiết bị điện:** Không hướng dẫn tự tháo sửa điện nguy hiểm; yêu cầu ngắt nguồn và báo Ban Kỹ thuật khi có sự cố chập/cháy/mùi khét.
- **Bản quyền:** Không sao chép trái phép lời bài hát hoặc giáo trình có bản quyền vào kho dữ liệu.
- **Đánh giá năng lực:** AI chỉ hỗ trợ luyện tập, không thay thế xác minh kỹ năng (`UserSkill.verification_status`) của CLB.
