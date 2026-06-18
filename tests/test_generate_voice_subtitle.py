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


def test_generate_voice_keeps_voice_newer_than_subtitle(tmp_path, monkeypatch):
    # Regression: generate_voice rewrites subtitle.json AFTER finalizing voice, and the
    # rename preserves the temp file's older mtime. It must bump the voice files' mtime
    # so voice >= subtitle; otherwise _project_payload flags the fresh voice as stale
    # (has_voice=False) and the Prompt step is unreachable.
    import os
    monkeypatch.setattr(vp, "TextToVoiceRunner", _FakeRunner)
    project = _project_with_subtitle(tmp_path)

    vp.generate_voice(project, {}, log=lambda _m: None)

    voice_mtime = os.path.getmtime(project / "voices" / "voice.wav")
    seg_mtime = os.path.getmtime(project / "voices" / "voice.segments.json")
    sub_mtime = os.path.getmtime(project / "scripts" / "subtitle.json")
    assert voice_mtime >= sub_mtime
    assert seg_mtime >= sub_mtime


def test_generate_voice_requires_subtitle(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "TextToVoiceRunner", _FakeRunner)
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text("Câu một.", encoding="utf-8")
    import pytest
    with pytest.raises(Exception) as exc:
        vp.generate_voice(project, {}, log=lambda _m: None)
    assert "phụ đề" in str(exc.value).lower()
