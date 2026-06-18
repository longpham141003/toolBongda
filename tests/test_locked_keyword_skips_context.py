# tests/test_locked_keyword_skips_context.py
"""
Integration tests: search_and_download_asset must NOT call _apply_script_visual_context
or the match-photography block when prompt_keyword_locked=True is set on the item (I2).

When prompt_keyword_locked is absent, the context block must still be called (guard is
conditional, not a blanket skip).
"""
import sys
import types
import unittest.mock as mock
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Mirror the sys.modules stub pattern from test_search_preserves_prompt_keyword.py
# so that text_to_voice_queue (which imports heavy deps) is safely mocked.
with mock.patch.dict(sys.modules, {
    "app.voice.text_to_voice_queue": types.ModuleType("app.voice.text_to_voice_queue"),
}):
    sys.modules["app.voice.text_to_voice_queue"].TextToVoiceRunner = mock.MagicMock()
    from app.pipeline import visual_pipeline as vp


PROMPT_KEYWORD = "west african woman office"
FOOTBALL_SCRIPT = "Portugal vs France match, goal, penalty, world cup"


def _make_locked_item():
    return {
        "asset_id": "asset_0001",
        "keyword": PROMPT_KEYWORD,
        "ai_search_keyword": PROMPT_KEYWORD,
        "google_queries": ["woman office"],
        "keyword_ai_scene_refreshed": True,
        "prompt_keyword_locked": True,
        "status": "pending",
        "sentence_text": "match action",
        "visual_source_type": "",
    }


def _make_project_with_football_script(tmp_path):
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text(
        FOOTBALL_SCRIPT, encoding="utf-8"
    )
    return project


def test_locked_keyword_skips_script_context_block(tmp_path, monkeypatch):
    """
    When prompt_keyword_locked=True, _apply_script_visual_context must NOT be called,
    and the keyword reaching crawl_image_candidates must equal the original prompt keyword.
    """
    project = _make_project_with_football_script(tmp_path)
    item = _make_locked_item()

    context_called = {"called": False}

    def fake_context(items, *a, **k):
        context_called["called"] = True
        # Simulate what the real function would do: overwrite with match keywords
        for it in items:
            it["keyword"] = "football match action goal"
        return items

    captured_keyword = {}

    def fake_crawl(project, item, attempt, count=6, settings=None, log=None):
        captured_keyword["keyword"] = item.get("keyword")
        raise RuntimeError("crawl-reached")

    monkeypatch.setattr(vp, "refresh_asset_keyword_with_ai", lambda p, it, s, log=None: it)
    monkeypatch.setattr(vp, "_apply_script_visual_context", fake_context)
    monkeypatch.setattr(vp, "crawl_image_candidates", fake_crawl)

    try:
        vp.search_and_download_asset(
            project,
            item,
            log=lambda *a: None,
            settings={"gemini_api_key": "x"},
        )
    except RuntimeError as exc:
        assert "crawl-reached" in str(exc), f"Unexpected error: {exc}"

    assert not context_called["called"], (
        "_apply_script_visual_context was called despite prompt_keyword_locked=True — "
        "the script-context block must be skipped for locked items."
    )
    assert captured_keyword.get("keyword") == PROMPT_KEYWORD, (
        f"keyword was mutated before crawl: got {captured_keyword.get('keyword')!r}, "
        f"expected {PROMPT_KEYWORD!r}"
    )


def test_unlocked_keyword_does_call_script_context_block(tmp_path, monkeypatch):
    """
    When prompt_keyword_locked is absent (old flow), _apply_script_visual_context
    MUST still be called — the guard is conditional, not a blanket skip.
    """
    project = _make_project_with_football_script(tmp_path)

    # Item WITHOUT prompt_keyword_locked
    item = {
        "asset_id": "asset_0002",
        "keyword": PROMPT_KEYWORD,
        "ai_search_keyword": PROMPT_KEYWORD,
        "google_queries": ["woman office"],
        "keyword_ai_scene_refreshed": True,
        "status": "pending",
        "sentence_text": "match action",
        "visual_source_type": "",
    }

    context_called = {"called": False}

    def fake_context(items, *a, **k):
        context_called["called"] = True
        # Return items unchanged so the rest of the function proceeds to crawl
        return items

    captured_keyword = {}

    def fake_crawl(project, item, attempt, count=6, settings=None, log=None):
        captured_keyword["keyword"] = item.get("keyword")
        raise RuntimeError("crawl-reached")

    monkeypatch.setattr(vp, "refresh_asset_keyword_with_ai", lambda p, it, s, log=None: it)
    monkeypatch.setattr(vp, "_apply_script_visual_context", fake_context)
    monkeypatch.setattr(vp, "crawl_image_candidates", fake_crawl)

    try:
        vp.search_and_download_asset(
            project,
            item,
            log=lambda *a: None,
            settings={"gemini_api_key": "x"},
        )
    except RuntimeError as exc:
        assert "crawl-reached" in str(exc), f"Unexpected error: {exc}"

    assert context_called["called"], (
        "_apply_script_visual_context was NOT called for an item without prompt_keyword_locked — "
        "the guard must be conditional, not a blanket skip."
    )
