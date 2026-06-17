# tests/test_prompt_studio_pure.py
from pathlib import Path
import json
from app.pipeline import prompt_studio as ps


def test_coerce_prompt_array_pads_and_truncates():
    assert ps.coerce_prompt_array('["a","b"]', 3) == ["a", "b", ""]
    assert ps.coerce_prompt_array('```json\n["a","b","c","d"]\n```', 2) == ["a", "b"]


def test_enforce_realistic_prompt_strips_number_and_appends_tag():
    out = ps.enforce_realistic_prompt("3. A man (desc) walking")
    assert not out.startswith("3.")
    assert out.endswith(ps.REALISTIC_TAG)
    # idempotent: does not double-append
    assert ps.enforce_realistic_prompt(out).count(ps.REALISTIC_TAG) == 1


def test_enforce_realistic_prompt_sanitizes_policy_words():
    out = ps.enforce_realistic_prompt("a nude person holding a gun")
    assert "nude" not in out.lower()
    assert "gun" not in out.lower()


def test_build_numbered_srt():
    lines = [{"index": 1, "text": "Hello"}, {"index": 2, "text": "World"}]
    assert ps.build_numbered_srt(lines) == "1. Hello\n2. World"


def test_save_load_analysis_roundtrip(tmp_path):
    project = tmp_path / "proj"
    data = {"version": 1, "storyContext": "x", "characters": [{"name": "A", "role": "r", "description": "d"}], "sceneMap": []}
    saved = ps.save_prompt_analysis(project, data)
    assert ps.analysis_path(project).exists()
    assert ps.load_prompt_analysis(project)["characters"][0]["name"] == "A"
    assert ps.load_prompt_analysis(tmp_path / "none") == {}
