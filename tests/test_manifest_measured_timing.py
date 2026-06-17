"""TDD test for I2+M3: build_asset_manifest must not call refine_timing_with_whisper
or estimate_timing_from_script when timing_source=="measured".

RED before fix: one of the call-trackers fires (whisper or repair was invoked).
GREEN after fix: both guards block those calls, so neither tracker fires.

Note: raising AssertionError inside whisper stub would NOT cause RED because the
current code wraps it in `except Exception` and swallows it. We instead use boolean
call-tracking flags to prove the invariant.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.pipeline.visual_pipeline as vp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_measured_project(tmp_path: Path) -> Path:
    """Scaffold the minimum project layout for build_asset_manifest."""
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "voices").mkdir(parents=True)
    (project / "assets").mkdir(parents=True)

    # script_final.txt (required by build_asset_manifest → reads for video context)
    (project / "scripts" / "script_final.txt").write_text(
        "Team A won the match. Team B fought hard. The final score was decided late. Great game.",
        encoding="utf-8",
    )

    # voice.wav — a tiny stub file so audio_path.exists() is True
    (project / "voices" / "voice.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")

    # voice.segments.json with timing_source="measured" and 4 short segments
    # each ending with "." so merge_segments_into_sentences groups each as 1 sentence.
    # Durations are ~0.2s — short enough that _timing_needs_repair "very_short" heuristic
    # would fire (>45% under 0.35s) IF audio_duration > 2.0.
    # We set probe_duration to 5.0 (> 2.0) so the duration check applies, and the
    # is_measured guard must block the repair call.
    segments = [
        {"text": "Team A won the match.", "start": 0.0, "end": 0.22, "duration": 0.22},
        {"text": "Team B fought hard.", "start": 0.47, "end": 0.68, "duration": 0.21},
        {"text": "The final score was decided late.", "start": 0.93, "end": 1.15, "duration": 0.22},
        {"text": "Great game.", "start": 1.40, "end": 1.60, "duration": 0.20},
    ]
    timing_data = {
        "audio": str(project / "voices" / "voice.wav"),
        "duration": 1.60,
        "sampleRate": 24000,
        "lang": "en",
        "voice": "af_heart",
        "speed": 1.0,
        "delivery": "dramatic",
        "engine": "kokoro-server",
        "timing_source": "measured",
        "segments": segments,
    }
    (project / "voices" / "voice.segments.json").write_text(
        json.dumps(timing_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return project


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------

def test_measured_timing_skips_whisper_and_repair(tmp_path, monkeypatch):
    """With timing_source="measured", neither Whisper re-alignment nor the
    repair estimator should be called, even when:
    - whisper_timing_enabled=True  (I2 guard)
    - segments are very short / duration mismatch would trigger _timing_needs_repair (M3 guard)
    """
    project = _make_measured_project(tmp_path)

    # Use call-tracking flags (not exceptions) to detect unwanted calls.
    # AssertionError inside the whisper block is swallowed by 'except Exception'.
    whisper_called = []
    repair_called = []

    def _track_whisper(proj, settings, log=None):
        whisper_called.append(True)
        return {}  # Return something so the function doesn't crash

    def _track_repair(proj, timing):
        repair_called.append(True)
        return timing or {}

    # Stub heavy downstream helpers so the function runs without AI/network.
    monkeypatch.setattr(vp, "refine_timing_with_whisper", _track_whisper)
    monkeypatch.setattr(vp, "estimate_timing_from_script", _track_repair)
    monkeypatch.setattr(vp, "_load_or_build_video_context", lambda *a, **k: {})
    monkeypatch.setattr(vp, "_resolve_pack", lambda *a, **k: None)
    monkeypatch.setattr(vp, "_apply_script_visual_context", lambda assets, *a, **k: assets)

    # probe_duration returns 5.0 (> 2.0) so _timing_needs_repair does NOT short-circuit.
    # With audio_duration=5.0 and timing_duration=1.60, the ratio check (1.60 < 5.0*0.7=3.5)
    # would flag timing as invalid → estimate_timing_from_script would be called
    # WITHOUT the is_measured guard (M3 RED proof).
    monkeypatch.setattr(vp, "probe_duration", lambda path: 5.0)

    # Call with whisper_timing_enabled=True to exercise both guards.
    assets = vp.build_asset_manifest(project, {"whisper_timing_enabled": True}, log=None)

    # --- I2 guard: whisper must not have been called ---
    assert not whisper_called, "I2 FAILED: refine_timing_with_whisper was called on measured timing"

    # --- M3 guard: repair must not have been called ---
    assert not repair_called, "M3 FAILED: estimate_timing_from_script was called on measured timing"

    # Each terminal-punctuation segment → 1 sentence → 1 scene.
    assert len(assets) == 4, f"Expected 4 scenes, got {len(assets)}"

    # Manifest JSON must exist and reflect the measured engine.
    manifest_path = project / "assets" / "asset_manifest.json"
    assert manifest_path.exists(), "asset_manifest.json was not written"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("timing_engine") == "kokoro-server", (
        f"timing_engine should be 'kokoro-server' (from measured timing), got {manifest.get('timing_engine')!r}"
    )
