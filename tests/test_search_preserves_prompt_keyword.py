# tests/test_search_preserves_prompt_keyword.py
"""
Integration test: search_and_download_asset skips refresh_asset_keyword_with_ai
when keyword_ai_scene_refreshed=True, so the prompt-derived keyword is preserved.

This validates the crawler-side contract that apply_prompt_keywords relies on after
setting keyword_ai_scene_refreshed=True on each item.
"""
import sys
import types
import unittest.mock as mock
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Mirror the sys.modules stub pattern from test_manifest_one_scene_per_line.py
# so that text_to_voice_queue (which imports heavy deps) is safely mocked.
with mock.patch.dict(sys.modules, {
    "app.voice.text_to_voice_queue": types.ModuleType("app.voice.text_to_voice_queue"),
}):
    sys.modules["app.voice.text_to_voice_queue"].TextToVoiceRunner = mock.MagicMock()
    from app.pipeline import visual_pipeline as vp


PROMPT_KEYWORD = "west african woman office"


def test_search_skips_refresh_when_flag_set(tmp_path, monkeypatch):
    """
    When keyword_ai_scene_refreshed=True is set on the item (as apply_prompt_keywords
    now does), search_and_download_asset must NOT call refresh_asset_keyword_with_ai,
    and the keyword must reach crawl_image_candidates unchanged.
    """
    project = tmp_path / "proj"
    (project / "scripts").mkdir(parents=True)
    # Provide a script_final.txt so the script block runs (passthrough keeps keyword).
    (project / "scripts" / "script_final.txt").write_text("She sits.", encoding="utf-8")

    item = {
        "asset_id": "asset_0001",
        "keyword": PROMPT_KEYWORD,
        "ai_search_keyword": PROMPT_KEYWORD,
        "google_queries": ["woman office"],
        "keyword_ai_scene_refreshed": True,
        "status": "pending",
        "sentence_text": "She sits.",
        "visual_source_type": "",
    }

    refresh_called = {"called": False}

    def fake_refresh(project, item, settings, log=None):
        refresh_called["called"] = True
        item = dict(item)
        item["keyword"] = "OVERWRITTEN BY REFRESH"  # would clobber the prompt kw
        return item

    captured_keyword = {}

    def fake_crawl(project, item, attempt, count=6, settings=None, log=None):
        captured_keyword["keyword"] = item.get("keyword")
        raise RuntimeError("crawl-reached")

    monkeypatch.setattr(vp, "refresh_asset_keyword_with_ai", fake_refresh)
    monkeypatch.setattr(vp, "_apply_script_visual_context", lambda items, *a, **k: items)
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

    assert not refresh_called["called"], (
        "refresh_asset_keyword_with_ai was called despite keyword_ai_scene_refreshed=True — "
        "the prompt keyword would have been silently overwritten."
    )
    assert captured_keyword.get("keyword") == PROMPT_KEYWORD, (
        f"keyword was mutated before crawl: got {captured_keyword.get('keyword')!r}, "
        f"expected {PROMPT_KEYWORD!r}"
    )
