# SP2 — Voice bám theo SRT: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo giọng đọc theo từng dòng `subtitle.json` (1 dòng = 1 lần TTS, đo thời lượng thật, ghép có pause 0.25s), cho cả Kokoro lẫn Magic Voice; timing thật ghi đè timing ước tính trong `subtitle.json`/`subtitle.srt`.

**Architecture:** Thêm hàm thuần `assemble_line_segments` (lắp ráp timing cộng dồn từ thời lượng per-line). Thêm phương thức `TextToVoiceRunner.submit_lines(lines, label, output_path)` chạy per-line cho cả hai engine qua 2 helper mỏng `_kokoro_audio_for_text` / `_clone_audio_for_text` (mỗi cái tạo audio cho MỘT đoạn text, trả `(part_path, duration)`). `submit_file` (đường preview/whole-text) GIỮ NGUYÊN. `generate_voice` đọc `subtitle.json`, gọi `submit_lines`, rồi ghi đè timing vào `subtitle.json`. `/api/voice` báo lỗi nếu chưa có phụ đề.

**Tech Stack:** Python 3 + FastAPI + pytest; module voice `app/voice/text_to_voice_queue.py`, `app/voice/text_to_voice_cli.py`; SP1 `app/pipeline/subtitle_store.py`.

## Global Constraints

- Voice đọc các dòng `scripts/subtitle.json` (SP1 canonical, mỗi dòng `{index,start,end,text,edited}`). KHÔNG dùng `script_final.txt` làm text TTS.
- Khoảng lặng giữa các dòng đã ghép = **0.25s** cho CẢ HAI engine (hằng số cứng trong `combine_wavs`, `app/voice/text_to_voice_cli.py:158`). Timing lắp ráp phải dùng đúng 0.25s.
- 1 dòng SRT = 1 segment voice; `voice.segments.json` có số segment = số dòng, `timing_source: "measured"`, không `estimated_magicvoice`.
- Sau khi tạo voice, ghi đè `start`/`end` trong `subtitle.json` bằng timing thật (giữ `text`/`edited`), sinh lại `subtitle.srt` qua `save_subtitle`.
- Tiến độ log dạng `Text to Voice {label}: đang tạo đoạn {i}/{N}` (regex `đoạn i/N` trong `/api/voice` đã có) — N = số dòng.
- Thiếu/empty `subtitle.json` → lỗi: "Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước khi tạo giọng đọc."
- Engine chọn như cũ: `voice_clone_enabled` + `_clone_reference_path(settings)` → Magic Voice; ngược lại Kokoro.
- Giữ nguyên `submit_file` (preview/chapter) và không hồi quy voice-preview.

---

### Task 1: Hàm thuần `assemble_line_segments`

**Files:**
- Modify: `app/pipeline/subtitle_store.py` (thêm hàm; đặt sau `normalize_subtitle_segments`)
- Test: `tests/test_assemble_line_segments.py`

**Interfaces:**
- Produces: `assemble_line_segments(lines: list[dict], durations: list[float], pause: float = 0.25) -> list[dict]` — trả list `{index,start,end,text,edited,timing_source:"measured"}`, start/end cộng dồn, pause giữa các dòng (không sau dòng cuối).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assemble_line_segments.py
from app.pipeline.subtitle_store import assemble_line_segments


def test_cumulative_timing_with_pause():
    lines = [{"text": "A", "edited": False}, {"text": "B", "edited": True}, {"text": "C"}]
    segs = assemble_line_segments(lines, [1.0, 2.0, 0.5], pause=0.25)
    assert [s["index"] for s in segs] == [1, 2, 3]
    assert (segs[0]["start"], segs[0]["end"]) == (0.0, 1.0)
    assert (segs[1]["start"], segs[1]["end"]) == (1.25, 3.25)   # 1.0 + 0.25 pause
    assert (segs[2]["start"], segs[2]["end"]) == (3.5, 4.0)     # 3.25 + 0.25 pause
    assert segs[1]["edited"] is True
    assert all(s["timing_source"] == "measured" for s in segs)
    assert segs[0]["text"] == "A"


def test_zero_duration_gets_min_span():
    segs = assemble_line_segments([{"text": "A"}], [0.0])
    assert segs[0]["end"] > segs[0]["start"]


