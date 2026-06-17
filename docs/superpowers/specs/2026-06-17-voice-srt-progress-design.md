# Thiết kế: Lưu SRT khi tạo voice + hiển thị tiến độ "đoạn i/N"

Ngày: 2026-06-17

## Bối cảnh

Luồng người dùng: dán kịch bản có sẵn → **Lưu** → **chọn giọng đọc** → tạo voice.
Khi tạo voice, kịch bản được "băm thành các đoạn" để chạy TTS.

Hai yêu cầu:

1. **Lưu SRT** khi tạo voice, để **bước 3 (tạo ảnh)** dùng lại mà **không nghe lại
   voice** và **không sinh mới SRT**.
2. **Hiển thị tiến độ "đoạn i/N"** để người dùng nắm được tiến độ (tham khảo cách
   Magic Voice đang làm).

## Hiện trạng (đã khảo sát code)

- `generate_voice()` (`app/pipeline/visual_pipeline.py`) gọi `TextToVoiceRunner`
  và ghi ra `voices/voice.wav` + `voices/voice.segments.json`.
- Đường **Kokoro** (`TextToVoiceRunner.submit_file`,
  `app/voice/text_to_voice_queue.py`) băm kịch bản bằng
  `split_text_for_text_to_voice(text, max_chars)` với `max_chars ≈ 10000`. Một
  kịch bản thường = **1 đoạn** → log "đang tạo đoạn 1/1" → tiến độ không có ý nghĩa.
  Trong 1 đoạn chỉ có log "sampling X%".
- Đường **Magic Voice** (`_submit_file_magicvoice`) băm nhỏ (~480 ký tự) → nhiều
  đoạn → log "đang clone đoạn i/N" → tiến độ thật. Sau khi ghép, ghi
  `segments.json` theo **từng câu** qua `_estimated_segments_from_text`.
- `web_server.py` (`/api/voice`) đã có `voice_log()` parse regex
  `đoạn\s+(\d+)\s*/\s*(\d+)` → cập nhật `job.total_units`, `job.completed_units`,
  `job.progress`, `job.current_label`. Frontend đã poll `/api/jobs/{id}` và hiển
  thị `current_label` + thanh tiến độ.
- Bước 3 (`build_asset_manifest`) đã đọc `voice.segments.json` trực tiếp và
  **không chạy Whisper** mặc định (`whisper_timing_enabled` mặc định False), mỗi
  câu SRT = 1 cảnh. Tức "không nghe lại" về cơ bản đã đạt.
- **Chưa có** file `.srt` thật được ghi ra khi tạo voice.

## Quyết định

Mô phỏng đúng cơ chế Magic Voice cho đường Kokoro/luồng thường.

### 1. Băm cụm câu để có tiến độ thật (1/N)

- Đường Kokoro băm theo **cụm câu** với ngưỡng ký tự nhỏ (mặc định ~600, cấu hình
  qua setting riêng, không động vào `text_to_voice_max_chars` 10000 mặc định để
  tránh đổi hành vi chỗ khác).
- Vòng lặp Kokoro đã log `"đang tạo đoạn {i}/{N}"` và `web_server` đã parse → chỉ
  cần băm nhỏ là tiến độ "đoạn i/N" tự chạy. **Không cần đổi frontend.**

### 2. Lưu SRT thật cạnh voice.wav

- Kokoro server trả timing **theo từng câu** trong mỗi đoạn → gộp lại thành SRT
  chuẩn theo câu.
- Sau khi ghép voice, ghi `voices/voice.srt` (số thứ tự + timestamp + câu) bằng
  hàm `_write_srt` đã có trong `visual_pipeline.py` (hoặc hàm tương đương trong
  voice module nếu tránh import vòng).
- Vẫn giữ `voice.segments.json` là nguồn chính cho bước 3; `voice.srt` là bản SRT
  thật để xem/sửa và để CapCut dùng.

### 3. Bước 3 tái dùng, không nghe lại

- `build_asset_manifest` ưu tiên dùng timing/SRT có sẵn (`segments.json`, và nếu
  có `voice.srt`), **không chạy Whisper** trừ khi bật thủ công. Hành vi này phần
  lớn đã đúng; chỉ cần đảm bảo và không hồi quy.

## Phạm vi thay đổi

- `app/voice/text_to_voice_queue.py`: băm cụm câu cho đường Kokoro; ghi `voice.srt`
  sau khi tạo voice (cả Kokoro và, nếu hợp lý, Magic Voice cho nhất quán).
- `app/pipeline/visual_pipeline.py`: đảm bảo bước 3 dùng SRT/segments có sẵn,
  không nghe lại.
- Frontend: không bắt buộc đổi cho tiến độ. (Tùy chọn) thêm dòng trạng thái
  "Đã lưu SRT" ở bước 2.

## Đánh đổi

- Băm cụm câu nhỏ hơn → nhiều request Kokoro hơn → chậm hơn một chút và có thể hơi
  gợn ở ranh giới đoạn. Đổi lại: tiến độ thật + SRT chuẩn. Đây chính là cách Magic
  Voice đang vận hành.

## Tiêu chí hoàn thành

- Tạo voice một kịch bản nhiều câu → log/thanh tiến độ hiện "đoạn i/N" với N > 1.
- Sau khi tạo voice, tồn tại `voices/voice.srt` đúng định dạng SRT, timestamp tăng
  dần, khớp số câu.
- Vào bước 3 → tạo cảnh từ SRT/segments có sẵn, **không** có log "nghe lại"/Whisper.
- Không hồi quy đường Magic Voice và đường preview voice.
