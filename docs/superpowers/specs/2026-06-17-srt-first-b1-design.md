# Thiết kế: SP1 — SRT-first ở Bước 1 (quy trình chuẩn)

Ngày: 2026-06-17

## Bối cảnh tổng thể (quy trình chuẩn)

Người dùng muốn một **quy trình chuẩn** cho trường hợp đã có kịch bản sẵn. Quy trình
mới **thay thế** luồng hiện tại (bỏ logic gom cảnh + định tuyến bóng đá/SportsDB;
giữ lại hạ tầng search/download/export ở phần sau):

| Bước | Nội dung | Nguồn logic |
|---|---|---|
| **B1** | Dán kịch bản → tự tách SRT (timing ước tính theo WPS), **sửa được từng dòng**; sau lần tách đầu **SRT là nguồn chính** → Lưu & chọn giọng | `/api/script/srt-preview` (mở rộng) |
| **B2** | Chọn giọng clone → logic **Magic Voice**; voice tạo **theo từng dòng SRT**, timing thật ghi đè timing ước tính | `magicvoice_clone_cli` + `text_to_voice_queue` |
| **B3** | Mỗi dòng SRT → 1 prompt điện ảnh, **port đầy đủ 2 pha Auto Prompt** (phân tích nhân vật + scene map + chọn style + prompt khoá-cứng nhân vật + hậu xử lý) | Port từ app Electron `Auto Prompt` |
| **B4** | Mỗi prompt → 1 keyword → tìm **1 ảnh stock** (Google Images/SportsDB) | `keyword_for_text` (điều chỉnh) + search hiện có |
| Sau đó | Giữ nguyên (review ảnh → export CapCut) | — |

Vì phạm vi lớn, dự án được chia thành **4 sub-project** (mỗi cái có spec → plan →
implement riêng), theo thứ tự phụ thuộc:

1. **SP1 — SRT-first ở B1** *(spec này)*. Nền tảng cho mọi thứ sau.
2. **SP2 — Voice bám theo SRT** (phụ thuộc SP1).
3. **SP3 — Port Auto Prompt 2 pha** (phụ thuộc SP1).
4. **SP4 — Prompt → keyword → ảnh stock** (phụ thuộc SP3).

### Cảnh báo thiết kế (ghi lại để quyết sau)

Prompt của Auto Prompt vốn để **sinh ảnh AI** (nhân vật phịa tên + mô tả ngoại hình
khoá cứng, rất chi tiết), trong khi B4 lại **tìm ảnh stock**. Cầu nối "prompt điện
ảnh → keyword stock" sẽ mất phần lớn chi tiết → ảnh stock khó khớp khung hình/nhân
vật cụ thể. Người dùng đã chọn stock + "giữ nguyên phần sau", nên B3/B4 cần được
thiết kế **mở để dễ chuyển sang sinh ảnh AI** về sau.

---

## SP1 — Phạm vi spec này

Đưa SRT phụ đề lên thành **sản phẩm chính của Bước 1**: tự tách từ kịch bản, sửa
được từng dòng, và sau khi tách trở thành **nguồn chính** (source of truth) cho voice
(B2) và prompt (B3).

## Hiện trạng (đã khảo sát code)

- `B1` hiện: dán kịch bản → Lưu → tạo project, ghi `scripts/script_final.txt`
  (`createProject`/`persistScript` trong `webui/src/App.jsx`;
  `POST /api/projects/script` trong `app/web/web_server.py`).
- Đã có `POST /api/script/srt-preview` (`web_server.py`) ước tính SRT từ kịch bản:
  tách câu, tính thời lượng theo WPS (vi≈2.3, en≈2.6 từ/giây), trả `segments`, `srt`,
  `duration`, `word_count`. **Chỉ ước tính, không ghi file.**
- Hiện **chưa có** artifact SRT chuẩn ở B1. SRT thật (`voices/voice.srt`) chỉ sinh
  ra **sau** khi tạo voice, từ timing TTS.
- `stepStates` trong `App.jsx` đã phân biệt `done`/`stale`/`todo` dựa trên
  `project.has_voice` vs `project.voice_exists` → tái dùng cho cảnh báo "cần làm lại".

## Quyết định thiết kế

### 1. Mô hình dữ liệu & nguồn chính

- Artifact phụ đề chuẩn cho mỗi video:
  - `scripts/subtitle.json` — danh sách dòng có cấu trúc (nguồn chính để chỉnh sửa).
  - `scripts/subtitle.srt` — bản SRT xuất ra để xem / CapCut dùng.
- Cấu trúc mỗi dòng trong `subtitle.json`:
  ```json
  { "index": 1, "start": 0.0, "end": 2.4, "text": "Câu thoại thứ nhất", "edited": false }
  ```
  - `start`/`end`: giây (float). `edited`: true nếu người dùng đã chỉnh tay dòng đó.
