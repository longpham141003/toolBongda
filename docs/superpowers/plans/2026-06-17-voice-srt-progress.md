# Lưu SRT khi tạo voice + tiến độ "đoạn i/N" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khi tạo voice (luồng dán kịch bản → Lưu → chọn giọng → tạo voice), băm kịch bản theo cụm câu nhỏ để hiện tiến độ "đoạn i/N" và ghi ra `voices/voice.srt` để bước 3 tái dùng mà không nghe lại voice.

**Architecture:** Thêm hai hàm thuần (pure) vào `app/voice/text_to_voice_cli.py`: bộ băm cụm câu mịn và bộ ghi SRT. Đường Kokoro trong `app/voice/text_to_voice_queue.py` dùng bộ băm mịn (→ tiến độ "đoạn i/N" tự chạy nhờ regex parse đã có ở `web_server.py`) và ghi `voice.srt` cạnh `voice.segments.json`. `generate_voice` trong `app/pipeline/visual_pipeline.py` đổi tên file `.srt` tạm thành `voices/voice.srt`. Bước 3 đã đọc timing có sẵn và không chạy Whisper mặc định — chỉ cần xác nhận không hồi quy.

**Tech Stack:** Python 3, pytest (test thuần, không I/O), FastAPI (web_server), React (frontend — không đổi).

## Global Constraints

- Không động vào hành vi của `split_text_for_text_to_voice` (floor 1000, ceil 12000) — nhiều nơi đang dùng. Bộ băm mịn là hàm RIÊNG.
- Chỉ đường Kokoro đổi cách băm; đường Magic Voice giữ nguyên cách băm (đã có tiến độ).
- Không thêm dependency mới. Hàm test phải thuần, không gọi Kokoro server / subprocess / file I/O nặng.
- Comment/chuỗi log giữ tiếng Việt theo đúng phong cách file hiện có.
- File `.srt` chuẩn: số thứ tự bắt đầu từ 1, timestamp `HH:MM:SS,mmm`, cách nhau một dòng trống.

---

### Task 1: Bộ băm cụm câu mịn (`split_text_into_progress_segments`)

**Files:**
- Modify: `app/voice/text_to_voice_cli.py:67-114` (refactor `split_text_for_text_to_voice` thành wrapper + thêm hàm mới)
- Test: `tests/test_voice_segmentation.py` (create)

**Interfaces:**
- Produces:
  - `_split_text_by_chars(text: str, max_chars: int, *, floor: int, ceil: int) -> list[str]`
  - `split_text_for_text_to_voice(text: str, max_chars: int) -> list[str]` (hành vi KHÔNG đổi: floor=1000, ceil=12000)
  - `split_text_into_progress_segments(text: str, max_chars: int) -> list[str]` (floor=80, ceil=2000)

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_voice_segmentation.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.voice.text_to_voice_cli import (
    split_text_for_text_to_voice,
    split_text_into_progress_segments,
)


class TestProgressSegments:
    def test_empty_returns_empty(self):
        assert split_text_into_progress_segments("", 350) == []

    def test_short_text_single_segment(self):
        assert split_text_into_progress_segments("Hello world.", 350) == ["Hello world."]

    def test_many_sentences_split_into_several_chunks(self):
        text = " ".join(f"Sentence number {i} here." for i in range(40))
        chunks = split_text_into_progress_segments(text, 120)
        # ~24 ký tự/câu, 120 ký tự/đoạn => nhiều đoạn, không phải 1
        assert len(chunks) > 5
        # ghép lại không mất từ
        joined = " ".join(chunks).split()
        assert joined == text.split()

    def test_floor_allows_small_chunks(self):
        text = "One. Two. Three. Four. Five. Six. Seven. Eight."
        chunks = split_text_into_progress_segments(text, 80)
        assert len(chunks) >= 2

    def test_oversized_single_sentence_splits_by_words(self):
        sentence = "word " * 200  # 1 câu ~1000 ký tự, không dấu kết thúc
        chunks = split_text_into_progress_segments(sentence.strip(), 100)
        assert len(chunks) > 1
        assert all(len(c) <= 100 for c in chunks)


