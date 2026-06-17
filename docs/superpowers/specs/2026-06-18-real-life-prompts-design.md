# Thiết kế: SP3 — Prompt đời thật theo từng câu (port Auto Prompt 2 pha)

Ngày: 2026-06-18

## Bối cảnh

Sub-project thứ 3 của "quy trình chuẩn" (xem
`docs/superpowers/specs/2026-06-17-srt-first-b1-design.md`). SP1 đưa SRT thành nguồn
chính (`scripts/subtitle.json`); SP2 tạo voice theo từng dòng + ghi timing thật.

SP3 sinh **prompt cho từng dòng phụ đề**, port **cấu trúc 2 pha** của app Electron
`Auto Prompt` (gốc dự án) NHƯNG đổi đầu ra sang **ảnh chụp đời thật / thực tế** (để
khớp ảnh stock ở SP4), KHÔNG phải prompt điện ảnh ("film still/35mm/HDR/dramatic")
như bản gốc. Mỗi dòng SRT = 1 cảnh = 1 prompt (đồng thời trả nợ I1 của SP2).

## Quyết định người dùng đã chốt

- 1 dòng SRT = 1 prompt = 1 cảnh (= 1 ảnh ở SP4).
- Port đầy đủ 2 pha: Pha 1 phân tích bối cảnh + **nhân vật (sửa được đầy đủ)**; Pha 2
  prompt từng dòng có "khoá cứng" mô tả nhân vật.
- **Ảnh chụp thực tế, bỏ style nghệ thuật** (không anime/ghibli/pixar/oil…; không
  dropdown style).
- Chỉ chế độ ảnh (bỏ chế độ video 8s của Auto Prompt).
- Prompt bằng tiếng Anh (như Auto Prompt và `keyword_for_text` hiện tại).
- Luồng chuẩn THAY logic cũ `group_scenes_with_ai` + `optimize_asset_keywords_with_ai`.

## Hiện trạng (đã khảo sát code)

- AI helper tái dùng được trong `app/pipeline/visual_pipeline.py`:
  `_pack_ai_caller(settings) -> _call(prompt)->str` (đa provider: gemini/openai/
  claude/kiro); `_gemini_raw_text`; parse JSON strip-markdown
  `_parse_video_context_json` / `_parse_keyword_ai_json`; resolver provider/key
  (`gemini_api_key`, `gemini_keyword_model` mặc định `gemini-2.5-flash`); cơ chế
  pause khi quota (`_AI_PROVIDER_PAUSE_UNTIL`).
- `build_asset_manifest` (SP2) đọc `voice.segments.json` (đã 1 segment/dòng, timing
  measured), nhưng `merge_segments_into_sentences` còn gộp dòng không kết thúc `.!?`.
- `_manifest_item` tạo asset có `keyword` nhưng CHƯA có `prompt`.
- `load_manifest`/`save_manifest` ở `assets/asset_manifest.json`.
- Frontend màn `step2b` = `PromptScreen` (hiện chỉ sửa keyword/câu).
- Auto Prompt gốc (`Auto Prompt/renderer/index.html`): `SYS_ANALYZE` (JSON: language,
  storyContext, mainSetting, tone, characters[], sceneMap[]); `SYS_PROMPT` (per-line,
  cinematic — sẽ KHÔNG port nguyên văn); batch ~8; `enforceDescriptions` (bỏ số thứ
  tự, ≤3 nhân vật có tên, gắn style-suffix, đảm bảo đuôi "no text", sanitize policy
  words).

## Quyết định thiết kế

### 1. Artifact & mô hình dữ liệu

- `scripts/prompt_analysis.json` (nguồn của pha 2, sửa được):
  ```json
  {
    "version": 1,
    "language": "Vietnamese|English",
    "storyContext": "...",
    "mainSetting": "...",
    "tone": "...",
    "characters": [
      {"name": "...", "role": "...", "description": "<mô tả ngoại hình đời thật, khoá cứng>"}
    ],
    "sceneMap": [
      {"startLine": 1, "endLine": 1, "location": "...", "timeOfDay": "...",
       "sceneSummary": "...", "charactersPresent": ["..."], "characterPositions": {},
       "spatialLayout": "...", "crowdNotes": ""}
    ]
  }
  ```
