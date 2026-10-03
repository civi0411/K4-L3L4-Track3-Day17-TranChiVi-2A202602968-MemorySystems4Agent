# Báo Cáo Phân Tích & Đánh Giá Hệ Thống Bộ Nhớ AI Agent (Day 17)

> **Thông tin học viên / sinh viên:**
> - **Họ và tên:** Trần Chí Vĩ
> - **MSSV:** 2A202602968
> - **Khóa học:** AI Engineer Training Program (Cohort 4) - Phase 2, Track 3, Day 17

## 1. Kết Quả Benchmark Thực Nghiệm

Hệ thống được kiểm thử tự động trên môi trường Conda (`k4-lab01`) với hai bộ dữ liệu chuẩn tiếng Việt:

### Bảng 1: Standard Benchmark (10 Hội Thoại Thường)
```
+----------+---------------------+---------------------------+------------------------+--------------------+-------------------------+---------------+
| Agent    |   Agent tokens only |   Prompt tokens processed | Cross-session recall   | Response quality   | Memory growth (bytes)   |   Compactions |
+==========+=====================+===========================+========================+====================+=========================+===============+
| Baseline |               2,207 |                    17,462 | 0.0%                   | 6.00 / 10          | 0 B                     |             0 |
+----------+---------------------+---------------------------+------------------------+--------------------+-------------------------+---------------+
| Advanced |               2,592 |                    28,764 | 100.0%                 | 10.00 / 10         | 269 B                   |             0 |
+----------+---------------------+---------------------------+------------------------+--------------------+-------------------------+---------------+
```

### Bảng 2: Long-Context Stress Benchmark (16 Lượt Siêu Dài)
```
+----------+---------------------+---------------------------+------------------------+--------------------+-------------------------+---------------+
| Agent    |   Agent tokens only |   Prompt tokens processed | Cross-session recall   | Response quality   | Memory growth (bytes)   |   Compactions |
+==========+=====================+===========================+========================+====================+=========================+===============+
| Baseline |                 405 |                    25,971 | 0.0%                   | 6.00 / 10          | 0 B                     |             0 |
+----------+---------------------+---------------------------+------------------------+--------------------+-------------------------+---------------+
| Advanced |                 725 |                    11,269 | 100.0%                 | 10.00 / 10         | 217 B                   |             6 |
+----------+---------------------+---------------------------+------------------------+--------------------+-------------------------+---------------+
```

---

## 2. Phân Tích Chuyên Sâu Các Trade-Off

### 2.1. Vì sao Advanced Agent có Recall vượt trội (100% vs 0%)?
- **Baseline Agent** chỉ duy trì bộ nhớ cục bộ trong cùng một `thread_id`. Khi chuyển sang câu hỏi kiểm tra ở một thread mới, toàn bộ ngữ cảnh trước đó bị xoá hoàn toàn, dẫn đến `Cross-session recall` đạt **0.0%**.
- **Advanced Agent** tích hợp tầng lưu trữ bền vững **`User.md` (Persistent Memory Store)**. Mọi thông tin cốt lõi (Tên, Nơi ở, Nghề nghiệp, Món ăn, Thú cưng, Gu trả lời) được trích xuất và đồng bộ vào file markdown. Khi sang thread mới, hệ thống tự động nạp `User.md` vào System Prompt, cho phép nhớ lại chính xác 100% các dữ kiện cá nhân qua nhiều phiên làm việc độc lập.

### 2.2. Vì sao Advanced Agent lại tốn nhiều token hơn ở hội thoại ngắn?
- Ở các phiên ngắn (Standard Benchmark), `Advanced Agent` tiêu tốn **28,764 prompt tokens** so với **17,462** của Baseline.
- **Nguyên nhân**: Ở mỗi lượt chat, Advanced Agent luôn phải "gánh" thêm chi phí cố định (overhead) gồm cấu trúc mẫu System Prompt và nội dung file `User.md` (~30-50 tokens/lượt). Với các câu nói ngắn ("Chào bạn", "Hôm nay trời đẹp"), chi phí ngữ cảnh nền này chiếm tỷ trọng lớn hơn bản thân tin nhắn.

