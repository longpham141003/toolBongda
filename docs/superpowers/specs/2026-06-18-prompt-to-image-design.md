# Thiết kế: SP4 — Prompt → keyword → ảnh stock

Ngày: 2026-06-18

## Bối cảnh

Sub-project thứ 4 (cuối) của "quy trình chuẩn" (xem
`docs/superpowers/specs/2026-06-17-srt-first-b1-design.md`). SP1 đưa SRT thành nguồn
chính; SP2 voice theo dòng + timing thật; SP3 sinh **prompt đời thật** cho từng cảnh
(field `prompt` mỗi asset, 1 cảnh/dòng).

SP4 biến mỗi `prompt` thành **truy vấn tìm kiếm ngắn** rồi tìm/tải **1 ảnh stock** phù
hợp (Google Images crawler sẵn có). Hoàn tất chuỗi: 1 dòng = 1 prompt = 1 keyword =
1 ảnh. Sau SP4, quy trình chuẩn chạy end-to-end.

## Quyết định người dùng đã chốt

- Rút keyword: **AI tóm tắt prompt → truy vấn ngắn, fallback heuristic** khi thiếu
  key/AI lỗi.
- **Một nút**: tạo keyword + tìm ảnh luôn (vẫn sửa keyword/tìm lại từng ảnh sau).
- Ghi keyword vào các field search đang dùng: `keyword` + `ai_search_keyword` +
  `google_queries`.
- Nút "Tạo keyword & tìm ảnh" ở màn Prompt (step2b), xong nhảy sang review ảnh
  (step3b).

## Hiện trạng (đã khảo sát code)

- `search_and_download_asset(project, item, ...)` (`visual_pipeline.py` ~4141) tìm ảnh
  dùng `google_queries`/`keyword`/`sportsdb_queries` qua Google Images (Playwright
  crawler) + TheSportsDB; set `local_path`/`status`/`source_page`. KHÔNG cần API key
  nguồn ảnh.
- `keyword_for_text(text)` (~705): rút proper-noun + ascii words, ≤8 từ, fallback
  "cinematic documentary scene".
- `optimize_asset_keywords_with_ai()` (~2487): hiện rút keyword AI từ `sentence_text`
  + định tuyến bóng đá → set `search_keyword`/`google_queries`/`fallback_keywords`/
  `sportsdb_queries` qua `_apply_keyword_ai_row`. (Luồng chuẩn SP4 sẽ KHÔNG dùng hàm
  này nữa — keyword giờ từ `prompt`.)
- `_search_assets_parallel(project, items, settings, job, ...)` (`web_server.py` ~861):
  chạy song song (`image_search_parallel_jobs`, mặc định 1), filter `status != approved`.
- Endpoints: `/api/search` (job "B3 Tim anh"), `/api/assets/{id}/retry`,
  `/api/assets/{id}/keyword` (set `keyword` + `ai_search_keyword`).
- SP3: `prompt_studio.py` (`_ai_call`, `_load_manifest`/`_save_manifest`,
  `coerce`/`parse` helpers), asset có field `prompt`.

## Quyết định thiết kế

### 1. Rút keyword từ prompt (AI + fallback)

- Hàm `keyword_from_prompt(prompt: str, settings: dict, fallback_text: str = "") -> dict`
  trong `prompt_studio.py`, trả `{"search_keyword": str, "google_queries": list[str]}`:
  - Gọi `_ai_call` với `SYS_KEYWORD` (mới): biến mô tả ảnh đời thật thành **truy vấn
    Google Images 4-8 từ, thực tế, bỏ tên nhân vật phịa**, trả JSON
    `{"search_keyword": "...", "google_queries": ["...", "..."]}` (2-3 biến thể).
    Parse bằng `parse_json_block`.
  - **Fallback** (AI rỗng/lỗi/JSON hỏng/thiếu key): `kw = keyword_for_text(prompt or
    fallback_text)`; trả `{"search_keyword": kw, "google_queries": [kw]}`.
  - Luôn đảm bảo `search_keyword` không rỗng và `google_queries` có ít nhất 1 phần tử
    (chèn `search_keyword` nếu rỗng).

