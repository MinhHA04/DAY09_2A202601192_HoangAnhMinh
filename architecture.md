# Kiến trúc multi-agent giải quyết khiếu nại Olist

## 1. Hệ thống này giải quyết việc gì?

Hệ thống nhận 50 yêu cầu điều tra trong `input/EC_001.json` đến
`input/EC_050.json`. Mỗi input cung cấp một `claimed_order_id`. Hệ thống dùng ID
này để truy vấn các CSV Olist, điều tra khách hàng, order, item, seller, product,
payment và delivery, sau đó áp dụng `EC_POLICY_V2` để tạo một JSON kết luận.

Kết quả trả lời các câu hỏi nghiệp vụ sau:

- Vấn đề chính và các vấn đề phụ của case là gì?
- Order có thực sự giao trễ hay không?
- Nếu trễ thì seller hay đơn vị logistics chịu trách nhiệm?
- Payment có khớp với tổng item và freight không?
- Nên hoàn toàn bộ payment, chỉ hoàn freight hay không hoàn?
- Evidence ID nào chứng minh trực tiếp cho quyết định?
- Bộ phận xử lý cần thực hiện các action nào?

Thiết kế là hybrid:

- Python truy vấn CSV, join khóa, tính tiền, tính thời gian và áp dụng policy.
- `gpt-4o-mini` review báo cáo của từng specialist agent.
- Verifier dùng code xác định để hard-gate kết quả trước khi ghi output.

Model không được tự tạo order, payment, seller, tracking event hoặc refund event
không tồn tại trong CSV.

## 2. Multi-agent có thực sự chạy không?

### 2.1 Câu trả lời ngắn

Có, khi chạy lệnh mặc định:

```bash
python main.py
```

Coordinator tạo năm specialist agent khác nhau. Với mỗi case, từng specialist
tạo báo cáo domain của mình rồi thực hiện một OpenAI Responses API request riêng
đến `gpt-4o-mini`. Kết quả được handoff về Coordinator và ghi vào `trace.jsonl`.

Số API request của một lượt chạy đầy đủ:

```text
50 case × 5 model-backed specialist agent = 250 OpenAI API requests
```

Năm agent gọi model là:

1. Customer Agent.
2. Order & Product Agent.
3. Payment Agent.
4. Delivery Agent.
5. Policy Agent.

Coordinator và Verifier không gọi model. Coordinator chịu trách nhiệm orchestration;
Verifier phải độc lập với model để kiểm tra lại kết quả.

### 2.2 Đây là loại multi-agent nào?

Đây là custom in-process multi-agent orchestration bằng Python:

- Mỗi agent là một class riêng với nhiệm vụ và contract riêng.
- Mỗi model-backed agent thực hiện một API request riêng.
- Các agent không nằm trong một prompt tổng duy nhất.
- Policy Agent chỉ chạy sau khi có handoff từ các agent dữ liệu.
- Mọi handoff đều được trace với sender, recipient, event và payload.
- Verifier có quyền chặn output nếu phát hiện sai dữ liệu hoặc schema.

Đây không phải:

- các agent chạy thành nhiều server hoặc process độc lập;
- giao thức A2A qua HTTP giữa các agent;
- OpenAI Agents SDK;
- agent tự trị tự chọn tool và tự lập kế hoạch không giới hạn;
- nhiều model khác nhau cho nhiều vai trò.

Tất cả specialist dùng chung cấu hình `gpt-4o-mini` và cùng một OpenAI client,
nhưng mỗi specialist có API request, task, facts và model response riêng.

### 2.3 Model có quyết định output cuối cùng không?

Model tham gia với vai trò domain reviewer, không phải nguồn dữ liệu có thẩm quyền.
Mỗi agent làm hai bước:

```text
CSV facts + deterministic calculation
                 ↓
       structured domain report
                 ↓
       GPT-4o mini model review
                 ↓
 report + model_review handoff cho Coordinator
```

Output cuối dùng các field đã tính bằng Python. `model_review` được giữ trong
trace để chứng minh model thực sự tham gia, nhưng không được chép vào output JSON
vì schema đề bài không có field này.

