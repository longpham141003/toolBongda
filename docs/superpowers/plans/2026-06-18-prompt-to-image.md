# SP4 — Prompt → keyword → ảnh stock: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Biến `prompt` đời thật của mỗi cảnh thành truy vấn tìm kiếm ngắn (AI + fallback heuristic) rồi tìm/tải 1 ảnh stock, qua một nút "Tạo keyword & tìm ảnh".

**Architecture:** Thêm `keyword_from_prompt` + `apply_prompt_keywords` vào `app/pipeline/prompt_studio.py` (tái dùng `_ai_call`, `keyword_for_text` qua adapter lazy, `_load_manifest`/`_save_manifest`). Endpoint `POST /api/prompt-search` chạy `apply_prompt_keywords` rồi `_search_assets_parallel` (crawler sẵn có). UI thêm nút trong `PromptScreen` → job → sang step3b.

**Tech Stack:** Python 3 + FastAPI + pytest; React/Vite; AI qua Gemini (`_pack_ai_caller`); ảnh qua Google Images Playwright crawler sẵn có.

## Global Constraints

- Keyword rút từ field `prompt` (SP3), fallback `sentence_text`. Ghi vào `keyword` + `ai_search_keyword` + `google_queries` (các field search đang dùng).
- AI tóm tắt prompt → truy vấn Google Images **4-8 từ thực tế, bỏ tên nhân vật phịa**, tiếng Anh; JSON `{"search_keyword": str, "google_queries": [str,...]}`.
- Fallback khi AI rỗng/lỗi/JSON hỏng/thiếu key: `keyword_for_text(prompt or fallback_text)`.
- Luôn đảm bảo `search_keyword` không rỗng và `google_queries` có ≥1 phần tử.
- Một nút: `/api/prompt-search` = `apply_prompt_keywords` + `_search_assets_parallel`; crawler không đổi; 1 ảnh/cảnh.
- Thay `optimize_asset_keywords_with_ai` trong luồng chuẩn (không gọi nó nữa ở nút mới; bỏ định tuyến SportsDB — để `sportsdb_queries` rỗng).
- Không hồi quy `/api/search`, retry/keyword endpoints, step3b.

---

### Task 1: `keyword_from_prompt` + `apply_prompt_keywords`

**Files:**
- Modify: `app/pipeline/prompt_studio.py`
- Test: `tests/test_keyword_from_prompt.py`

**Interfaces:**
- Consumes: `_ai_call`, `parse_json_block`, `_load_manifest`, `_save_manifest` (SP3); `keyword_for_text` (visual_pipeline) qua adapter lazy.
- Produces:
  - `keyword_from_prompt(prompt: str, settings: dict, fallback_text: str = "") -> dict` → `{"search_keyword": str, "google_queries": list[str]}`.
  - `apply_prompt_keywords(project: Path, settings: dict, log=None) -> list[dict]` → set `keyword`/`ai_search_keyword`/`google_queries` cho mỗi asset từ `prompt`, lưu manifest, trả về.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_keyword_from_prompt.py
from pathlib import Path
from app.pipeline import prompt_studio as ps


def test_keyword_from_prompt_uses_ai(monkeypatch):
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt, **k: '{"search_keyword": "west african woman office worried", "google_queries": ["woman office worried", "african woman blue blouse office"]}')
    out = ps.keyword_from_prompt("Ama (West African woman, blue blouse) looks worried in an office", {"gemini_api_key": "x"})
    assert out["search_keyword"] == "west african woman office worried"
    assert out["google_queries"][0] == "woman office worried"


def test_keyword_from_prompt_falls_back_when_ai_empty(monkeypatch):
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt, **k: "")
    out = ps.keyword_from_prompt("A worried office worker at her desk", {}, fallback_text="A worried office worker")
    # heuristic keyword_for_text produced something non-empty, mirrored into google_queries
    assert out["search_keyword"].strip()
    assert out["google_queries"] and out["google_queries"][0] == out["search_keyword"]


