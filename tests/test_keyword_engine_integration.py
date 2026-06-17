"""Integration tests for the pack-driven keyword generation engine (Phase C).

These prove that app/visual_pipeline.py consumes the Domain Pack instead of
hardcoding football knowledge:
  1. Football regression stays on-topic (snapshot stability).
  2. A brand-new domain (true-crime) runs through the generic pack with no
     engine code changes and does not inject football words.
  3. resolve_action is wired into _scene_action_hint.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Stub the heavy TTS dependency before importing visual_pipeline. Use a
# MagicMock module so any attribute other test modules import from it (e.g.
# kokoro_custom_voice_dir, used by app.web_server) still resolves regardless of
# pytest collection order.
sys.modules.setdefault("app.text_to_voice_queue", MagicMock())
sys.modules["app.text_to_voice_queue"].TextToVoiceRunner = MagicMock()  # type: ignore[attr-defined]

from app import visual_pipeline as vp  # noqa: E402
from keyword_engine import domain_pack as dp  # noqa: E402


def _no_braces(values) -> None:
    for value in values:
        assert "{" not in value and "}" not in value, f"slot leak in {value!r}"


class TestFootballRegression:
    SCRIPT = (
        "Argentina vs Brazil met in the 2022 World Cup final. "
        "Lionel Messi celebrated after the final whistle for Argentina."
    )

    def _item(self) -> dict:
        return {
            "sentence_text": "Lionel Messi celebrated after the final whistle.",
            "main_subject": "Lionel Messi",
            "match_teams": ["Argentina", "Brazil"],
            "keyword": "Lionel Messi celebration",
            "google_queries": ["Lionel Messi celebration"],
        }

    def test_football_keyword_on_topic_and_clean(self):
        video_context = {"video_domain": "football", "match_teams": ["Argentina", "Brazil"]}
        out = vp._apply_script_visual_context([self._item()], self.SCRIPT, video_context)[0]
        keyword = out.get("keyword") or ""
        queries = out.get("google_queries") or []
        assert keyword, "expected a non-empty primary keyword"
        assert queries, "expected non-empty google_queries"
        _no_braces([keyword, *queries])
        # On-topic: a team or the subject token must be present.
        lowered = keyword.lower()
        assert any(token in lowered for token in ("argentina", "brazil", "messi"))

    def test_football_primary_keyword_snapshot(self):
        # Stability snapshot for the primary keyword string.
        video_context = {"video_domain": "football", "match_teams": ["Argentina", "Brazil"]}
        out = vp._apply_script_visual_context([self._item()], self.SCRIPT, video_context)[0]
        assert out.get("keyword") == "Lionel Messi Argentina Brazil 2022 World Cup final match"


class TestNonFootballEndToEnd:
    SCRIPT = (
        "In 1888, a series of murders shocked Whitechapel. "
        "Detective Frederick Abberline investigated the crime scene at night."
    )

    def test_true_crime_runs_without_football_injection(self):
        # No pack file for true-crime and no ai_caller -> resolve falls to generic.
        item = {
            "sentence_text": "Detective Frederick Abberline investigated the crime scene.",
            "main_subject": "Frederick Abberline",
            "keyword": "Frederick Abberline investigation",
            "google_queries": ["Frederick Abberline investigation"],
        }
        video_context = {"video_domain": "true-crime"}
        out = vp._apply_script_visual_context([item], self.SCRIPT, video_context)[0]
        keyword = out.get("keyword") or ""
        queries = out.get("google_queries") or []
        assert keyword, "expected a non-empty keyword for a new domain"
        _no_braces([keyword, *queries])
        # No football vocabulary leaked into a non-football domain.
        joined = " ".join([keyword, *queries]).lower()
        for football_word in ("football", "soccer", "world cup", "match action", "touchline", "argentina"):
            assert football_word not in joined, f"football word leaked: {football_word!r}"
        # Stays on the actual subject.
        assert "abberline" in joined


class TestResolveActionWired:
    def test_scene_action_hint_uses_pack(self):
        football_pack = dp.resolve_domain_pack("", {"video_domain": "football"})
        result = vp._scene_action_hint(
            {"sentence_text": "cả đội ăn mừng bàn thắng"}, pack=football_pack
        )
        assert result == "goal celebration"
