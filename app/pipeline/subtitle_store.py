"""Lưu trữ phụ đề canonical cho Bước 1 (SRT-first).

`subtitle.json` là nguồn chính (có cấu trúc, sửa được từng dòng); `subtitle.srt`
là bản xuất ra để xem / CapCut dùng. Voice (B2) và prompt (B3) đọc từ đây.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.voice.text_to_voice_cli import build_srt_from_segments


def normalize_subtitle_segments(raw: list[dict]) -> list[dict]:
    result: list[dict] = []
    index = 0
    for seg in raw or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        start = max(0.0, float(seg.get("start") or 0.0))
        end = float(seg.get("end") or 0.0)
        if end <= start:
            end = start + 0.05
        index += 1
        result.append(
            {
                "index": index,
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "edited": bool(seg.get("edited")),
            }
        )
    return result


def subtitle_paths(project: Path) -> tuple[Path, Path]:
    base = Path(project) / "scripts"
    return base / "subtitle.json", base / "subtitle.srt"


def save_subtitle(project: Path, raw: list[dict]) -> list[dict]:
    segments = normalize_subtitle_segments(raw)
    json_path, srt_path = subtitle_paths(project)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps({"version": 1, "segments": segments}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    srt_path.write_text(build_srt_from_segments(segments), encoding="utf-8")
    return segments


def load_subtitle(project: Path) -> list[dict]:
    json_path, _ = subtitle_paths(project)
    if not json_path.exists():
        return []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("segments"), list):
        return normalize_subtitle_segments(data["segments"])
    return []
