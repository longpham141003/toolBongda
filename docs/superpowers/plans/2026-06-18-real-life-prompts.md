# SP3 — Prompt đời thật theo từng câu: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sinh prompt mô tả ảnh đời thật cho từng dòng phụ đề qua 2 pha (phân tích bối cảnh+nhân vật → prompt per-line), port cấu trúc Auto Prompt nhưng đầu ra thực tế (không cinematic), và chốt 1 dòng SRT = 1 cảnh.

**Architecture:** Module mới `app/pipeline/prompt_studio.py` chứa logic 2 pha + hàm thuần (parse JSON, hậu xử lý prompt, đọc/ghi `prompt_analysis.json`), tái dùng AI helpers từ `visual_pipeline` (`_pack_ai_caller`, `_parse_video_context_json`). `visual_pipeline.build_asset_manifest` đổi sang 1 asset/dòng và `_manifest_item` thêm field `prompt`. `web_server` thêm 4 endpoint. `PromptScreen` (React) thêm khu sửa nhân vật + prompt per-line.

**Tech Stack:** Python 3 + FastAPI + pytest; React/Vite (`webui/`); AI qua Gemini (`gemini_api_key`).

## Global Constraints

- 1 dòng `subtitle.json` = 1 asset/scene = 1 prompt (luồng chuẩn; bỏ gộp câu).
- Prompt là **ảnh chụp đời thật** (English), KHÔNG cinematic. Mọi prompt KẾT THÚC bằng đúng chuỗi: `Natural lighting, candid real-life photograph, true-to-life, no text, no captions, no watermark.`
- Mô tả ngoại hình nhân vật CHỈ nằm trong ngoặc đơn, copy NGUYÊN VĂN từ mô tả khoá cứng; tối đa **3 nhân vật có tên** mỗi prompt.
- KHÔNG style nghệ thuật, KHÔNG chế độ video.
- Artifact: `scripts/prompt_analysis.json` (schema ở spec §1); manifest item thêm khoá `prompt` (str, mặc định `""`).
- Tái dùng AI: `_pack_ai_caller(settings)` trả `_call(prompt)->str`; nhúng system instructions vào chuỗi prompt (Gemini không có system role). Parse JSON: strip markdown fence trước `json.loads`.
- Provider mặc định Gemini (`gemini_api_key`, `gemini_keyword_model`); tôn trọng pause-quota sẵn có. (Lưu ý: đường openai/claude trong `_pack_ai_caller` giới hạn `max_tokens=1200` — đủ cho batch nhỏ; Gemini không bị giới hạn này.)
- Không hồi quy voice/preview/search; giữ code cũ `group_scenes_with_ai`/`optimize_asset_keywords_with_ai` (không gọi ở luồng chuẩn).

---

### Task 1: `build_asset_manifest` 1 dòng = 1 cảnh + manifest có field `prompt`

**Files:**
- Modify: `app/pipeline/visual_pipeline.py` (`_manifest_item` ~2363; `build_asset_manifest` ~857 phần `sentences = merge_segments_into_sentences(...)`)
- Test: `tests/test_manifest_one_scene_per_line.py`

**Interfaces:**
- Produces: mỗi asset `_manifest_item(...)` có khoá `"prompt": ""`. `build_asset_manifest` (luồng measured) tạo đúng 1 asset/segment (1/dòng).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manifest_one_scene_per_line.py
import sys, types, json
from pathlib import Path
import unittest.mock as mock

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

with mock.patch.dict(sys.modules, {"app.voice.text_to_voice_queue": types.ModuleType("app.voice.text_to_voice_queue")}):
    sys.modules["app.voice.text_to_voice_queue"].TextToVoiceRunner = mock.MagicMock()
    from app.pipeline import visual_pipeline as vp