def test_missing_duration_treated_as_zero():
    segs = assemble_line_segments([{"text": "A"}, {"text": "B"}], [1.0])  # 2nd dur missing
    assert segs[1]["end"] > segs[1]["start"]
    assert segs[1]["start"] == 1.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_assemble_line_segments.py -v`
Expected: FAIL — `ImportError: cannot import name 'assemble_line_segments'`

- [ ] **Step 3: Write minimal implementation**

Thêm vào `app/pipeline/subtitle_store.py` (sau `normalize_subtitle_segments`):

```python
def assemble_line_segments(
    lines: list[dict], durations: list[float], pause: float = 0.25
) -> list[dict]:
    """Build one segment per subtitle line from measured per-line audio durations.

    `durations[i]` is the real audio length (seconds) of line i; `pause` is the
    silence inserted between consecutive lines (combine_wavs uses 0.25s). No pause
    after the last line. Carries text/edited through so the result is also valid
    subtitle rows for save_subtitle.
    """
    segments: list[dict] = []
    cursor = 0.0
    total = len(lines)
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        dur = max(0.0, float(durations[i] if i < len(durations) else 0.0))
        start = cursor
        end = start + dur
        if end <= start:
            end = start + 0.05
        segments.append(
            {
                "index": i + 1,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": str(line.get("text") or "").strip(),
                "edited": bool(line.get("edited")),
                "timing_source": "measured",
            }
        )
        cursor = end
        if i < total - 1:
            cursor += max(0.0, float(pause))
    return segments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_assemble_line_segments.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/subtitle_store.py tests/test_assemble_line_segments.py
git commit -m "feat(voice): assemble_line_segments — measured per-line timing"
```

---

### Task 2: Tách `_clone_audio_for_text` từ `_submit_file_magicvoice` (giữ nguyên hành vi)

**Files:**
- Modify: `app/voice/text_to_voice_queue.py` (`__init__` thêm cache; tách helper từ thân vòng lặp `_submit_file_magicvoice`, ~dòng 669-809)

**Interfaces:**
- Produces: `TextToVoiceRunner._clone_audio_for_text(self, text: str, label: str, index: int, total: int, output_path: Path) -> tuple[Path, float]` — tạo 1 part wav clone cho một đoạn text, trả `(part_path, duration_seconds)`; tự bootstrap MagicVoice (cache trên `self`); log `đang tạo đoạn {index}/{total}`.

Đây là refactor **giữ nguyên hành vi**: `_submit_file_magicvoice` (đường clone whole-text) sau khi tách vẫn tạo cùng output. Không có test tự động cho đường clone (cần subprocess), nên xác minh bằng: full suite không hồi quy + đối chiếu kỹ code.

- [ ] **Step 1: Thêm cache bootstrap vào `__init__`**

Trong `TextToVoiceRunner.__init__` (gần `self._last_sampling_log = ""`, ~dòng 522) thêm:

```python
        self._magicvoice_cmd: list[str] | None = None