### 2. Gán keyword vào manifest

- Hàm `apply_prompt_keywords(project: Path, settings: dict, log=None) -> list[dict]`:
  - Load manifest (`_load_manifest`). Raise nếu rỗng ("Chưa có phân cảnh...").
  - Mỗi asset: `text = item.get("prompt") or item.get("sentence_text") or ""`;
    `kw = keyword_from_prompt(text, settings, fallback_text=item.get("sentence_text"))`;
    set `item["keyword"] = kw["search_keyword"]`,
    `item["ai_search_keyword"] = kw["search_keyword"]`,
    `item["google_queries"] = kw["google_queries"]`.
  - Lưu manifest (`_save_manifest`), trả về.
  - Đây **thay** `optimize_asset_keywords_with_ai` trong luồng chuẩn (bỏ định tuyến
    bóng đá/SportsDB cho luồng này; `sportsdb_queries` để rỗng).

### 3. Một nút: keyword + tìm ảnh

- Endpoint `POST /api/prompt-search` (job "B3 Tao keyword va tim anh"):
  - `apply_prompt_keywords(project, settings, log=job.log)`.
  - `_search_assets_parallel(project, items, settings, job)` (tái dùng nguyên).
  - Trả `{"project": _project_payload(project)}`.
- Search crawler không đổi (đọc `google_queries`/`keyword` như cũ), 1 ảnh/cảnh.

### 4. UI

- `PromptScreen` (step2b): sau khi có prompt (asset có `prompt`), hiện nút **"Tạo
  keyword & tìm ảnh"** gọi `startJob("/api/prompt-search", ...)`. Khi job xong (tên
  "B3 Tao keyword va tim anh"), điều hướng sang `step3b` (review ảnh) như luồng search
  cũ.
- Giữ nguyên: sửa keyword 1 cảnh (`/api/assets/{id}/keyword`), tìm lại 1 ảnh
  (`/api/assets/{id}/retry`), upload thủ công ở step3b.

### 5. AI provider

- Tái dùng `_ai_call` (đã có `max_tokens`; keyword ngắn nên budget nhỏ là đủ — dùng
  mặc định hoặc truyền nhỏ). Tôn trọng pause-quota. Fallback heuristic khi không có AI.

## Phạm vi thay đổi

- `app/pipeline/prompt_studio.py`: `SYS_KEYWORD`, `keyword_from_prompt`,
  `apply_prompt_keywords` (import `keyword_for_text` từ visual_pipeline qua adapter lazy
  để tránh vòng).
- `app/web/web_server.py`: endpoint `POST /api/prompt-search`.
- `webui/src/App.jsx`: nút "Tạo keyword & tìm ảnh" trong `PromptScreen` + điều hướng
  job-done sang step3b.
- Không đổi crawler/search hiện có, không đổi step3b review.

## Đánh đổi

- Prompt đời thật → keyword stock vẫn lossy (ảnh stock khó khớp khung hình cụ thể);
  AI tóm tắt giúp query thực tế hơn heuristic. Thiết kế mở để sau chuyển sinh ảnh AI.
- Bỏ định tuyến SportsDB cho luồng chuẩn → nội dung bóng đá mất tối ưu riêng (đã chấp
  nhận khi quyết "thay thế luồng cũ" ở SP1).

## Tiêu chí hoàn thành

- `keyword_from_prompt`: AI trả query ngắn → dùng query đó; AI rỗng/lỗi → fallback
  `keyword_for_text`; luôn có `search_keyword` + `google_queries` không rỗng. Có test
  (mock AI thành công + nhánh fallback).
- `apply_prompt_keywords`: mỗi asset có `prompt` → `keyword`/`ai_search_keyword`/
  `google_queries` được set từ prompt; lưu manifest. Có test (mock).
- `/api/prompt-search`: chạy apply + search; trả project. (Search crawler mock trong
  test wiring; không gọi mạng thật.)
- UI: nút "Tạo keyword & tìm ảnh" → job → sang step3b; ảnh tải về hiển thị review.
- Không hồi quy `/api/search`, `/api/assets/{id}/retry|keyword`, step3b.