Cách làm này tránh để LLM tự cộng tiền, tự tính timestamp hoặc tạo evidence giả.
Nếu model nhận xét `concern`, nhận xét đó xuất hiện trong trace để audit; Verifier
vẫn là hard gate cuối dựa trên CSV và policy code.

## 3. Sơ đồ tổng thể

```text
                         ┌──────────────────────────┐
                         │ input/EC_NNN.json        │
                         │ claimed_order_id, scope  │
                         └────────────┬─────────────┘
                                      │
                                      v
┌──────────────┐             ┌──────────────────────┐
│ Olist CSVs   │────────────>│ OlistRepository      │
│ read-only    │             │ filtered indexes     │
└──────────────┘             └──────────┬───────────┘
                                       │
                                       v
                           ┌────────────────────────┐
                           │ Coordinator Agent      │
                           └────────────┬───────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
              v                         v                         v
   ┌───────────────────┐    ┌─────────────────────┐    ┌──────────────────┐
   │ Customer Agent    │    │ Order/Product Agent │    │ Payment Agent    │
   │ + GPT-4o mini     │    │ + GPT-4o mini       │    │ + GPT-4o mini    │
   └─────────┬─────────┘    └──────────┬──────────┘    └────────┬─────────┘
             │                         │                         │
             └───────────────┬─────────┴──────────────┬──────────┘
                             │                        │
                             v                        v
                  ┌───────────────────┐    ┌──────────────────────┐
                  │ Delivery Agent    │    │ Policy Agent         │
                  │ + GPT-4o mini     │    │ + GPT-4o mini        │
                  └─────────┬─────────┘    └──────────┬───────────┘
                            │                         │
                            └────────────┬────────────┘
                                         v
                              ┌──────────────────────┐
                              │ Coordinator assembles│
                              │ required JSON schema │
                              └──────────┬───────────┘
                                         v
                              ┌──────────────────────┐
                              │ Verifier Agent       │
                              │ deterministic gate   │
                              └──────────┬───────────┘
                                         v
                 ┌───────────────────────────────────────────────┐
                 │ output/*.json, trace.jsonl, metadata.json, ZIP│
                 └───────────────────────────────────────────────┘
```

Trong code hiện tại các agent chạy tuần tự. Customer Agent và Order & Product
Agent về lý thuyết có thể chạy song song, nhưng implementation ưu tiên trace có
thứ tự ổn định và xử lý đơn giản.

## 4. Thành phần và quyền truy cập

| Thành phần | Được đọc | Được ghi | Có gọi GPT? | Vai trò |
|---|---|---|---:|---|
| `main.py` | Input, cấu hình | Output, trace, metadata, ZIP | Không | Bootstrap và chạy 50 case |
| `OlistRepository` | CSV Olist | Không | Không | Index và cung cấp dữ liệu nguồn |
| Coordinator Agent | Input và các handoff | Không trực tiếp | Không | Phân phối và tổng hợp |
| Customer Agent | Customer và history index | Không | Có | Identity và lịch sử khách hàng |
| Order & Product Agent | Order, item, product, seller | Không | Có | Entity và product context |
| Payment Agent | Payment rows và item rows | Không | Có | Đối soát thanh toán |
| Delivery Agent | Order timestamps và item limits | Không | Có | Phân tích giao hàng |
| Policy Agent | Handoff từ các agent trước | Không | Có | Policy decision và review |
| Verifier Agent | Output tạm và repository | Không | Không | Hard gate dữ liệu/schema |
| TraceWriter | Agent events | `trace.jsonl` | Không | Audit handoff |

API key chỉ được đọc từ `.env` thông qua `python-dotenv`. Key không được đưa vào
prompt, model input, trace, metadata hoặc output.

## 5. Data Repository và quan hệ khóa

Điểm bắt đầu của mọi case:

```text
input.customer_request.claimed_order_id -> orders.order_id
```

Các quan hệ tiếp theo:

