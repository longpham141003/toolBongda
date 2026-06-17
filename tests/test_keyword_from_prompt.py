# tests/test_keyword_from_prompt.py
from pathlib import Path
from app.pipeline import prompt_studio as ps


def test_keyword_from_prompt_uses_ai(monkeypatch):
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt, **k: '{"search_keyword": "west african woman office worried", "google_queries": ["woman office worried", "african woman blue blouse office"]}')
    out = ps.keyword_from_prompt("Ama (West African woman, blue blouse) looks worried in an office", {"gemini_api_key": "x"})
    assert out["search_keyword"] == "west african woman office worried"
    assert out["google_queries"][0] == "woman office worried"


def test_keyword_from_prompt_falls_back_when_ai_empty(monkeypatch):
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt, **k: "")
    out = ps.keyword_from_prompt("A worried office worker at her desk", {}, fallback_text="A worried office worker")
    # heuristic keyword_for_text produced something non-empty, mirrored into google_queries
    assert out["search_keyword"].strip()
    assert out["google_queries"] and out["google_queries"][0] == out["search_keyword"]


def test_keyword_from_prompt_falls_back_on_bad_json(monkeypatch):
    monkeypatch.setattr(ps, "_ai_call", lambda settings, prompt, **k: "not json at all")
    out = ps.keyword_from_prompt("Children playing football in a park", {"gemini_api_key": "x"})
    assert out["search_keyword"].strip()
    assert out["google_queries"]


def test_apply_prompt_keywords_writes_fields(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    manifest = [
        {"asset_id": "asset_0001", "prompt": "A woman at a desk", "sentence_text": "She sits.", "keyword": "", "google_queries": []},
        {"asset_id": "asset_0002", "prompt": "", "sentence_text": "A dog runs.", "keyword": "", "google_queries": []},
    ]
    saved = {}
    monkeypatch.setattr(ps, "_load_manifest", lambda p: manifest)
    monkeypatch.setattr(ps, "_save_manifest", lambda p, items: saved.update({"items": items}))
    monkeypatch.setattr(ps, "keyword_from_prompt", lambda text, settings, fallback_text="": {"search_keyword": f"kw:{text or fallback_text}", "google_queries": [f"q:{text or fallback_text}"]})
    out = ps.apply_prompt_keywords(project, {}, log=None)
    assert out[0]["keyword"] == "kw:A woman at a desk"
    assert out[0]["ai_search_keyword"] == "kw:A woman at a desk"
    assert out[0]["google_queries"] == ["q:A woman at a desk"]
    # asset 2 has empty prompt → falls back to sentence_text
    assert out[1]["keyword"] == "kw:A dog runs."
    assert saved["items"][0]["keyword"] == "kw:A woman at a desk"
