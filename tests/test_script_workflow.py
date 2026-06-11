"""Tests for app/script_workflow.py."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from app.script_workflow import (
    default_workflow_steps,
    normalize_workflow_steps,
    run_script_workflow,
)


# ===========================================================================
# default_workflow_steps() tests
# ===========================================================================

class TestDefaultWorkflowSteps:
    def test_returns_list(self):
        steps = default_workflow_steps()
        assert isinstance(steps, list)

    def test_returns_three_steps(self):
        steps = default_workflow_steps()
        assert len(steps) == 3

    def test_all_steps_are_dicts(self):
        for step in default_workflow_steps():
            assert isinstance(step, dict)

    def test_all_steps_enabled(self):
        for step in default_workflow_steps():
            assert step["enabled"] is True

    def test_all_steps_have_name(self):
        for step in default_workflow_steps():
            assert step.get("name") and isinstance(step["name"], str)

    def test_all_steps_have_prompt(self):
        for step in default_workflow_steps():
            assert step.get("prompt") and isinstance(step["prompt"], str)

    def test_returns_independent_copies(self):
        """Mutating one result should not affect the next call."""
        a = default_workflow_steps()
        a[0]["enabled"] = False
        b = default_workflow_steps()
        assert b[0]["enabled"] is True


# ===========================================================================
# normalize_workflow_steps() tests
# ===========================================================================

class TestNormalizeWorkflowSteps:
    def test_none_returns_empty_list(self):
        assert normalize_workflow_steps(None) == []

    def test_empty_list_returns_empty_list(self):
        assert normalize_workflow_steps([]) == []

    def test_skips_non_dict_items(self):
        result = normalize_workflow_steps(["string", 42, None, {"prompt": "hello"}])
        assert len(result) == 1
        assert result[0]["prompt"] == "hello"

    def test_skips_item_with_empty_prompt(self):
        result = normalize_workflow_steps([{"prompt": ""}, {"prompt": "   "}])
        assert result == []

    def test_skips_item_with_missing_prompt(self):
        result = normalize_workflow_steps([{"name": "Step 1"}])
        assert result == []

    def test_prompt_stripped(self):
        result = normalize_workflow_steps([{"prompt": "  hello world  "}])
        assert result[0]["prompt"] == "hello world"

    def test_enabled_defaults_to_true(self):
        result = normalize_workflow_steps([{"prompt": "do something"}])
        assert result[0]["enabled"] is True

    def test_enabled_false_preserved(self):
        result = normalize_workflow_steps([{"prompt": "do something", "enabled": False}])
        assert result[0]["enabled"] is False

    def test_enabled_true_preserved(self):
        result = normalize_workflow_steps([{"prompt": "do something", "enabled": True}])
        assert result[0]["enabled"] is True

    def test_name_default_when_missing(self):
        result = normalize_workflow_steps([{"prompt": "p1"}, {"prompt": "p2"}])
        assert result[0]["name"] == "Bước 1"
        assert result[1]["name"] == "Bước 2"

    def test_name_default_when_empty_string(self):
        result = normalize_workflow_steps([{"prompt": "do it", "name": ""}])
        # empty string after strip -> fallback
        assert result[0]["name"] == "Bước 1"

    def test_name_default_when_none(self):
        result = normalize_workflow_steps([{"prompt": "do it", "name": None}])
        assert result[0]["name"] == "Bước 1"

    def test_custom_name_preserved(self):
        result = normalize_workflow_steps([{"prompt": "do it", "name": "My Step"}])
        assert result[0]["name"] == "My Step"

    def test_name_whitespace_stripped(self):
        result = normalize_workflow_steps([{"prompt": "do it", "name": "  Trimmed  "}])
        assert result[0]["name"] == "Trimmed"

    def test_index_in_default_name_matches_input_position(self):
        """Even if first item is skipped, index counts from 1 of the enumeration."""
        raw = [
            "not a dict",              # skipped
            {"prompt": "valid step"},  # index=2 in enumerate
        ]
        result = normalize_workflow_steps(raw)
        assert len(result) == 1
        assert result[0]["name"] == "Bước 2"

    def test_multiple_valid_steps(self):
        raw = [
            {"prompt": "step A", "name": "Alpha", "enabled": True},
            {"prompt": "step B", "enabled": False},
            {"prompt": "step C"},
        ]
        result = normalize_workflow_steps(raw)
        assert len(result) == 3
        assert result[0]["name"] == "Alpha"
        assert result[1]["enabled"] is False
        assert result[2]["name"] == "Bước 3"


# ===========================================================================
# run_script_workflow() tests - input validation
# ===========================================================================

class TestRunScriptWorkflowInputValidation:
    _valid_steps = [{"prompt": "do something", "enabled": True, "name": "S1"}]
    _valid_settings = {"keyword_ai_provider": "openai", "openai_api_key": "sk-test"}

    def test_raises_if_source_input_empty_string(self):
        with pytest.raises(ValueError, match="chủ đề"):
            run_script_workflow("", self._valid_steps, self._valid_settings)

    def test_raises_if_source_input_whitespace_only(self):
        with pytest.raises(ValueError, match="chủ đề"):
            run_script_workflow("   ", self._valid_steps, self._valid_settings)

    def test_raises_if_source_input_none(self):
        with pytest.raises(ValueError, match="chủ đề"):
            run_script_workflow(None, self._valid_steps, self._valid_settings)

    def test_raises_if_no_enabled_steps(self):
        disabled_steps = [{"prompt": "p", "enabled": False}]
        with pytest.raises(ValueError, match="bước"):
            run_script_workflow("topic", disabled_steps, self._valid_settings)

    def test_raises_if_steps_is_empty_list(self):
        with pytest.raises(ValueError, match="bước"):
            run_script_workflow("topic", [], self._valid_settings)

    def test_raises_if_steps_is_none(self):
        with pytest.raises(ValueError, match="bước"):
            run_script_workflow("topic", None, self._valid_settings)


# ===========================================================================
# run_script_workflow() tests - provider validation
# ===========================================================================

class TestRunScriptWorkflowProviderValidation:
    _steps = [{"prompt": "do it", "enabled": True, "name": "S"}]

    def test_openai_raises_if_key_missing(self):
        settings = {"keyword_ai_provider": "openai", "openai_api_key": ""}
        with pytest.raises(RuntimeError, match="sk-"):
            run_script_workflow("topic", self._steps, settings)

    def test_openai_raises_if_key_invalid_prefix(self):
        settings = {"keyword_ai_provider": "openai", "openai_api_key": "not-a-real-key"}
        with pytest.raises(RuntimeError, match="sk-"):
            run_script_workflow("topic", self._steps, settings)

    def test_gemini_raises_if_key_empty(self):
        settings = {"keyword_ai_provider": "gemini", "gemini_api_key": ""}
        with pytest.raises(RuntimeError, match="Gemini"):
            run_script_workflow("topic", self._steps, settings)

    def test_gemini_raises_if_key_missing_from_settings(self):
        settings = {"keyword_ai_provider": "gemini"}
        with pytest.raises(RuntimeError, match="Gemini"):
            run_script_workflow("topic", self._steps, settings)

    def test_auto_selects_openai_when_sk_key(self):
        settings = {
            "keyword_ai_provider": "auto",
            "openai_api_key": "sk-abc123",
            "keyword_ai_model": "gpt-4.1-mini",
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "result text"}}]
        }
        with patch("app.script_workflow._call_openai", return_value="result text") as mock_openai:
            result = run_script_workflow("topic", self._steps, settings)
        mock_openai.assert_called_once()
        assert result == "result text"

    def test_auto_selects_gemini_when_no_sk_key(self):
        settings = {
            "keyword_ai_provider": "auto",
            "openai_api_key": "not-sk",
            "gemini_api_key": "AIza-key",
            "gemini_keyword_model": "gemini-2.5-flash",
        }
        with patch("app.script_workflow._call_gemini", return_value="gemini result") as mock_gemini:
            result = run_script_workflow("topic", self._steps, settings)
        mock_gemini.assert_called_once()
        assert result == "gemini result"

    def test_auto_selects_gemini_when_openai_key_empty(self):
        settings = {
            "keyword_ai_provider": "auto",
            "openai_api_key": "",
            "gemini_api_key": "my-gemini-key",
        }
        with patch("app.script_workflow._call_gemini", return_value="ok") as mock_gemini:
            result = run_script_workflow("topic", self._steps, settings)
        mock_gemini.assert_called_once()


# ===========================================================================
# run_script_workflow() tests - successful execution
# ===========================================================================

class TestRunScriptWorkflowExecution:
    _steps = [
        {"prompt": "step 1 prompt", "enabled": True, "name": "Step One"},
        {"prompt": "step 2 prompt", "enabled": True, "name": "Step Two"},
    ]
    _settings = {
        "keyword_ai_provider": "openai",
        "openai_api_key": "sk-valid",
        "keyword_ai_model": "gpt-4.1-mini",
    }

    def test_returns_final_step_output(self):
        with patch("app.script_workflow._call_openai", side_effect=["step1 out", "step2 out"]):
            result = run_script_workflow("my topic", self._steps, self._settings)
        assert result == "step2 out"

    def test_log_called_for_each_step(self):
        log_messages = []
        with patch("app.script_workflow._call_openai", side_effect=["out1", "out2"]):
            run_script_workflow("topic", self._steps, self._settings, log=log_messages.append)
        # 2 step logs + 1 completion log
        assert len(log_messages) == 3

    def test_log_none_does_not_raise(self):
        with patch("app.script_workflow._call_openai", side_effect=["out1", "out2"]):
            result = run_script_workflow("topic", self._steps, self._settings, log=None)
        assert result == "out2"

    def test_raises_if_step_returns_empty(self):
        with patch("app.script_workflow._call_openai", return_value="   "):
            with pytest.raises(RuntimeError, match="không trả về"):
                run_script_workflow("topic", self._steps, self._settings)

    def test_disabled_steps_skipped(self):
        steps_mixed = [
            {"prompt": "enabled step", "enabled": True, "name": "Active"},
            {"prompt": "disabled step", "enabled": False, "name": "Skipped"},
        ]
        call_count = []
        def fake_call(api_key, model, prompt):
            call_count.append(1)
            return "output"
        with patch("app.script_workflow._call_openai", side_effect=fake_call):
            run_script_workflow("topic", steps_mixed, self._settings)
        assert len(call_count) == 1

    def test_single_step_workflow(self):
        single = [{"prompt": "only step", "enabled": True, "name": "Only"}]
        with patch("app.script_workflow._call_openai", return_value="single output"):
            result = run_script_workflow("topic", single, self._settings)
        assert result == "single output"

    def test_output_is_stripped(self):
        with patch("app.script_workflow._call_openai", return_value="  spaced  "):
            # Two steps so the last one's result is stripped at the end
            single = [{"prompt": "p", "enabled": True, "name": "N"}]
            result = run_script_workflow("topic", single, self._settings)
        assert result == "spaced"

    def test_gemini_provider_executes(self):
        settings = {
            "keyword_ai_provider": "gemini",
            "gemini_api_key": "my-key",
            "gemini_keyword_model": "gemini-2.5-flash",
        }
        single = [{"prompt": "p", "enabled": True, "name": "N"}]
        with patch("app.script_workflow._call_gemini", return_value="gemini output") as mock:
            result = run_script_workflow("topic", single, settings)
        mock.assert_called_once()
        assert result == "gemini output"
