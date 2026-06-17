"""Integration test for generate_voice persisting voices/voice.srt.

Stubs TextToVoiceRunner so we never touch the real Kokoro server; we only
verify that the .srt artifact produced next to the temp WAV is renamed to
voices/voice.srt (and the temp files are cleaned up).

Updated for SP2 Task 4: generate_voice now reads subtitle.json (via
load_subtitle) instead of script_final.txt, so the project needs a saved
subtitle and the fake runner implements submit_lines instead of submit_file.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import unittest.mock as mock

with mock.patch.dict(
    sys.modules,
    {"app.voice.text_to_voice_queue": types.ModuleType("app.voice.text_to_voice_queue")},
):
    sys.modules["app.voice.text_to_voice_queue"].TextToVoiceRunner = mock.MagicMock()  # type: ignore[attr-defined]
    from app.pipeline import visual_pipeline as vp

from app.pipeline.subtitle_store import save_subtitle


class _FakeRunner:
    """Writes the same sibling artifacts the real Kokoro path produces."""

    def __init__(self, settings, log, stop_check):
        self.log = log

    def start(self):
        return None

    def submit_lines(self, lines, label, output_path):
        import json
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"RIFFfakewav")
        segments = [{"index": 1, "start": 0.0, "end": 1.0, "text": "Câu một.", "edited": False, "timing_source": "measured"}]
        output_path.with_suffix(".segments.json").write_text(
            json.dumps({"engine": "kokoro-server", "segments": segments}, ensure_ascii=False),
            encoding="utf-8",
        )
        output_path.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nCâu một.\n", encoding="utf-8"
        )
        return str(output_path)

    def close(self):
        return None


def test_generate_voice_persists_srt_and_cleans_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "TextToVoiceRunner", _FakeRunner)
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text("Câu một.", encoding="utf-8")
    # SP2 Task 4: generate_voice now requires subtitle.json to be present.
    save_subtitle(project, [{"start": 0.0, "end": 1.0, "text": "Câu một.", "edited": False}])

    result = vp.generate_voice(project, {}, log=lambda _msg: None)

    voices = project / "voices"
    assert result == voices / "voice.wav"
    assert (voices / "voice.wav").exists()
    assert (voices / "voice.segments.json").exists()
    # The key new artifact: a real SRT reused by step 3 without re-listening.
    srt = voices / "voice.srt"
    assert srt.exists()
    assert srt.read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> 00:00:01,000\nCâu một.")

    # No temp working files left behind.
    leftovers = [p.name for p in voices.glob("voice.*.working.*")]
    assert leftovers == []