- Manifest item thêm field **`prompt`** (str, prompt ảnh đời thật per-line). Giữ
  `keyword` (SP4 sẽ derive keyword từ `prompt`).

### 2. Chốt 1 dòng = 1 cảnh (trả nợ I1 SP2)

- Trong `build_asset_manifest`, khi segments là measured (1/dòng), **mỗi segment = 1
  asset** (bỏ `merge_segments_into_sentences` cho luồng chuẩn). Khớp "1 dòng = 1
  prompt = 1 ảnh". Đảm bảo `start/end/sentence_text` lấy đúng từng dòng.

### 3. Pha 1 — Phân tích (port SYS_ANALYZE, giữ JSON, chỉnh sang đời thật)

- Hàm mới `analyze_story(project, settings, log=None) -> dict`:
  - Đầu vào: các dòng `subtitle.json` dựng thành "SRT đánh số dòng" + script.
  - Gọi AI qua `_pack_ai_caller` với system prompt `SYS_ANALYZE` (port từ Auto Prompt,
    nhưng `suggestedDescription` yêu cầu **mô tả ngoại hình ĐỜI THẬT** (sắc tộc, giới,
    độ tuổi, vóc dáng, tóc, trang phục thường ngày) — KHÔNG yêu cầu chân dung điện
    ảnh). parse JSON bằng helper sẵn có.
  - Ghi `scripts/prompt_analysis.json`. Trả về dict.
- `SYS_ANALYZE` (port, rút gọn — nguyên tắc, không cinematic):
  > "You are a story analyst. Analyze the numbered subtitle lines and return ONLY raw
  > JSON (no markdown) with: language, storyContext (4-5 sentences), mainSetting, tone,
  > characters [{name (exact as in text; invent a fitting realistic name if unnamed),
  > role, description = REAL-LIFE upper-body appearance: ethnicity+gender, age bracket,
  > build, skin tone, hair, everyday clothing — no cinematic styling}], sceneMap [one
  > entry per subtitle line: startLine=endLine=line index, location, timeOfDay,
  > sceneSummary (one plain sentence), charactersPresent, characterPositions,
  > spatialLayout, crowdNotes]. Cover every line with no gaps."

### 4. Sửa nhân vật (UI) — không style

- Màn step2b thêm khu "Phân tích": danh sách nhân vật **sửa được** (tên/vai/mô tả),
  thêm/xoá; hiển thị storyContext/mainSetting (đọc). Không có dropdown style.
- Lưu chỉnh sửa về `prompt_analysis.json` qua endpoint riêng.

### 5. Pha 2 — Prompt đời thật per-line (viết lại SYS_PROMPT)

- Hàm `generate_line_prompts(project, settings, log=None) -> list[dict]`:
  - Với mỗi dòng, dựng user-message: storyContext + mainSetting + **mô tả nhân vật
    khoá cứng** (copy nguyên văn) + dòng scene map tương ứng + text câu thoại.
  - Gọi AI theo **batch ~8 dòng** (cấu hình `prompt_batch_size`, mặc định 8; giảm dần
    khi parse JSON lỗi như Auto Prompt), parse JSON array N chuỗi.
  - `SYS_PROMPT_REALISTIC` (viết lại, BỎ cinematic):
    > "You generate REAL-LIFE photo prompts for stock-image search. Each prompt = a
    > believable real-world photograph of the moment. ALL character appearance ONLY
    > inside parentheses, copied EXACTLY from the locked description (never shorten/
    > change). RULES: [R1] 1 line = 1 prompt. [R2] character lock. [R3] place
    > characters at their positions. [R4] MAX 3 named characters; others are unnamed
    > background people. [R5] dialogue → body language + expression only (never the
    > spoken words). [R6] one clear action/moment. [R7] no shot labels (no 'close-up'/
    > 'wide shot'). [R8] vary viewpoint for consecutive prompts in the same location.
    > End EVERY prompt with EXACTLY: 'Natural lighting, candid real-life photograph,
    > true-to-life, no text, no captions, no watermark.' Output ONLY a raw JSON array
    > of N strings, no scene numbers."
  - **Hậu xử lý** (port `enforceDescriptions`, bỏ phần style-suffix nghệ thuật): bỏ số
    thứ tự đầu chuỗi; ép ≤3 nhân vật có tên; đảm bảo đuôi tag thực tế; sanitize policy
    words (nude→casually dressed, gun→object in hand, …). Ghi `prompt` vào từng asset
    theo `sentence_indexes`/thứ tự dòng.