```text
orders.customer_id       -> customers.customer_id
orders.order_id          -> order_items.order_id
orders.order_id          -> order_payments.order_id
order_items.product_id   -> products.product_id
order_items.seller_id    -> sellers.seller_id
customer_unique_id       -> các customer_id/order lịch sử
```

Repository không nạp mọi row item/payment/product/seller vào bộ nhớ. Nó giữ:

- tất cả ánh xạ cần để tìm lịch sử customer;
- full order row của 50 target order;
- item và payment chỉ thuộc 50 target order;
- product và seller chỉ được các target item tham chiếu.

Nếu `claimed_order_id`, `customer_id`, `product_id` hoặc `seller_id` cần thiết
không tồn tại, repository raise `DataIntegrityError` và pipeline dừng.

## 6. Prompt dùng chung cho các model-backed agent

Prompt nằm tại `ecommerce_agents/llm.py`. GPT-4o mini hỗ trợ Structured Outputs,
vì vậy mỗi API call dùng schema Pydantic thay vì yêu cầu model tự đóng JSON:

```python
response = client.responses.parse(
    model="gpt-4o-mini",
    instructions=instructions,
    input=model_input,
    text_format=ModelReviewPayload,
    temperature=0,
    max_output_tokens=200,
)
```

### 6.1 Instructions thật

Phần instructions được tạo động theo tên agent:

```text
You are {agent_name}, summarizing one deterministic Olist report that has
already been validated by code. The input review_protocol is authoritative:
copy required_status exactly. Do not recalculate, search for new
contradictions, or reinterpret valid business differences.
Domain rule: <agent-specific rule>. Use only supplied facts.
```

Mục đích của từng câu:

- `review_protocol`: model nhỏ copy kết quả precheck thay vì tự tính lại facts.
- `Do not recalculate`: tránh false concern khi tổng tiền bằng nhau hoặc variance
  âm/dương là kết quả hợp lệ.
- `agent-specific rule`: giải thích ngắn các trạng thái hợp lệ theo từng domain.
- `Use only supplied facts`: model không được tạo dữ liệu mới.
- `Structured Outputs`: API khóa enum, kiểu dữ liệu và các key bắt buộc.

### 6.2 Input thật

`input` của Responses API là JSON:

```json
{
  "task": "<task riêng của agent>",
  "review_protocol": {
    "deterministic_validation": "passed",
    "required_status": "accepted"
  },
  "verified_facts": {
    "<structured report do Python tạo>": "<value>"
  }
}
```

Model không nhận API key, toàn bộ 9 CSV hay output của 50 case. Nó chỉ nhận facts
của đúng agent và đúng case đang xử lý.

### 6.3 Output model mong đợi

```json
{
  "status": "accepted",
  "summary": "Payment khớp với tổng item và freight.",
  "observations": []
}
```

Adapter gắn thêm thông tin audit:

```json
{
  "model": "gpt-4o-mini",
  "request_id": "<OpenAI request ID>",
  "status": "accepted",
  "summary": "...",
  "observations": []
}
```

`ModelReviewPayload` khóa `status` vào `accepted|concern`, yêu cầu summary string
và observations array. Parser JSON thủ công chỉ còn là fallback nếu provider
không trả `output_parsed`; model response vẫn không được thay đổi số liệu nguồn.

## 7. Chi tiết từng agent

### 7.1 Coordinator Agent

File: `ecommerce_agents/coordinator.py`.

Coordinator không gọi GPT. Nó thực hiện:

1. Kiểm tra `policy_version == EC_POLICY_V2`.
2. Lấy `claimed_order_id` và investigation scope.
3. Giao việc lần lượt cho các specialist.
4. Nhận và trace từng handoff.
5. Chuyển toàn bộ báo cáo sang Policy Agent.
6. Assemble đúng output schema.
7. Gửi output tạm sang Verifier.
8. Chỉ trả kết quả khi Verifier pass.

Coordinator không tự truy vấn chi tiết customer/payment/delivery và không tự gọi
OpenAI. Việc tách này giúp nó chỉ chịu trách nhiệm orchestration.

