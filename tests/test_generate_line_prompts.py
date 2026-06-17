import json, sys, types
import pytest
from pathlib import Path
import unittest.mock as mock

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.pipeline import prompt_studio as ps
import app.pipeline.visual_pipeline as vp
from app.pipeline.subtitle_store import save_subtitle


def _setup(project):
    (project / "scripts").mkdir(parents=True)
    save_subtitle(project, [
        {"start": 0.0, "end": 1.0, "text": "Ama steps forward."},
        {"start": 1.0, "end": 2.0, "text": "Eleanor frowns."},
    ])
    ps.save_prompt_analysis(project, {
        "storyContext": "A tense meeting.", "mainSetting": "office",
        "characters": [{"name": "Ama", "role": "clerk", "description": "West African woman, late 20s, blue blouse"}],
        "sceneMap": [
            {"startLine": 1, "endLine": 1, "location": "office", "timeOfDay": "day", "sceneSummary": "Ama steps forward", "charactersPresent": ["Ama"], "characterPositions": {}, "spatialLayout": "open office", "crowdNotes": ""},
            {"startLine": 2, "endLine": 2, "location": "office", "timeOfDay": "day", "sceneSummary": "Eleanor frowns", "charactersPresent": [], "characterPositions": {}, "spatialLayout": "open office", "crowdNotes": ""},
        ],
    })


def test_generate_line_prompts_writes_prompts(tmp_path, monkeypatch):
    # Stub manifest IO + AI on the prompt_studio module's references.
    project = tmp_path / "proj"
    _setup(project)
    manifest = [
        {"asset_id": "asset_0001", "sentence_text": "Ama steps forward.", "prompt": "", "sentence_indexes": [1]},
        {"asset_id": "asset_0002", "sentence_text": "Eleanor frowns.", "prompt": "", "sentence_indexes": [2]},
    ]
    saved = {}
    monkeypatch.setattr(ps, "_load_manifest", lambda p: manifest)
    monkeypatch.setattr(ps, "_save_manifest", lambda p, items: saved.update({"items": items}))
    # AI returns a raw JSON array of N strings (one batch of 2 here).
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: json.dumps([
        "1. Ama (West African woman, late 20s, blue blouse) steps forward in an open office",
        "Eleanor frowns at her desk",
    ]))
    assets = ps.generate_line_prompts(project, {"gemini_api_key": "x"}, log=None, batch_size=8)
    assert len(assets) == 2
    assert assets[0]["prompt"].endswith(ps.REALISTIC_TAG)
    assert not assets[0]["prompt"].startswith("1.")
    assert assets[1]["prompt"].endswith(ps.REALISTIC_TAG)
    assert saved["items"][0]["prompt"] == assets[0]["prompt"]


# I1 — _pack_ai_caller forwards max_tokens to _call_openai_compatible_json
def test_pack_ai_caller_forwards_max_tokens(monkeypatch):
    """_pack_ai_caller must pass the max_tokens kwarg through to the openai branch."""
    captured = {}

    def fake_openai_json(**kwargs):
        captured.update(kwargs)
        return '["ok"]'

    monkeypatch.setattr(vp, "_call_openai_compatible_json", fake_openai_json)
    settings = {"openai_api_key": "sk-fake", "keyword_ai_provider": "openai"}
    caller = vp._pack_ai_caller(settings, max_tokens=8000)
    assert caller is not None, "_pack_ai_caller returned None for valid openai settings"
    caller("hello")
    assert captured.get("max_tokens") == 8000, (
        f"Expected max_tokens=8000, got {captured.get('max_tokens')}"
    )


# I2 — mismatched subtitle/manifest lengths raise a clear error
def test_generate_line_prompts_raises_on_length_mismatch(tmp_path, monkeypatch):
    """If subtitle has more lines than manifest, generate_line_prompts must raise."""
    project = tmp_path / "proj"
    _setup(project)  # subtitle has 2 lines
    # Manifest has only 1 item — deliberate mismatch
    manifest_1 = [
        {"asset_id": "asset_0001", "sentence_text": "Ama steps forward.", "prompt": "", "sentence_indexes": [1]},
    ]
    monkeypatch.setattr(ps, "_load_manifest", lambda p: manifest_1)
    monkeypatch.setattr(ps, "_save_manifest", lambda p, items: None)
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: '["ok"]')
    with pytest.raises(RuntimeError, match="Phụ đề đã thay đổi"):
        ps.generate_line_prompts(project, {}, log=None)


# I3 — all-empty AI response raises instead of silently saving blanks
def test_generate_line_prompts_raises_when_all_prompts_empty(tmp_path, monkeypatch):
    """If AI returns empty string for every line, must raise rather than persist blanks."""
    project = tmp_path / "proj"
    _setup(project)
    manifest = [
        {"asset_id": "asset_0001", "sentence_text": "Ama steps forward.", "prompt": "", "sentence_indexes": [1]},
        {"asset_id": "asset_0002", "sentence_text": "Eleanor frowns.", "prompt": "", "sentence_indexes": [2]},
    ]
    monkeypatch.setattr(ps, "_load_manifest", lambda p: manifest)
    monkeypatch.setattr(ps, "_save_manifest", lambda p, items: None)
    # AI failure — returns empty string (simulates network error / quota)
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: "")
    with pytest.raises(RuntimeError, match="AI không tạo được"):
        ps.generate_line_prompts(project, {}, log=None)