### 6. UI prompt per-line

- `PromptScreen`: mỗi dòng hiển thị câu thoại + **prompt** (textarea sửa được). Nút
  theo thứ tự: "Phân tích" (pha 1) → khu nhân vật → "Tạo prompt" (pha 2) → (SP4) "Tạo
  keyword & tìm ảnh". Sửa prompt 1 dòng lưu qua endpoint.

### 7. API & thay thế luồng

- `POST /api/analyze-story` — pha 1 (job), trả analysis.
- `POST /api/prompt-analysis` — lưu nhân vật/bối cảnh đã sửa.
- `POST /api/generate-prompts` — pha 2 (job), ghi `prompt` vào manifest.
- `POST /api/assets/{asset_id}/prompt` — sửa prompt 1 dòng.
- Luồng chuẩn dùng 1 dòng=1 cảnh + pha 1/pha 2 thay cho `group_scenes_with_ai` +
  `optimize_asset_keywords_with_ai`. (Code cũ giữ lại trong file nhưng không gọi ở
  luồng chuẩn; dọn triệt để là việc sau, tránh phình SP3.)

### 8. AI provider

- Tái dùng resolver/`_pack_ai_caller` (Gemini mặc định `gemini_api_key` +
  `gemini_keyword_model`; hỗ trợ kiro/openai/claude). System prompt là
  `SYS_ANALYZE`/`SYS_PROMPT_REALISTIC` ở trên. Tôn trọng cơ chế pause-quota sẵn có.

## Phạm vi thay đổi

- `app/pipeline/visual_pipeline.py`: `build_asset_manifest` (1 dòng=1 cảnh);
  `analyze_story`, `generate_line_prompts`, hậu xử lý prompt; `_manifest_item` thêm
  `prompt`. (Cân nhắc tách module mới `app/pipeline/prompt_studio.py` cho 2 pha để
  tránh phình `visual_pipeline.py` ~4700 dòng — quyết trong plan.)
- `app/web/web_server.py`: 4 endpoint mới; cập nhật `/api/analyze` / `/api/analyze-search`
  dùng luồng mới.
- `webui/src/App.jsx`: mở rộng `PromptScreen` (khu phân tích nhân vật + prompt per-line).

## Đánh đổi

- 2 pha + per-line batch = nhiều lệnh AI hơn (tốn token/chậm hơn keyword 1 vòng cũ).
  Đổi lại: prompt nhất quán nhân vật + bám từng câu, đúng "1 dòng = 1 ảnh".
- Prompt đời thật khó "khớp 100%" ảnh stock (SP4 sẽ rút keyword ngắn từ prompt). Thiết
  kế mở để sau này chuyển sang sinh ảnh AI nếu muốn.
- Giữ code scene-grouping/keyword cũ (không gọi) để giảm rủi ro; nợ dọn dẹp ghi lại.

## Tiêu chí hoàn thành

- `build_asset_manifest` cho luồng chuẩn tạo đúng 1 asset/dòng phụ đề (khớp số dòng).
- Pha 1 tạo `scripts/prompt_analysis.json` đúng schema (characters + sceneMap phủ mọi
  dòng); sửa nhân vật rồi lưu → file cập nhật.
- Pha 2 ghi `prompt` cho mọi asset; prompt là mô tả **đời thật** (đuôi tag thực tế,
  KHÔNG "cinematic/35mm/HDR"), ≤3 nhân vật có tên, không lộ lời thoại.
- Hậu xử lý: bỏ số thứ tự, ép ≤3 nhân vật, sanitize, đảm bảo đuôi tag — có unit test
  trên hàm thuần (không cần AI).
- Sửa prompt 1 dòng qua UI/endpoint được lưu.
- Parse JSON pha 1/pha 2 chịu được markdown fence và mảng thiếu/thừa phần tử (đệm/cắt
  theo số dòng) — có test.
- Không hồi quy voice/preview/search hiện có.
