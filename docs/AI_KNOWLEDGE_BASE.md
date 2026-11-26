# KMG AI — Quản trị Kho Tri thức (Knowledge Base)

## 1. Cấu trúc `ClubKnowledge` (`aiassist/models.py`)
| Trường | Mô tả |
|---|---|
| `knowledge_id` | Mã định danh duy nhất (vd: `K01`, `MUSIC-K01`) phục vụ đồng bộ không trùng lặp |
| `category` | `GENERAL`, `EVENT`, `RECRUITMENT`, `FINANCE`, `RULE`, `MUSIC`, `STUDENT_LIFE`, `TRAINING`, `TECH` |
| `visibility` | `PUBLIC` (Công khai), `INTERNAL` (Nội bộ CLB), `CONFIDENTIAL` (Mật / Quản trị) |
| `approval_status` | `DRAFT`, `PENDING`, `APPROVED`, `ARCHIVED` — **chỉ `APPROVED` mới được đưa vào RAG** |
| `version` & `effective_date` | Phiên bản tài liệu và ngày bắt đầu hiệu lực |
| `source_urls` & `source_note` | Nguồn tham chiếu xác minh |
| `owner`, `is_admin_edited`, `revision_history` | Người phụ trách, cờ chống ghi đè khi đồng bộ và lịch sử duyệt/sửa |

## 2. Quy trình vòng lặp cải tiến (AI Studio)
1. Thu thập câu hỏi bị 👎 hoặc `unknown` tại Tab 3 của AI Studio (`/troly/huan-luyen/`).
2. Biên tập hoặc nhập ứng viên tri thức (`PENDING`).
3. Trưởng ban / BCN rà soát, bấm **Duyệt** (`approve_kb`) để chuyển sang `APPROVED` + `is_active=True`.
4. Chạy `evaluate_ai` kiểm thử hồi quy trước khi xuất dữ liệu.
