# Thiết kế: SP2 — Voice bám theo SRT (quy trình chuẩn)

Ngày: 2026-06-17

## Bối cảnh

Sub-project thứ 2 của "quy trình chuẩn" (xem
`docs/superpowers/specs/2026-06-17-srt-first-b1-design.md`). SP1 đã đưa SRT phụ đề
thành nguồn chính (`scripts/subtitle.json` + `scripts/subtitle.srt`, mỗi dòng
`{index,start,end,text,edited}`, timing ban đầu là ước tính theo WPS).

SP2 làm cho **giọng đọc bám theo từng dòng SRT**: voice được tạo theo từng dòng
trong `subtitle.json`, và **timing thật từ audio ghi đè timing ước tính**. Áp dụng
cho cả giọng thường (Kokoro) lẫn giọng clone (Magic Voice).

## Hiện trạng (đã khảo sát code)

- `generate_voice()` (`app/pipeline/visual_pipeline.py:210-240`) đọc
  `scripts/script_final.txt`, gọi `TextToVoiceRunner.submit_file()`, rồi rename các
  file tạm thành `voices/voice.wav` + `voice.segments.json` + `voice.srt`
  (+`.ttv.meta.json`), và xoá `assets/asset_manifest.json` để buộc rebuild cảnh.
- `TextToVoiceRunner` (`app/voice/text_to_voice_queue.py`):
  - **Kokoro**: băm text thành chunk (`split_text_into_progress_segments`,
    floor=80/ceil=2000) để hiện tiến độ; mỗi chunk gọi Kokoro server, **trả timing
    thật theo câu**; ghép nhiều chunk bằng offset + pause 0.25s; ghi
    `voice.segments.json` (engine `kokoro-server`) + `.srt` qua `write_srt_file`.
  - **Magic Voice clone** (`_submit_file_magicvoice`): băm ~480 ký tự
    (`voice_clone_max_chars`), mỗi chunk gọi `magicvoice_clone_cli.py` (subprocess)
    với `--ref <reference>`; **không có timing thật** → ước tính bằng
    `_estimated_segments_from_text(text, duration)` (chia theo trọng số số từ),
    `timing_source = "estimated_magicvoice"`. Ghép wav bằng `combine_wavs`.
  - Chọn engine: nếu `voice_clone_enabled` và có `_clone_reference_path(settings)` →
    Magic Voice; ngược lại Kokoro.
- `voice.segments.json`: dict có `segments: [{text,start,end,...}]`.
- `build_asset_manifest()` (`visual_pipeline.py:822-878`) đọc `voice.segments.json`
  qua `load_timing`/`normalize_voice_segments`, gộp câu (`merge_segments_into_sentences`),
  mỗi câu = 1 cảnh.
- `combine_wavs(paths, output)` (`text_to_voice_queue.py:158`) ghép wav, trả duration.
- Hàm thuần đã có để tái dùng: `build_srt_from_segments`, `write_srt_file`
  (`text_to_voice_cli.py`); SP1: `save_subtitle`, `load_subtitle`,
  `normalize_subtitle_segments`, `subtitle_paths` (`app/pipeline/subtitle_store.py`).

## Quyết định thiết kế

### 1. Nguồn đầu vào: subtitle.json

- Voice đọc các dòng trong `scripts/subtitle.json` (theo thứ tự `index`) làm **đơn vị
  TTS**. `script_final.txt` không còn điều khiển voice.
- Nếu `subtitle.json` không tồn tại hoặc rỗng → báo lỗi rõ ràng: "Hãy tạo & lưu phụ
  đề ở Bước 1 trước khi tạo giọng đọc." (Không giữ fallback băm-script: SP1 luôn ghi
  subtitle khi lưu.)

### 2. Tạo voice theo từng dòng (cả hai engine)

- Với mỗi dòng phụ đề (text): gọi TTS riêng **1 lần/dòng**:
  - Kokoro: 1 request/dòng (đổi từ băm-theo-chunk sang per-line — nhất quán + timing
    thật theo dòng). Quyết định đã chốt với người dùng.
  - Magic Voice: 1 lần clone/dòng (tổng quát hoá vòng lặp per-chunk hiện có).
- Đo **thời lượng audio thật** của từng dòng (từ `duration` Kokoro trả về, hoặc đo
  wav per-line bằng `_audio_duration_seconds`). Ghép các wav theo thứ tự bằng
  `combine_wavs`, hàm này **luôn chèn 0.25s** giữa các part (hằng số cứng trong
  `text_to_voice_cli.py:158`). Vì vậy khoảng lặng giữa dòng = **0.25s cho cả hai
  engine**, và timing lắp ráp phải dùng đúng 0.25s để khớp audio. (Lưu ý
  `magicvoice_sentence_pause` là pause nội bộ trong một lần clone, KHÔNG phải pause
  giữa các part đã ghép.)
- Tiến độ log "đang tạo đoạn {i}/{N}" với N = số dòng phụ đề → thanh tiến độ
  `/api/voice` (regex `đoạn i/N` đã có) chạy đúng cho cả hai engine, sửa luôn lỗi
  Kokoro cũ hiện "1/1".
- Dòng nào TTS lỗi → dừng job với thông báo kèm số thứ tự dòng.