- **Quy tắc nguồn chính:**
  - *Trước lần tách/lưu đầu tiên*: ô kịch bản là nơi nhập; gõ → SRT preview tự sinh
    lại (debounce ~500ms). Đúng "sửa kịch bản, SRT update theo".
  - *Sau khi tách/lưu*: `subtitle.json` là nguồn chính. Sửa trực tiếp từng dòng SRT
    (text + timecode). Ô kịch bản vẫn hiển thị kèm nút **"Tách lại (ghi đè)"** —
    bấm sẽ tách lại từ kịch bản và **cảnh báo ghi đè chỉnh tay**.
  - Voice (B2) và prompt (B3) đọc từ `subtitle.json`, **không** đọc `script_final.txt`.

### 2. Thuật toán tách

- Tái dùng & mở rộng logic của `/api/script/srt-preview`:
  - Tách kịch bản theo câu (dấu `.`/`!`/`?` + xuống dòng).
  - Ước tính thời lượng mỗi dòng theo WPS (vi≈2.3, en≈2.6), cộng dồn timestamp.
  - Mỗi câu = 1 dòng SRT (khớp "1 dòng SRT = 1 prompt = 1 ảnh" ở B3/B4).
- Có chốt độ dài: dòng quá ngắn gộp vào dòng kế; dòng quá dài có thể tách theo dấu
  phẩy/cụm (ngưỡng cấu hình, mặc định hợp lý) để tránh phụ đề lệch.

### 3. API

- `POST /api/script/srt-preview` (mở rộng nếu cần): nhận `script` + `language` +
  `speed` → trả `segments[]` (index/start/end/text). Dùng cho live-preview,
  **không ghi file**.
- `POST /api/projects/subtitle` (mới): nhận `segments[]` đã chỉnh → ghi
  `subtitle.json` + `subtitle.srt` (canonical), trả project đã cập nhật. Việc ghi
  này đánh dấu B2+ **stale** (giống khi đổi kịch bản).
- `/api/state` / `/api/projects/open`: project trả thêm `has_subtitle` (và segments
  khi mở video) để frontend nạp lại trình sửa SRT.

### 4. Giao diện B1

- Màn B1 chia 2 vùng: **ô kịch bản** (nhập/dán) + **trình sửa SRT** (danh sách dòng).
- Trình sửa SRT: mỗi dòng có timecode (start/end) + text sửa được; hỗ trợ
  thêm/xoá/gộp/tách dòng.
- Gõ/sửa kịch bản (trước khi lưu) → preview SRT cập nhật (debounce).
- Nút **"Lưu & chọn giọng"**: ghi canonical (`subtitle.json`/`.srt`) rồi sang B2.
- Nút **"Tách lại (ghi đè)"**: tách lại từ kịch bản, cảnh báo mất chỉnh tay.
- Nếu đã có voice mà sửa SRT → hiện cảnh báo "cần tạo lại giọng đọc" (tái dùng
  `stepStates` stale).

## Phạm vi thay đổi

- `app/web/web_server.py`: mở rộng `srt-preview`; thêm `POST /api/projects/subtitle`;
  trả `has_subtitle`/segments trong state/open.
- `app/pipeline/visual_pipeline.py` (hoặc module phụ đề mới): hàm tách câu → segments,
  ghi `subtitle.json` + `subtitle.srt`, nạp lại. Tái dùng `_write_srt`/`_srt_time`.
- `webui/src/App.jsx` + component mới: trình sửa SRT ở B1, live-preview, lưu canonical.
- Không động vào logic voice/prompt trong SP1 (chỉ đảm bảo chúng *sẽ* đọc từ
  `subtitle.json` ở SP2/SP3).

## Đánh đổi

- Thêm artifact phụ đề (`subtitle.json`/`.srt`) song song `script_final.txt` → một
  nguồn dữ liệu mới phải giữ đồng bộ. Đổi lại: SRT thành nguồn chính rõ ràng, voice
  và prompt bám đúng phụ đề người dùng đã chỉnh.
- Live-preview debounce khi gõ → vài lần tách thừa. Chấp nhận được (chỉ tính toán,
  không ghi file).

## Tiêu chí hoàn thành

- Gõ kịch bản nhiều câu → thấy SRT preview tách dòng + timing ước tính, cập nhật khi sửa.
- Sửa 1 dòng SRT rồi Lưu → `scripts/subtitle.json` và `scripts/subtitle.srt` tồn tại,
  đúng định dạng SRT (timestamp tăng dần, khớp số dòng), **giữ chỉnh tay**.
- Mở lại video → SRT canonical được nạp lại đúng vào trình sửa.
- Sửa SRT khi đã có voice → B2 chuyển trạng thái "cần làm lại" (stale).
- "Tách lại (ghi đè)" cảnh báo trước khi xoá chỉnh tay.