```

- [ ] **Step 2: Thêm helper `_clone_audio_for_text`**

Thêm phương thức mới (đặt ngay trước `_submit_file_magicvoice`). Thân lấy nguyên văn từ vòng lặp hiện có (dòng ~680-768), gói lại để tạo MỘT part và trả `(part_path, duration)`:

```python
    def _clone_audio_for_text(
        self, text: str, label: str, index: int, total: int, output_path: Path
    ) -> tuple[Path, float]:
        if self._magicvoice_cmd is None:
            _root, self._magicvoice_cmd = bootstrap_magicvoice(self.settings, log=self.log)
        python_cmd = self._magicvoice_cmd
        reference_path = _clone_reference_path(self.settings)
        timeout_seconds = max(900, int(self.settings.get("voice_clone_timeout") or 3600))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.wav")
        text_part_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.txt")
        stdout_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.stdout.log")
        stderr_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.stderr.log")
        text_part_path.write_text(text, encoding="utf-8")
        self.log(f"Text to Voice {label}: đang tạo đoạn {index}/{total}")
        command = [
            *python_cmd,
            str(Path(__file__).resolve().parent / "magicvoice_clone_cli.py"),
            "--text-file", str(text_part_path),
            "--ref", str(reference_path),
            "--out", str(part_path),
            "--steps", str(max(8, min(16, int(self.settings.get("magicvoice_steps") or 16)))),
            "--speed", str(float(self.settings.get("text_to_voice_speed") or 1.0)),
            "--device", str(self.settings.get("magicvoice_device") or "auto"),
            "--dtype", str(self.settings.get("magicvoice_dtype") or "auto"),
            "--sentence-pause", str(float(self.settings.get("magicvoice_sentence_pause") or 0.28)),
            "--clause-pause", str(float(self.settings.get("magicvoice_clause_pause") or 0.12)),
            "--paragraph-pause", str(float(self.settings.get("magicvoice_paragraph_pause") or 0.43)),
            "--clarity-speed", str(float(self.settings.get("magicvoice_clarity_speed") or 0.96)),
            "--language", str(self.settings.get("text_to_voice_language") or "vi"),
            "--batch-size", "1",
        ]
        with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
            process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parents[1]),
                stdout=stdout,
                stderr=stderr,
                text=True,
                **_win_hidden_kwargs(),
            )
            deadline = time.time() + timeout_seconds
            while process.poll() is None:
                if self.stop_check():
                    _terminate_process_tree(process, timeout=5)
                    part_path.unlink(missing_ok=True)
                    raise RuntimeError("Stopped.")
                if time.time() >= deadline:
                    _terminate_process_tree(process, timeout=5)
                    raise TimeoutError(f"MagicVoice quá thời gian ở đoạn {index}/{total}.")
                time.sleep(0.25)
            returncode = int(process.returncode or 0)
        part_duration = _audio_duration_seconds(part_path) if part_path.exists() else 0.0
        if part_duration <= 0:
            detail_lines: list[str] = []
            for path in (stderr_path, stdout_path):
                if not path.exists():
                    continue
                for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    lowered = line.lower()
                    if (
                        "loading weights:" in lowered
                        or "fetching " in lowered
                        or line.startswith("[transformers]")
                        or "%|" in line
                        or "could not load symbol" in lowered
                        or "runtimewarning" in lowered
                        or "filterwarnings" in lowered
                    ):
                        continue
                    detail_lines.append(line)
            detail = " ".join(detail_lines[-8:]) or f"MagicVoice không tạo được file WAV hợp lệ (mã thoát {returncode})."
            raise RuntimeError(f"MagicVoice clone thất bại ở đoạn {index}/{total}. {detail}")
        if returncode != 0:
            self.log(
                f"Text to Voice {label}: đoạn {index}/{total} đã có audio hợp lệ; "
                "bỏ qua cảnh báo phụ của MagicVoice."
            )
        text_part_path.unlink(missing_ok=True)
        return part_path, part_duration
```

- [ ] **Step 3: Thay vòng lặp trong `_submit_file_magicvoice` để gọi helper**

Trong `_submit_file_magicvoice`, bỏ dòng `root, python_cmd = bootstrap_magicvoice(...)` ở đầu, và thay TOÀN BỘ thân vòng `for index, chunk in enumerate(chunks, start=1): ...` (phần tạo part + validate, ~dòng 677-768) bằng:

```python
        try:
            for index, chunk in enumerate(chunks, start=1):
                if self.stop_check():
                    raise RuntimeError("Stopped.")
                part_path, _part_duration = self._clone_audio_for_text(
                    chunk, label, index, len(chunks), output_path
                )
                generated_paths.append(part_path)
```

Giữ nguyên phần sau (`if len(generated_paths) == 1: ... combine_wavs ... estimated_segments ... write segments.json/srt ... finally cleanup`). Lưu ý `max_chars`/`chunks = split_text_for_text_to_voice(text, max_chars)` vẫn giữ (đường whole-text). `timeout_seconds` cục bộ trong hàm không còn cần (helper tự tính) — có thể bỏ biến thừa nếu có.

- [ ] **Step 4: Chạy full suite (lưới regression)**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS như trước (398), không lỗi mới. (Đường clone không có test tự động; xác minh bằng đối chiếu code: output `_submit_file_magicvoice` không đổi.)

- [ ] **Step 5: Commit**

```bash
git add app/voice/text_to_voice_queue.py
git commit -m "refactor(voice): extract _clone_audio_for_text (behavior-preserving)"
```

---

### Task 3: `submit_lines` + `_kokoro_audio_for_text` (chạy per-line cả hai engine)

**Files:**
- Modify: `app/voice/text_to_voice_queue.py` (thêm import `assemble_line_segments`; thêm `_kokoro_audio_for_text` và `submit_lines`)
- Test: `tests/test_submit_lines.py`

**Interfaces:**
- Consumes: `assemble_line_segments` (Task 1); `_clone_audio_for_text` (Task 2); `combine_wavs`, `write_srt_file`, `_kokoro_generate`, `_clone_reference_path`, `normalize_kokoro_language`, `kokoro_voice_choices`, `_audio_duration_seconds` (đã có).
- Produces: `TextToVoiceRunner.submit_lines(self, lines: list[dict], label: str, output_path: Path) -> str` — tạo audio per-line cho cả hai engine; ghi `output_path` + `.segments.json` (`segments` từ `assemble_line_segments`, `timing_source:"measured"`) + `.srt`. Và `_kokoro_audio_for_text(self, text, label, index, total, output_path) -> tuple[Path, float]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_submit_lines.py
import json
from pathlib import Path

