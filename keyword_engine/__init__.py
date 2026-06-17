"""Config-driven keyword engine.

Tách "knowledge" (Domain Pack YAML trong packs/) khỏi "engine" (logic generic).
Engine chỉ tiêu thụ pack; mọi danh từ thuộc một lĩnh vực cụ thể (team, player,
pressing, sportsdb...) phải nằm trong packs/*.yaml, không nằm trong .py.
"""

from .domain_pack import (
    DomainPack,
    SourceRoute,
    resolve_domain_pack,
    resolve_action,
    route_source,
    build_scene_query,
    forbidden_for,
    safe_fallback,
)

__all__ = [
    "DomainPack",
    "SourceRoute",
    "resolve_domain_pack",
    "resolve_action",
    "route_source",
    "build_scene_query",
    "forbidden_for",
    "safe_fallback",
]
