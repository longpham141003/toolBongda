"""Tests for keyword-engine robustness when the AI keyword stage fails on a
non-English (e.g. Vietnamese) script.

Two behaviours are covered:

1. When the per-scene keyword AI fails but the video-context AI succeeded, the
   local fallback must build keywords from the AI-inferred ENGLISH entities
   (match_teams / main_entities) instead of scraping ASCII-capitalized
   fragments out of the Vietnamese sentence (which yields garbage like "Nha"
   from "Bồ Đào Nha" or "Tuy" from "Tuy nhiên").

2. When a provider rejects a request because of billing/quota, the error
   surfaced to the caller must be a clear, actionable message (not a raw blob)
   so the UI can tell the user to top up / switch provider.
"""
from __future__ import annotations

import sys
import types
import unittest.mock as mock
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

with mock.patch.dict(
    sys.modules,
    {"app.voice.text_to_voice_queue": types.ModuleType("app.voice.text_to_voice_queue")},
):
    sys.modules["app.voice.text_to_voice_queue"].TextToVoiceRunner = mock.MagicMock()  # type: ignore[attr-defined]
    from app.pipeline import visual_pipeline as vp


VI_SCENE_1 = (
    "World Cup 2026 tiếp tục mang đến những cuộc đối đầu đầy thú vị và trận "
    "đấu giữa Bồ Đào Nha với Kongo là một trong số đó."
)
VI_SCENE_RONALDO = (
    "Tuy nhiên, tâm điểm của trận đấu chắc chắn vẫn là Cristiano Ronaldo. "
    "Ở tuổi 41, siêu sao người Bồ Đào Nha đang đứng trước trận đấu lớn."
)

AI_CONTEXT = {
    "video_topic": "World Cup 2026 match preview: Portugal vs Congo",
    "video_domain": "Football match analysis",
    "main_entities": [
        "Portugal national football team",
        "Congo national football team",
        "Cristiano Ronaldo",
    ],
    "match_teams": ["Portugal", "Congo"],
    "secondary_entities": ["World Cup 2026", "FIFA World Cup"],
    "visual_boundaries": [],
    "forbidden_contexts": [],
    "source": "kiro",
}

# Vietnamese fragments that proper-noun scraping wrongly pulls out of the text.
VI_GARBAGE = {"nha", "tuy", "kongo", "tiep", "nguoi"}


def _has_garbage(text: str) -> bool:
    words = set(vp._ascii_words(text))
    return bool(words & VI_GARBAGE)


class TestNonEnglishFallbackKeywords:
    def test_match_scene_uses_ai_teams_not_vietnamese_fragments(self):
        item = {"asset_id": "asset_0001", "sentence_text": VI_SCENE_1, "start": 0, "end": 5, "duration": 5}
        out = vp._apply_script_visual_context([item], "", dict(AI_CONTEXT))[0]
        keyword = str(out.get("keyword") or "")
        assert keyword, "expected a non-empty fallback keyword"
        words = set(vp._ascii_words(keyword))
        assert "portugal" in words and "congo" in words, f"expected both AI teams in {keyword!r}"
        assert not _has_garbage(keyword), f"keyword still contains scraped Vietnamese fragments: {keyword!r}"

    def test_named_subject_rejects_foreign_fragment(self):
        # Scene 1 has no real person name -> must not lock onto "Nha".
        item = {"asset_id": "a1", "sentence_text": VI_SCENE_1}
        subject = vp._lock_scene_named_subject(item, "", dict(AI_CONTEXT))
        assert not _has_garbage(subject), f"named subject is a foreign fragment: {subject!r}"

    def test_named_subject_keeps_real_ai_entity(self):
        # The Ronaldo scene names a real entity that IS in the AI entity set.
        item = {"asset_id": "a2", "sentence_text": VI_SCENE_RONALDO}
        subject = vp._lock_scene_named_subject(item, "", dict(AI_CONTEXT))
        assert "ronaldo" in set(vp._ascii_words(subject)), f"expected Ronaldo to be kept, got {subject!r}"

    def test_local_context_still_falls_back_without_crashing(self):
        # When the AI fully failed (local_fallback) we cannot do better, but the
        # call must still return a keyword and not raise.
        local_ctx = dict(AI_CONTEXT)
        local_ctx["source"] = "local_fallback"
        item = {"asset_id": "a3", "sentence_text": VI_SCENE_1, "start": 0, "end": 5}
        out = vp._apply_script_visual_context([item], "", local_ctx)[0]
        assert str(out.get("keyword") or "")


class TestBillingErrorSurfacing:
    def _fake_response(self, status: int, text: str):
        resp = mock.MagicMock()
        resp.status_code = status
        resp.text = text
        resp.json.return_value = {}
        return resp

    def test_billing_error_message_is_actionable(self):
        body = '{"error":{"code":"billing_error","message":"billing failed"}}'
        fake = self._fake_response(500, body)
        # reset any prior pause state
        vp._AI_PROVIDER_PAUSE_UNTIL.pop("kiro", None)
        with mock.patch("requests.post", return_value=fake):
            with pytest.raises(RuntimeError) as exc:
                vp._call_openai_compatible_json(
                    provider="kiro",
                    api_key="sk-test",
                    base_url="https://example.com/v1",
                    model="kr/claude-opus-4.8",
                    system="x",
                    prompt="y",
                    max_tokens=100,
                    temperature=0.1,
                )
        msg = str(exc.value).lower()
        assert any(tok in msg for tok in ("quota", "thanh toán", "credit", "billing")), msg
        # billing failures should pause the provider like a 429 does
        assert vp._AI_PROVIDER_PAUSE_UNTIL.get("kiro", 0) > 0

    def test_non_billing_error_keeps_status_detail(self):
        fake = self._fake_response(404, "not found")
        vp._AI_PROVIDER_PAUSE_UNTIL.pop("kiro", None)
        with mock.patch("requests.post", return_value=fake):
            with pytest.raises(RuntimeError) as exc:
                vp._call_openai_compatible_json(
                    provider="kiro",
                    api_key="sk-test",
                    base_url="https://example.com/v1",
                    model="m",
                    system="x",
                    prompt="y",
                    max_tokens=100,
                    temperature=0.1,
                )
        assert "404" in str(exc.value)
        # a plain 404 must NOT trigger the quota pause
        assert vp._AI_PROVIDER_PAUSE_UNTIL.get("kiro", 0) == 0