def test_one_asset_per_subtitle_line(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text("A b. C d e. F.", encoding="utf-8")
    (project / "voices").mkdir(parents=True)
    # Two subtitle lines, NEITHER ending with sentence punctuation (would merge before).
    segments = [
        {"index": 1, "start": 0.0, "end": 1.0, "text": "first line no period", "timing_source": "measured"},
        {"index": 2, "start": 1.25, "end": 2.5, "text": "second line also none", "timing_source": "measured"},
    ]
    (project / "voices" / "voice.segments.json").write_text(
        json.dumps({"engine": "kokoro-server", "timing_source": "measured", "segments": segments}), encoding="utf-8")
    (project / "voices" / "voice.wav").write_bytes(b"RIFFfake")
    monkeypatch.setattr(vp, "probe_duration", lambda *a, **k: 2.5)
    monkeypatch.setattr(vp, "_load_or_build_video_context", lambda *a, **k: {})
    monkeypatch.setattr(vp, "_resolve_pack", lambda *a, **k: None)
    monkeypatch.setattr(vp, "_apply_script_visual_context", lambda assets, *a, **k: assets)

    assets = vp.build_asset_manifest(project, {}, log=None)
    assert len(assets) == 2
    assert assets[0]["sentence_text"] == "first line no period"
    assert assets[1]["sentence_text"] == "second line also none"
    assert assets[0]["prompt"] == ""
    assert (assets[0]["start"], assets[0]["end"]) == (0.0, 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_manifest_one_scene_per_line.py -v`
Expected: FAIL — current `merge_segments_into_sentences` merges the two non-terminal lines into 1 asset (len==1), and `prompt` key missing.

- [ ] **Step 3: Add `prompt` to `_manifest_item`**

Trong `_manifest_item` (`visual_pipeline.py:2367`), thêm `"prompt": "",` vào dict trả về (đặt cạnh `"keyword"`):

```python
        "keyword": keyword_for_text(text),
        "prompt": "",
        "search_attempt": 0,
```

- [ ] **Step 4: 1 cảnh/dòng trong `build_asset_manifest`**

Trong `build_asset_manifest`, đoạn dựng `sentences`/`assets` (~857-863). `merge_segments_into_sentences` hiện gộp segment không kết thúc `.!?`. Đổi để: nếu timing measured (segments đã 1/dòng) thì mỗi segment = 1 sentence (không gộp). Sửa:

```python
    is_measured = str(timing.get("timing_source") or "").lower() == "measured"
    if is_measured:
        # SP3: one scene per subtitle line — do not merge lines into sentences.
        sentences = [
            {
                "sentence_index": seg["sentence_index"],
                "text": seg["text"],
                "start": seg["start"],
                "end": seg["end"],
                "segment_indexes": [seg["sentence_index"]],
            }
            for seg in segments
        ]
    else:
        sentences = merge_segments_into_sentences(segments)
    split_mode = "srt_line_scenes" if is_measured else "srt_sentence_scenes"
```

(Confirm `segments` items have keys `sentence_index/text/start/end` — they come from `normalize_voice_segments` which sets exactly those. `_manifest_item` reads `sentence["segment_indexes"]`, `sentence["sentence_index"]`, `sentence["text"]`, `sentence["start"/"end"]` — the dict above supplies all. `normalize_voice_segments` output does NOT include `segment_indexes`, which is why `merge_segments_into_sentences` adds it — so the measured branch must add `segment_indexes` as shown.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_manifest_one_scene_per_line.py -v`
Expected: PASS

- [ ] **Step 6: Full suite (chú ý test_manifest_measured_timing.py từ SP2 vẫn xanh)**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS. (Nếu `test_manifest_measured_timing.py` khẳng định số cảnh = số segment đã đúng — vẫn xanh; nếu nó dựa trên gộp câu, cập nhật assertion cho khớp 1/dòng.)

- [ ] **Step 7: Commit**

```bash
git add app/pipeline/visual_pipeline.py tests/test_manifest_one_scene_per_line.py
git commit -m "feat(prompt): one scene per subtitle line + manifest prompt field"
```

---

### Task 2: `prompt_studio` — hàm thuần (parse, hậu xử lý, artifact)

**Files:**
- Create: `app/pipeline/prompt_studio.py`
- Test: `tests/test_prompt_studio_pure.py`

**Interfaces:**
- Produces:
  - `REALISTIC_TAG: str` = `"Natural lighting, candid real-life photograph, true-to-life, no text, no captions, no watermark."`
  - `parse_json_block(content: str) -> Any` — strip markdown fence rồi `json.loads`.
  - `coerce_prompt_array(content: str, expected_n: int) -> list[str]` — parse mảng chuỗi; pad bằng `""`/truncate về đúng `expected_n`.
  - `enforce_realistic_prompt(text: str, named_count_limit: int = 3) -> str` — bỏ số thứ tự đầu, sanitize policy words, đảm bảo kết thúc bằng `REALISTIC_TAG`.
  - `analysis_path(project: Path) -> Path`; `load_prompt_analysis(project) -> dict`; `save_prompt_analysis(project, data) -> dict`.
  - `build_numbered_srt(lines: list[dict]) -> str` — `"<i>. <text>"` mỗi dòng.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_prompt_studio_pure.py
from pathlib import Path
import json
from app.pipeline import prompt_studio as ps


def test_coerce_prompt_array_pads_and_truncates():
    assert ps.coerce_prompt_array('["a","b"]', 3) == ["a", "b", ""]
    assert ps.coerce_prompt_array('```json\n["a","b","c","d"]\n```', 2) == ["a", "b"]


def test_enforce_realistic_prompt_strips_number_and_appends_tag():
    out = ps.enforce_realistic_prompt("3. A man (desc) walking")
    assert not out.startswith("3.")
    assert out.endswith(ps.REALISTIC_TAG)
    # idempotent: does not double-append
    assert ps.enforce_realistic_prompt(out).count(ps.REALISTIC_TAG) == 1


def test_enforce_realistic_prompt_sanitizes_policy_words():
    out = ps.enforce_realistic_prompt("a nude person holding a gun")
    assert "nude" not in out.lower()
    assert "gun" not in out.lower()


def test_build_numbered_srt():
    lines = [{"index": 1, "text": "Hello"}, {"index": 2, "text": "World"}]
    assert ps.build_numbered_srt(lines) == "1. Hello\n2. World"


def test_save_load_analysis_roundtrip(tmp_path):
    project = tmp_path / "proj"
    data = {"version": 1, "storyContext": "x", "characters": [{"name": "A", "role": "r", "description": "d"}], "sceneMap": []}
    saved = ps.save_prompt_analysis(project, data)
    assert ps.analysis_path(project).exists()
    assert ps.load_prompt_analysis(project)["characters"][0]["name"] == "A"
    assert ps.load_prompt_analysis(tmp_path / "none") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prompt_studio_pure.py -v`
Expected: FAIL — `ModuleNotFoundError: app.pipeline.prompt_studio`

- [ ] **Step 3: Write implementation**

```python
# app/pipeline/prompt_studio.py
"""Two-phase real-life prompt generation (SP3), ported in structure from the
Auto Prompt app but producing realistic stock-photo prompts (no cinematic styling).

Pure helpers here are AI-free and unit-tested. The AI phases live in this module
too (analyze_story / generate_line_prompts) and reuse visual_pipeline's AI caller.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

REALISTIC_TAG = "Natural lighting, candid real-life photograph, true-to-life, no text, no captions, no watermark."

# Crude policy-word softening (ported from Auto Prompt's sanitize step).
_POLICY_REPLACEMENTS = [
    (re.compile(r"\bnude\b", re.I), "casually dressed"),
    (re.compile(r"\bnaked\b", re.I), "casually dressed"),
    (re.compile(r"\bgun\b", re.I), "object in hand"),
    (re.compile(r"\bguns\b", re.I), "objects in hand"),
    (re.compile(r"\bgore\b", re.I), "intense"),
    (re.compile(r"\bblood\b", re.I), "intense"),
    (re.compile(r"\bsuicide\b", re.I), "crisis moment"),
    (re.compile(r"\bcorpse\b", re.I), "still figure"),
]


def parse_json_block(content: str) -> Any:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def coerce_prompt_array(content: str, expected_n: int) -> list[str]:
    """Parse a JSON array of strings; pad with '' or truncate to expected_n."""
    try:
        data = parse_json_block(content)
    except Exception:
        data = []
    if not isinstance(data, list):
        data = []
    result = [str(item or "").strip() for item in data]
    if len(result) < expected_n:
        result += [""] * (expected_n - len(result))
    return result[:expected_n]


def enforce_realistic_prompt(text: str, named_count_limit: int = 3) -> str:
    value = str(text or "").strip()
    # Drop a leading "N." / "N)" / "N -" scene number.
    value = re.sub(r"^\s*\d+\s*[\.\):\-]\s*", "", value)
    for pattern, replacement in _POLICY_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    value = value.strip()
    # Ensure exactly one realistic tag at the end.
    if value.endswith(REALISTIC_TAG):
        return value
    # Strip any partial/duplicate tag fragment then append once.
    value = value.rstrip()
    if not value.endswith((".", "!", "?")):
        value += "."
    return f"{value} {REALISTIC_TAG}"


def build_numbered_srt(lines: list[dict]) -> str:
    out = []
    for i, line in enumerate(lines, start=1):
        idx = int(line.get("index") or i)
        text = str(line.get("text") or "").strip()
        out.append(f"{idx}. {text}")
    return "\n".join(out)


def analysis_path(project: Path) -> Path:
    return Path(project) / "scripts" / "prompt_analysis.json"


def save_prompt_analysis(project: Path, data: dict) -> dict:
    path = analysis_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data or {})
    payload.setdefault("version", 1)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_prompt_analysis(project: Path) -> dict:
    path = analysis_path(project)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_prompt_studio_pure.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/prompt_studio.py tests/test_prompt_studio_pure.py
git commit -m "feat(prompt): prompt_studio pure helpers (parse, enforce, analysis io)"
```

---

### Task 3: Pha 1 — `analyze_story` (SYS_ANALYZE)

**Files:**
- Modify: `app/pipeline/prompt_studio.py` (thêm `SYS_ANALYZE`, `analyze_story`)
- Test: `tests/test_analyze_story.py`

**Interfaces:**
- Consumes: `load_subtitle` (subtitle_store); `_pack_ai_caller` (visual_pipeline); pure helpers (Task 2).
- Produces: `analyze_story(project: Path, settings: dict, log=None) -> dict` — gọi AI pha 1, ghi `prompt_analysis.json`, trả dict. Raise nếu không có subtitle hoặc AI không cấu hình.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analyze_story.py
import json
from pathlib import Path
from app.pipeline import prompt_studio as ps
from app.pipeline.subtitle_store import save_subtitle


def test_analyze_story_writes_analysis(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    save_subtitle(project, [
        {"start": 0.0, "end": 1.0, "text": "Ama steps forward."},
        {"start": 1.0, "end": 2.0, "text": "Eleanor frowns."},
    ])
    fake_json = json.dumps({
        "language": "English", "storyContext": "A tense meeting.", "mainSetting": "office",
        "tone": "tense",
        "characters": [{"name": "Ama", "role": "junior clerk", "description": "West African woman, late 20s, slim, dark skin, short black hair, plain blue blouse"}],
        "sceneMap": [{"startLine": 1, "endLine": 1, "location": "office", "timeOfDay": "day", "sceneSummary": "Ama steps forward", "charactersPresent": ["Ama"], "characterPositions": {}, "spatialLayout": "open office", "crowdNotes": ""}],
    })
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: fake_json)
    out = ps.analyze_story(project, {"gemini_api_key": "x"}, log=None)
    assert out["characters"][0]["name"] == "Ama"
    assert ps.load_prompt_analysis(project)["storyContext"] == "A tense meeting."


def test_analyze_story_requires_subtitle(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: "{}")
    import pytest
    with pytest.raises(Exception) as exc:
        ps.analyze_story(project, {}, log=None)
    assert "phụ đề" in str(exc.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_analyze_story.py -v`
Expected: FAIL — `analyze_story`/`_ai_call` chưa tồn tại.

- [ ] **Step 3: Add imports + `_ai_call` + `SYS_ANALYZE` + `analyze_story`**

Thêm vào đầu `prompt_studio.py` (sau các import hiện có):

```python
from app.pipeline.subtitle_store import load_subtitle


def _ai_call(settings: dict, prompt: str) -> str:
    """Single AI call returning raw text. Imported lazily to avoid import cycle."""
    from app.pipeline.visual_pipeline import _pack_ai_caller
    caller = _pack_ai_caller(settings)
    if caller is None:
        raise RuntimeError("Chưa cấu hình AI (thiếu API key) để tạo prompt.")
    return caller(prompt)
```

Thêm system prompt + pha 1 (đặt cuối file):

```python
SYS_ANALYZE = (
    "You are a story analyst for REAL-LIFE stock photography. Read the numbered "
    "subtitle lines and return ONLY raw JSON (no markdown, no backticks) with this "
    "exact shape:\n"
    "{\n"
    '  "language": "English or Vietnamese",\n'
    '  "storyContext": "4-5 sentence plain summary of plot, setting, key events",\n'
    '  "mainSetting": "primary real-world location",\n'
    '  "tone": "everyday/tense/heartwarming/etc",\n'
    '  "characters": [{"name": "name exactly as in text; invent a fitting realistic '
    'name if unnamed", "role": "their role in 4-6 words", "description": "REAL-LIFE '
    "UPPER-BODY appearance only: [ethnicity+nationality] [gender], [age bracket], "
    "[build], [skin tone], [hair: color+length+style], [everyday TOP clothing only — "
    'no cinematic styling, no pants, no shoes]"}],\n'
    '  "sceneMap": [{"startLine": N, "endLine": N, "location": "specific real place", '
    '"timeOfDay": "time + natural light", "sceneSummary": "one plain sentence of the '
    'action", "charactersPresent": ["Name"], "characterPositions": {"Name": "where"}, '
    '"spatialLayout": "describe the real space", "crowdNotes": "background people if any"}]\n'
    "}\n"
    "RULES: Extract EVERY character who physically appears; description is upper-body, "
    "real-life, everyday clothing (no film/cinematic styling). For children use 'young "
    "boy'/'young girl'. sceneMap MUST have one entry per subtitle line (startLine == "
    "endLine == that line's number), covering all lines with no gaps."
)


def analyze_story(project: Path, settings: dict, log=None) -> dict:
    lines = load_subtitle(project)
    if not lines:
        raise RuntimeError("Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước khi phân tích.")
    if callable(log):
        log(f"Phân tích {len(lines)} dòng phụ đề để dựng bối cảnh & nhân vật...")
    numbered = build_numbered_srt(lines)
    prompt = f"{SYS_ANALYZE}\n\nNumbered subtitle lines ({len(lines)} total):\n{numbered}"
    raw = _ai_call(settings, prompt)
    try:
        data = parse_json_block(raw)
    except Exception as exc:
        raise RuntimeError(f"AI phân tích trả về JSON không hợp lệ: {exc}")
    if not isinstance(data, dict):
        raise RuntimeError("AI phân tích không trả về object JSON.")
    data.setdefault("characters", [])
    data.setdefault("sceneMap", [])
    if callable(log):
        log(f"Đã nhận {len(data.get('characters') or [])} nhân vật từ AI.")
    return save_prompt_analysis(project, data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_analyze_story.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/prompt_studio.py tests/test_analyze_story.py
git commit -m "feat(prompt): phase-1 analyze_story (real-life SYS_ANALYZE)"
```

---

### Task 4: Pha 2 — `generate_line_prompts` (SYS_PROMPT_REALISTIC + hậu xử lý)

**Files:**
- Modify: `app/pipeline/prompt_studio.py` (thêm `SYS_PROMPT_REALISTIC`, `generate_line_prompts`, `_character_block`, `_scene_for_line`)
- Test: `tests/test_generate_line_prompts.py`

**Interfaces:**
- Consumes: `load_subtitle`; `load_manifest`/`save_manifest` (visual_pipeline); `load_prompt_analysis`; pure helpers; `_ai_call`.
- Produces: `generate_line_prompts(project: Path, settings: dict, log=None, batch_size: int = 8) -> list[dict]` — ghi `prompt` (đã hậu xử lý) vào từng asset của manifest theo thứ tự dòng, lưu manifest, trả về assets.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generate_line_prompts.py
import json, sys, types
from pathlib import Path
import unittest.mock as mock

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.pipeline import prompt_studio as ps
from app.pipeline.subtitle_store import save_subtitle


def _setup(project):
    (project / "scripts").mkdir(parents=True)
    save_subtitle(project, [
        {"start": 0.0, "end": 1.0, "text": "Ama steps forward."},
        {"start": 1.0, "end": 2.0, "text": "Eleanor frowns."},
    ])
    ps.save_prompt_analysis(project, {
        "storyContext": "A tense meeting.", "mainSetting": "office",
        "characters": [{"name": "Ama", "role": "clerk", "description": "West African woman, late 20s, blue blouse"}],
        "sceneMap": [
            {"startLine": 1, "endLine": 1, "location": "office", "timeOfDay": "day", "sceneSummary": "Ama steps forward", "charactersPresent": ["Ama"], "characterPositions": {}, "spatialLayout": "open office", "crowdNotes": ""},
            {"startLine": 2, "endLine": 2, "location": "office", "timeOfDay": "day", "sceneSummary": "Eleanor frowns", "charactersPresent": [], "characterPositions": {}, "spatialLayout": "open office", "crowdNotes": ""},
        ],
    })


def test_generate_line_prompts_writes_prompts(tmp_path, monkeypatch):
    # Stub manifest IO + AI on the prompt_studio module's references.
    project = tmp_path / "proj"
    _setup(project)
    manifest = [
        {"asset_id": "asset_0001", "sentence_text": "Ama steps forward.", "prompt": "", "sentence_indexes": [1]},
        {"asset_id": "asset_0002", "sentence_text": "Eleanor frowns.", "prompt": "", "sentence_indexes": [2]},
    ]
    saved = {}
    monkeypatch.setattr(ps, "_load_manifest", lambda p: manifest)
    monkeypatch.setattr(ps, "_save_manifest", lambda p, items: saved.update({"items": items}))
    # AI returns a raw JSON array of N strings (one batch of 2 here).
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: json.dumps([
        "1. Ama (West African woman, late 20s, blue blouse) steps forward in an open office",
        "Eleanor frowns at her desk",
    ]))
    assets = ps.generate_line_prompts(project, {"gemini_api_key": "x"}, log=None, batch_size=8)
    assert len(assets) == 2
    assert assets[0]["prompt"].endswith(ps.REALISTIC_TAG)
    assert not assets[0]["prompt"].startswith("1.")
    assert assets[1]["prompt"].endswith(ps.REALISTIC_TAG)
    assert saved["items"][0]["prompt"] == assets[0]["prompt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generate_line_prompts.py -v`
Expected: FAIL — `generate_line_prompts`/`_load_manifest` chưa tồn tại.

- [ ] **Step 3: Implement**

Thêm vào `prompt_studio.py`. Trước tiên các adapter manifest (cho phép test monkeypatch):

```python
def _load_manifest(project: Path) -> list[dict]:
    from app.pipeline.visual_pipeline import load_manifest
    return load_manifest(project)


def _save_manifest(project: Path, items: list[dict]) -> None:
    from app.pipeline.visual_pipeline import save_manifest
    save_manifest(project, items)
```

System prompt + helpers + pha 2:

```python
SYS_PROMPT_REALISTIC = (
    "You generate REAL-LIFE photo prompts for stock-image search. Each prompt is a "
    "believable real-world photograph of the moment in the line.\n"
    "GOLDEN RULE: ALL character physical appearance goes ONLY inside parentheses right "
    "after the name, copied EXACTLY from the locked description — never shorten, "
    "rephrase, or invent appearance outside the parentheses.\n"
    "RULES:\n"
    "[R1] 1 line = 1 prompt. Never merge or split.\n"
    "[R2] CHARACTER LOCK: copy each character's description verbatim inside ().\n"
    "[R3] Place characters at their given positions in the real space.\n"
    "[R4] MAX 3 named characters per prompt; everyone else is an unnamed background person.\n"
    "[R5] Dialogue becomes body language + facial expression only — never write the spoken words.\n"
    "[R6] One clear action/moment per prompt.\n"
    "[R7] No shot labels (no 'close-up', 'wide shot', 'POV'), no cinematic/film grading, "
    "no artistic style — these are ordinary real photographs.\n"
    "[R8] For consecutive prompts in the same location, vary the natural viewpoint.\n"
    f"[R9] End EVERY prompt with EXACTLY: {REALISTIC_TAG}\n"
    "OUTPUT: ONLY a raw JSON array of strings (one per line, in order). No scene numbers, "
    "no markdown, no commentary."
)


def _character_block(characters: list[dict]) -> str:
    blocks = []
    for ch in characters or []:
        name = str(ch.get("name") or "").strip()
        role = str(ch.get("role") or "").strip()
        desc = str(ch.get("description") or "").strip()
        if name and desc:
            blocks.append(f"{name} ({role}):\n{desc}")
    return "\n\n".join(blocks) if blocks else "(no named characters)"


def _scene_for_line(scene_map: list[dict], line_index: int) -> dict:
    for scene in scene_map or []:
        try:
            if int(scene.get("startLine") or 0) <= line_index <= int(scene.get("endLine") or 0):
                return scene
        except (TypeError, ValueError):
            continue
    return {}


def _line_context(line_index: int, text: str, scene: dict) -> str:
    parts = [f"--- LINE {line_index} ---"]
    if scene.get("location"):
        parts.append(f"Location: {scene.get('location')} | {scene.get('timeOfDay') or ''}")
    if scene.get("sceneSummary"):
        parts.append(f"Scene: {scene.get('sceneSummary')}")
    if scene.get("spatialLayout"):
        parts.append(f"Space: {scene.get('spatialLayout')}")
    if scene.get("charactersPresent"):
        parts.append(f"Characters present: {', '.join(scene.get('charactersPresent') or [])}")
    if scene.get("crowdNotes"):
        parts.append(f"Background: {scene.get('crowdNotes')}")
    parts.append(f"Subtitle text: {text}")
    return "\n".join(parts)


def generate_line_prompts(project: Path, settings: dict, log=None, batch_size: int = 8) -> list[dict]:
    lines = load_subtitle(project)
    if not lines:
        raise RuntimeError("Chưa có phụ đề.")
    manifest = _load_manifest(project)
    if not manifest:
        raise RuntimeError("Chưa có phân cảnh. Hãy phân tích cảnh trước khi tạo prompt.")
    analysis = load_prompt_analysis(project)
    if not analysis:
        raise RuntimeError("Chưa phân tích. Hãy chạy phân tích nhân vật trước.")
    characters = analysis.get("characters") or []
    scene_map = analysis.get("sceneMap") or []
    story = str(analysis.get("storyContext") or "")
    setting = str(analysis.get("mainSetting") or "")
    char_block = _character_block(characters)

    n = len(lines)
    size = max(1, int(batch_size or 8))
    prompts: list[str] = []
    for start in range(0, n, size):
        batch = lines[start:start + size]
        if callable(log):
            log(f"Tạo prompt đoạn {start // size + 1}/{(n + size - 1) // size} ({len(batch)} dòng)")
        ctx_blocks = []
        for offset, line in enumerate(batch):
            li = int(line.get("index") or (start + offset + 1))
            ctx_blocks.append(_line_context(li, str(line.get("text") or ""), _scene_for_line(scene_map, li)))
        user_msg = (
            f"{SYS_PROMPT_REALISTIC}\n\n"
            f"=== STORY ===\n{story}\nMain setting: {setting}\n\n"
            f"=== LOCKED CHARACTER DESCRIPTIONS (copy EXACTLY inside parentheses) ===\n{char_block}\n\n"
            f"=== GENERATE {len(batch)} PROMPTS, ONE PER LINE, IN ORDER ===\n" + "\n\n".join(ctx_blocks)
        )
        raw = _ai_call(settings, user_msg)
        prompts.extend(coerce_prompt_array(raw, len(batch)))

    prompts = [enforce_realistic_prompt(p) if p.strip() else "" for p in prompts[:n]]
    # Map prompts onto manifest assets in order (1 asset per line).
    for i, item in enumerate(manifest):
        item["prompt"] = prompts[i] if i < len(prompts) else ""
    _save_manifest(project, manifest)
    if callable(log):
        log(f"Đã tạo prompt cho {sum(1 for it in manifest if it.get('prompt'))}/{len(manifest)} cảnh.")
    return manifest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generate_line_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS.

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/prompt_studio.py tests/test_generate_line_prompts.py
git commit -m "feat(prompt): phase-2 generate_line_prompts (real-life per-line)"
```

---

### Task 5: Endpoints — analyze-story, save analysis, generate-prompts, edit prompt

**Files:**
- Modify: `app/web/web_server.py`
- Test: `tests/test_web_server.py` (thêm test theo harness)

**Interfaces:**
- Consumes: `analyze_story`, `generate_line_prompts`, `load_prompt_analysis`, `save_prompt_analysis` (prompt_studio); `runtime.require_project()`, `runtime.start_job`, `load_manifest`/`save_manifest`, `_project_payload`.
- Produces:
  - `POST /api/analyze-story` → job chạy `analyze_story`; trả analysis.
  - `POST /api/prompt-analysis` (body `{analysis: dict}`) → `save_prompt_analysis`; trả analysis.
  - `GET /api/prompt-analysis` → `load_prompt_analysis`.
  - `POST /api/generate-prompts` → job chạy `generate_line_prompts`.
  - `POST /api/assets/{asset_id}/prompt` (body `{prompt: str}`) → sửa `item["prompt"]`, save_manifest.

- [ ] **Step 1: Write the failing test**

Theo harness `tests/test_web_server.py` (TestClient; `app.pipeline.visual_pipeline` đã bị mock ở module — nên thêm `prompt_studio` cũng cần mock hoặc gọi thật; vì test này chỉ kiểm route + lưu, mock `app.pipeline.prompt_studio` cùng kiểu). Mượn pattern set current project (`ws.runtime.current_project = project`). Test tối thiểu:

```python
# tests/test_web_server.py — thêm:
class TestPromptAnalysisEndpoint:
    def test_save_and_get_prompt_analysis(self, tmp_path):
        project = tmp_path / "proj"
        (project / "scripts").mkdir(parents=True)
        (project / "scripts" / "script_final.txt").write_text("x", encoding="utf-8")
        ws.runtime.current_project = project
        client = TestClient(ws.app)
        analysis = {"characters": [{"name": "A", "role": "r", "description": "d"}], "sceneMap": []}
        r1 = client.post("/api/prompt-analysis", json={"analysis": analysis})
        assert r1.status_code == 200
        r2 = client.get("/api/prompt-analysis")
        assert r2.status_code == 200
        assert r2.json()["analysis"]["characters"][0]["name"] == "A"
```

(Nếu `prompt_studio` chưa được inject vào sys.modules như visual_pipeline, import thật `save/load_prompt_analysis` chạy với file thật — chấp nhận; chúng là I/O thuần. Đọc đầu `test_web_server.py` để quyết mock hay import thật, mirror cách các test khác.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_server.py::TestPromptAnalysisEndpoint -v`
Expected: FAIL — route chưa tồn tại (404).

- [ ] **Step 3: Implement endpoints + models**

Thêm import (cạnh import subtitle_store, ~dòng 36):

```python
from app.pipeline.prompt_studio import analyze_story, generate_line_prompts, load_prompt_analysis, save_prompt_analysis
```

Thêm model (cạnh `SubtitleRequest`):

```python
class PromptAnalysisRequest(BaseModel):
    analysis: dict[str, Any] = {}


class PromptEditRequest(BaseModel):
    prompt: str = ""
```

Thêm endpoints (đặt cạnh các endpoint analyze/voice):

```python
@app.post("/api/analyze-story")
def analyze_story_endpoint() -> dict[str, Any]:
    project = runtime.require_project()
    if not load_subtitle(project):
        raise HTTPException(status_code=400, detail="Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước.")
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        analysis = analyze_story(project, settings, log=job.log)
        return {"analysis": analysis, "project": _project_payload(project)}

    return {"job": runtime.start_job("B2 Phan tich nhan vat", task).payload()}


@app.get("/api/prompt-analysis")
def get_prompt_analysis() -> dict[str, Any]:
    project = runtime.require_project()
    return {"analysis": load_prompt_analysis(project)}


@app.post("/api/prompt-analysis")
def save_prompt_analysis_endpoint(request: PromptAnalysisRequest) -> dict[str, Any]:
    project = runtime.require_project()
    saved = save_prompt_analysis(project, request.analysis)
    return {"analysis": saved}


@app.post("/api/generate-prompts")
def generate_prompts_endpoint() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        generate_line_prompts(project, settings, log=job.log)
        return {"project": _project_payload(project)}

    return {"job": runtime.start_job("B2 Tao prompt", task).payload()}


@app.post("/api/assets/{asset_id}/prompt")
def edit_asset_prompt(asset_id: str, request: PromptEditRequest) -> dict[str, Any]:
    project = runtime.require_project()
    items = load_manifest(project)
    found = False
    for item in items:
        if item.get("asset_id") == asset_id:
            item["prompt"] = request.prompt
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Không tìm thấy asset.")
    save_manifest(project, items)
    return {"project": _project_payload(project)}
```

(`load_subtitle`, `load_manifest`, `save_manifest`, `Job`, `_project_payload`, `runtime`, `load_settings`, `HTTPException` đã có trong web_server. Verify `load_manifest`/`save_manifest` đã được import từ visual_pipeline trong web_server — nếu chưa, dùng cách module đó đang truy cập manifest.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web_server.py::TestPromptAnalysisEndpoint -v`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS.

- [ ] **Step 6: Commit**

```bash
git add app/web/web_server.py tests/test_web_server.py
git commit -m "feat(prompt): endpoints for analyze-story, analysis save, generate-prompts, edit prompt"
```

---

### Task 6: Frontend — khu phân tích nhân vật + prompt per-line trong PromptScreen

**Files:**
- Modify: `webui/src/App.jsx` (component `PromptScreen` ~dòng 2129; App wiring cho analysis state + job navigation)
- Modify: `webui/src/styles.css` (style khu nhân vật/prompt)

**Interfaces:**
- Consumes: endpoints Task 5; `api()` helper; `startJob`; job names "B2 Phan tich nhan vat", "B2 Tao prompt".
- Produces: PromptScreen hiển thị: nút "Phân tích nhân vật" (gọi `/api/analyze-story`); danh sách nhân vật sửa được + storyContext (đọc) lưu qua `/api/prompt-analysis`; nút "Tạo prompt" (gọi `/api/generate-prompts`); mỗi dòng hiển thị câu thoại + `prompt` (textarea sửa được, lưu qua `/api/assets/{id}/prompt`).

Frontend không có test tự động; verify bằng `npm run build` + manual.

- [ ] **Step 1: Thêm state + loaders trong App**

Trong `App()`, thêm state:

```jsx
  const [promptAnalysis, setPromptAnalysis] = useState(null)
```

Hàm tải/lưu analysis (đặt cạnh các hàm api khác):

```jsx
  const loadPromptAnalysis = useCallback(async () => {
    try {
      const data = await api("/api/prompt-analysis")
      setPromptAnalysis(data.analysis && Object.keys(data.analysis).length ? data.analysis : null)
    } catch { /* ignore */ }
  }, [])

  async function savePromptAnalysis(next) {
    const data = await api("/api/prompt-analysis", { method: "POST", body: JSON.stringify({ analysis: next }) })
    setPromptAnalysis(data.analysis)
    return data.analysis
  }

  async function saveAssetPrompt(assetId, prompt) {
    const data = await api(`/api/assets/${assetId}/prompt`, { method: "POST", body: JSON.stringify({ prompt }) })
    setState((current) => ({ ...current, project: data.project }))
  }
```

Gọi `loadPromptAnalysis()` khi mở project/vào step2b (thêm vào `loadProjectIntoState` và effect khi `activeScreen === "step2b"`).

Trong effect job-poll (job `done`), thêm điều hướng/refresh: khi `job.name === "B2 Phan tich nhan vat"` → `loadPromptAnalysis()`; khi `job.name === "B2 Tao prompt"` → `loadState(true)` (manifest đã có prompt) và ở lại step2b.

- [ ] **Step 2: Truyền props vào PromptScreen**

Tại chỗ render `<PromptScreen .../>` thêm: `promptAnalysis={promptAnalysis}`, `savePromptAnalysis={savePromptAnalysis}`, `saveAssetPrompt={saveAssetPrompt}`, `loadPromptAnalysis={loadPromptAnalysis}`.

- [ ] **Step 3: Mở rộng PromptScreen — khu phân tích nhân vật**

Trong `PromptScreen` nhận thêm props ở chữ ký, và thêm UI (đặt trên danh sách câu): nút "Phân tích nhân vật" gọi `startJob("/api/analyze-story", undefined, "analyze-story")`; khi có `promptAnalysis`, render storyContext (đọc) + danh sách nhân vật sửa được:

```jsx
        <div className="prompt-analysis">
          <div className="panel-title"><div><h2>Phân tích & nhân vật</h2><p>AI dựng bối cảnh và nhân vật từ phụ đề. Sửa cho khớp rồi tạo prompt.</p></div></div>
          <Button variant="secondary" disabled={isBusy} onClick={() => startJob("/api/analyze-story", undefined, "analyze-story")}>
            <Bot className="h-4 w-4" /> Phân tích nhân vật
          </Button>
          {promptAnalysis && (
            <>
              {promptAnalysis.storyContext && <p className="prompt-story">{promptAnalysis.storyContext}</p>}
              <div className="character-list">
                {(promptAnalysis.characters || []).map((ch, i) => (
                  <div className="character-row" key={i}>
                    <Input value={ch.name || ""} placeholder="Tên"
                      onChange={(e) => updateCharacter(i, { name: e.target.value })} />
                    <Input value={ch.role || ""} placeholder="Vai trò"
                      onChange={(e) => updateCharacter(i, { role: e.target.value })} />
                    <Textarea value={ch.description || ""} placeholder="Mô tả ngoại hình đời thật"
                      onChange={(e) => updateCharacter(i, { description: e.target.value })} />
                    <button title="Xoá" onClick={() => removeCharacter(i)}><Trash2 className="h-4 w-4" /></button>
                  </div>
                ))}
                <Button variant="ghost" onClick={addCharacter}><Plus className="h-4 w-4" /> Thêm nhân vật</Button>
              </div>
              <Button disabled={isBusy} onClick={() => startJob("/api/generate-prompts", undefined, "generate-prompts")}>
                <Sparkles className="h-4 w-4" /> Tạo prompt cho từng câu
              </Button>
            </>
          )}
        </div>
```

Helper trong PromptScreen (dùng `savePromptAnalysis` prop, debounce-lite: lưu on blur hoặc ngay):

```jsx
  const chars = promptAnalysis?.characters || []
  const persist = (nextChars) => savePromptAnalysis({ ...(promptAnalysis || {}), characters: nextChars })
  const updateCharacter = (i, patch) => persist(chars.map((c, idx) => idx === i ? { ...c, ...patch } : c))
  const removeCharacter = (i) => persist(chars.filter((_, idx) => idx !== i))
  const addCharacter = () => persist([...chars, { name: "", role: "", description: "" }])
```

- [ ] **Step 4: Mở rộng PromptScreen — prompt per-line**

Trong danh sách asset, dưới câu thoại, thay phần keyword bằng (hoặc thêm) textarea prompt sửa được:

```jsx
            <Textarea className="asset-prompt" value={asset.prompt || ""} placeholder="Prompt ảnh đời thật cho câu này..."
              onChange={(e) => onPromptChange(asset.asset_id, e.target.value)}
              onBlur={(e) => saveAssetPrompt(asset.asset_id, e.target.value)} />
```

(Quản lý giá trị cục bộ trước khi blur để tránh mỗi keystroke gọi API — dùng một map state cục bộ `editingPrompts` trong PromptScreen, hoặc lưu on blur như trên.)

- [ ] **Step 5: Style**

Thêm vào `webui/src/styles.css`:

```css
.prompt-analysis { margin-bottom:18px; }
.prompt-story { color:#cbd5e1; font-size:13px; line-height:20px; margin:8px 0; }
.character-list { display:flex; flex-direction:column; gap:10px; margin:10px 0; }
.character-row { display:grid; grid-template-columns:140px 160px 1fr auto; gap:8px; align-items:start; }
.character-row .asset-prompt, .character-row textarea { min-height:44px; }
.asset-prompt { width:100%; min-height:56px; font-size:13px; }
```

- [ ] **Step 6: Verify build**

Run: `cd webui && npm run build`
Expected: build thành công.

- [ ] **Step 7: Manual verification**

Chạy app: vào B1 lưu phụ đề → B2 tạo voice → màn Prompt: bấm "Phân tích nhân vật" (cần có `gemini_api_key` trong Cài đặt) → thấy bối cảnh + nhân vật, sửa 1 nhân vật → bấm "Tạo prompt" → mỗi câu có prompt đời thật (đuôi "...no watermark."), sửa 1 prompt → reload vẫn giữ.

- [ ] **Step 8: Commit**

```bash
git add webui/src/App.jsx webui/src/styles.css
git commit -m "feat(prompt): PromptScreen character editor + per-line real-life prompts"
```

---

## Self-Review (đã rà)

- **Spec coverage:** §1 artifact/`prompt` field → Task 1+2. §2 1 dòng=1 cảnh → Task 1. §3 pha 1 analyze → Task 3. §4 sửa nhân vật (UI) → Task 6. §5 pha 2 + hậu xử lý → Task 2 (enforce) + Task 4. §6 UI prompt per-line → Task 6. §7 API → Task 5. §8 provider → Task 3/4 (`_ai_call` qua `_pack_ai_caller`). Tiêu chí hoàn thành → test Task 1-5 + manual Task 6.
- **Placeholder scan:** không TBD; system prompt `SYS_ANALYZE`/`SYS_PROMPT_REALISTIC` ghi nguyên văn. Ngoại lệ chủ ý: Task 5/6 mượn pattern harness/`PromptScreen` hiện có (implementer đọc file để mirror) — hợp đồng (route, field `prompt`, đuôi tag) cố định.
- **Type consistency:** `prompt_analysis.json` schema + field `prompt` nhất quán; `analyze_story`/`generate_line_prompts`/`_ai_call`/`enforce_realistic_prompt`/`coerce_prompt_array`/`load_prompt_analysis`/`save_prompt_analysis` khớp tên giữa Task 2-5. `REALISTIC_TAG` dùng nhất quán.
- **Rủi ro ghi:** `_pack_ai_caller` đường openai/claude cap `max_tokens=1200` (đủ batch nhỏ; Gemini không cap). `analyze_story` cần subtitle (Task 3 raise). Manifest phải tồn tại trước pha 2 (Task 4 raise) — luồng UI: phân tích cảnh (`/api/analyze`) tạo manifest trước, rồi `/api/generate-prompts`. Task 6 phải đảm bảo manifest đã có (gọi analyze trước generate-prompts) — ghi rõ trong manual.
