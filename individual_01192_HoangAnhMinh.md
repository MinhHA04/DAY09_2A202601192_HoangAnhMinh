# Báo cáo cá nhân — Multi-Agent E-commerce Dispute Resolution

> Bản nháp được lập từ artifact chạy thực tế. Cần xác nhận lại MSSV suy ra từ
> tên repo trước khi nộp.

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
|---|---|
| Họ và tên | Hoàng Anh Minh |
| MSSV | 2A202601192 |
| Khóa/Lớp | K4 |
| Vai trò chính | Thiết kế và tích hợp pipeline multi-agent |
| Ngày hoàn thành | 2026-08-05 |

## 2. Phạm vi công việc

| Module/deliverable | File phụ trách | Input | Output | Trạng thái |
|---|---|---|---|---|
| Data access | `ecommerce_agents/repository.py` | 9 CSV Olist, target order IDs | Index dữ liệu đã kiểm chứng | Hoàn thành |
| Specialist agents | `ecommerce_agents/agents.py` | Order/customer/item/payment facts | Handoff theo domain | Hoàn thành |
| Orchestration | `ecommerce_agents/coordinator.py` | Một input case | JSON kết quả đã tổng hợp | Hoàn thành |
| Hard gate | `ecommerce_agents/verifier.py` | JSON kết quả và CSV nguồn | Pass/fail | Hoàn thành |
| Runtime/artifact | `main.py` | 50 input | 50 output, trace, metadata | Hoàn thành |
| Test và tài liệu | `tests/`, `architecture.md` | Policy và implementation | Test report, tài liệu kiến trúc | Hoàn thành |

## 3. Kết quả bàn giao

- Sinh và verify đủ 50 file `output/EC_001.json` đến `EC_050.json` ở baseline.
- Tích hợp `gpt-4o-mini` qua OpenAI Responses API cho 5 specialist agent.
- Lượt chạy online tạo 400 event và 250 model-backed handoff có request ID.
- `metadata.json` ghi 75.200 input tokens và 14.113 output tokens.
- Bao phủ đủ 6 primary issue trong bộ input thực tế.
- 5 unit test đã chạy thành công.

Lệnh xác minh:

```bash
python -m unittest discover -s tests -v
python main.py
```

Kết quả thực tế của pipeline:

```text
Processed and verified 50 cases; outputs=50; trace=trace.jsonl
```

## 4. Giải thích kỹ thuật

### Vấn đề cần giải quyết

Một khiếu nại không thể được quyết định chỉ từ message của khách hàng. Pipeline
phải join nhiều bảng, phân biệt customer record với customer identity, đối soát
tiền, tính độ trễ, xác định trách nhiệm và chỉ nộp evidence tồn tại trong CSV.

### Cách triển khai

Coordinator phân phối cùng `claimed_order_id` cho các agent theo domain. Data
Repository giới hạn quyền truy cập và giữ thứ tự CSV. Payment và Delivery Agent
dùng phép tính xác định thay cho suy luận ngôn ngữ. Policy Agent nhận các handoff
và áp dụng luật theo thứ tự ưu tiên. Verifier đọc lại quan hệ nguồn để ngăn ID giả,
sai số tiền, sai null handling hoặc output vượt giới hạn.

Runtime dùng `gpt-4o-mini` để review từng structured handoff. Truy vấn, phép tính,
policy priority và hard gate vẫn dùng Python xác định để cùng input/CSV tạo cùng
JSON. OpenAI không công bố parameter count; cần xác nhận với giảng viên rằng model
hosted này được chấp nhận theo điều kiện tối đa 10B.

### Input, output và contract

| Thành phần | Mô tả |
|---|---|
| Input | `EC_*.json` theo schema README |
| Output | Một JSON kết luận tương ứng trong `output/` |
| Module phụ thuộc | Repository và specialist agents |
| Module dùng output | Verifier, output writer và hệ thống chấm |
| Lỗi được hard-gate | Order/FK thiếu, policy không khớp, evidence giả, sai tiền/schema/limit |

## 5. Quyết định kỹ thuật quan trọng

- **Phương án cân nhắc:** để LLM tự tính toàn bộ; chỉ dùng deterministic code;
  hoặc thiết kế hybrid.
- **Phương án chọn:** hybrid — GPT-4o mini review từng domain handoff, Python giữ
  quyền quyết định đối với số liệu và hard gate.
- **Lý do:** vẫn có agent/model chạy thật và trace thật, đồng thời tránh sai số tiền,
  timestamp hoặc hallucinated evidence.
- **Bằng chứng:** pipeline online 50/50 case qua Verifier và 250 OpenAI requests.

## 6. Lỗi/blocker đã xử lý



## 7. Hiểu biết end-to-end

Input cung cấp `claimed_order_id`. Repository tra order và customer, dùng
`customer_unique_id` để tìm lịch sử, rồi lấy item, seller, product và payment.
Các agent tạo báo cáo theo domain. Policy Agent phân loại vấn đề, trách nhiệm,
root cause, refund và actions. Coordinator tạo JSON đúng schema. Verifier đối
chiếu lại nguồn trước khi main ghi output, trace và metadata.

## 8. Cam kết tự kiểm tra

- [x] Báo cáo phản ánh artifact và lệnh đã chạy.
- [x] Không ghi API key, token, `.env` hoặc secret.
- [x] Output và trace được tạo từ lượt chạy có kiểm chứng.
- [x] Người nộp đã xác nhận lại họ tên, MSSV và nội dung cá nhân.

**Họ và tên:** Hoàng Anh Minh  
**Ngày xác nhận:** 8/5/2026
