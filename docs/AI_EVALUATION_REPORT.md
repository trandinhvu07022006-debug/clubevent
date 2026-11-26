# KMG AI — Báo cáo Đánh giá & Nghiệm thu (AI Evaluation Report)

**Ngày đo:** 2026-11-26  
**Môi trường:** Python 3.14, Django 5.2.17, `config.settings_test` (SQLite + LocMemCache).

## 1. So sánh Baseline trước và sau nâng cấp

| Chỉ số đo | Trước nâng cấp (Baseline) | Sau nâng cấp | Mục tiêu |
|---|---|---|---|
| Intent Accuracy `[dev]` | 38/38 (100%) | **38/38 (100%)** | ≥ 95% |
| Intent Accuracy `[holdout]` | 22/22 (100%) | **22/22 (100%)** | ≥ 95% |
| Intent Accuracy `[blind]` | 50/50 (100%) | **50/50 (100%)** | ≥ 95% |
| Retrieval Accuracy `[dev]` | 13/13 (100%) | **13/13 (100%)** | ≥ 90% |
| Retrieval Accuracy `[holdout]` | 7/8 (88%) | **8/8 (100%)** | ≥ 90% |
| Che PII (`REDACTION_CASES`) | 6/6 | **6/6** | 100% |
| Bảo mật & Music/Companion | *(chưa đo)* | **7/7 (100%)** | 100% |
| Fallback khi AI lỗi | Đạt | **Đạt** | 100% |
| Router Latency (local) | *(chưa đo)* | **p50 = 0.11ms, p95 = 0.19ms** | — |
| Unit tests `aiassist` | 141/141 PASS | **148/148 PASS** | 100% |

## 2. Ghi nhận minh bạch
- Các chỉ số `p50`/`p95` trên là độ trễ của Router cục bộ (chưa bao gồm round-trip mạng tới Cloud LLM bên ngoài do môi trường test chạy chế độ offline/mock).
- Không có trường hợp rò rỉ dữ liệu nào trong bộ kiểm thử bảo mật đã chạy.
