"""Tests for app/config.py - load_settings() and save_settings()."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import os

import pytest

# ---------------------------------------------------------------------------
# Helpers to patch module-level constants in app.config
# ---------------------------------------------------------------------------

def _patch_config(monkeypatch, tmp_path, settings_json_content=None, write_file=False):
    """
    Redirect SETTINGS_PATH and APP_DIR to tmp_path.
    Optionally write a settings.json file in tmp_path.
    Returns the patched module.
    """
    import app.config as cfg

    fake_settings_path = tmp_path / "settings.json"
    fake_app_dir = tmp_path

    monkeypatch.setattr(cfg, "APP_DIR", fake_app_dir)
    monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_settings_path)

    if write_file and settings_json_content is not None:
        fake_settings_path.write_text(
            json.dumps(settings_json_content), encoding="utf-8"
        )

    return cfg


# ===========================================================================
# load_settings() tests
# ===========================================================================

class TestLoadSettingsNoFile:
    """Behaviour when settings.json does not exist."""

    def test_returns_dict(self, monkeypatch, tmp_path):
        cfg = _patch_config(monkeypatch, tmp_path)
        result = cfg.load_settings()
        assert isinstance(result, dict)

    def test_returns_default_keys(self, monkeypatch, tmp_path):
        cfg = _patch_config(monkeypatch, tmp_path)
        result = cfg.load_settings()
        for key in cfg.DEFAULT_SETTINGS:
            assert key in result

    def test_projects_dir_is_absolute(self, monkeypatch, tmp_path):
        cfg = _patch_config(monkeypatch, tmp_path)
        result = cfg.load_settings()
        assert Path(result["projects_dir"]).is_absolute()

    def test_projects_dir_under_app_dir(self, monkeypatch, tmp_path):
        """projects_dir default is APP_DIR/Projects; after patching APP_DIR the
        DEFAULT_SETTINGS string is already baked in (module-level constant), so
        the returned path is the real APP_DIR/Projects — just verify it is absolute
        and ends with 'Projects'."""
        cfg = _patch_config(monkeypatch, tmp_path)
        result = cfg.load_settings()
        p = Path(result["projects_dir"])
        assert p.is_absolute()
        assert p.name == "Projects"

    def test_openai_api_key_default_empty(self, monkeypatch, tmp_path):
        cfg = _patch_config(monkeypatch, tmp_path)
        result = cfg.load_settings()
        assert result["openai_api_key"] == ""

    def test_gemini_api_key_default_empty(self, monkeypatch, tmp_path):
        cfg = _patch_config(monkeypatch, tmp_path)
        result = cfg.load_settings()
        assert result["gemini_api_key"] == ""

    def test_keyword_ai_provider_default_auto(self, monkeypatch, tmp_path):
        cfg = _patch_config(monkeypatch, tmp_path)
        result = cfg.load_settings()
        assert result["keyword_ai_provider"] == "auto"


class TestLoadSettingsWithValidFile:
    """Behaviour when settings.json exists and contains valid JSON."""

    def test_custom_value_overrides_default(self, monkeypatch, tmp_path):
        cfg = _patch_config(
            monkeypatch, tmp_path,
            settings_json_content={"openai_api_key": "sk-test123"},
            write_file=True,
        )
        result = cfg.load_settings()
        assert result["openai_api_key"] == "sk-test123"

    def test_unset_keys_keep_defaults(self, monkeypatch, tmp_path):
        cfg = _patch_config(
            monkeypatch, tmp_path,
            settings_json_content={"openai_api_key": "sk-test"},
            write_file=True,
        )
        result = cfg.load_settings()
        assert result["keyword_ai_model"] == cfg.DEFAULT_SETTINGS["keyword_ai_model"]

    def test_absolute_projects_dir_kept_as_is(self, monkeypatch, tmp_path):
        absolute_dir = str(tmp_path / "MyProjects")
        cfg = _patch_config(
            monkeypatch, tmp_path,
            settings_json_content={"projects_dir": absolute_dir},
            write_file=True,
        )
        result = cfg.load_settings()
        assert result["projects_dir"] == absolute_dir
        assert Path(result["projects_dir"]).is_absolute()

    def test_relative_projects_dir_resolved(self, monkeypatch, tmp_path):
        cfg = _patch_config(
            monkeypatch, tmp_path,
            settings_json_content={"projects_dir": "RelativeProjects"},
            write_file=True,
        )
        result = cfg.load_settings()
        assert Path(result["projects_dir"]).is_absolute()
        assert result["projects_dir"] == str(tmp_path / "RelativeProjects")

    def test_extra_unknown_keys_preserved(self, monkeypatch, tmp_path):
        cfg = _patch_config(
            monkeypatch, tmp_path,
            settings_json_content={"custom_extra_key": "hello"},
            write_file=True,
        )
        result = cfg.load_settings()
        assert result["custom_extra_key"] == "hello"

    def test_utf8_bom_file_loads(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        # Write with UTF-8 BOM
        fake_path.write_bytes(b'\xef\xbb\xbf' + json.dumps({"openai_api_key": "sk-bom"}).encode("utf-8"))
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        result = cfg.load_settings()
        assert result["openai_api_key"] == "sk-bom"


class TestLoadSettingsCorruptFile:
    """Behaviour when settings.json has invalid or non-dict content."""

    def test_corrupt_json_returns_defaults(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        fake_path.write_text("THIS IS NOT JSON!!!", encoding="utf-8")
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        result = cfg.load_settings()
        # Should return defaults without raising
        assert isinstance(result, dict)
        assert result["keyword_ai_provider"] == "auto"

    def test_json_list_returns_defaults(self, monkeypatch, tmp_path):
        """JSON array (not dict) should be ignored, defaults returned."""
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        fake_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        result = cfg.load_settings()
        assert isinstance(result, dict)
        assert "openai_api_key" in result

    def test_empty_file_returns_defaults(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        fake_path.write_text("", encoding="utf-8")
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        result = cfg.load_settings()
        assert isinstance(result, dict)

    def test_null_projects_dir_resolved_to_absolute(self, monkeypatch, tmp_path):
        """projects_dir=null (None) -> empty string -> resolved to APP_DIR."""
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        fake_path.write_text(json.dumps({"projects_dir": None}), encoding="utf-8")
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        result = cfg.load_settings()
        assert Path(result["projects_dir"]).is_absolute()


# ===========================================================================
# save_settings() tests
# ===========================================================================

class TestSaveSettings:
    """Tests for save_settings()."""

    def test_creates_settings_json(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        # Use an absolute path for projects_dir so mkdir works
        data = {"projects_dir": str(tmp_path / "Projects"), "openai_api_key": "sk-abc"}
        cfg.save_settings(data)
        assert fake_path.exists()

    def test_saved_json_is_valid(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        data = {"projects_dir": str(tmp_path / "Projects"), "openai_api_key": "sk-xyz"}
        cfg.save_settings(data)
        loaded = json.loads(fake_path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)

    def test_saved_value_persisted(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        data = {"projects_dir": str(tmp_path / "Projects"), "openai_api_key": "sk-saved"}
        cfg.save_settings(data)
        loaded = json.loads(fake_path.read_text(encoding="utf-8"))
        assert loaded["openai_api_key"] == "sk-saved"

    def test_creates_projects_dir(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        projects = tmp_path / "NewProjectsDir"
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        assert not projects.exists()
        cfg.save_settings({"projects_dir": str(projects)})
        assert projects.exists()

    def test_creates_nested_projects_dir(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        projects = tmp_path / "a" / "b" / "c" / "Projects"
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        cfg.save_settings({"projects_dir": str(projects)})
        assert projects.exists()

    def test_defaults_merged_into_saved_file(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        cfg.save_settings({"projects_dir": str(tmp_path / "P")})
        loaded = json.loads(fake_path.read_text(encoding="utf-8"))
        # Default keys should be present in the saved file
        assert "keyword_ai_model" in loaded
        assert "gemini_api_key" in loaded

    def test_none_settings_uses_defaults(self, monkeypatch, tmp_path):
        """save_settings(None) should not raise; uses defaults."""
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        # Use default projects_dir under tmp_path
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        # Patch DEFAULT_SETTINGS projects_dir to point inside tmp_path
        orig_default = cfg.DEFAULT_SETTINGS.copy()
        monkeypatch.setitem(cfg.DEFAULT_SETTINGS, "projects_dir", str(tmp_path / "Projects"))
        cfg.save_settings(None)
        assert fake_path.exists()
        monkeypatch.setattr(cfg, "DEFAULT_SETTINGS", orig_default)

    def test_roundtrip_load_after_save(self, monkeypatch, tmp_path):
        import app.config as cfg
        fake_path = tmp_path / "settings.json"
        monkeypatch.setattr(cfg, "APP_DIR", tmp_path)
        monkeypatch.setattr(cfg, "SETTINGS_PATH", fake_path)
        data = {
            "projects_dir": str(tmp_path / "RoundTrip"),
            "openai_api_key": "sk-roundtrip",
        }
        cfg.save_settings(data)
        loaded = cfg.load_settings()
        assert loaded["openai_api_key"] == "sk-roundtrip"