class TestBackwardCompatibility:
    def test_existing_splitter_unchanged_for_short(self):
        assert split_text_for_text_to_voice("Hi there.", 10000) == ["Hi there."]

    def test_existing_splitter_floor_still_1000(self):
        # truyền max_chars nhỏ vẫn bị nâng lên >=1000 như cũ
        text = "A. " * 400  # 1200 ký tự
        chunks = split_text_for_text_to_voice(text, 200)
        assert all(len(c) <= 1000 for c in chunks)
        assert len(chunks) >= 1
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python -m pytest tests/test_voice_segmentation.py -v`
Expected: FAIL với `ImportError: cannot import name 'split_text_into_progress_segments'`

- [ ] **Step 3: Refactor + thêm hàm mới**

Trong `app/voice/text_to_voice_cli.py`, thay nguyên hàm `split_text_for_text_to_voice` (dòng 67-114) bằng:

```python
def _split_text_by_chars(text: str, max_chars: int, *, floor: int, ceil: int) -> list[str]:
    source = str(text or "").strip()
    if not source:
        return []

    max_chars = max(floor, min(int(max_chars or ceil), ceil))
    if len(source) <= max_chars:
        return [source]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0

    pieces = [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n\s*\n", source) if item.strip()]
    for piece in pieces:
        if len(piece) > max_chars:
            flush()
            words = piece.split()
            block: list[str] = []
            block_len = 0
            for word in words:
                add = len(word) + (1 if block else 0)
                if block and block_len + add > max_chars:
                    chunks.append(" ".join(block))
                    block = [word]
                    block_len = len(word)
                else:
                    block.append(word)
                    block_len += add
            if block:
                chunks.append(" ".join(block))
            continue

        add = len(piece) + (2 if current else 0)
        if current and current_len + add > max_chars:
            flush()
        current.append(piece)
        current_len += add

    flush()
    return chunks


def split_text_for_text_to_voice(text: str, max_chars: int) -> list[str]:
    # Giữ nguyên hành vi cũ: đoạn lớn (>=1000 ký tự) cho chất lượng tổng hợp tốt.
    return _split_text_by_chars(text, max_chars, floor=1000, ceil=12000)


def split_text_into_progress_segments(text: str, max_chars: int) -> list[str]:
    # Băm mịn theo cụm câu để hiển thị tiến độ "đoạn i/N" và timing theo câu.
    return _split_text_by_chars(text, max_chars, floor=80, ceil=2000)
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `python -m pytest tests/test_voice_segmentation.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add app/voice/text_to_voice_cli.py tests/test_voice_segmentation.py
git commit -m "feat(voice): add fine-grained sentence-cluster splitter for progress"
```

---

### Task 2: Bộ ghi SRT thuần (`build_srt_from_segments` / `write_srt_file`)

**Files:**
- Modify: `app/voice/text_to_voice_cli.py` (thêm hàm, sau khối splitter)
- Test: `tests/test_voice_srt.py` (create)

**Interfaces:**
- Produces:
  - `build_srt_from_segments(segments: list[dict]) -> str`
  - `write_srt_file(path: Path, segments: list[dict]) -> None`
  - Segment dict dạng: `{"text": str, "start": float, "end": float}` (khóa thừa bị bỏ qua).

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_voice_srt.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.voice.text_to_voice_cli import build_srt_from_segments, write_srt_file


def test_empty_segments_returns_empty_string():
    assert build_srt_from_segments([]) == ""


def test_basic_srt_format():
    segments = [
        {"text": "Câu một.", "start": 0.0, "end": 2.5},
        {"text": "Câu hai.", "start": 2.5, "end": 5.0},
    ]
    out = build_srt_from_segments(segments)
    assert out == (
        "1\n00:00:00,000 --> 00:00:02,500\nCâu một.\n\n"
        "2\n00:00:02,500 --> 00:00:05,000\nCâu hai.\n"
    )


def test_skips_blank_text_and_renumbers():
    segments = [
        {"text": "  ", "start": 0.0, "end": 1.0},
        {"text": "Thật.", "start": 1.0, "end": 2.0},
    ]
    out = build_srt_from_segments(segments)
    assert out.startswith("1\n00:00:01,000 --> 00:00:02,000\nThật.")


def test_non_increasing_end_is_clamped():
    segments = [{"text": "X.", "start": 3.0, "end": 3.0}]
    out = build_srt_from_segments(segments)
    assert "00:00:03,000 --> 00:00:03,050" in out


def test_write_srt_file(tmp_path):
    target = tmp_path / "voice.srt"
    write_srt_file(target, [{"text": "Hi.", "start": 0.0, "end": 1.0}])
    assert target.read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> 00:00:01,000\nHi.")
```

- [ ] **Step 2: Chạy test để xác nhận FAIL**

Run: `python -m pytest tests/test_voice_srt.py -v`
Expected: FAIL với `ImportError: cannot import name 'build_srt_from_segments'`

- [ ] **Step 3: Thêm hàm ghi SRT**

Trong `app/voice/text_to_voice_cli.py`, thêm ngay sau `split_text_into_progress_segments`:

```python
def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds or 0.0) * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def build_srt_from_segments(segments: list[dict]) -> str:
    blocks: list[str] = []
    index = 0
    for segment in segments or []:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        index += 1
        start = float(segment.get("start") or 0.0)
        end = float(segment.get("end") or 0.0)
        if end <= start:
            end = start + 0.05
        blocks.append(f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_srt_file(path: Path, segments: list[dict]) -> None:
    Path(path).write_text(build_srt_from_segments(segments), encoding="utf-8")
```

- [ ] **Step 4: Chạy test để xác nhận PASS**

Run: `python -m pytest tests/test_voice_srt.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add app/voice/text_to_voice_cli.py tests/test_voice_srt.py
git commit -m "feat(voice): add pure SRT builder/writer from timing segments"
```

---

### Task 3: Đường Kokoro dùng băm mịn + ghi voice.srt (cả Magic Voice)

**Files:**
- Modify: `app/voice/text_to_voice_queue.py:16-22` (import), `:565-567` (băm Kokoro), `:636-653` (ghi srt Kokoro), `:777-795` (ghi srt Magic Voice)
- Modify: `app/pipeline/visual_pipeline.py:220-237` (đổi tên file `.srt` tạm → `voices/voice.srt`)

**Interfaces:**
- Consumes: `split_text_into_progress_segments`, `write_srt_file` (Task 1, 2); `combined_segments` (Kokoro), `estimated_segments` (Magic Voice) đã có sẵn trong hàm.
- Produces: file `voices/voice.srt` cạnh `voices/voice.wav`; log Kokoro `"đang tạo đoạn i/N"` với N = số cụm câu.

- [ ] **Step 1: Thêm import**

Trong `app/voice/text_to_voice_queue.py`, sửa khối import (dòng 16-22) thành:

```python
from .text_to_voice_cli import (
    combine_wavs,
    is_voice_segment_text,
    sanitize_text_for_tts,
    shift_segment_timing,
    split_text_for_text_to_voice,
    split_text_into_progress_segments,
    write_srt_file,
)
```

- [ ] **Step 2: Đổi cách băm đường Kokoro**

Trong `submit_file`, thay 3 dòng (565-567):

```python
        max_chars = max(1000, min(int(self.settings.get("text_to_voice_max_chars") or 10000), 12000))
        chunks = split_text_for_text_to_voice(text, max_chars)
        chunk_estimate = len(chunks)
```

bằng:

```python
        # Băm mịn theo cụm câu để tiến độ "đoạn i/N" có ý nghĩa và timing theo câu.
        progress_chars = max(80, min(int(self.settings.get("text_to_voice_progress_chars") or 350), 2000))
        chunks = split_text_into_progress_segments(text, progress_chars)
        chunk_estimate = len(chunks)
```

(Lưu ý: đường Magic Voice ở `_submit_file_magicvoice` tự băm riêng tại dòng 668, KHÔNG ảnh hưởng.)

- [ ] **Step 3: Ghi voice.srt sau segments.json (Kokoro)**

Trong `submit_file`, ngay SAU khối ghi `output_path.with_suffix(".segments.json")` (kết thúc ở dòng 653, trước `finally`), thêm:

```python
            write_srt_file(output_path.with_suffix(".srt"), combined_segments)
```

- [ ] **Step 4: Ghi voice.srt sau segments.json (Magic Voice)**

Trong `_submit_file_magicvoice`, ngay SAU khối ghi `output_path.with_suffix(".segments.json")` (kết thúc ở dòng 795, trước `finally`), thêm:

```python
            write_srt_file(output_path.with_suffix(".srt"), estimated_segments)
```

- [ ] **Step 5: Đổi tên file .srt tạm → voices/voice.srt**

Trong `app/pipeline/visual_pipeline.py`, hàm `generate_voice`, sửa danh sách `replacements` (dòng 220-224) thành:

```python
        replacements = [
            (temporary_path, output_path),
            (temporary_path.with_suffix(".segments.json"), output_path.with_suffix(".segments.json")),
            (temporary_path.with_suffix(".srt"), output_path.with_suffix(".srt")),
            (temporary_path.with_suffix(".ttv.meta.json"), output_path.with_suffix(".ttv.meta.json")),
        ]
```

và trong khối `finally` (dòng 235-237), thêm dòng dọn dẹp file srt tạm:

```python
    finally:
        runner.close()
        temporary_path.unlink(missing_ok=True)
        temporary_path.with_suffix(".segments.json").unlink(missing_ok=True)
        temporary_path.with_suffix(".srt").unlink(missing_ok=True)
        temporary_path.with_suffix(".ttv.meta.json").unlink(missing_ok=True)
```

- [ ] **Step 6: Kiểm tra không vỡ import / cú pháp**

Run: `python -c "import app.voice.text_to_voice_queue; import app.pipeline.visual_pipeline; print('ok')"`
Expected: in ra `ok` (không lỗi import/cú pháp).

> Nếu lệnh trên báo thiếu dependency nặng (ví dụ chỉ khi import kéo theo gói TTS), chạy thay bằng kiểm tra biên dịch:
> Run: `python -m py_compile app/voice/text_to_voice_queue.py app/voice/text_to_voice_cli.py app/pipeline/visual_pipeline.py`
> Expected: không output, exit code 0.

- [ ] **Step 7: Chạy lại toàn bộ test thuần để chắc không hồi quy**

Run: `python -m pytest tests/test_voice_segmentation.py tests/test_voice_srt.py tests/test_visual_pipeline_pure.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/voice/text_to_voice_queue.py app/pipeline/visual_pipeline.py
git commit -m "feat(voice): fine-grained progress + persist voice.srt on voice creation"
```

---

### Task 4: Xác nhận bước 3 dùng SRT/timing có sẵn, không nghe lại (verification)

**Files:**
- Read-only: `app/pipeline/visual_pipeline.py:820-876` (`build_asset_manifest`)

**Interfaces:**
- Consumes: `voices/voice.segments.json` + `voices/voice.srt` do Task 3 tạo.

Bước 3 đã đọc `load_timing()` (segments.json) và chỉ chạy Whisper khi `settings["whisper_timing_enabled"]` bật (mặc định False). Task này chỉ xác nhận bằng tay, không đổi code.

- [ ] **Step 1: Xác nhận điều kiện Whisper mặc định tắt**

Mở `app/pipeline/visual_pipeline.py` dòng 831 và xác nhận: `if bool(settings.get("whisper_timing_enabled", False)):` — mặc định False ⇒ không nghe lại. Nếu đúng, không cần sửa.

- [ ] **Step 2: Chạy thử thực tế (manual)**

1. Chạy app: `run_visual_capcut_web.bat` (theo `memory/project_run_instructions.md`).
2. Dán một kịch bản nhiều câu (>5 câu) → Lưu → chọn giọng → tạo voice.
3. Quan sát: thanh/nhãn tiến độ hiện "Đang tạo voice đoạn i/N" với **N > 1**.
4. Mở thư mục project `voices/` → có `voice.srt`, mở ra thấy số thứ tự + timestamp tăng dần khớp số câu.
5. Sang bước 3 (phân cảnh) → tạo cảnh ngay từ SRT/timing, **không** có log "nghe lại"/"Whisper timing".

Expected: cả 5 điểm đạt.

- [ ] **Step 3 (tùy chọn): dòng trạng thái "Đã lưu SRT"**

Chỉ làm nếu người dùng muốn. Trong `app/web/web_server.py` `voice_log`/task của `/api/voice`, có thể thêm log `"Đã lưu phụ đề SRT để dùng cho bước 3."` sau khi job xong. Frontend đã hiển thị log nên không cần đổi React.

---

## Self-Review

**1. Spec coverage:**
- "Lưu SRT cho bước 3, không nghe lại / không sinh mới SRT" → Task 2 (bộ ghi) + Task 3 (ghi `voices/voice.srt`) + Task 4 (xác nhận bước 3 không Whisper). ✔
- "Hiển thị tiến độ đoạn i/N (tham khảo Magic Voice)" → Task 1 (băm mịn) + Task 3 Step 2 (dùng băm mịn ⇒ regex `đoạn (\d+)/(\d+)` ở `web_server.py` cập nhật tiến độ tự động). ✔
- "Băm kịch bản như Magic Voice" → Task 1 + Task 3 (Kokoro băm cụm câu; cả hai đường ghi SRT). ✔

**2. Placeholder scan:** Không có TODO/TBD; mọi step có code/lệnh cụ thể. ✔

**3. Type consistency:** `split_text_into_progress_segments(text, max_chars) -> list[str]`, `write_srt_file(path, segments)`, `build_srt_from_segments(segments) -> str` dùng nhất quán giữa các task. Segment dict `{"text","start","end"}` khớp `combined_segments`/`estimated_segments` đang tạo trong queue. ✔
