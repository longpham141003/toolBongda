# tests/test_subtitle_store.py
import json
from pathlib import Path

from app.pipeline.subtitle_store import (
    load_subtitle,
    normalize_subtitle_segments,
    save_subtitle,
    subtitle_paths,
)


def test_normalize_reindexes_and_drops_empty():
    raw = [
        {"start": 0.0, "end": 2.0, "text": "  Câu một  "},
        {"start": 2.0, "end": 2.0, "text": ""},          # rỗng -> bỏ
        {"start": 2.0, "end": 1.0, "text": "Câu hai", "edited": True},  # end<=start -> ép tăng
    ]
    out = normalize_subtitle_segments(raw)
    assert [s["index"] for s in out] == [1, 2]
    assert out[0]["text"] == "Câu một"
    assert out[1]["text"] == "Câu hai"
    assert out[1]["edited"] is True
    assert out[1]["end"] > out[1]["start"]


def test_save_then_load_roundtrip(tmp_path):
    project = tmp_path / "video1"
    raw = [
        {"start": 0.0, "end": 2.4, "text": "Câu một"},
        {"start": 2.4, "end": 5.0, "text": "Câu hai"},
    ]
    saved = save_subtitle(project, raw)
    json_path, srt_path = subtitle_paths(project)
    assert json_path.exists() and srt_path.exists()
    # subtitle.json giữ đúng cấu trúc
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["segments"] == saved
    # subtitle.srt đúng định dạng SRT, timestamp tăng dần
    srt_text = srt_path.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:02,400" in srt_text
    assert "1\n00:00:00,000" in srt_text
    # load lại khớp
    assert load_subtitle(project) == saved


def test_load_missing_returns_empty(tmp_path):
    assert load_subtitle(tmp_path / "nope") == []