from app.voice import text_to_voice_queue as q


def _runner(tmp_path, settings):
    r = q.TextToVoiceRunner(settings, log=lambda _m: None)
    r.root = tmp_path          # non-None: submit_lines proceeds without start()
    r.python = tmp_path
    return r


def _stub_part(tmp_path):
    # returns a fn that "generates" a part wav and a fixed duration
    def gen(text, label, index, total, output_path):
        p = Path(output_path).with_name(f"part{index:03d}.wav")
        p.write_bytes(b"RIFFfake")
        return p, float(index)  # durations 1.0, 2.0, ...
    return gen


def test_submit_lines_kokoro(tmp_path, monkeypatch):
    r = _runner(tmp_path, {})
    monkeypatch.setattr(r, "_kokoro_audio_for_text", _stub_part(tmp_path))
    monkeypatch.setattr(q, "combine_wavs", lambda paths, out: (Path(out).write_bytes(b"RIFFfake"), 3.25)[1])
    out = tmp_path / "voice.working.wav"
    lines = [{"index": 1, "text": "One.", "edited": False}, {"index": 2, "text": "Two.", "edited": True}]
    r.submit_lines(lines, "test", out)
    data = json.loads(out.with_suffix(".segments.json").read_text(encoding="utf-8"))
    assert data["engine"] == "kokoro-server"
    assert len(data["segments"]) == 2
    assert (data["segments"][0]["start"], data["segments"][0]["end"]) == (0.0, 1.0)
    assert (data["segments"][1]["start"], data["segments"][1]["end"]) == (1.25, 3.25)
    assert all(s["timing_source"] == "measured" for s in data["segments"])
    assert data["segments"][1]["edited"] is True
    assert out.with_suffix(".srt").exists()


def test_submit_lines_clone(tmp_path, monkeypatch):
    r = _runner(tmp_path, {"voice_clone_enabled": True})
    monkeypatch.setattr(q, "_clone_reference_path", lambda settings: tmp_path / "ref.wav")
    monkeypatch.setattr(r, "_clone_audio_for_text", _stub_part(tmp_path))
    monkeypatch.setattr(q, "combine_wavs", lambda paths, out: (Path(out).write_bytes(b"RIFFfake"), 3.25)[1])
    out = tmp_path / "voice.working.wav"
    lines = [{"index": 1, "text": "Một.", "edited": False}, {"index": 2, "text": "Hai.", "edited": False}]
    r.submit_lines(lines, "test", out)
    data = json.loads(out.with_suffix(".segments.json").read_text(encoding="utf-8"))
    assert data["engine"] == "magicvoice"
    assert data["timing_source"] == "measured"
    assert len(data["segments"]) == 2


