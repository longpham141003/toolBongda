"""
Comprehensive pytest tests for pure/logic functions in app/visual_pipeline.py.
No external I/O (PIL, requests, Whisper, subprocess) is used.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out the TextToVoiceRunner import so we can import visual_pipeline
# without needing its real dependencies.
# ---------------------------------------------------------------------------
mock_ttvr = MagicMock()
sys.modules.setdefault("app.text_to_voice_queue", mock_ttvr)
sys.modules["app.text_to_voice_queue"].TextToVoiceRunner = MagicMock()

# Now import the module under test.
import importlib
import types

# We need to import as a package module; add repo root to path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Patch the text_to_voice_queue module before importing visual_pipeline
import unittest.mock as mock

with mock.patch.dict(
    sys.modules,
    {"app.text_to_voice_queue": types.ModuleType("app.text_to_voice_queue")},
):
    sys.modules["app.text_to_voice_queue"].TextToVoiceRunner = MagicMock()  # type: ignore[attr-defined]
    from app import visual_pipeline as vp


# ===========================================================================
# 1. _ascii_words
# ===========================================================================
class TestAsciiWords:
    def test_basic_ascii(self):
        assert vp._ascii_words("hello world") == ["hello", "world"]

    def test_lowercases(self):
        assert vp._ascii_words("Hello World") == ["hello", "world"]

    def test_strips_punctuation(self):
        assert vp._ascii_words("hello, world!") == ["hello", "world"]

    def test_unicode_normalization(self):
        # é should become e after NFKD stripping
        result = vp._ascii_words("café naïve")
        assert result == ["cafe", "naive"]

    def test_numbers_kept(self):
        assert vp._ascii_words("score 3 goals") == ["score", "3", "goals"]

    def test_empty_string(self):
        assert vp._ascii_words("") == []

    def test_none_treated_as_empty(self):
        assert vp._ascii_words(None) == []  # type: ignore[arg-type]

    def test_only_punctuation(self):
        assert vp._ascii_words("!!! ???") == []

    def test_alphanumeric_mix(self):
        assert vp._ascii_words("team1 vs team2") == ["team1", "vs", "team2"]

    def test_unicode_chinese(self):
        # Chinese characters have no alpha equivalents, should produce no words
        result = vp._ascii_words("你好世界")
        assert result == []


# ===========================================================================
# 2. _safe_name
# ===========================================================================
class TestSafeName:
    def test_basic(self):
        assert vp._safe_name("Hello World") == "hello-world"

    def test_max_10_words(self):
        text = " ".join(f"word{i}" for i in range(15))
        result = vp._safe_name(text)
        assert result.count("-") <= 9  # 10 words means 9 hyphens max

    def test_max_72_chars(self):
        text = "a" * 200
        assert len(vp._safe_name(text)) <= 72

    def test_fallback_on_empty(self):
        assert vp._safe_name("") == "visual-project"

    def test_fallback_on_none(self):
        assert vp._safe_name(None) == "visual-project"  # type: ignore[arg-type]

    def test_custom_fallback(self):
        assert vp._safe_name("", "my-fallback") == "my-fallback"

    def test_unicode_input(self):
        result = vp._safe_name("Trận đấu Pháp Brazil")
        # Should produce ascii-only, hyphen-joined result
        assert "-" in result or len(result) > 0
        assert all(c.isalnum() or c == "-" for c in result)

    def test_numbers_in_name(self):
        result = vp._safe_name("Scene 2024 highlights")
        assert "2024" in result

    def test_only_spaces(self):
        assert vp._safe_name("   ") == "visual-project"


# ===========================================================================
# 3. _srt_time
# ===========================================================================
class TestSrtTime:
    def test_zero(self):
        assert vp._srt_time(0) == "00:00:00,000"

    def test_one_second(self):
        assert vp._srt_time(1.0) == "00:00:01,000"

    def test_one_minute(self):
        assert vp._srt_time(60.0) == "00:01:00,000"

    def test_one_hour(self):
        assert vp._srt_time(3600.0) == "01:00:00,000"

    def test_milliseconds(self):
        assert vp._srt_time(1.5) == "00:00:01,500"

    def test_complex(self):
        # 1h 2m 3.456s
        seconds = 3600 + 120 + 3.456
        assert vp._srt_time(seconds) == "01:02:03,456"

    def test_negative_clamped_to_zero(self):
        assert vp._srt_time(-1.0) == "00:00:00,000"

    def test_rounding(self):
        # 1.9995 rounds to 2.000
        result = vp._srt_time(1.9995)
        assert result == "00:00:02,000"

    def test_fractional_seconds(self):
        assert vp._srt_time(0.001) == "00:00:00,001"


# ===========================================================================
# 4. keyword_for_text
# ===========================================================================
class TestKeywordForText:
    def test_basic(self):
        # New phrasing leads with capitalized proper-noun phrases, so casing is
        # preserved ("Messi"); assert case-insensitively.
        result = vp.keyword_for_text("Lionel Messi scores a beautiful goal").lower()
        assert "messi" in result
        assert "scores" in result

    def test_stop_words_excluded(self):
        result = vp.keyword_for_text("a an the of and")
        # All stop words -> fallback
        assert result == "cinematic documentary scene"

    def test_empty_string(self):
        assert vp.keyword_for_text("") == "cinematic documentary scene"

    def test_max_8_words(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        result = vp.keyword_for_text(text)
        assert len(result.split()) <= 8

    def test_no_digits_in_result(self):
        result = vp.keyword_for_text("goal scored in 90 minutes")
        words = result.split()
        for w in words:
            assert not w.isdigit()

    def test_short_words_excluded(self):
        # words <= 2 chars are excluded
        result = vp.keyword_for_text("go do it so")
        # All 2-char words removed, stop words removed -> fallback
        assert result == "cinematic documentary scene"

    def test_deduplication(self):
        result = vp.keyword_for_text("messi messi messi scored")
        assert result.split().count("messi") == 1

    def test_unicode_text(self):
        result = vp.keyword_for_text("Pháp đấu Brazil")
        # Should produce something (unicode normalized)
        assert isinstance(result, str)


# ===========================================================================
# 5. _clean_search_keyword
# ===========================================================================
class TestCleanSearchKeyword:
    def test_removes_quotes(self):
        assert '"' not in vp._clean_search_keyword('"hello world"')

    def test_removes_backticks(self):
        assert '`' not in vp._clean_search_keyword('`test`')

    def test_removes_filler_words(self):
        result = vp._clean_search_keyword("best free stock photo of messi")
        assert "free" not in result.lower()
        assert "stock" not in result.lower()
        assert "photo" not in result.lower()

    def test_removes_hd_4k(self):
        result = vp._clean_search_keyword("messi hd 4k")
        assert "hd" not in result.lower()
        assert "4k" not in result.lower()

    def test_max_90_chars(self):
        result = vp._clean_search_keyword("a" * 200)
        assert len(result) <= 90

    def test_strips_leading_trailing(self):
        result = vp._clean_search_keyword("  , ; - hello - ,  ")
        assert result == result.strip(" ,;:-")

    def test_empty_string(self):
        assert vp._clean_search_keyword("") == ""

    def test_none_treated_as_empty(self):
        assert vp._clean_search_keyword(None) == ""  # type: ignore[arg-type]

    def test_multiple_spaces_collapsed(self):
        result = vp._clean_search_keyword("messi   barcelona   photo")
        assert "  " not in result

    def test_real_life_removed(self):
        result = vp._clean_search_keyword("real life messi")
        assert "real life" not in result.lower()

    def test_image_removed(self):
        result = vp._clean_search_keyword("messi image")
        assert "image" not in result.lower()

    def test_picture_removed(self):
        result = vp._clean_search_keyword("messi picture")
        assert "picture" not in result.lower()


# ===========================================================================
# 6. _is_generic_keyword
# ===========================================================================
class TestIsGenericKeyword:
    def test_too_short_is_generic(self):
        assert vp._is_generic_keyword("messi") is True  # only 1 non-stop word

    def test_two_words_is_generic(self):
        assert vp._is_generic_keyword("football player") is True

    def test_specific_enough(self):
        # 3+ words, specific enough
        assert vp._is_generic_keyword("Messi Barcelona dribbling defender") is False

    def test_all_generic_terms(self):
        assert vp._is_generic_keyword("football player ball sport") is True

    def test_scene_context_helps(self):
        # New early-acceptance rule: a 2-word query is NOT generic when it has a
        # specific word (len>2, not a generic image term) that also appears in the
        # scene text. Here "goal" is specific and present in the scene, so the
        # query is rescued -> not generic.
        result = vp._is_generic_keyword("goal celebration", "Messi scored a beautiful goal against Real Madrid")
        assert result is False

    def test_two_words_no_scene_overlap_is_generic(self):
        # Two non-stop words but no specific word shared with the scene -> generic.
        result = vp._is_generic_keyword("stadium crowd", "Messi scored a beautiful goal against Real Madrid")
        assert result is True

    def test_empty_string(self):
        assert vp._is_generic_keyword("") is True

    def test_stop_words_ignored(self):
        # "in the a" -> all stop words -> 0 meaningful words -> generic
        assert vp._is_generic_keyword("in the a") is True


# ===========================================================================
# 7. _concise_match_query
# ===========================================================================
class TestConciseMatchQuery:
    def _item(self, **kw):
        return {"sentence_text": "", **kw}

    def test_removes_banned_phrases(self):
        result = vp._concise_match_query("France Brazil players competing game action", self._item())
        assert "players competing" not in result
        assert "game action" not in result

    def test_removes_banned_words(self):
        # "photo" is still a harmful pollutant and must be removed, but
        # "editorial" is now a legitimate Getty filter and must be KEPT.
        result = vp._concise_match_query("France Brazil editorial photo", self._item())
        assert "photo" not in result
        assert "editorial" in result.lower()

    def test_strips_numeric_scores(self):
        # Match scores like "3-0" are not indexable by image databases.
        result = vp._concise_match_query("France Brazil 3-0 victory", self._item())
        assert "3-0" not in result

    def test_keeps_useful_descriptors(self):
        # training, portrait, reaction, highlights are legitimate descriptors.
        result = vp._concise_match_query("Messi training portrait reaction highlights", self._item())
        lowered = result.lower()
        assert "training" in lowered
        assert "portrait" in lowered
        assert "reaction" in lowered
        assert "highlights" in lowered

    def test_max_9_words(self):
        query = " ".join(f"word{i}" for i in range(12))
        result = vp._concise_match_query(query, self._item())
        assert len(result.split()) <= 9

    def test_max_120_chars(self):
        query = " ".join(["longword"] * 30)
        result = vp._concise_match_query(query, self._item())
        assert len(result) <= 120

    def test_empty_returns_empty(self):
        assert vp._concise_match_query("", self._item()) == ""

    def test_cleans_whitespace(self):
        result = vp._concise_match_query("France  Brazil  goal", self._item())
        assert "  " not in result

    def test_removes_thumbnail(self):
        result = vp._concise_match_query("France Brazil thumbnail match", self._item())
        assert "thumbnail" not in result

    def test_removes_harmful_word(self):
        # editorial-family words are now KEPT; instead a genuinely harmful
        # pollutant like "wallpaper" / "logo" must still be stripped.
        result = vp._concise_match_query("France Brazil wallpaper logo match", self._item())
        lowered = result.lower()
        assert "wallpaper" not in lowered
        assert "logo" not in lowered


# ===========================================================================
# 8. _infer_match_teams
# ===========================================================================
class TestInferMatchTeams:
    def test_vs_pattern(self):
        result = vp._infer_match_teams("France vs Brazil was a great match.")
        assert result == ["France", "Brazil"]

    def test_versus_pattern(self):
        result = vp._infer_match_teams("France versus Brazil kicked off at 8pm.")
        assert result == ["France", "Brazil"]

    def test_faced_pattern(self):
        result = vp._infer_match_teams("France faced Brazil in the final.")
        assert result == ["France", "Brazil"]

    def test_match_against_pattern(self):
        result = vp._infer_match_teams("France played a tough match against Brazil.")
        assert result == ["France", "Brazil"]

    def test_no_teams_found(self):
        result = vp._infer_match_teams("This is just a normal sentence.")
        assert result == []

    def test_empty_string(self):
        assert vp._infer_match_teams("") == []

    def test_same_team_ignored(self):
        result = vp._infer_match_teams("France vs France in training.")
        assert result == []

    def test_multi_word_team(self):
        result = vp._infer_match_teams("Real Madrid vs Manchester City in the final.")
        assert result[0] == "Real Madrid"
        assert result[1] == "Manchester City"

    def test_lowercase_no_match(self):
        # Pattern requires capital letters
        result = vp._infer_match_teams("france vs brazil")
        assert result == []

    def test_vs_dot_pattern(self):
        result = vp._infer_match_teams("France vs. Brazil on Tuesday.")
        assert result == ["France", "Brazil"]


# ===========================================================================
# 8b. _extract_year_competition
# ===========================================================================
class TestExtractYearCompetition:
    def test_year_and_competition(self):
        result = vp._extract_year_competition(
            "It was the 2022 World Cup final in Qatar that sealed his legacy."
        )
        assert "2022" in result
        assert "World Cup" in result

    def test_appends_round(self):
        result = vp._extract_year_competition("The 2014 World Cup final ended in heartbreak.")
        assert "final" in result.lower()

    def test_no_year_or_competition(self):
        assert vp._extract_year_competition("He trained hard every single day.") == ""

    def test_empty_string(self):
        assert vp._extract_year_competition("") == ""

    def test_competition_only(self):
        # No year, but a competition is still returned.
        result = vp._extract_year_competition("They won the Champions League that season.")
        assert "Champions League" in result


# ===========================================================================
# 8c. _apply_match_search_context / _contextual_match_query (year+competition)
# ===========================================================================
_SCORE_TOKEN = re.compile(r"\b\d+[-–]\d+\b")


class TestApplyMatchSearchContext:
    SCRIPT = (
        "Argentina vs Brazil at the 2022 World Cup final was unforgettable. "
        "Argentina won three nil thanks to a brilliant team effort."
    )

    def test_year_competition_injected_not_score(self):
        item = {
            "sentence_text": "Argentina vs Brazil clashed at the 2022 World Cup final.",
        }
        result = vp._apply_match_search_context([item], self.SCRIPT)
        queries = result[0].get("google_queries") or []
        assert queries, "expected google_queries to be populated"
        joined = " ".join(queries)
        # Year and/or competition should appear in the enriched queries.
        assert "2022" in joined or "World Cup" in joined
        # No bare score token like "3-0" should leak into any query.
        for query in queries:
            assert not _SCORE_TOKEN.search(query), f"score token leaked: {query!r}"

    def test_no_numeric_score_token_anywhere(self):
        item = {"sentence_text": "Argentina scored the winning goal against Brazil."}
        result = vp._apply_match_search_context([item], self.SCRIPT)
        for query in result[0].get("google_queries") or []:
            assert "3-0" not in query and "3-1" not in query


class TestContextualMatchQueryEvent:
    def test_includes_year_competition_not_score(self):
        script = (
            "Argentina vs Brazil met in the 2022 World Cup final. "
            "Argentina won three nil in a famous victory."
        )
        item = {"sentence_text": "Lionel Messi celebrated the goal against Brazil."}
        teams = vp._infer_match_teams(script)
        assert len(teams) == 2
        query = vp._contextual_match_query(item, script, teams)
        assert query
        assert "2022" in query or "World Cup" in query
        assert not _SCORE_TOKEN.search(query), f"score token leaked: {query!r}"


# ===========================================================================
# 8d. FIX #4 — strong single-subject queries survive enrichment
# ===========================================================================
class TestApplyScriptVisualContextStrongSubject:
    def test_strong_single_subject_query_survives(self):
        script = (
            "Argentina vs Brazil met in the 2022 World Cup final. "
            "Lionel Messi was the star of the night for Argentina."
        )
        item = {
            "sentence_text": "Lionel Messi celebrated after the final whistle.",
            "main_subject": "Lionel Messi",
            "match_teams": ["Argentina", "Brazil"],
            "keyword": "Lionel Messi celebration",
            "google_queries": ["Lionel Messi celebration"],
        }
        result = vp._apply_script_visual_context([item], script)
        queries = result[0].get("google_queries") or []
        joined = " ".join(queries).lower()
        # The strong single-subject query must not be overwritten into a generic
        # both-teams matchup; Messi must still be present.
        assert "messi" in joined


# ===========================================================================
# 9. _script_sentences
# ===========================================================================
class TestScriptSentences:
    def test_basic_periods(self):
        result = vp._script_sentences("Hello world. This is a test.")
        assert result == ["Hello world.", "This is a test."]

    def test_exclamation(self):
        result = vp._script_sentences("Goal! Amazing strike!")
        assert result == ["Goal!", "Amazing strike!"]

    def test_question_mark(self):
        result = vp._script_sentences("Who scored? Messi did.")
        assert result == ["Who scored?", "Messi did."]

    def test_empty_string(self):
        assert vp._script_sentences("") == []

    def test_none_treated_as_empty(self):
        assert vp._script_sentences(None) == []  # type: ignore[arg-type]

    def test_multiple_spaces_normalized(self):
        result = vp._script_sentences("Hello   world.   This   is   fine.")
        assert len(result) == 2

    def test_single_sentence_no_break(self):
        result = vp._script_sentences("No punctuation here")
        assert result == ["No punctuation here"]

    def test_quote_after_punctuation(self):
        result = vp._script_sentences('He said "great." Then left.')
        # The sentence should split after the quote
        assert len(result) == 2


# ===========================================================================
# 10. normalize_voice_segments
# ===========================================================================
class TestNormalizeVoiceSegments:
    def test_basic(self):
        timing = {
            "segments": [
                {"text": "Hello world.", "start": 0.0, "end": 2.0},
            ]
        }
        result = vp.normalize_voice_segments(timing)
        assert len(result) == 1
        assert result[0]["text"] == "Hello world."
        assert result[0]["start"] == 0.0
        assert result[0]["end"] == 2.0
        assert result[0]["sentence_index"] == 1

    def test_empty_text_skipped(self):
        timing = {
            "segments": [
                {"text": "", "start": 0.0, "end": 1.0},
                {"text": "Hello.", "start": 1.0, "end": 2.0},
            ]
        }
        result = vp.normalize_voice_segments(timing)
        assert len(result) == 1
        assert result[0]["text"] == "Hello."

    def test_end_clamped_above_start(self):
        timing = {
            "segments": [
                {"text": "Hi.", "start": 1.0, "end": 0.5},  # end < start
            ]
        }
        result = vp.normalize_voice_segments(timing)
        # end must be >= start + 0.05
        assert result[0]["end"] >= result[0]["start"] + 0.05

    def test_empty_segments(self):
        assert vp.normalize_voice_segments({"segments": []}) == []

    def test_no_segments_key(self):
        assert vp.normalize_voice_segments({}) == []

    def test_non_dict_segment_skipped(self):
        timing = {"segments": ["not a dict", {"text": "Ok.", "start": 0.0, "end": 1.0}]}
        result = vp.normalize_voice_segments(timing)
        assert len(result) == 1

    def test_sentence_index_increments(self):
        timing = {
            "segments": [
                {"text": "First.", "start": 0.0, "end": 1.0},
                {"text": "Second.", "start": 1.0, "end": 2.0},
            ]
        }
        result = vp.normalize_voice_segments(timing)
        assert result[0]["sentence_index"] == 1
        assert result[1]["sentence_index"] == 2

    def test_start_clamped_at_zero(self):
        timing = {"segments": [{"text": "Hi.", "start": -1.0, "end": 1.0}]}
        result = vp.normalize_voice_segments(timing)
        assert result[0]["start"] == 0.0

    def test_uses_start_time_key(self):
        timing = {"segments": [{"text": "Hi.", "start_time": 1.5, "end": 3.0}]}
        result = vp.normalize_voice_segments(timing)
        assert result[0]["start"] == 1.5


# ===========================================================================
# 11. merge_segments_into_sentences
# ===========================================================================
class TestMergeSegmentsIntoSentences:
    def _seg(self, text, start, end, idx=1):
        return {"sentence_index": idx, "text": text, "start": start, "end": end}

    def test_single_complete_sentence(self):
        segs = [self._seg("Hello world.", 0.0, 2.0, 1)]
        result = vp.merge_segments_into_sentences(segs)
        assert len(result) == 1
        assert result[0]["text"] == "Hello world."

    def test_two_separate_sentences(self):
        segs = [
            self._seg("First sentence.", 0.0, 2.0, 1),
            self._seg("Second sentence.", 2.0, 4.0, 2),
        ]
        result = vp.merge_segments_into_sentences(segs)
        assert len(result) == 2

    def test_merges_segments_without_punctuation(self):
        segs = [
            self._seg("Part one", 0.0, 1.0, 1),
            self._seg("part two.", 1.0, 2.0, 2),
        ]
        result = vp.merge_segments_into_sentences(segs)
        assert len(result) == 1
        assert "Part one" in result[0]["text"]
        assert "part two" in result[0]["text"]

    def test_exclamation_splits(self):
        segs = [
            self._seg("Goal!", 0.0, 1.0, 1),
            self._seg("Amazing.", 1.0, 2.0, 2),
        ]
        result = vp.merge_segments_into_sentences(segs)
        assert len(result) == 2

    def test_empty_list(self):
        assert vp.merge_segments_into_sentences([]) == []

    def test_pending_segments_flushed_at_end(self):
        segs = [
            self._seg("No punctuation here", 0.0, 2.0, 1),
        ]
        result = vp.merge_segments_into_sentences(segs)
        assert len(result) == 1

    def test_sentence_start_end(self):
        segs = [
            self._seg("Hello.", 1.0, 3.0, 1),
        ]
        result = vp.merge_segments_into_sentences(segs)
        assert result[0]["start"] == 1.0
        assert result[0]["end"] == 3.0

    def test_question_mark_splits(self):
        segs = [
            self._seg("Who scored?", 0.0, 1.0, 1),
            self._seg("Messi did.", 1.0, 2.0, 2),
        ]
        result = vp.merge_segments_into_sentences(segs)
        assert len(result) == 2


# ===========================================================================
# 12. split_sentences_into_scenes
# ===========================================================================
class TestSplitSentencesIntoScenes:
    def _sent(self, text, start, end, idx=1):
        return {
            "sentence_index": idx,
            "text": text,
            "start": start,
            "end": end,
            "segment_indexes": [idx],
        }

    def test_empty_returns_empty(self):
        assert vp.split_sentences_into_scenes([]) == []

    def test_single_sentence_one_scene(self):
        sentences = [self._sent("Hello world.", 0.0, 3.0, 1)]
        scenes = vp.split_sentences_into_scenes(sentences)
        assert len(scenes) == 1
        assert scenes[0]["break_reason"] == "opening"

    def test_short_sentences_merged(self):
        # All sentences < 5s total -> should stay in one scene
        sentences = [
            self._sent("First.", 0.0, 1.0, 1),
            self._sent("Second.", 1.0, 2.0, 2),
        ]
        scenes = vp.split_sentences_into_scenes(sentences)
        assert len(scenes) == 1

    def test_long_scene_guard_over_25s(self):
        # Pacing is intentionally softer now (AI grouping is primary; this local
        # splitter is a fallback). The hard long_scene_guard fires at >= 25s.
        # A single >=25s sentence makes the next one start a new scene with the
        # long_scene_guard reason (shorter accumulations break earlier via
        # target_scene_duration / scene_sentence_limit instead).
        sentences = [
            self._sent("A long uninterrupted narration that runs well past the soft pacing target.", 0.0, 26.0, 1),
            self._sent("Then the next part begins.", 26.0, 30.0, 2),
        ]
        scenes = vp.split_sentences_into_scenes(sentences)
        assert len(scenes) >= 2
        reasons = [s["break_reason"] for s in scenes]
        assert "long_scene_guard" in reasons

    def test_scene_sentence_limit_at_4(self):
        # 4 sentences in current -> 5th triggers scene_sentence_limit
        sentences = [
            self._sent("Sentence one.", 0.0, 1.0, 1),
            self._sent("Sentence two.", 1.0, 2.0, 2),
            self._sent("Sentence three.", 2.0, 3.0, 3),
            self._sent("Sentence four.", 3.0, 4.0, 4),
            self._sent("Sentence five.", 4.0, 5.0, 5),
        ]
        scenes = vp.split_sentences_into_scenes(sentences)
        reasons = [s["break_reason"] for s in scenes]
        assert "scene_sentence_limit" in reasons

    def test_transition_word_breaks_scene(self):
        # "Meanwhile" is a SCENE_SHIFT_PREFIX - should break scene if current >= 4s
        sentences = [
            self._sent("France was playing brilliantly.", 0.0, 5.0, 1),
            self._sent("Meanwhile, Brazil attacked.", 5.0, 8.0, 2),
        ]
        scenes = vp.split_sentences_into_scenes(sentences)
        assert len(scenes) >= 2
        reasons = [s["break_reason"] for s in scenes]
        assert "transition" in reasons

    def test_first_scene_always_opening(self):
        sentences = [self._sent("Hello.", 0.0, 2.0, 1)]
        scenes = vp.split_sentences_into_scenes(sentences)
        assert scenes[0]["break_reason"] == "opening"


# ===========================================================================
# 13. _proper_names
# ===========================================================================
class TestProperNames:
    def test_basic_names(self):
        result = vp._proper_names("Messi scored against Real Madrid")
        assert "messi" in result
        assert "real" in result
        assert "madrid" in result

    def test_empty_string(self):
        assert vp._proper_names("") == set()

    def test_none_treated_as_empty(self):
        assert vp._proper_names(None) == set()  # type: ignore[arg-type]

    def test_ignored_words_excluded(self):
        result = vp._proper_names("Then After Meanwhile Suddenly")
        assert "then" not in result
        assert "after" not in result
        assert "meanwhile" not in result

    def test_lowercase_not_included(self):
        result = vp._proper_names("messi scored")
        assert "messi" not in result  # not capitalized

    def test_short_words_not_matched(self):
        # Pattern requires at least 2 lowercase letters after capital
        result = vp._proper_names("It Is At")
        # "It" = I + t = 1 lowercase; "Is" = I + s = 1 lowercase; "At" = A + t = 1 lowercase
        # Pattern is [A-Z][a-z]{2,} so these should not match
        assert "it" not in result
        assert "is" not in result

    def test_returns_lowercase(self):
        result = vp._proper_names("France")
        assert "france" in result


# ===========================================================================
# 14. _capitalized_phrases
# ===========================================================================
class TestCapitalizedPhrases:
    def test_single_cap_word(self):
        result = vp._capitalized_phrases("Messi played well")
        assert "Messi" in result

    def test_multi_word_phrase(self):
        result = vp._capitalized_phrases("Real Madrid won the match")
        assert "Real Madrid" in result

    def test_ignored_words_excluded(self):
        result = vp._capitalized_phrases("The player scored")
        # "The" is in the ignored list
        assert "The" not in result
        assert "The player" not in result

    def test_empty_string(self):
        assert vp._capitalized_phrases("") == []

    def test_none_treated_as_empty(self):
        assert vp._capitalized_phrases(None) == []  # type: ignore[arg-type]

    def test_possessive_stripped(self):
        result = vp._capitalized_phrases("Messi's goal was stunning")
        # 's should be stripped
        for phrase in result:
            assert "'s" not in phrase

    def test_deduplication(self):
        result = vp._capitalized_phrases("Messi scored. Messi celebrated.")
        assert result.count("Messi") == 1

    def test_max_phrase_length(self):
        # Pattern allows up to 5 words
        result = vp._capitalized_phrases("France Brazil Argentina Germany Spain Italy Portugal")
        # Should not get a 6-word phrase
        for phrase in result:
            assert len(phrase.split()) <= 5


# ===========================================================================
# 15. read_json / write_json
# ===========================================================================
class TestReadWriteJson:
    def test_write_and_read_back(self, tmp_path):
        path = tmp_path / "data.json"
        data = {"key": "value", "number": 42}
        vp.write_json(path, data)
        result = vp.read_json(path)
        assert result == data

    def test_write_creates_parents(self, tmp_path):
        path = tmp_path / "subdir" / "nested" / "data.json"
        vp.write_json(path, [1, 2, 3])
        assert path.exists()
        assert vp.read_json(path) == [1, 2, 3]

    def test_read_missing_file_returns_fallback(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        result = vp.read_json(path, fallback={"default": True})
        assert result == {"default": True}

    def test_read_missing_file_default_fallback_none(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        result = vp.read_json(path)
        assert result is None

    def test_read_invalid_json_returns_fallback(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("this is not json", encoding="utf-8")
        result = vp.read_json(path, fallback="fallback_value")
        assert result == "fallback_value"

    def test_write_unicode(self, tmp_path):
        path = tmp_path / "unicode.json"
        data = {"text": "Pháp vs Brazil – trận đấu lịch sử"}
        vp.write_json(path, data)
        result = vp.read_json(path)
        assert result["text"] == data["text"]

    def test_write_list(self, tmp_path):
        path = tmp_path / "list.json"
        vp.write_json(path, [1, "two", 3.0])
        assert vp.read_json(path) == [1, "two", 3.0]


# ===========================================================================
# 16. _microseconds
# ===========================================================================
class TestMicroseconds:
    def test_zero(self):
        assert vp._microseconds(0) == 0

    def test_one_second(self):
        assert vp._microseconds(1.0) == 1_000_000

    def test_half_second(self):
        assert vp._microseconds(0.5) == 500_000

    def test_negative_clamped_to_zero(self):
        assert vp._microseconds(-1.0) == 0

    def test_rounding(self):
        # 0.0000006 * 1_000_000 = 0.6 -> rounds to 1 (> 0.5 always rounds up)
        assert vp._microseconds(0.0000006) == 1

    def test_integer_input(self):
        assert vp._microseconds(2) == 2_000_000

    def test_large_value(self):
        assert vp._microseconds(3600.0) == 3_600_000_000


# ===========================================================================
# 17. _image_filter_settings
# ===========================================================================
class TestImageFilterSettings:
    def test_defaults(self):
        result = vp._image_filter_settings({})
        assert result["aspect"] == pytest.approx(16 / 9)
        assert result["min_width"] == vp.DEFAULT_IMAGE_MIN_WIDTH
        assert result["min_height"] == vp.DEFAULT_IMAGE_MIN_HEIGHT
        assert result["target_width"] == vp.DEFAULT_IMAGE_TARGET_WIDTH
        assert result["target_height"] == vp.DEFAULT_IMAGE_TARGET_HEIGHT

    def test_none_input(self):
        result = vp._image_filter_settings(None)
        assert result["aspect"] == pytest.approx(16 / 9)

    def test_custom_aspect(self):
        result = vp._image_filter_settings({"image_aspect_width": 4, "image_aspect_height": 3})
        assert result["aspect"] == pytest.approx(4 / 3)

    def test_tolerance_minimum(self):
        result = vp._image_filter_settings({"image_aspect_tolerance": 0.0})
        assert result["tolerance"] >= 0.001

    def test_min_width_clamped(self):
        result = vp._image_filter_settings({"image_min_width": 100})
        assert result["min_width"] == 320  # minimum enforced

    def test_min_height_clamped(self):
        result = vp._image_filter_settings({"image_min_height": 50})
        assert result["min_height"] == 180  # minimum enforced

    def test_enhance_enabled_default_true(self):
        result = vp._image_filter_settings({})
        assert result["enhance_enabled"] is True

    def test_enhance_enabled_false(self):
        result = vp._image_filter_settings({"image_enhance_enabled": False})
        assert result["enhance_enabled"] is False


# ===========================================================================
# _google_tbs (recency date filter)
# ===========================================================================
class TestGoogleTbs:
    def test_full_date(self):
        assert vp._google_tbs("2026-01-01") == "cdr:1,cd_min:01/01/2026"

    def test_year_only(self):
        assert vp._google_tbs("2026") == "cdr:1,cd_min:01/01/2026"

    def test_month_day_padded(self):
        assert vp._google_tbs("2022-3-5") == "cdr:1,cd_min:03/05/2022"

    def test_empty(self):
        assert vp._google_tbs("") == ""

    def test_garbage_returns_empty(self):
        assert vp._google_tbs("not a date") == ""


# ===========================================================================
# 18. _is_target_aspect
# ===========================================================================
class TestIsTargetAspect:
    def test_16_9_exact(self):
        assert vp._is_target_aspect(1920, 1080, {}) is True

    def test_16_9_close(self):
        assert vp._is_target_aspect(1280, 720, {}) is True

    def test_4_3_rejected(self):
        assert vp._is_target_aspect(640, 480, {}) is False

    def test_zero_width(self):
        assert vp._is_target_aspect(0, 1080, {}) is False

    def test_zero_height(self):
        assert vp._is_target_aspect(1920, 0, {}) is False

    def test_negative_dimension(self):
        assert vp._is_target_aspect(-100, 1080, {}) is False

    def test_none_settings_uses_defaults(self):
        assert vp._is_target_aspect(1920, 1080, None) is True

    def test_custom_aspect_4_3(self):
        settings = {"image_aspect_width": 4, "image_aspect_height": 3}
        assert vp._is_target_aspect(800, 600, settings) is True

    def test_within_tolerance(self):
        # 1918/1080 is slightly off 16/9 but within tolerance
        assert vp._is_target_aspect(1918, 1080, {}) is True


class TestDiversifySceneKeywords:
    def test_duplicate_primary_promotes_alternative(self):
        items = [
            {
                "keyword": "Argentina Brazil match action",
                "ai_search_keyword": "Argentina Brazil match action",
                "google_queries": ["Argentina Brazil match action"],
                "fallback_keywords": [],
            },
            {
                "keyword": "Argentina Brazil match action",
                "ai_search_keyword": "Argentina Brazil match action",
                "google_queries": [
                    "Argentina Brazil match action",
                    "Messi celebration World Cup",
                ],
                "fallback_keywords": ["Neymar dribble Brazil"],
            },
        ]
        result = vp._diversify_scene_keywords(items)
        first, second = result[0], result[1]
        # The two primaries must now differ.
        assert first["keyword"] != second["keyword"]
        # First item keeps its original primary (it was unique when seen).
        assert first["keyword"] == "Argentina Brazil match action"
        # Second item's new primary is one of its own alternatives.
        assert second["keyword"] in (
            "Messi celebration World Cup",
            "Neymar dribble Brazil",
        )
        assert second["keyword"] == "Messi celebration World Cup"
        # ai_search_keyword tracks the promoted primary.
        assert second["ai_search_keyword"] == second["keyword"]
        # google_queries is reordered so the chosen primary is first.
        assert second["google_queries"][0] == second["keyword"]
        # The original primary is preserved further down (deduped).
        assert "Argentina Brazil match action" in second["google_queries"]

    def test_fallback_used_when_google_queries_exhausted(self):
        items = [
            {
                "keyword": "Argentina Brazil match action",
                "google_queries": ["Argentina Brazil match action"],
                "fallback_keywords": [],
            },
            {
                "keyword": "Argentina Brazil match action",
                # Only a single google query (the duplicate); the distinct
                # option lives in fallback_keywords.
                "google_queries": ["Argentina Brazil match action"],
                "fallback_keywords": ["Brazil defense pressing"],
            },
        ]
        result = vp._diversify_scene_keywords(items)
        assert result[1]["keyword"] == "Brazil defense pressing"
        assert result[0]["keyword"] != result[1]["keyword"]

    def test_all_alternatives_are_duplicates_stays_as_is(self):
        # First two scenes lock "A B match" and "C D match". The third scene's
        # only alternatives duplicate already-used primaries, so it must stay
        # as-is without crashing (degraded case).
        items = [
            {
                "keyword": "A B match",
                "google_queries": ["A B match"],
                "fallback_keywords": [],
            },
            {
                "keyword": "C D match",
                "google_queries": ["C D match"],
                "fallback_keywords": [],
            },
            {
                "keyword": "A B match",
                "google_queries": ["A B match", "C D match"],
                "fallback_keywords": ["a b match", "C   D match"],
            },
        ]
        result = vp._diversify_scene_keywords(items)
        # No unused alternative -> third item stays as its original primary.
        assert result[2]["keyword"] == "A B match"
        assert result[2]["google_queries"] == ["A B match", "C D match"]

    def test_missing_keys_no_crash(self):
        items = [
            {"keyword": "Argentina Brazil match action"},
            # Duplicate primary but no google_queries / fallback_keywords keys.
            {"keyword": "Argentina Brazil match action"},
            # No keyword at all.
            {},
        ]
        result = vp._diversify_scene_keywords(items)
        assert len(result) == 3
        # Second item has no alternatives -> stays as-is.
        assert result[1]["keyword"] == "Argentina Brazil match action"

    def test_all_unique_primaries_unchanged(self):
        items = [
            {
                "keyword": "Messi free kick",
                "ai_search_keyword": "Messi free kick",
                "google_queries": ["Messi free kick", "Argentina celebration"],
                "fallback_keywords": ["Argentina squad"],
            },
            {
                "keyword": "Neymar dribble",
                "ai_search_keyword": "Neymar dribble",
                "google_queries": ["Neymar dribble", "Brazil attack"],
                "fallback_keywords": ["Brazil squad"],
            },
        ]
        import copy

        before = copy.deepcopy(items)
        result = vp._diversify_scene_keywords(items)
        assert result == before

    def test_normalization_ignores_case_and_punctuation(self):
        items = [
            {
                "keyword": "Argentina Brazil Match Action",
                "google_queries": ["Argentina Brazil Match Action"],
                "fallback_keywords": [],
            },
            {
                # Differs only by case/punctuation -> treated as duplicate.
                "keyword": "argentina, brazil match-action!",
                "google_queries": [
                    "argentina, brazil match-action!",
                    "Di Maria assist",
                ],
                "fallback_keywords": [],
            },
        ]
        result = vp._diversify_scene_keywords(items)
        assert result[1]["keyword"] == "Di Maria assist"


class TestStripForeignContextPhrases:
    def test_name_in_main_subject_is_kept(self):
        # "Maracana" is name-like and absent from the script/context, but it is
        # present in the item's own main_subject, so it must be kept.
        item = {"main_subject": "Maracana stadium"}
        result = vp._strip_foreign_context_phrases(
            "Maracana stadium match action", "a football match", item
        )
        assert "Maracana" in result

    def test_unknown_proper_noun_is_demoted_not_dropped(self):
        # DEMOTE semantics: a name-like word absent from script, context, and
        # main_subject is now KEPT (not dropped). We no longer band-aid away
        # proper nouns the engine simply did not see in the surrounding text.
        item = {"main_subject": "stadium crowd"}
        result = vp._strip_foreign_context_phrases(
            "Zzyzxland stadium crowd", "a football match", item
        )
        assert "Zzyzxland" in result
        assert "stadium" in result


class TestScenePromptEnglishRule:
    def test_scene_prompt_requires_english(self):
        prompt = vp._scene_prompt("script", [], 4.0, 25.0)
        assert "ENGLISH" in prompt

    def test_video_context_prompt_requires_english(self):
        prompt = vp._video_context_prompt("script")
        assert "English" in prompt