Handoff bắt đầu:

```json
{
  "order_id": "<claimed_order_id>",
  "policy_version": "EC_POLICY_V2",
  "scope": {
    "include_customer_history": true,
    "include_product_context": true
  }
}
```

### 7.2 Customer Agent

File/class: `agents.py::CustomerAgent`.

Nhiệm vụ:

- lấy `customer_id` từ target order;
- tra `customer_unique_id`;
- tìm các `customer_id` khác có cùng `customer_unique_id`;
- tìm order lịch sử;
- loại target order khỏi `related_order_ids`.

Task gửi GPT:

```text
Review customer identity and order history.
```

Facts gửi GPT:

```json
{
  "customer_unique_id": "<id>",
  "related_order_ids": ["<other_order_id>"]
}
```

Handoff được Policy Agent dùng để thêm secondary issue `repeat_customer`.
History order không được thêm vào `affected_entities`.

### 7.3 Order & Product Agent

File/class: `agents.py::OrderProductAgent`.

Nhiệm vụ:

- lấy full order row;
- lấy tất cả item rows theo `order_id`;
- tạo item ID dạng `<order_id>:<order_item_id>`;
- giữ seller theo thứ tự xuất hiện đầu tiên;
- lấy product và `product_category_name`;
- phát hiện dữ kiện multi-item, multi-seller và multiple-category.

Task gửi GPT:

```text
Review order, item, seller and product facts.
```

Facts chính gửi GPT:

```json
{
  "order": {"order_id": "...", "order_status": "...", "...": "..."},
  "items": [{"order_item_id": "1", "seller_id": "...", "...": "..."}],
  "item_ids": ["<order_id>:1"],
  "seller_ids": ["<seller_id>"],
  "product_ids": ["<product_id>"],
  "category_names": ["<category>"]
}
```

Payment Agent và Delivery Agent sử dụng `items`; Policy Agent sử dụng order,
seller count và category count.

### 7.4 Payment Agent

File/class: `agents.py::PaymentAgent`.

Nhiệm vụ:

- lấy tất cả payment rows của order;
- tính item total, freight total và payment total;
- tính expected total và difference;
- kiểm tra sai số đối soát 0.10 BRL;
- giữ payment type theo thứ tự nguồn;
- tạo payment ID `<order_id>:<payment_sequential>`.

Công thức deterministic:

```text
item_total_brl     = sum(order_items.price)
freight_total_brl  = sum(order_items.freight_value)
expected_total_brl = item_total_brl + freight_total_brl
payment_total_brl  = sum(order_payments.payment_value)
difference_brl     = payment_total_brl - expected_total_brl
reconciled         = abs(difference_brl) <= 0.10
```

Task gửi GPT:

```text
Review payment reconciliation facts.
```

Facts gửi GPT gồm raw payment rows, các total, difference, reconciled,
payment types và payment IDs. GPT review kết quả nhưng không thực hiện phép cộng
được dùng cho output.

Với order không có item, `expected_total_brl`, `difference_brl` và `reconciled`
được đặt `null` trước khi gọi model.

### 7.5 Delivery Agent

File/class: `agents.py::DeliveryAgent`.

Nhiệm vụ:

- lấy delivered, estimated và carrier handoff timestamp;
- tính delivery variance;
- nhóm item theo seller;
- chọn `shipping_limit_date` sớm nhất của mỗi seller;
- tính handoff variance;
- xác định seller bàn giao muộn.

Công thức deterministic:

```text
delivery_variance_hours
  = delivered_customer_date - estimated_delivery_date

handoff_variance_hours
  = delivered_carrier_date - earliest_shipping_limit_date_of_seller
```

Task gửi GPT:

```text
Review delivery and seller handoff timing.
```

Facts gửi GPT:

```json
{
  "delivered_at": "...",
  "estimated_delivery_at": "...",
  "carrier_handoff_at": "...",
  "delivery_variance_hours": 87.39,
  "seller_handoff_analysis": [
    {
      "seller_id": "...",
      "shipping_limit_at": "...",
      "handoff_variance_hours": 1.04,
      "late_handoff": true
    }
  ],
  "late_handoff_seller_ids": ["..."],
  "late_delivery": true,
  "delivery_timing_complete": true,
  "handoff_timing_complete": true
}
```