def test_submit_lines_single_line_no_combine(tmp_path, monkeypatch):
    r = _runner(tmp_path, {})
    monkeypatch.setattr(r, "_kokoro_audio_for_text", _stub_part(tmp_path))
    # combine_wavs must NOT be called for a single line; make it raise if used
    monkeypatch.setattr(q, "combine_wavs", lambda *a, **k: (_ for _ in ()).throw(AssertionError("combine called")))
    out = tmp_path / "voice.working.wav"
    r.submit_lines([{"index": 1, "text": "Solo.", "edited": False}], "test", out)
    data = json.loads(out.with_suffix(".segments.json").read_text(encoding="utf-8"))
    assert len(data["segments"]) == 1 and data["segments"][0]["start"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_submit_lines.py -v`
Expected: FAIL — `AttributeError: 'TextToVoiceRunner' object has no attribute 'submit_lines'`

- [ ] **Step 3: Thêm import**

Gần đầu `app/voice/text_to_voice_queue.py`, cạnh import từ `text_to_voice_cli`, thêm:

```python
from app.pipeline.subtitle_store import assemble_line_segments
```

- [ ] **Step 4: Thêm `_kokoro_audio_for_text` và `submit_lines`**

Thêm hai phương thức (đặt sau `submit_file`, trước `_submit_file_magicvoice`):

```python
    def _kokoro_audio_for_text(
        self, text: str, label: str, index: int, total: int, output_path: Path
    ) -> tuple[Path, float]:
        requested_language = str(self.settings.get("text_to_voice_language") or "en").lower()
        language, _warn = normalize_kokoro_language(requested_language)
        voices = kokoro_voice_choices(self.settings, language)
        voice = str(self.settings.get("text_to_voice_voice") or "").strip()
        if voice not in voices:
            voice = voices[0]
        self.log(f"Text to Voice {label}: đang tạo đoạn {index}/{total}")
        result = _kokoro_generate(
            self.settings,
            {
                "text": text,
                "lang": KOKORO_LANGUAGE_CODES[language],
                "voice": voice,
                "speed": float(self.settings.get("text_to_voice_speed") or 1.0),
                "prefix": "preview" if label == "preview" else "",
                "delivery": str(self.settings.get("text_to_voice_delivery") or "dramatic"),
            },
            timeout_seconds=self._adaptive_timeout_seconds(1),
        )
        source_path = Path(str(result.get("path") or ""))
        if not source_path.exists():
            raise RuntimeError(f"Kokoro không tạo file: {source_path}")
        part_path = output_path.with_name(f"{output_path.stem}.part{index:03d}.wav")
        shutil.copy2(source_path, part_path)
        return part_path, float(result.get("duration") or 0.0)

    def submit_lines(self, lines: list[dict], label: str, output_path: Path) -> str:
        if self.root is None or self.python is None:
            raise RuntimeError("Text to Voice runner chưa start.")
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        use_clone = bool(self.settings.get("voice_clone_enabled")) and bool(_clone_reference_path(self.settings))
        total = len(lines)
        parts: list[Path] = []
        durations: list[float] = []
        try:
            for i, line in enumerate(lines, start=1):
                if self.stop_check():
                    raise RuntimeError("Stopped.")
                text = str(line.get("text") or "").strip()
                if use_clone:
                    part_path, duration = self._clone_audio_for_text(text, label, i, total, output_path)
                else:
                    part_path, duration = self._kokoro_audio_for_text(text, label, i, total, output_path)
                parts.append(part_path)
                durations.append(duration)
            if not parts:
                raise ValueError("Không có dòng phụ đề để tạo voice.")
            if len(parts) == 1:
                shutil.copy2(parts[0], output_path)
                total_duration = durations[0]
            else:
                total_duration = combine_wavs(parts, output_path)
                if total_duration <= 0:
                    total_duration = _audio_duration_seconds(output_path)
            segments = assemble_line_segments(lines, durations, 0.25)
            engine = "magicvoice" if use_clone else "kokoro-server"
            output_path.with_suffix(".segments.json").write_text(
                json.dumps(
                    {
                        "audio": str(output_path),
                        "duration": round(float(total_duration), 4),
                        "sampleRate": 24000,
                        "lang": str(self.settings.get("text_to_voice_language") or "vi"),
                        "voice": str(_clone_reference_path(self.settings) or self.settings.get("text_to_voice_voice") or ""),
                        "speed": float(self.settings.get("text_to_voice_speed") or 1.0),
                        "delivery": "magicvoice-clone" if use_clone else str(self.settings.get("text_to_voice_delivery") or "dramatic"),
                        "engine": engine,
                        "timing_source": "measured",
                        "segments": segments,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            write_srt_file(output_path.with_suffix(".srt"), segments)
        finally:
            for part_path in parts:
                part_path.unlink(missing_ok=True)
        self.log(f"Text to Voice {label}: đã lưu audio {output_path.name} ({total} dòng)")
        return str(output_path)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_submit_lines.py -v`
Expected: PASS (3 passed). Nếu một helper thật chạm tới hệ thống/mạng trong môi trường của bạn, đã được stub trong test; không cần stub thêm vì test stub trực tiếp `_kokoro_audio_for_text`/`_clone_audio_for_text`.

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS.

- [ ] **Step 7: Commit**

```bash
git add app/voice/text_to_voice_queue.py tests/test_submit_lines.py
git commit -m "feat(voice): submit_lines — per-line voice for both engines"
```

---

### Task 4: `generate_voice` đọc subtitle + ghi đè timing

**Files:**
- Modify: `app/pipeline/visual_pipeline.py` (`generate_voice`, ~dòng 210-240; thêm import `load_subtitle, save_subtitle`)
- Test: `tests/test_generate_voice_subtitle.py`

**Interfaces:**
- Consumes: `load_subtitle`, `save_subtitle` (SP1, `app/pipeline/subtitle_store.py`); `TextToVoiceRunner.submit_lines` (Task 3); `read_json` (đã có trong visual_pipeline).
- Produces: `generate_voice` đọc `subtitle.json` → `runner.submit_lines(lines, ...)`; raise nếu không có phụ đề; sau khi rename, ghi đè timing `subtitle.json` từ `voices/voice.segments.json`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_generate_voice_subtitle.py
import sys
import types
from pathlib import Path
import unittest.mock as mock

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

with mock.patch.dict(
    sys.modules,
    {"app.voice.text_to_voice_queue": types.ModuleType("app.voice.text_to_voice_queue")},
):
    sys.modules["app.voice.text_to_voice_queue"].TextToVoiceRunner = mock.MagicMock()  # type: ignore[attr-defined]
    from app.pipeline import visual_pipeline as vp

from app.pipeline.subtitle_store import save_subtitle, load_subtitle


class _FakeRunner:
    """Mimics submit_lines: writes measured segments.json + srt next to output."""

    def __init__(self, settings, log, stop_check):
        self.captured_lines = None

    def start(self):
        return None

    def submit_lines(self, lines, label, output_path):
        self.captured_lines = lines
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFFfake")
        # Real measured timing differs from the estimated timing in subtitle.json.
        segments = [
            {"index": 1, "start": 0.0, "end": 1.5, "text": lines[0]["text"], "edited": lines[0].get("edited", False), "timing_source": "measured"},
            {"index": 2, "start": 1.75, "end": 4.0, "text": lines[1]["text"], "edited": lines[1].get("edited", False), "timing_source": "measured"},
        ]
        import json
        output_path.with_suffix(".segments.json").write_text(
            json.dumps({"engine": "kokoro-server", "segments": segments}, ensure_ascii=False),
            encoding="utf-8",
        )
        output_path.with_suffix(".srt").write_text("1\n00:00:00,000 --> 00:00:01,500\n" + lines[0]["text"] + "\n", encoding="utf-8")
        return str(output_path)

    def close(self):
        return None


def _project_with_subtitle(tmp_path):
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text("Câu một. Câu hai.", encoding="utf-8")
    # estimated subtitle from SP1 (timing will be overwritten by measured)
    save_subtitle(project, [
        {"start": 0.0, "end": 2.0, "text": "Câu một.", "edited": True},
        {"start": 2.0, "end": 4.5, "text": "Câu hai.", "edited": False},
    ])
    return project


def test_generate_voice_reads_subtitle_and_overwrites_timing(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "TextToVoiceRunner", _FakeRunner)
    project = _project_with_subtitle(tmp_path)

    result = vp.generate_voice(project, {}, log=lambda _m: None)

    assert result == project / "voices" / "voice.wav"
    assert (project / "voices" / "voice.segments.json").exists()
    # subtitle.json timing overwritten by measured timing, text + edited preserved
    rows = load_subtitle(project)
    assert [r["text"] for r in rows] == ["Câu một.", "Câu hai."]
    assert rows[0]["edited"] is True
    assert (rows[0]["start"], rows[0]["end"]) == (0.0, 1.5)
    assert (rows[1]["start"], rows[1]["end"]) == (1.75, 4.0)


def test_generate_voice_requires_subtitle(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "TextToVoiceRunner", _FakeRunner)
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text("Câu một.", encoding="utf-8")
    import pytest
    with pytest.raises(Exception) as exc:
        vp.generate_voice(project, {}, log=lambda _m: None)
    assert "phụ đề" in str(exc.value).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generate_voice_subtitle.py -v`
Expected: FAIL — `_FakeRunner` has no `submit_file`/generate_voice still calls submit_file (AttributeError) hoặc timing không bị ghi đè.

- [ ] **Step 3: Thêm import vào `visual_pipeline.py`**

Gần các import nội bộ khác (tìm chỗ import từ `app.pipeline` hoặc đầu file), thêm:

```python
from app.pipeline.subtitle_store import load_subtitle, save_subtitle
```

(Nếu đã có import vòng do `text_to_voice_queue` import `subtitle_store` import `text_to_voice_cli` — không liên quan `visual_pipeline`; an toàn.)

- [ ] **Step 4: Sửa `generate_voice`**

Thay thân `generate_voice` (dòng 210-240) bằng:

```python
def generate_voice(project: Path, settings: dict, log: Callable[[str], None], stop_check=lambda: False) -> Path:
    lines = load_subtitle(project)
    if not lines:
        raise RuntimeError("Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước khi tạo giọng đọc.")
    output_path = project / "voices" / "voice.wav"
    temporary_path = output_path.with_name(f"voice.{uuid.uuid4().hex}.working.wav")
    runner = TextToVoiceRunner(settings, log=log, stop_check=stop_check)
    runner.start()
    try:
        runner.submit_lines(lines, "visual_pipeline", temporary_path)
        if stop_check():
            raise RuntimeError("Stopped.")
        replacements = [
            (temporary_path, output_path),
            (temporary_path.with_suffix(".segments.json"), output_path.with_suffix(".segments.json")),
            (temporary_path.with_suffix(".srt"), output_path.with_suffix(".srt")),
            (temporary_path.with_suffix(".ttv.meta.json"), output_path.with_suffix(".ttv.meta.json")),
        ]
        for source, target in replacements:
            if source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                _replace_file_windows(source, target)
        # Ghi đè timing ước tính trong subtitle.json bằng timing thật vừa đo.
        measured = read_json(output_path.with_suffix(".segments.json"), {})
        measured_segments = measured.get("segments") if isinstance(measured, dict) else None
        if isinstance(measured_segments, list) and measured_segments:
            save_subtitle(project, measured_segments)
        # A new voice means the old scene/timing-to-asset mapping is no longer
        # trustworthy. Force the next analyze-search run to rebuild scenes.
        (project / "assets" / "asset_manifest.json").unlink(missing_ok=True)
    finally:
        runner.close()
        temporary_path.unlink(missing_ok=True)
        temporary_path.with_suffix(".segments.json").unlink(missing_ok=True)
        temporary_path.with_suffix(".srt").unlink(missing_ok=True)
        temporary_path.with_suffix(".ttv.meta.json").unlink(missing_ok=True)
    return output_path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_generate_voice_subtitle.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Full suite (chú ý test cũ test_generate_voice_srt.py)**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS. **Lưu ý:** `tests/test_generate_voice_srt.py` cũ dùng `_FakeRunner.submit_file` và project KHÔNG có subtitle.json → giờ `generate_voice` sẽ raise. Cập nhật test cũ đó cho khớp hành vi mới: thêm `save_subtitle(project, [...])` vào project và đổi fake runner sang `submit_lines` (giống test mới). Sửa file `tests/test_generate_voice_srt.py` cho khớp, không xoá ý nghĩa kiểm thử (vẫn xác minh voice.srt tồn tại + dọn temp).

```python
# tests/test_generate_voice_srt.py — cập nhật:
# 1) _FakeRunner.submit_file  ->  def submit_lines(self, lines, label, output_path):
#    (ghi voice.wav + .segments.json measured + .srt, như test_generate_voice_subtitle)
# 2) trong test, thêm trước khi gọi generate_voice:
#    from app.pipeline.subtitle_store import save_subtitle
#    save_subtitle(project, [{"start":0.0,"end":1.0,"text":"Câu một.","edited":False}])
```

(Áp dụng thay đổi tương đương; chạy lại `python -m pytest tests/test_generate_voice_srt.py -v` → PASS.)

- [ ] **Step 7: Commit**

```bash
git add app/pipeline/visual_pipeline.py tests/test_generate_voice_subtitle.py tests/test_generate_voice_srt.py
git commit -m "feat(voice): generate_voice reads subtitle, overwrites timing per line"
```

---

### Task 5: `/api/voice` yêu cầu phụ đề, bỏ phụ thuộc script làm TTS

**Files:**
- Modify: `app/web/web_server.py` (`/api/voice`, ~dòng 1460-1498; import `load_subtitle`)
- Test: `tests/test_web_server.py` (thêm test theo harness sẵn có)

**Interfaces:**
- Consumes: `load_subtitle` (SP1); `runtime.require_project()` (đã có).
- Produces: `POST /api/voice` trả 400 nếu chưa có phụ đề; nếu có, chạy job như cũ (vẫn đồng bộ `script_final.txt` để lưu vết).

- [ ] **Step 1: Write the failing test**

Theo harness của `tests/test_web_server.py` (TestClient + cách mở project có sẵn trong file). Thêm test khẳng định: mở/đặt một project KHÔNG có `scripts/subtitle.json` rồi `POST /api/voice` → trả 400 với thông điệp chứa "phụ đề". (Dùng đúng fixture/cách set current project mà các test endpoint khác trong file đang dùng; `load_subtitle` ở đây là thật vì `subtitle_store` không bị mock.)

```python
# tests/test_web_server.py — thêm (đặt cạnh các test endpoint khác):
def test_voice_requires_subtitle(tmp_path):
    # Tạo project hợp lệ nhưng KHÔNG có subtitle.json, đặt làm current project
    # theo đúng cách các test khác trong file này dùng (runtime.set_project / open).
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text("Câu một.", encoding="utf-8")
    ws.runtime.set_project(project)  # dùng API thật mà file test này đã dùng ở chỗ khác
    client = TestClient(ws.app)
    resp = client.post("/api/voice", json={"script": "Câu một."})
    assert resp.status_code == 400
    assert "phụ đề" in (resp.json().get("detail") or "").lower()
```

Nếu API set-project khác (ví dụ `runtime.project = project` hoặc một endpoint `/api/projects/open`), dùng đúng cách file test đã dùng — kiểm tra các test endpoint hiện có trong `test_web_server.py` để mượn pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_server.py::test_voice_requires_subtitle -v`
Expected: FAIL — hiện `/api/voice` không kiểm tra subtitle (status 200/khởi tạo job).

- [ ] **Step 3: Thêm import + guard**

Trong `app/web/web_server.py`, đảm bảo có import (gộp với import subtitle_store đã thêm ở SP1 nếu chưa có `load_subtitle`):

```python
from app.pipeline.subtitle_store import load_subtitle, save_subtitle
```

Trong `create_voice` (`/api/voice`), ngay sau `project = runtime.require_project()` và `_sync_script(...)`, thêm guard trước khi tạo job:

```python
    if not load_subtitle(project):
        raise HTTPException(status_code=400, detail="Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước khi tạo giọng đọc.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web_server.py::test_voice_requires_subtitle -v`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `python -m pytest tests/ -q`
Expected: tất cả PASS.

- [ ] **Step 6: Commit**

```bash
git add app/web/web_server.py tests/test_web_server.py
git commit -m "feat(voice): /api/voice requires saved subtitle before generating"
```

---

## Self-Review (đã rà)

- **Spec coverage:** SP2.1 nguồn subtitle → Task 4 (generate_voice đọc subtitle) + Task 5 (endpoint guard). SP2.2 per-line cả hai engine → Task 3 (submit_lines) + Task 2 (tách clone). SP2.3 hàm thuần assemble → Task 1. SP2.4 ghi timing thật + ghi đè subtitle → Task 3 (segments.json measured) + Task 4 (save_subtitle). SP2.5 chọn engine/API → Task 3 (use_clone) + Task 5. Tiêu chí hoàn thành → test Task 1/3/4/5.
- **Placeholder scan:** không có TBD; mọi step có code/lệnh. Ngoại lệ chủ ý: Task 5 mượn pattern set-project từ harness `test_web_server.py` (giá trị/đường set-project tùy harness) — implementer đối chiếu file test hiện có; assertion (400 + "phụ đề") là hợp đồng cố định.
- **Type consistency:** segment dùng nhất quán `index/start/end/text/edited/timing_source`; `assemble_line_segments(lines,durations,pause=0.25)`, `submit_lines(lines,label,output_path)`, `_kokoro_audio_for_text/_clone_audio_for_text(...) -> (Path,float)` khớp giữa Task 1-4. `generate_voice` dùng `submit_lines` (không còn `submit_file`).
- **Rủi ro đã ghi:** Task 2 (tách clone) không có test tự động cho đường clone whole-text → dựa vào full suite + đối chiếu; đường clone vốn không bị test trước đây. Task 4 buộc cập nhật `test_generate_voice_srt.py` cũ cho khớp hành vi mới (đã nêu rõ ở Step 6).
