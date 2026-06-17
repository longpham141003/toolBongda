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