`late_delivery` là fact tri-state trong handoff: `true`, `false` hoặc `null` khi
thiếu delivered/estimated timestamp. Policy chỉ áp dụng rule giao đúng hạn hoặc
split payment khi giá trị là `false`; một order giao trễ chỉ được quy trách nhiệm
seller/logistics khi `handoff_timing_complete = true`. Các cờ completeness là dữ
liệu audit nội bộ và không được thêm vào output schema.

### 7.6 Policy Agent

File/class: `agents.py::PolicyAgent`.

Policy Agent không đọc CSV trực tiếp. Nó nhận bốn handoff trước đó rồi áp dụng
primary issue theo đúng thứ tự ưu tiên:

1. `canceled_order_paid`.
2. `unavailable_order_paid`.
3. `late_delivery_seller`.
4. `late_delivery_logistics`.
5. `valid_split_payment`.
6. `unsupported_late_claim`.

Sau đó agent thêm secondary issues theo thứ tự:

1. `multi_item_order`.
2. `multi_seller_order`.
3. `split_payment`.
4. `repeat_customer`.
5. `multiple_categories`.

Policy Agent xác định cause code, responsible parties, refund và actions bằng
mapping cố định trong `config.py`.

Task gửi GPT:

```text
Review the EC_POLICY_V2 decision.
```

GPT nhận decision đã tính gồm primary, secondary, status, confidence, cause,
responsible parties, refund và actions. Vai trò GPT ở đây là review quyết định,
không tự thay đổi thứ tự policy.

Nếu không điều kiện primary nào khớp, Policy Agent raise `PolicyDecisionError`.

### 7.7 Verifier Agent

File/class: `verifier.py::VerifierAgent`.

Verifier không gọi GPT. Đây là lựa chọn có chủ ý để bước kiểm chứng độc lập với
model đã review các agent trước đó.

Verifier kiểm tra:

- top-level schema có đúng 11 field bắt buộc;
- confidence nằm trong `[0, 1]`;
- affected order đúng bằng claimed order;
- item, payment, seller và product IDs tồn tại trong quan hệ nguồn;
- tổng item, freight và payment khớp CSV;
- difference và reconciled đúng;
- null handling đúng với order không có item;
- evidence ID đúng format và có nguồn;
- array không vượt giới hạn;
- `case_status` nhất quán với refund.

Nếu một check sai, `VerificationError` làm pipeline dừng. Case đó không được công
bố là output hợp lệ.

## 8. Trình tự chạy một case

Một case tạo tám trace event và năm API request:

| Bước | Sender | Recipient | Event | Gọi GPT? |
|---:|---|---|---|---:|
| 1 | `main` | `coordinator_agent` | `case_received` | Không |
| 2 | `customer_agent` | `coordinator_agent` | `analysis_handoff` | Có |
| 3 | `order_product_agent` | `coordinator_agent` | `analysis_handoff` | Có |
| 4 | `payment_agent` | `coordinator_agent` | `analysis_handoff` | Có |
| 5 | `delivery_agent` | `coordinator_agent` | `analysis_handoff` | Có |
| 6 | `policy_agent` | `coordinator_agent` | `analysis_handoff` | Có |
| 7 | `verifier_agent` | `coordinator_agent` | `verification_passed` | Không |
| 8 | `coordinator_agent` | `main` | `case_completed` | Không |

Dependency giữa các bước:

```text
Customer report ───────────────────────────────┐
                                               │
Order/Product report ──┬──> Payment report ───┼──> Policy decision
                       └──> Delivery report ───┘          │
                                                         v
                                                  Assemble + Verify
```

Payment và Delivery không tự truy vấn lại order context; chúng nhận item/order
từ handoff của Order & Product Agent. Đây là dependency thực giữa các agent.

## 9. Handoff và trace minh chứng