### 3. Lắp ráp segments + timing thật (hàm thuần, test được)

- Tách hàm thuần `assemble_line_segments(lines, durations, pause=0.25) -> list[dict]`:
  nhận danh sách dòng (index/text/edited) + thời lượng thật từng dòng + pause (0.25),
  trả segments `{index, text, start, end, edited, timing_source: "measured"}` với
  start/end cộng dồn (mỗi dòng + pause, trừ pause sau dòng cuối). 1 dòng = 1 segment.
- Đây là nguồn cho cả `voice.segments.json` và phần ghi đè subtitle.

### 4. Ghi timing thật

Sau khi tạo xong, ghi:
- `voices/voice.wav` (audio ghép).
- `voices/voice.segments.json`: `segments` = kết quả `assemble_line_segments`
  (1 segment/dòng, timing thật, nhãn `engine` đúng), giữ các khoá meta như hiện tại.
- `voices/voice.srt` qua `write_srt_file`.
- **Ghi đè timing trong `scripts/subtitle.json`**: cập nhật `start`/`end` mỗi dòng
  bằng timing thật (giữ nguyên `text`; `edited` của text vẫn giữ), sinh lại
  `scripts/subtitle.srt` qua `save_subtitle`. Realize "timing thật ghi đè timing ước
  tính" của SP1.
- `build_asset_manifest` vẫn đọc `voice.segments.json` (không đổi) — giờ khớp 1-1 với
  dòng phụ đề, không cần Whisper.

### 5. Chọn engine & API

- Giữ nguyên cách chọn engine (`voice_clone_enabled` + reference). UI B2 không đổi
  cấu trúc chọn giọng.
- `/api/voice`: đọc `subtitle.json` thay vì băm `script`. Vẫn có thể đồng bộ
  `script_final.txt` để lưu vết, nhưng không dùng nó làm text TTS.

## Phạm vi thay đổi

- `app/voice/text_to_voice_queue.py`: thêm đường per-line cho cả hai engine (tạo audio
  1 dòng + đo duration), tách hàm thuần `assemble_line_segments`; ghép wav per-line.
- `app/pipeline/visual_pipeline.py` (`generate_voice`): đọc subtitle.json (qua
  `load_subtitle`), truyền danh sách dòng cho runner; sau khi tạo xong, ghi đè timing
  subtitle.json (qua `save_subtitle`).
- `app/pipeline/subtitle_store.py`: (nếu cần) hàm cập nhật timing giữ text/edited.
- `app/web/web_server.py` (`/api/voice`): bỏ phụ thuộc `script` làm nguồn TTS; báo lỗi
  khi thiếu subtitle.
- Không đổi `build_asset_manifest`, không đổi UI B2 cấu trúc.

## Đánh đổi

- Per-line cho Kokoro → nhiều request hơn (mỗi dòng 1 request) → chậm hơn với bài dài
  và prosody ở ranh giới dòng có thể hơi khác. Đổi lại: timing thật theo dòng cho cả
  hai engine + khớp 1-1 hoàn hảo với "1 dòng = 1 ảnh" ở SP3/SP4. Người dùng đã chấp
  nhận đánh đổi này.
- Ghi đè timing vào subtitle.json → nếu người dùng từng chỉnh tay timing 1 dòng, nó
  bị thay bằng timing thật. Đúng mô hình SP1 (timing thật thắng); text chỉnh tay vẫn
  được giữ và là cái được đọc.

## Tiêu chí hoàn thành

- Tạo voice từ subtitle nhiều dòng → `voice.segments.json` có số segment = số dòng
  phụ đề, timing tăng dần và là timing thật (không `estimated_magicvoice`).
- Sau khi tạo voice, `subtitle.json`/`subtitle.srt` được cập nhật bằng timing thật.
- Cả Kokoro và Magic Voice clone đều chạy per-line; log/tiến độ "đoạn i/N" với N>1.
- Thiếu `subtitle.json` → `/api/voice` báo lỗi yêu cầu lưu phụ đề ở B1.
- `build_asset_manifest` đọc được segments measured (1 segment/dòng) mà KHÔNG bị
  Whisper hay heuristic repair ghi đè timing thật.
- **Khớp 1-1 cảnh ↔ dòng phụ đề (deferred sang SP3):** SP2 tạo 1 segment voice/dòng,
  nhưng `merge_segments_into_sentences` trong `build_asset_manifest` vẫn gộp các
  segment không kết thúc bằng `.!?` thành một cảnh. Với phụ đề tách theo câu của SP1
  (kết thúc bằng `.!?`) thì 1-1 đạt; với dòng người dùng chỉnh tay không có dấu kết
  câu thì chưa. Đảm bảo 1-1 tuyệt đối thuộc SP3 (nơi thiết kế chính là 1 dòng = 1
  prompt = 1 cảnh) — SP2 không sửa logic gộp cảnh để tránh đụng phần SP3 sẽ làm lại.
- `assemble_line_segments` có unit test (timing cộng dồn đúng, pause đúng, không pause
  sau dòng cuối); ghi đè subtitle.json có test (giữ text/edited, đổi start/end).
- Không hồi quy đường voice-preview.
