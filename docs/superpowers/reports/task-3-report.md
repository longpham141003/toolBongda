# Task 3 Report: Đường Kokoro dùng băm mịn + ghi voice.srt

**Date:** 2026-06-17
**Branch:** feat/voice-srt-progress
**Commit:** 26d4e52

---

## Edit 1 — Import thêm vào `app/voice/text_to_voice_queue.py` (dòng 16-22)

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

Thêm `split_text_into_progress_segments` và `write_srt_file` vào khối import hiện có, giữ thứ tự alpha.

---

## Edit 2 — Đổi cách băm đường Kokoro trong `submit_file`

**Trước:**
```python
        max_chars = max(1000, min(int(self.settings.get("text_to_voice_max_chars") or 10000), 12000))
        chunks = split_text_for_text_to_voice(text, max_chars)
        chunk_estimate = len(chunks)
```

**Sau:**
```python
        # Băm mịn theo cụm câu để tiến độ "đoạn i/N" có ý nghĩa và timing theo câu.
        progress_chars = max(80, min(int(self.settings.get("text_to_voice_progress_chars") or 350), 2000))
        chunks = split_text_into_progress_segments(text, progress_chars)
        chunk_estimate = len(chunks)
```

`_submit_file_magicvoice` (dòng 668) không động vào — vẫn dùng `split_text_for_text_to_voice`.

---

## Edit 3 — Ghi voice.srt sau segments.json trong `submit_file` (Kokoro)

Thêm ngay sau khối `.write_text(json.dumps(...))` và trước `finally:`:

```python
            write_srt_file(output_path.with_suffix(".srt"), combined_segments)
```

---

## Edit 4 — Ghi voice.srt sau segments.json trong `_submit_file_magicvoice`

Thêm ngay sau khối `.write_text(json.dumps(...))` và trước `finally:`:

```python
            write_srt_file(output_path.with_suffix(".srt"), estimated_segments)
```

---

## Edit 5 — Thêm `.srt` vào `replacements` trong `generate_voice` (visual_pipeline.py)

```python
        replacements = [
            (temporary_path, output_path),
            (temporary_path.with_suffix(".segments.json"), output_path.with_suffix(".segments.json")),
            (temporary_path.with_suffix(".srt"), output_path.with_suffix(".srt")),
            (temporary_path.with_suffix(".ttv.meta.json"), output_path.with_suffix(".ttv.meta.json")),
        ]
```

---

## Edit 6 — Thêm cleanup `.srt` tạm trong `finally` của `generate_voice`

```python
    finally:
        runner.close()
        temporary_path.unlink(missing_ok=True)
        temporary_path.with_suffix(".segments.json").unlink(missing_ok=True)
        temporary_path.with_suffix(".srt").unlink(missing_ok=True)
        temporary_path.with_suffix(".ttv.meta.json").unlink(missing_ok=True)
```

---

## Verification

### py_compile (exit 0, no output)

```
py -3 -m py_compile app/voice/text_to_voice_queue.py app/voice/text_to_voice_cli.py app/pipeline/visual_pipeline.py
# => py_compile OK
```

### pytest pure-function suite

```
python -m pytest tests/test_voice_segmentation.py tests/test_voice_srt.py tests/test_visual_pipeline_pure.py -q
# 190 passed in 0.26s
```

---

## Commit

```
26d4e52 feat(voice): fine-grained progress + persist voice.srt on voice creation
 2 files changed, 67 insertions(+), 17 deletions(-)
```

Files staged: `app/voice/text_to_voice_queue.py`, `app/pipeline/visual_pipeline.py`