Mỗi handoff được ghi JSONL với cấu trúc:

```json
{
  "sequence": 2,
  "timestamp_utc": "<UTC timestamp>",
  "case_id": "EC_001",
  "sender": "customer_agent",
  "recipient": "coordinator_agent",
  "event": "analysis_handoff",
  "payload": {
    "customer_unique_id": "...",
    "related_order_ids": ["..."],
    "model_review": {
      "model": "gpt-4o-mini",
      "request_id": "<OpenAI request ID>",
      "status": "accepted",
      "summary": "...",
      "observations": []
    }
  }
}
```

Sau lượt chạy API đầy đủ, bằng chứng multi-agent mong đợi là:

- `trace.jsonl` có 400 event;
- có 250 `analysis_handoff` chứa `model_review`;
- các model review ghi model `gpt-4o-mini`;
- các API response thành công có OpenAI request ID;
- `metadata.json.model.usage.request_count` bằng 250;
- token usage lớn hơn 0;
- mỗi case có đủ năm model-backed handoff và một verification event.

`trace.jsonl` luôn được mở ở chế độ `w`, vì đề bài yêu cầu chỉ giữ lượt chạy mới
nhất và không append trace cũ.

## 10. Online mode và offline mode

### Online mode dùng để nộp

```bash
python main.py
```

Điều kiện:

- đã cài `openai` và `python-dotenv`;
- `.env` có `OPENAI_API_KEY` hợp lệ;
- máy có network đến OpenAI API;
- tài khoản API có quyền truy cập `gpt-4o-mini`.

Mode này tạo model-backed trace thật và cập nhật token usage.

### Offline mode chỉ dùng phát triển

```bash
python main.py --offline
```

Offline adapter không gọi OpenAI. Nó gắn:

```json
{
  "model": "offline-development-mode",
  "request_id": null,
  "status": "skipped"
}
```

Offline mode giúp test join, calculation, policy, verifier và schema nhưng không
chứng minh GPT-4o mini đã chạy. Không dùng trace offline để nộp bài.

## 11. Cách tự kiểm tra multi-agent chạy thật

### 11.1 Chạy pipeline

```bash
python -m pip install -r requirements.txt
# Điền OPENAI_API_KEY trong .env
python -m unittest discover -s tests -v
python main.py
```

### 11.2 Kiểm tra trace và metadata

Chạy đoạn kiểm tra sau:

```python
import json
from pathlib import Path

records = [
    json.loads(line)
    for line in Path("trace.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]

reviews = [
    row["payload"]["model_review"]
    for row in records
    if row["event"] == "analysis_handoff"
    and "model_review" in row["payload"]
]

assert len(records) == 400
assert len(reviews) == 250
assert all(review["model"] == "gpt-4o-mini" for review in reviews)
assert all(review["status"] != "skipped" for review in reviews)
assert all(review["request_id"] for review in reviews)

metadata = json.loads(Path("metadata.json").read_text(encoding="utf-8"))
assert metadata["model"]["execution_mode"] == "openai-api"
assert metadata["model"]["usage"]["request_count"] == 250
assert metadata["model"]["usage"]["input_tokens"] > 0
assert metadata["latest_run"]["status"] == "completed_and_verified"

print("Verified: 250 real GPT-4o-mini agent calls")
```

Nếu assertion `status != skipped` thất bại thì trace được tạo bằng offline mode.
Nếu request count nhỏ hơn 250 thì lượt chạy API chưa hoàn thành toàn bộ 50 case.

## 12. Output assembly và artifact

Sau Policy Agent, Coordinator tạo đúng schema README. `model_review` không được
đưa vào output. Sau khi 50 case pass Verifier:

- `output/` có đúng `EC_001.json` đến `EC_050.json`;
- `trace.jsonl` chứa trace lượt chạy mới nhất;
- `metadata.json` chứa model/runtime/usage của lượt chạy;
- `output.zip` được tạo lại chỉ với 50 JSON, không có `.gitkeep` hoặc source code.

Việc tạo ZIP chỉ xảy ra sau khi danh sách output khớp danh sách input.

