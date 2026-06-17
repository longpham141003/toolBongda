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


# ---------------------------------------------------------------------------
# Tests for _limit_named_characters (M5: ≤3 named characters per prompt)
# ---------------------------------------------------------------------------

def test_limit_named_characters_drops_4th_distinct_name():
    """4 distinct named characters: A, B, C kept; D block replaced."""
    text = "Alpha (tall man) walks in, greets Beta (short woman) and Gamma (old man). Delta (young boy) runs away."
    result = ps._limit_named_characters(text, limit=3)
    # First three names' parenthetical blocks must be preserved
    assert "(tall man)" in result
    assert "(short woman)" in result
    assert "(old man)" in result
    # The 4th name block must be gone
    assert "Delta (" not in result
    assert "another person nearby" in result


def test_limit_named_characters_repeated_name_counts_once():
    """Repeated name Ama counts as 1 distinct character; both blocks kept."""
    text = "Ama (tall woman) laughs. Ben (young man) waves. Ama (tall woman) sits down. Cara (older woman) watches."
    result = ps._limit_named_characters(text, limit=3)
    # Ama appears twice - both should be kept (same character)
    assert result.count("Ama (") == 2
    # Ben and Cara are 2nd and 3rd distinct names
    assert "Ben (" in result
    assert "Cara (" in result


def test_limit_named_characters_within_limit_unchanged():
    """≤3 named characters → no blocks are replaced."""
    text = "Anna (brunette woman) talks to Bob (bearded man) while Cara (young girl) watches."
    result = ps._limit_named_characters(text, limit=3)
    assert "(brunette woman)" in result
    assert "(bearded man)" in result
    assert "(young girl)" in result
    assert "another person nearby" not in result


def test_enforce_realistic_prompt_applies_named_character_limit():
    """enforce_realistic_prompt with 4 distinct names: 4th name block replaced."""
    text = "Alpha (tall man) walks, Beta (short woman) talks, Gamma (old man) sits, Delta (young boy) runs."
    out = ps.enforce_realistic_prompt(text, named_count_limit=3)
    # Leading number strip not applicable here; policy sanitize fine
    # 4th character Delta block must be gone
    assert "Delta (" not in out
    assert "another person nearby" in out
    # Tag appended exactly once at end
    assert out.endswith(ps.REALISTIC_TAG)


def test_enforce_realistic_prompt_still_strips_number_sanitizes_appends_tag():
    """Existing behaviors: strip leading number, sanitize policy words, append tag."""
    out = ps.enforce_realistic_prompt("3. A nude person holding a gun")
    assert not out.startswith("3.")
    assert "nude" not in out.lower()
    assert "gun" not in out.lower()
    assert out.endswith(ps.REALISTIC_TAG)


# ---------------------------------------------------------------------------
# Tests for _sanitize_policy_words (M6: smarter policy-word sanitizer)
# ---------------------------------------------------------------------------

def test_sanitize_blood_test_unchanged():
    """'blood test' is a benign collocation — must NOT be replaced."""
    result = ps._sanitize_policy_words("She needs a blood test today")
    assert "blood test" in result
    assert "dramatic" not in result


def test_sanitize_blood_pressure_unchanged():
    """'blood pressure' is a benign collocation — must NOT be replaced."""
    result = ps._sanitize_policy_words("checking her blood pressure")
    assert "blood pressure" in result
    assert "dramatic" not in result


def test_sanitize_standalone_blood_replaced():
    """Standalone 'blood' (not followed by a benign word) must be replaced."""
    result = ps._sanitize_policy_words("the floor covered in blood")
    assert "blood" not in result.lower()
    assert "dramatic scene" in result


def test_sanitize_gun_replaced():
    """'gun' → 'a handheld object'."""
    result = ps._sanitize_policy_words("a man holding a gun")
    assert "gun" not in result.lower()
    assert "handheld object" in result


def test_sanitize_nude_replaced():
    """'nude' → 'casually dressed'."""
    result = ps._sanitize_policy_words("a nude figure")
    assert "nude" not in result.lower()
    assert "casually dressed" in result


def test_sanitize_naked_replaced():
    """'naked' → 'casually dressed'."""
    result = ps._sanitize_policy_words("a naked person")
    assert "naked" not in result.lower()
    assert "casually dressed" in result


def test_sanitize_gore_left_as_is():
    """'gore' is dropped from replacements — must remain unchanged."""
    result = ps._sanitize_policy_words("gore everywhere")
    assert "gore" in result.lower()


def test_enforce_realistic_prompt_integration():
    """Integration: strips leading number, sanitizes gun, enforces ≤3 names, ends with REALISTIC_TAG."""
    text = "2. Alpha (tall man) walks, Beta (short woman) talks, Gamma (old man) sits, Delta (young boy) holds a gun."
    out = ps.enforce_realistic_prompt(text, named_count_limit=3)
    # Leading number stripped
    assert not out.startswith("2.")
    # gun sanitized
    assert "gun" not in out.lower()
    assert "handheld object" in out
    # 4th named character dropped
    assert "Delta (" not in out
    assert "another person nearby" in out
    # ends with REALISTIC_TAG
    assert out.endswith(ps.REALISTIC_TAG)