def test_keyword_from_prompt_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt, **k: "not json at all")
    out = ps.keyword_from_prompt("Children playing football in a park", {"gemini_api_key": "x"})
    assert out["search_keyword"].strip()
    assert out["google_queries"]


def test_apply_prompt_keywords_writes_fields(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    manifest = [
        {"asset_id": "asset_0001", "prompt": "A woman at a desk", "sentence_text": "She sits.", "keyword": "", "google_queries": []},
        {"asset_id": "asset_0002", "prompt": "", "sentence_text": "A dog runs.", "keyword": "", "google_queries": []},
    ]
    saved = {}
    monkeypatch.setattr(ps, "_load_manifest", lambda p: manifest)
    monkeypatch.setattr(ps, "_save_manifest", lambda p, items: saved.update({"items": items}))
    monkeypatch.setattr(ps, "keyword_from_prompt", lambda text, settings, fallback_text="": {"search_keyword": f"kw:{text or fallback_text}", "google_queries": [f"q:{text or fallback_text}"]})
    out = ps.apply_prompt_keywords(project, {}, log=None)
    assert out[0]["keyword"] == "kw:A woman at a desk"
    assert out[0]["ai_search_keyword"] == "kw:A woman at a desk"
    assert out[0]["google_queries"] == ["q:A woman at a desk"]
    # asset 2 has empty prompt → falls back to sentence_text
    assert out[1]["keyword"] == "kw:A dog runs."
    assert saved["items"][0]["keyword"] == "kw:A woman at a desk"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_keyword_from_prompt.py -v`
Expected: FAIL — `keyword_from_prompt`/`apply_prompt_keywords` chưa tồn tại.

- [ ] **Step 3: Implement**

Thêm vào `app/pipeline/prompt_studio.py`:

```python
def _keyword_for_text(text: str) -> str:
    """Lazy adapter to the heuristic extractor in visual_pipeline (avoids cycle)."""
    from app.pipeline.visual_pipeline import keyword_for_text
    return keyword_for_text(text)


SYS_KEYWORD = (
    "You turn a real-life photo description into a SHORT image-search query for "
    "stock photos. Return ONLY raw JSON (no markdown): "
    '{"search_keyword": "4-8 plain real-world words people would type into Google '
    'Images", "google_queries": ["2-3 short query variants"]}. '
    "Drop invented character names and any text-on-image instructions; keep concrete, "
    "searchable real-world nouns (people type, setting, action, clothing). English only."
)


def keyword_from_prompt(prompt: str, settings: dict, fallback_text: str = "") -> dict:
    text = str(prompt or "").strip()
    result: dict | None = None
    if text:
        try:
            raw = _ai_call(settings, f"{SYS_KEYWORD}\n\nDescription:\n{text}", max_tokens=400)
            data = parse_json_block(raw)
            if isinstance(data, dict):
                kw = str(data.get("search_keyword") or "").strip()
                queries = [str(q or "").strip() for q in (data.get("google_queries") or []) if str(q or "").strip()]
                if kw:
                    result = {"search_keyword": kw, "google_queries": queries or [kw]}
        except Exception:
            result = None
    if result is None:
        kw = _keyword_for_text(text or str(fallback_text or "")).strip()
        result = {"search_keyword": kw, "google_queries": [kw] if kw else []}
    if not result["google_queries"] and result["search_keyword"]:
        result["google_queries"] = [result["search_keyword"]]
    return result


def apply_prompt_keywords(project: Path, settings: dict, log=None) -> list[dict]:
    manifest = _load_manifest(project)
    if not manifest:
        raise RuntimeError("Chưa có phân cảnh. Hãy phân cảnh trước khi tạo keyword.")
    for index, item in enumerate(manifest, start=1):
        text = str(item.get("prompt") or "").strip()
        fallback = str(item.get("sentence_text") or "")
        kw = keyword_from_prompt(text, settings, fallback_text=fallback)
        item["keyword"] = kw["search_keyword"]
        item["ai_search_keyword"] = kw["search_keyword"]
        item["google_queries"] = kw["google_queries"]
        if callable(log):
            log(f"Keyword {index}/{len(manifest)}: {kw['search_keyword']}")
    _save_manifest(project, manifest)
    if callable(log):
        log(f"Đã tạo keyword cho {len(manifest)} cảnh.")
    return manifest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_keyword_from_prompt.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Full suite**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS.

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/prompt_studio.py tests/test_keyword_from_prompt.py
git commit -m "feat(prompt): keyword_from_prompt + apply_prompt_keywords (AI + fallback)"
```

---

### Task 2: Endpoint `POST /api/prompt-search`

**Files:**
- Modify: `app/web/web_server.py`
- Test: `tests/test_web_server.py`

**Interfaces:**
- Consumes: `apply_prompt_keywords` (Task 1); `_search_assets_parallel`, `load_manifest`, `_project_payload`, `runtime.require_project`/`start_job`, `load_settings`, `Job` (đã có).
- Produces: `POST /api/prompt-search` → job "B3 Tao keyword va tim anh" chạy `apply_prompt_keywords` rồi `_search_assets_parallel`; trả `{"project": ...}`.

- [ ] **Step 1: Write the failing test**

Theo harness `tests/test_web_server.py` (TestClient; `visual_pipeline` + `text_to_voice_queue` mock ở module-level; `prompt_studio` thật). Mượn pattern set project (`ws.runtime.current_project = project`). Vì job chạy trong thread, kiểm route đăng ký + yêu cầu project; với project hợp lệ stub `ws.apply_prompt_keywords` và `ws._search_assets_parallel` để job chạy nhanh không mạng. Đọc các test job-endpoint hiện có (vd `/api/search`) để mirror cách chờ/assert job. Test tối thiểu:

```python
# tests/test_web_server.py — thêm:
class TestPromptSearchEndpoint:
    def test_prompt_search_requires_project(self):
        ws.runtime.current_project = None
        client = TestClient(ws.app)
        resp = client.post("/api/prompt-search")
        assert resp.status_code == 400  # require_project → HTTPException

    def test_prompt_search_starts_job(self, tmp_path, monkeypatch):
        project = tmp_path / "proj"
        (project / "scripts").mkdir(parents=True)
        (project / "scripts" / "script_final.txt").write_text("x", encoding="utf-8")
        ws.runtime.current_project = project
        monkeypatch.setattr(ws, "apply_prompt_keywords", lambda p, s, log=None: [])
        monkeypatch.setattr(ws, "_search_assets_parallel", lambda p, items, s, job, **k: items)
        monkeypatch.setattr(ws, "load_manifest", lambda p: [])
        client = TestClient(ws.app)
        resp = client.post("/api/prompt-search")
        assert resp.status_code == 200
        assert resp.json().get("job")
```

(Nếu `require_project` không raise 400 mà raise khác khi `current_project=None`, dùng đúng status/cách các test khác trong file kỳ vọng — đọc `require_project` + các test require-project sẵn có để mirror.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_server.py::TestPromptSearchEndpoint -v`
Expected: FAIL — route chưa tồn tại (404).

- [ ] **Step 3: Implement**

Thêm import (cùng dòng import `prompt_studio` đã có ở SP3, ~dòng 36):

```python
from app.pipeline.prompt_studio import analyze_story, apply_prompt_keywords, generate_line_prompts, load_prompt_analysis, save_prompt_analysis
```

(Thêm `apply_prompt_keywords` vào danh sách import sẵn có.)

Thêm endpoint (đặt cạnh `/api/search`, ~dòng 1738):

```python
@app.post("/api/prompt-search")
def prompt_search() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.current_label = "Đang tạo keyword từ prompt"
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        apply_prompt_keywords(project, settings, log=job.log)
        items = load_manifest(project)
        job.determinate = True
        job.total_units = len(items)
        job.current_label = "Đang tìm ảnh theo keyword"
        items = _search_assets_parallel(project, items, settings, job)
        job.completed_units = job.total_units
        job.progress = 100
        job.current_label = "Đã tìm ảnh xong"
        return {"items": items, "project": _project_payload(project)}

    return {"job": runtime.start_job("B3 Tao keyword va tim anh", task).payload()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web_server.py::TestPromptSearchEndpoint -v`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS.

- [ ] **Step 6: Commit**

```bash
git add app/web/web_server.py tests/test_web_server.py
git commit -m "feat(prompt): POST /api/prompt-search — keyword from prompt then search"
```

---

### Task 3: UI — nút "Tạo keyword & tìm ảnh" trong PromptScreen

**Files:**
- Modify: `webui/src/App.jsx` (component `PromptScreen`; job-done handler trong App)

**Interfaces:**
- Consumes: endpoint Task 2; `startJob`; job name "B3 Tao keyword va tim anh"; điều hướng `goStep("step3b")`.
- Produces: nút "Tạo keyword & tìm ảnh" hiện khi đã có prompt; khi job xong → sang step3b.

- [ ] **Step 1: Thêm điều hướng job-done**

Trong App, ở effect job-poll (chỗ xử lý `job.status === "done"` đã có các nhánh theo `job.name`), thêm:

```jsx
          if (job.name === "B3 Tao keyword va tim anh") goStep("step3b")
```

(Đặt cạnh các nhánh `if (job.name === "B3 Tim anh") goStep("step3b")` sẵn có — mirror đúng cách điều hướng search hiện tại.)

- [ ] **Step 2: Thêm nút trong PromptScreen**

Trong `PromptScreen`, khu đã render khi có prompt (gần nút "Tạo prompt cho từng câu"), thêm nút mới — chỉ bật khi các asset đã có prompt:

```jsx
        {assets.some((a) => (a.prompt || "").trim()) && (
          <Button disabled={isBusy} onClick={() => startJob("/api/prompt-search", undefined, "prompt-search")}>
            <Image className="h-4 w-4" /> Tạo keyword & tìm ảnh
          </Button>
        )}
```

(`Image` icon đã import ở đầu App.jsx — xác minh; nếu thiếu, thêm vào import lucide-react. `assets` đã là prop của PromptScreen — xác minh; nếu chưa, dùng `project?.assets`.)

- [ ] **Step 3: Verify build**

Run: `cd webui && npm run build`
Expected: build thành công.

- [ ] **Step 4: Manual verification**

Chạy app: B1 lưu phụ đề → B2 voice → màn Prompt: Phân cảnh → Phân tích nhân vật → Tạo prompt → bấm **"Tạo keyword & tìm ảnh"** → job chạy (tạo keyword từ prompt rồi tìm ảnh) → tự sang step3b, mỗi cảnh có 1 ảnh; sửa keyword/tìm lại 1 ảnh vẫn hoạt động.

- [ ] **Step 5: Commit**

```bash
git add webui/src/App.jsx
git commit -m "feat(prompt): PromptScreen 'tạo keyword & tìm ảnh' button → step3b"
```

---

## Self-Review (đã rà)

- **Spec coverage:** §1 keyword_from_prompt → Task 1. §2 apply_prompt_keywords → Task 1. §3 endpoint một nút → Task 2. §4 UI → Task 3. §5 test → Task 1 (unit) + Task 2 (endpoint) + Task 3 (manual). Tiêu chí hoàn thành → Task 1-3.
- **Placeholder scan:** không TBD; SYS_KEYWORD ghi nguyên văn. Ngoại lệ chủ ý: Task 2/3 mượn pattern harness/PromptScreen hiện có (implementer đọc file để mirror) — hợp đồng (route, job name, field) cố định.
- **Type consistency:** `keyword_from_prompt(prompt, settings, fallback_text="") -> {search_keyword, google_queries}`; `apply_prompt_keywords(project, settings, log)`; field `keyword`/`ai_search_keyword`/`google_queries` nhất quán Task 1↔2. Job name "B3 Tao keyword va tim anh" khớp Task 2↔3.
- **Rủi ro ghi:** AI keyword dùng `max_tokens=400` (đủ cho query ngắn). `apply_prompt_keywords` raise nếu chưa có manifest → UI chỉ hiện nút khi đã có prompt (mà prompt cần manifest), nên thứ tự đảm bảo. Crawler/search không test mạng (mock ở endpoint test).
