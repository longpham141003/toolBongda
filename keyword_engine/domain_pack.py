"""Domain Pack resolver — nguồn sự thật config-driven cho keyword engine.

Engine (app/visual_pipeline.py) tiêu thụ pack qua các hàm public ở đây. Mọi
"knowledge" thuộc một lĩnh vực cụ thể (loại thực thể, lexicon hành động, định
tuyến nguồn, bối cảnh cấm...) nằm trong packs/*.yaml, KHÔNG nằm trong .py.

Phân giải 3 tầng (ưu tiên trên xuống):
  1. project override (project_config_path hoặc <repo>/project.yaml)
  2. packs/{video_domain}.yaml theo video_domain mà giai đoạn 0 đã infer
  3. synthetic pack do AI sinh từ video_context (cache theo script_hash); nếu
     AI lỗi -> packs/generic.yaml (pack tối thiểu, luôn chạy được).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class SourceRoute:
    source: str
    filters: dict = field(default_factory=dict)


@dataclass
class DomainPack:
    domain: str = "generic"
    language_out: str = "en"
    entity_types: list[dict] = field(default_factory=list)
    scene_types: list[dict] = field(default_factory=list)
    action_lexicon: list[dict] = field(default_factory=list)
    source_routes: list[dict] = field(default_factory=list)
    forbidden_contexts: list[str] = field(default_factory=list)
    safe_fallback: list[str] = field(default_factory=list)
    recency: dict = field(default_factory=dict)
    source: str = "generic"  # provenance: project | pack:<domain> | synthetic | generic

    # --- convenience accessors used by the engine ---
    def scene_type(self, scene_id: str) -> dict | None:
        for entry in self.scene_types:
            if str(entry.get("id") or "") == scene_id:
                return entry
        return None

    def subject_entity_ids(self) -> list[str]:
        ids = []
        for entry in self.entity_types:
            if str(entry.get("role") or "").strip().lower() == "subject":
                ids.append(str(entry.get("id") or "").strip())
        return [value for value in ids if value]

    def entity(self, entity_id: str) -> dict | None:
        for entry in self.entity_types:
            if str(entry.get("id") or "") == entity_id:
                return entry
        return None

    def recency_anchor(self) -> str:
        return str(self.recency.get("anchor") or "video_year").strip() or "video_year"


# ---------------------------------------------------------------------------
# Pack file loading
# ---------------------------------------------------------------------------
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _packs_dir(packs_dir: str | Path | None = None) -> Path:
    if packs_dir:
        return Path(packs_dir)
    return _repo_root() / "packs"


def _pack_from_dict(data: dict | None, source: str) -> DomainPack:
    data = data if isinstance(data, dict) else {}

    def _as_list(value) -> list:
        return value if isinstance(value, list) else []

    return DomainPack(
        domain=str(data.get("domain") or "generic").strip() or "generic",
        language_out=str(data.get("language_out") or "en").strip() or "en",
        entity_types=[v for v in _as_list(data.get("entity_types")) if isinstance(v, dict)],
        scene_types=[v for v in _as_list(data.get("scene_types")) if isinstance(v, dict)],
        action_lexicon=[v for v in _as_list(data.get("action_lexicon")) if isinstance(v, dict)],
        source_routes=[v for v in _as_list(data.get("source_routes")) if isinstance(v, dict)],
        forbidden_contexts=[str(v).strip() for v in _as_list(data.get("forbidden_contexts")) if str(v).strip()],
        safe_fallback=[str(v).strip() for v in _as_list(data.get("safe_fallback")) if str(v).strip()],
        recency=data.get("recency") if isinstance(data.get("recency"), dict) else {},
        source=source,
    )


# Parse each YAML pack at most once per (path, mtime); pack files are static for
# a run, so this removes repeated disk reads + YAML parsing on the hot path
# (detect_domain / resolve_domain_pack are called many times per manifest).
_YAML_CACHE: dict[str, tuple[float, dict | None]] = {}
# Memoize detect_domain results per (script hash, packs dir) within a run.
_DETECT_CACHE: dict[tuple[str, str], str | None] = {}


def _read_yaml_cached(path: Path) -> dict | None:
    try:
        if not path.is_file():
            return None
        mtime = path.stat().st_mtime
    except Exception:
        return None
    key = str(path)
    cached = _YAML_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        import yaml
    except Exception:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else None
    except Exception:
        data = None
    _YAML_CACHE[key] = (mtime, data)
    return data


def _load_pack_file(path: Path, source: str) -> DomainPack | None:
    data = _read_yaml_cached(path)
    if data is None:
        return None
    return _pack_from_dict(data, source)


def load_generic_pack(packs_dir: str | Path | None = None) -> DomainPack:
    pack = _load_pack_file(_packs_dir(packs_dir) / "generic.yaml", "generic")
    if pack is not None:
        return pack
    # Hard-coded minimal generic pack so the engine never crashes even without
    # the YAML file present. This is the ONLY non-domain default in code.
    return DomainPack(
        domain="generic",
        language_out="en",
        scene_types=[{"id": "general", "requires": [], "query_template": "{subject} {action} {year}", "enrich_when_weak": False}],
        source_routes=[{"default": None, "source": "google_images", "filters": {"date_min": "{video_year}"}}],
        forbidden_contexts=["logo", "wallpaper", "thumbnail", "ai generated", "fanart", "poster"],
        safe_fallback=["{subject} {year}", "{topic} background"],
        recency={"strict": False, "anchor": "video_year"},
        source="generic",
    )


# ---------------------------------------------------------------------------
# Domain detection (config-driven; replaces hardcoded term lists in the engine)
# ---------------------------------------------------------------------------
def detect_domain(script: str, packs_dir: str | Path | None = None) -> str | None:
    """Scan every packs/*.yaml 'detect' block and return the best-matching
    domain for the script (>= min_hits keyword hits), or None. Detection
    knowledge lives in the YAML packs, not in code."""
    text = str(script or "").lower()
    if not text.strip():
        return None
    directory = _packs_dir(packs_dir)
    cache_key = (hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest(), str(directory))
    if cache_key in _DETECT_CACHE:
        return _DETECT_CACHE[cache_key]
    best_domain: str | None = None
    best_score = 0
    try:
        pack_files = sorted(directory.glob("*.yaml"))
    except Exception:
        return None
    for path in pack_files:
        data = _read_yaml_cached(path)
        if not isinstance(data, dict):
            continue
        detect = data.get("detect")
        if not isinstance(detect, dict):
            continue
        keywords = [str(k).lower().strip() for k in (detect.get("keywords") or []) if str(k).strip()]
        if not keywords:
            continue
        min_hits = int(detect.get("min_hits") or 1)
        hits = sum(1 for kw in keywords if kw in text)
        if hits >= min_hits and hits > best_score:
            best_score = hits
            best_domain = str(data.get("domain") or path.stem).strip() or None
    _DETECT_CACHE[cache_key] = best_domain
    return best_domain


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def resolve_domain_pack(
    script: str,
    video_context: dict | None,
    project_config_path: str | None = None,
    *,
    packs_dir: str | Path | None = None,
    settings: dict | None = None,
    project: Any = None,
    ai_caller: Callable[[str], str] | None = None,
    log: Callable[[str], None] | None = None,
) -> DomainPack:
    """Phân giải pack theo 3 tầng (xem docstring module).

    ai_caller: hàm nhận prompt -> trả raw text (JSON). Engine truyền lambda dùng
    provider AI sẵn có. Nếu None, tầng synthetic bị bỏ qua -> rơi về generic.
    """
    video_context = video_context or {}

    # Tier 1: project override.
    candidates: list[Path] = []
    if project_config_path:
        candidates.append(Path(project_config_path))
    candidates.append(_repo_root() / "project.yaml")
    for candidate in candidates:
        pack = _load_pack_file(candidate, "project")
        if pack is not None:
            return pack

    # Tier 2: packs/{video_domain}.yaml
    domain = str(video_context.get("video_domain") or "").strip().lower()
    if domain and domain != "generic":
        pack = _load_pack_file(_packs_dir(packs_dir) / f"{domain}.yaml", f"pack:{domain}")
        if pack is not None:
            return pack

    # Tier 3: synthetic pack (AI). Implemented in a separate helper so it can be
    # cached/tested independently. Falls back to generic on any failure.
    pack = _synthetic_pack(
        script,
        video_context,
        settings=settings,
        project=project,
        ai_caller=ai_caller,
        packs_dir=packs_dir,
        log=log,
    )
    if pack is not None:
        return pack

    return load_generic_pack(packs_dir)


def resolve_action(text: str, pack: DomainPack) -> str | None:
    """Khớp text với action_lexicon, trả visual descriptor. Thay _scene_action_hint."""
    lowered = str(text or "").lower()
    if not lowered.strip():
        return None
    for entry in pack.action_lexicon:
        patterns = entry.get("match")
        patterns = patterns if isinstance(patterns, list) else [patterns]
        for pattern in patterns:
            needle = str(pattern or "").lower().strip()
            if needle and needle in lowered:
                visual = str(entry.get("visual") or "").strip()
                return visual or None
    return None


def _route_matches(when: dict, entity_type: str, scene_type: str) -> bool:
    def _ok(key: str, value: str) -> bool:
        allowed = when.get(key)
        if allowed is None:
            return True  # absent condition = wildcard
        if not isinstance(allowed, list):
            allowed = [allowed]
        allowed = [str(v).strip().lower() for v in allowed if str(v).strip()]
        return str(value or "").strip().lower() in allowed

    return _ok("entity_type", entity_type) and _ok("scene_type", scene_type)


def route_source(
    entity_type: str,
    scene_type: str,
    pack: DomainPack,
    slots: dict | None = None,
) -> SourceRoute:
    """Khớp source_routes từ trên xuống, fallback route 'default'. Thay nhánh sportsdb hardcode."""
    default_route: SourceRoute | None = None
    for route in pack.source_routes:
        if not isinstance(route, dict):
            continue
        filters = route.get("filters") if isinstance(route.get("filters"), dict) else {}
        source = str(route.get("source") or "").strip() or "google_images"
        if "default" in route and "when" not in route:
            default_route = SourceRoute(source=source, filters=_fill_filters(filters, slots))
            continue
        when = route.get("when") if isinstance(route.get("when"), dict) else {}
        if _route_matches(when, entity_type, scene_type):
            return SourceRoute(source=source, filters=_fill_filters(filters, slots))
    if default_route is not None:
        return default_route
    return SourceRoute(source="google_images", filters={})


def build_scene_query(scene_type: str, slots: dict, pack: DomainPack) -> str:
    """Điền slots vào query_template của scene_type. Không để chuỗi {..} lọt ra."""
    entry = pack.scene_type(scene_type)
    template = str((entry or {}).get("query_template") or "").strip()
    if not template:
        template = "{subject} {action} {year}"
    return _fill_template(template, slots)


def forbidden_for(pack: DomainPack) -> list[str]:
    """forbidden_contexts — dùng cho cả lọc query lẫn re-rank ảnh (Phase 2)."""
    return list(pack.forbidden_contexts)


def safe_fallback(slots: dict, pack: DomainPack) -> list[str]:
    """Sinh keyword fallback an toàn từ template safe_fallback."""
    result: list[str] = []
    for template in pack.safe_fallback:
        filled = _fill_template(template, slots)
        if filled and filled not in result:
            result.append(filled)
    return result


# ---------------------------------------------------------------------------
# Slot / template filling
# ---------------------------------------------------------------------------
def _fill_template(template: str, slots: dict | None) -> str:
    slots = slots or {}

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        return str(slots.get(key, "") or "").strip()

    filled = re.sub(r"\{(\w+)\}", _sub, str(template or ""))
    # Drop any stray unmatched braces, then collapse whitespace.
    filled = re.sub(r"\{[^}]*\}", " ", filled)
    return re.sub(r"\s+", " ", filled).strip()


def _fill_filters(filters: dict, slots: dict | None) -> dict:
    if not isinstance(filters, dict):
        return {}
    if slots is None:
        return dict(filters)
    resolved: dict = {}
    for key, value in filters.items():
        if isinstance(value, str):
            filled = _fill_template(value, slots)
            # A filter that resolves to empty (missing slot) is dropped so we do
            # not emit e.g. "-01-01" with no year.
            if "{" in value and not filled.replace("-", "").strip():
                continue
            resolved[key] = filled if filled else value if "{" not in value else None
            if resolved[key] is None:
                del resolved[key]
        else:
            resolved[key] = value
    return resolved


# ---------------------------------------------------------------------------
# Tier 3 synthetic pack — AI sinh pack rút gọn cho domain lạ, cache theo
# script_hash. Code chỉ tiêu thụ pack; AI sinh ra knowledge.
# ---------------------------------------------------------------------------
SYNTHETIC_FIELDS = ("entity_types", "action_lexicon", "source_routes", "forbidden_contexts")


def _script_hash(script: str) -> str:
    return hashlib.sha256(str(script or "").encode("utf-8", errors="ignore")).hexdigest()


def _synthetic_cache_path(project: Any) -> Path | None:
    if not project:
        return None
    try:
        return Path(project) / "scripts" / "domain_pack.ai.json"
    except Exception:
        return None


def _synthetic_prompt(video_context: dict) -> str:
    return (
        "You configure an image-search engine for a video production tool.\n"
        "Given the VIDEO CONTEXT, output a compact JSON 'domain pack' describing how to\n"
        "find real footage for this topic. Return JSON ONLY with exactly these keys:\n"
        "- entity_types: array of {id, role}, role is 'subject' or 'context'. Optional 'cardinality' integer.\n"
        "- action_lexicon: array of {match: [phrases that may appear in the narration, in its original language], visual: short ENGLISH image descriptor}.\n"
        "- source_routes: array of routing rules. Use {\"default\": null, \"source\": \"google_images\"} if unsure.\n"
        "- forbidden_contexts: array of short ENGLISH strings of image types to avoid (logo, wallpaper, thumbnail, ai generated...).\n"
        "Rules:\n"
        "- All output values in English (use international English spellings).\n"
        "- Do not invent entities/events not implied by the context.\n"
        "- Keep it small and concrete; this is configuration, not prose.\n\n"
        f"VIDEO CONTEXT:\n{json.dumps(video_context, ensure_ascii=False)}"
    )


def _parse_pack_json(content: str) -> dict:
    content = str(content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("synthetic pack is not a JSON object")
    return data


def _merge_synthetic(data: dict, video_context: dict, packs_dir: str | Path | None) -> DomainPack:
    """Overlay the 4 AI-provided fields on top of the generic pack so that
    scene_types / safe_fallback / recency always have sensible defaults."""
    base = load_generic_pack(packs_dir)
    merged = {
        "domain": str(video_context.get("video_domain") or "synthetic").strip() or "synthetic",
        "language_out": "en",
        "entity_types": base.entity_types,
        "scene_types": base.scene_types,
        "action_lexicon": base.action_lexicon,
        "source_routes": base.source_routes,
        "forbidden_contexts": base.forbidden_contexts,
        "safe_fallback": base.safe_fallback,
        "recency": base.recency,
    }
    for key in SYNTHETIC_FIELDS:
        value = data.get(key)
        if isinstance(value, list) and value:
            merged[key] = value
    return _pack_from_dict(merged, "synthetic")


def _synthetic_pack(
    script: str,
    video_context: dict,
    *,
    settings: dict | None = None,
    project: Any = None,
    ai_caller: Callable[[str], str] | None = None,
    packs_dir: str | Path | None = None,
    log: Callable[[str], None] | None = None,
) -> DomainPack | None:
    script_hash = _script_hash(script)
    cache_path = _synthetic_cache_path(project)

    # Reuse cached synthetic pack when the script is unchanged.
    if cache_path is not None:
        try:
            if cache_path.is_file():
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached.get("script_hash") == script_hash and isinstance(cached.get("pack"), dict):
                    return _pack_from_dict(cached["pack"], "synthetic")
        except Exception:
            pass

    if not callable(ai_caller):
        return None

    try:
        raw = ai_caller(_synthetic_prompt(video_context))
        data = _parse_pack_json(raw)
        if not any(isinstance(data.get(key), list) and data.get(key) for key in SYNTHETIC_FIELDS):
            raise ValueError("synthetic pack has no usable fields")
        pack = _merge_synthetic(data, video_context, packs_dir)
    except Exception as exc:
        if callable(log):
            log(f"Domain pack synthetic AI lỗi, dùng generic: {exc}")
        return None

    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "script_hash": script_hash,
                "pack": {
                    "domain": pack.domain,
                    "language_out": pack.language_out,
                    "entity_types": pack.entity_types,
                    "scene_types": pack.scene_types,
                    "action_lexicon": pack.action_lexicon,
                    "source_routes": pack.source_routes,
                    "forbidden_contexts": pack.forbidden_contexts,
                    "safe_fallback": pack.safe_fallback,
                    "recency": pack.recency,
                },
            }
            cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return pack
