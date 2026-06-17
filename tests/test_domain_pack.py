"""Tests for keyword_engine.domain_pack (config-driven Domain Pack resolver)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from keyword_engine import domain_pack as dp


# ===========================================================================
# Loading / 3-tier resolution
# ===========================================================================
class TestResolveDomainPack:
    def test_loads_football_pack_by_domain(self):
        pack = dp.resolve_domain_pack("", {"video_domain": "football"})
        assert pack.domain == "football"
        assert pack.source == "pack:football"
        assert pack.language_out == "en"

    def test_unknown_domain_falls_back_to_generic(self):
        # No pack file for this domain and synthetic returns None in Phase A.
        pack = dp.resolve_domain_pack("some script", {"video_domain": "underwater-basket-weaving"})
        assert pack.domain == "generic"
        assert pack.source == "generic"

    def test_empty_context_falls_back_to_generic(self):
        pack = dp.resolve_domain_pack("script", {})
        assert pack.domain == "generic"

    def test_generic_pack_has_safe_defaults(self):
        pack = dp.load_generic_pack()
        assert "logo" in dp.forbidden_for(pack)
        assert pack.recency_anchor() == "video_year"

    def test_project_override_takes_priority(self, tmp_path):
        override = tmp_path / "project.yaml"
        override.write_text("domain: custom\nlanguage_out: en\n", encoding="utf-8")
        pack = dp.resolve_domain_pack("", {"video_domain": "football"}, project_config_path=str(override))
        assert pack.domain == "custom"
        assert pack.source == "project"


# ===========================================================================
# resolve_action
# ===========================================================================
class TestResolveAction:
    @pytest.fixture
    def football(self):
        return dp.resolve_domain_pack("", {"video_domain": "football"})

    def test_vietnamese_celebration(self, football):
        assert dp.resolve_action("Cả đội ăn mừng bàn thắng", football) == "goal celebration"

    def test_vietnamese_coach(self, football):
        assert dp.resolve_action("huấn luyện viên chỉ đạo từ đường biên", football) == "manager on touchline"

    def test_english_keyword(self, football):
        assert dp.resolve_action("the winger sends a cross", football) == "winger crossing the ball"

    def test_no_match_returns_none(self, football):
        assert dp.resolve_action("a quiet afternoon in the library", football) is None

    def test_empty_text(self, football):
        assert dp.resolve_action("", football) is None


# ===========================================================================
# route_source
# ===========================================================================
class TestRouteSource:
    @pytest.fixture
    def football(self):
        return dp.resolve_domain_pack("", {"video_domain": "football"})

    def test_portrait_routes_to_sportsdb(self, football):
        route = dp.route_source("player", "portrait", football)
        assert route.source == "thesportsdb"

    def test_match_moment_routes_to_editorial(self, football):
        route = dp.route_source("team", "match_moment", football)
        assert route.source == "editorial_api"

    def test_unmatched_falls_to_default(self, football):
        route = dp.route_source("venue", "crowd", football)
        assert route.source == "google_images"

    def test_filters_slot_filled(self, football):
        route = dp.route_source("team", "match_moment", football, slots={"competition_year": "2026"})
        assert route.filters.get("date_min") == "2026-01-01"

    def test_generic_default_route(self):
        pack = dp.load_generic_pack()
        route = dp.route_source("x", "y", pack)
        assert route.source == "google_images"


# ===========================================================================
# build_scene_query / safe_fallback / slot filling
# ===========================================================================
class TestBuildSceneQuery:
    @pytest.fixture
    def football(self):
        return dp.resolve_domain_pack("", {"video_domain": "football"})

    def test_full_slots(self, football):
        q = dp.build_scene_query(
            "match_moment",
            {"team_a": "France", "team_b": "Brazil", "competition": "World Cup", "year": "2026", "action": "goal celebration"},
            football,
        )
        assert q == "France Brazil World Cup 2026 goal celebration"

    def test_missing_slot_no_leftover_braces(self, football):
        q = dp.build_scene_query(
            "match_moment",
            {"team_a": "France", "team_b": "Brazil"},
            football,
        )
        assert "{" not in q and "}" not in q
        assert q == "France Brazil"

    def test_unknown_scene_type_uses_default_template(self, football):
        q = dp.build_scene_query("does-not-exist", {"subject": "Messi", "year": "2022"}, football)
        assert "{" not in q
        assert "Messi" in q

    def test_safe_fallback_fills_and_dedups(self, football):
        out = dp.safe_fallback({"competition": "World Cup", "year": "2026", "venue": "MetLife Stadium", "team": "USA"}, football)
        assert out
        assert all("{" not in v for v in out)
        assert len(out) == len(set(out))


# ===========================================================================
# subject entities (used by score refactor in Phase C)
# ===========================================================================
class TestEntityHelpers:
    def test_football_subject_entities(self):
        pack = dp.resolve_domain_pack("", {"video_domain": "football"})
        subjects = pack.subject_entity_ids()
        assert "team" in subjects and "player" in subjects
        assert "competition" not in subjects  # role: context
