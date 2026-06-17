# tests/test_subtitle_staleness.py
"""I1 — Editing subtitle marks B2+ stale.

Saving subtitle.json newer than voice.wav must flip has_voice → False so the
front-end knows it needs to re-create the voice. mtime ordering is controlled
deterministically with os.utime so the test never races.
"""
import json
import os
import time

from app.pipeline.subtitle_store import save_subtitle
from app.web.web_server import _project_payload


def _make_project_with_voice(tmp_path):
    """Create a minimal project that has script + voice (has_voice == True)."""
    project = tmp_path / "video1"
    (project / "scripts").mkdir(parents=True)
    (project / "voices").mkdir(parents=True)

    script_path = project / "scripts" / "script_final.txt"
    script_path.write_text("Câu một. Câu hai.\n", encoding="utf-8")

    # script mtime = T0
    t0 = time.time() - 10
    os.utime(script_path, (t0, t0))

    # voice.wav + voice.segments.json  mtime = T1 > T0
    t1 = t0 + 1
    voice_wav = project / "voices" / "voice.wav"
    voice_wav.write_bytes(b"RIFF")
    os.utime(voice_wav, (t1, t1))

    timing_data = {"segments": [{"text": "Câu một.", "start": 0.0, "end": 1.5}]}
    timing_path = project / "voices" / "voice.segments.json"
    timing_path.write_text(json.dumps(timing_data), encoding="utf-8")
    os.utime(timing_path, (t1, t1))

    return project, t1


def test_subtitle_save_marks_voice_stale(tmp_path):
    project, voice_mtime = _make_project_with_voice(tmp_path)

    # Sanity: before subtitle is saved, voice must be fresh.
    payload_before = _project_payload(project)
    assert payload_before is not None
    assert payload_before["has_voice"] is True, (
        "Precondition failed: expected has_voice=True before subtitle save"
    )

    # Write subtitle.json at T2 > voice_mtime (strictly newer than voice).
    t2 = voice_mtime + 2
    save_subtitle(project, [{"start": 0.0, "end": 1.5, "text": "Câu một."}])
    subtitle_path = project / "scripts" / "subtitle.json"
    assert subtitle_path.exists(), "save_subtitle must create subtitle.json"
    os.utime(subtitle_path, (t2, t2))
    # Also set srt to same mtime
    subtitle_srt = project / "scripts" / "subtitle.srt"
    if subtitle_srt.exists():
        os.utime(subtitle_srt, (t2, t2))

    # After subtitle is newer than voice, has_voice must be False.
    payload_after = _project_payload(project)
    assert payload_after["has_voice"] is False, (
        "Expected has_voice=False after subtitle.json is newer than voice.wav"
    )