### 2.3. Sự cứu rỗi của Compact Memory ở hội thoại rất dài (Stress Benchmark)
- Trong Stress Benchmark (16 lượt chứa các đoạn tin tức và nhận định hệ thống rất dài):
  - **Baseline Agent** phải kéo theo toàn bộ lịch sử thô từ lượt 1 đến lượt 16. Chi phí prompt tích lũy theo cấp số cộng $O(N^2)$, làm bùng nổ lên tới **25,971 tokens**.
  - **Advanced Agent** kích hoạt **Compact Memory 6 lần**, nén các lượt cũ thành các gạch đầu dòng tóm tắt súc tích và chỉ giữ lại 2 lượt gần nhất nguyên vẹn.
  - **Kết quả**: Chi phí prompt context được giữ ở mức trần ổn định, giảm xuống chỉ còn **11,269 tokens** (**tiết kiệm hơn 56.6% tổng lượng prompt token**).

### 2.4. Phân tích Tốc Độ Tăng Trưởng Memory & Rủi Ro Tiềm Ẩn
- File `User.md` chỉ tăng trưởng **~217 - 269 bytes** cho toàn bộ quá trình nhờ cơ chế **Key-Value Fact Representation** (thay vì lưu text thô dạng nhật ký).
- **Rủi ro nếu không có cơ chế quản lý**:
  1. *Phình to theo thời gian*: Nếu không giới hạn số lượng fact, `User.md` sẽ dần trở nên quá nặng, làm tăng latency và chi phí nền cho mọi lượt chat.
  2. *Ảo giác do nhiễu (Noise Pollution)*: User nói đùa ("tôi là product manager") hoặc nhắc địa điểm tạm thời ("ra Hà Nội họp 2 ngày") nếu bị lưu thành fact vĩnh viễn sẽ làm sai lệch mọi câu trả lời sau đó.

---

## 3. Các Tính Năng Bonus Đã Triển Khai (Mục Tiêu Điểm Tuyệt Đối 90-100)

1. **Conflict Handling (Xử lý xung đột thông tin)**:
   - Tự động nhận diện phủ định ("không còn ở Đà Nẵng nữa") và cập nhật sang địa điểm mới ("Huế"). Hàm `upsert_fact` ghi đè trực tiếp fact cũ thay vì lưu trùng lặp.
2. **Confidence Threshold & Noise Filtering (Ngưỡng tin cậy & Lọc nhiễu)**:
   - Phân biệt giữa hành động tạm thời ("ra Hà Nội họp") và nơi ở thực tế.
   - Bỏ qua các câu đùa ("đùa chuyển sang làm product manager") để bảo vệ tính chính xác của trường nghề nghiệp.
3. **Structured Entity Extraction**:
   - Tách bạch rõ các thực thể: `Name`, `Location`, `Profession`, `Favorite Drink`, `Favorite Food`, `Pet`, `Response Style`, `Interests`.

### 3.1. Đánh Giá Hiệu Quả & Rủi Ro Của Các Bonus (Tiêu Chí 100 Điểm)
**Các bonus trên giải quyết vấn đề gì?**
- Cơ chế *Ngưỡng tin cậy (Confidence threshold)* và *Lọc nhiễu (Noise filtering)* bảo vệ tính toàn vẹn của dữ liệu, ngăn chặn thông tin rác (vd: "đi công tác Hà Nội", "nói đùa làm PM") xâm nhập vào bộ nhớ.
- *Xử lý xung đột (Conflict handling)* chấm dứt tình trạng "lưỡng lự nhận thức" của Agent khi giữ cả dữ liệu cũ và mới (vd: nhớ cả Huế và Đà Nẵng).

**Cải thiện Recall và Cost như thế nào?**
- Bằng cách chỉ lưu các Fact đã được làm sạch và nén lại thành Key-Value, hệ thống tối ưu hóa hoàn toàn dung lượng của `User.md`.
- Độ chính xác của **Cross-session recall tăng lên tuyệt đối (100%)** vì LLM không còn bị bối rối giữa thông tin nhiễu, thông tin cũ và thông tin mới.

**Rủi ro sinh ra cho hệ thống:**
1. **False Negatives (Bỏ sót thông tin):** Việc dùng logic lọc nhiễu nghiêm ngặt (Strict heuristic/regex) có thể vô tình chặn đứng một fact thực sự quan trọng nếu người dùng diễn đạt bằng cấu trúc câu quá phức tạp hoặc chưa được thiết kế trước.
2. **Chi phí bảo trì mở rộng:** Hardcode các rule cho Entity Extraction (chia key Name, Location...) sẽ rất khó vươn ra (scale) khi muốn hệ thống Agent tự học thêm hàng trăm sở thích mới mà không cần developer vào thêm code logic.
