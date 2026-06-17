import importlib
import json
import sys
import types
from pathlib import Path

import pytest

# test_keyword_engine_integration.py permanently installs a MagicMock for
# app.voice.text_to_voice_queue. Load the real module object by path so that
# our tests always run against the real implementation, whatever sys.modules holds.
_REAL_MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "voice" / "text_to_voice_queue.py"


def _load_real_module():
    """Return the real text_to_voice_queue module, bypassing sys.modules mocks."""
    spec = importlib.util.spec_from_file_location("app.voice.text_to_voice_queue", _REAL_MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Temporarily register it so relative imports inside the module resolve correctly.
    old = sys.modules.get("app.voice.text_to_voice_queue")
    sys.modules["app.voice.text_to_voice_queue"] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        if old is not None:
            sys.modules["app.voice.text_to_voice_queue"] = old
        elif "app.voice.text_to_voice_queue" in sys.modules:
            del sys.modules["app.voice.text_to_voice_queue"]
    return mod


q = _load_real_module()


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