## 13. Failure handling

- Thiếu package: dừng và yêu cầu `pip install -r requirements.txt`.
- `.env` không có key: dừng trước khi xử lý case.
- Model/API timeout: OpenAI SDK retry tối đa hai lần rồi raise lỗi.
- Thiếu order/FK trong CSV: repository raise `DataIntegrityError`.
- Không primary policy nào khớp: raise `PolicyDecisionError`.
- Output sai dữ liệu/schema: raise `VerificationError`.
- Không đúng 50 input: dừng, trừ khi dùng `--allow-partial` để phát triển.

Nếu lỗi API xảy ra giữa lượt chạy, trace có thể chỉ chứa các event đã hoàn thành;
`metadata.json` và `output.zip` không được công bố như một lượt chạy mới hoàn tất.
Cần sửa lỗi rồi chạy lại `python main.py`; trace sẽ được ghi mới từ đầu.

## 14. Giới hạn và quyết định thiết kế

### 14.1 Parameter count của GPT-4o mini

OpenAI không công bố parameter count chính thức của `gpt-4o-mini`. Vì vậy
`metadata.json` ghi `not publicly disclosed`. Không nên tự khai model là dưới 10B
nếu không có nguồn chính thức. Nhóm cần xác nhận với giảng viên rằng model hosted
này được chấp nhận theo giới hạn của đề.

### 14.2 Model là reviewer, không phải calculator

Ưu điểm:

- tránh sai số tiền và timestamp;
- tránh hallucinated evidence;
- output tái lập;
- dễ kiểm toán CSV → calculation → policy → output;
- vẫn có prompt, API request và handoff thật ở từng specialist.

Giới hạn:

- model review hiện không tự sửa decision;
- các agent chưa chạy song song;
- không có agent memory xuyên case;
- không có tool-calling loop tự trị;
- tất cả agent dùng cùng một model;
- model concern chỉ được lưu để audit, chưa có escalation workflow riêng.

Thiết kế này ưu tiên correctness của bài chấm có schema và công thức cố định hơn
mức tự trị của agent.

## 15. Ánh xạ code

| File | Nội dung |
|---|---|
| `main.py` | CLI, model bootstrap, vòng lặp 50 case, artifact writer |
| `ecommerce_agents/config.py` | Model name, policy mapping, array limits |
| `ecommerce_agents/llm.py` | Prompt và OpenAI Responses API adapter |
| `ecommerce_agents/repository.py` | CSV indexes và data integrity |
| `ecommerce_agents/agents.py` | 5 model-backed specialist agents |
| `ecommerce_agents/coordinator.py` | Orchestration, handoff, output assembly |
| `ecommerce_agents/verifier.py` | Deterministic hard gate |
| `ecommerce_agents/tracing.py` | JSONL event trace |
| `tests/` | Unit tests cho policy, model handoff và calculation |

## 16. Trạng thái lượt chạy online mới nhất

Sau khi reset toàn bộ artifact và chạy lại `python main.py`, hệ thống đã hoàn tất:

- 50/50 case pass Verifier;
- 50 JSON output và 50 entry trong `output.zip`;
- 400 trace event, đúng 8 event cho mỗi case;
- 250 model-backed handoff gọi `gpt-4o-mini`;
- 250/250 review có OpenAI request ID và không có trạng thái `skipped`;
- 109.700 input tokens và 7.596 output tokens;
- 250 model review có status `accepted`;
- 0 model review có status `concern`;
- 28 unit test pass.

Structured Outputs loại bỏ JSON malformed. Review protocol ngăn GPT-4o mini tự
diễn giải giao sớm/trễ, canceled vẫn có item hoặc payment split thành mâu thuẫn.
Verifier deterministic vẫn là hard gate cuối và model review không được thay đổi
source values hoặc output.

`metadata.json` hiện ghi `execution_mode = openai-api`, request count 250 và
`latest_run.status = completed_and_verified`. Đây là lượt chạy có thể dùng để
chứng minh các specialist agent đã thực sự gọi GPT-4o mini.
