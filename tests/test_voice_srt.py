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
