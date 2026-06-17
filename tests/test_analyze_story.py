import json
from pathlib import Path
from app.pipeline import prompt_studio as ps
from app.pipeline.subtitle_store import save_subtitle


def test_analyze_story_writes_analysis(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    save_subtitle(project, [
        {"start": 0.0, "end": 1.0, "text": "Ama steps forward."},
        {"start": 1.0, "end": 2.0, "text": "Eleanor frowns."},
    ])
    fake_json = json.dumps({
        "language": "English", "storyContext": "A tense meeting.", "mainSetting": "office",
        "tone": "tense",
        "characters": [{"name": "Ama", "role": "junior clerk", "description": "West African woman, late 20s, slim, dark skin, short black hair, plain blue blouse"}],
        "sceneMap": [{"startLine": 1, "endLine": 1, "location": "office", "timeOfDay": "day", "sceneSummary": "Ama steps forward", "charactersPresent": ["Ama"], "characterPositions": {}, "spatialLayout": "open office", "crowdNotes": ""}],
    })
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: fake_json)
    out = ps.analyze_story(project, {"gemini_api_key": "x"}, log=None)
    assert out["characters"][0]["name"] == "Ama"
    assert ps.load_prompt_analysis(project)["storyContext"] == "A tense meeting."


def test_analyze_story_requires_subtitle(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt: "{}")
    import pytest
    with pytest.raises(Exception) as exc:
        ps.analyze_story(project, {}, log=None)
    assert "phụ đề" in str(exc.value).lower()
