"""Two-phase real-life prompt generation (SP3), ported in structure from the
Auto Prompt app but producing realistic stock-photo prompts (no cinematic styling).

Pure helpers here are AI-free and unit-tested. The AI phases live in this module
too (analyze_story / generate_line_prompts) and reuse visual_pipeline's AI caller.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.pipeline.subtitle_store import load_subtitle


def _ai_call(settings: dict, prompt: str) -> str:
    """Single AI call returning raw text. Imported lazily to avoid import cycle."""
    from app.pipeline.visual_pipeline import _pack_ai_caller
    caller = _pack_ai_caller(settings)
    if caller is None:
        raise RuntimeError("Chưa cấu hình AI (thiếu API key) để tạo prompt.")
    return caller(prompt)

REALISTIC_TAG = "Natural lighting, candid real-life photograph, true-to-life, no text, no captions, no watermark."

# Crude policy-word softening (ported from Auto Prompt's sanitize step).
_POLICY_REPLACEMENTS = [
    (re.compile(r"\bnude\b", re.I), "casually dressed"),
    (re.compile(r"\bnaked\b", re.I), "casually dressed"),
    (re.compile(r"\bgun\b", re.I), "object in hand"),
    (re.compile(r"\bguns\b", re.I), "objects in hand"),
    (re.compile(r"\bgore\b", re.I), "intense"),
    (re.compile(r"\bblood\b", re.I), "intense"),
    (re.compile(r"\bsuicide\b", re.I), "crisis moment"),
    (re.compile(r"\bcorpse\b", re.I), "still figure"),
]


def parse_json_block(content: str) -> Any:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def coerce_prompt_array(content: str, expected_n: int) -> list[str]:
    """Parse a JSON array of strings; pad with '' or truncate to expected_n."""
    try:
        data = parse_json_block(content)
    except Exception:
        data = []
    if not isinstance(data, list):
        data = []
    result = [str(item or "").strip() for item in data]
    if len(result) < expected_n:
        result += [""] * (expected_n - len(result))
    return result[:expected_n]


def enforce_realistic_prompt(text: str, named_count_limit: int = 3) -> str:
    # named_count_limit is reserved for future enforcement; not applied yet.
    value = str(text or "").strip()
    # Drop a leading "N." / "N)" / "N -" scene number.
    value = re.sub(r"^\s*\d+\s*[\.\):\-]\s*", "", value)
    for pattern, replacement in _POLICY_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    value = value.strip()
    # Ensure exactly one realistic tag at the end.
    if value.endswith(REALISTIC_TAG):
        return value
    # Strip any partial/duplicate tag fragment then append once.
    value = value.rstrip()
    if not value.endswith((".", "!", "?")):
        value += "."
    return f"{value} {REALISTIC_TAG}"


def build_numbered_srt(lines: list[dict]) -> str:
    out = []
    for i, line in enumerate(lines, start=1):
        idx = int(line.get("index") or i)
        text = str(line.get("text") or "").strip()
        out.append(f"{idx}. {text}")
    return "\n".join(out)


def analysis_path(project: Path) -> Path:
    return Path(project) / "scripts" / "prompt_analysis.json"


def save_prompt_analysis(project: Path, data: dict) -> dict:
    path = analysis_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data or {})
    payload.setdefault("version", 1)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_prompt_analysis(project: Path) -> dict:
    path = analysis_path(project)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


SYS_ANALYZE = (
    "You are a story analyst for REAL-LIFE stock photography. Read the numbered "
    "subtitle lines and return ONLY raw JSON (no markdown, no backticks) with this "
    "exact shape:\n"
    "{\n"
    '  "language": "English or Vietnamese",\n'
    '  "storyContext": "4-5 sentence plain summary of plot, setting, key events",\n'
    '  "mainSetting": "primary real-world location",\n'
    '  "tone": "everyday/tense/heartwarming/etc",\n'
    '  "characters": [{"name": "name exactly as in text; invent a fitting realistic '
    'name if unnamed", "role": "their role in 4-6 words", "description": "REAL-LIFE '
    "UPPER-BODY appearance only: [ethnicity+nationality] [gender], [age bracket], "
    "[build], [skin tone], [hair: color+length+style], [everyday TOP clothing only — "
    'no cinematic styling, no pants, no shoes]"}],\n'
    '  "sceneMap": [{"startLine": N, "endLine": N, "location": "specific real place", '
    '"timeOfDay": "time + natural light", "sceneSummary": "one plain sentence of the '
    'action", "charactersPresent": ["Name"], "characterPositions": {"Name": "where"}, '
    '"spatialLayout": "describe the real space", "crowdNotes": "background people if any"}]\n'
    "}\n"
    "RULES: Extract EVERY character who physically appears; description is upper-body, "
    "real-life, everyday clothing (no film/cinematic styling). For children use 'young "
    "boy'/'young girl'. sceneMap MUST have one entry per subtitle line (startLine == "
    "endLine == that line's number), covering all lines with no gaps."
)


def _load_manifest(project: Path) -> list[dict]:
    from app.pipeline.visual_pipeline import load_manifest
    return load_manifest(project)


def _save_manifest(project: Path, items: list[dict]) -> None:
    from app.pipeline.visual_pipeline import save_manifest
    save_manifest(project, items)


def analyze_story(project: Path, settings: dict, log=None) -> dict:
    lines = load_subtitle(project)
    if not lines:
        raise RuntimeError("Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước khi phân tích.")
    if callable(log):
        log(f"Phân tích {len(lines)} dòng phụ đề để dựng bối cảnh & nhân vật...")
    numbered = build_numbered_srt(lines)
    prompt = f"{SYS_ANALYZE}\n\nNumbered subtitle lines ({len(lines)} total):\n{numbered}"
    raw = _ai_call(settings, prompt)
    try:
        data = parse_json_block(raw)
    except Exception as exc:
        raise RuntimeError(f"AI phân tích trả về JSON không hợp lệ: {exc}")
    if not isinstance(data, dict):
        raise RuntimeError("AI phân tích không trả về object JSON.")
    data.setdefault("characters", [])
    data.setdefault("sceneMap", [])
    if callable(log):
        log(f"Đã nhận {len(data.get('characters') or [])} nhân vật từ AI.")
    return save_prompt_analysis(project, data)


SYS_PROMPT_REALISTIC = (
    "You generate REAL-LIFE photo prompts for stock-image search. Each prompt is a "
    "believable real-world photograph of the moment in the line.\n"
    "GOLDEN RULE: ALL character physical appearance goes ONLY inside parentheses right "
    "after the name, copied EXACTLY from the locked description — never shorten, "
    "rephrase, or invent appearance outside the parentheses.\n"
    "RULES:\n"
    "[R1] 1 line = 1 prompt. Never merge or split.\n"
    "[R2] CHARACTER LOCK: copy each character's description verbatim inside ().\n"
    "[R3] Place characters at their given positions in the real space.\n"
    "[R4] MAX 3 named characters per prompt; everyone else is an unnamed background person.\n"
    "[R5] Dialogue becomes body language + facial expression only — never write the spoken words.\n"
    "[R6] One clear action/moment per prompt.\n"
    "[R7] No shot labels (no 'close-up', 'wide shot', 'POV'), no cinematic/film grading, "
    "no artistic style — these are ordinary real photographs.\n"
    "[R8] For consecutive prompts in the same location, vary the natural viewpoint.\n"
    f"[R9] End EVERY prompt with EXACTLY: {REALISTIC_TAG}\n"
    "OUTPUT: ONLY a raw JSON array of strings (one per line, in order). No scene numbers, "
    "no markdown, no commentary."
)


def _character_block(characters: list[dict]) -> str:
    blocks = []
    for ch in characters or []:
        name = str(ch.get("name") or "").strip()
        role = str(ch.get("role") or "").strip()
        desc = str(ch.get("description") or "").strip()
        if name and desc:
            blocks.append(f"{name} ({role}):\n{desc}")
    return "\n\n".join(blocks) if blocks else "(no named characters)"


def _scene_for_line(scene_map: list[dict], line_index: int) -> dict:
    for scene in scene_map or []:
        try:
            if int(scene.get("startLine") or 0) <= line_index <= int(scene.get("endLine") or 0):
                return scene
        except (TypeError, ValueError):
            continue
    return {}


def _line_context(line_index: int, text: str, scene: dict) -> str:
    parts = [f"--- LINE {line_index} ---"]
    if scene.get("location"):
        parts.append(f"Location: {scene.get('location')} | {scene.get('timeOfDay') or ''}")
    if scene.get("sceneSummary"):
        parts.append(f"Scene: {scene.get('sceneSummary')}")
    if scene.get("spatialLayout"):
        parts.append(f"Space: {scene.get('spatialLayout')}")
    if scene.get("charactersPresent"):
        parts.append(f"Characters present: {', '.join(scene.get('charactersPresent') or [])}")
    if scene.get("crowdNotes"):
        parts.append(f"Background: {scene.get('crowdNotes')}")
    parts.append(f"Subtitle text: {text}")
    return "\n".join(parts)


def generate_line_prompts(project: Path, settings: dict, log=None, batch_size: int = 8) -> list[dict]:
    lines = load_subtitle(project)
    if not lines:
        raise RuntimeError("Chưa có phụ đề.")
    manifest = _load_manifest(project)
    if not manifest:
        raise RuntimeError("Chưa có phân cảnh. Hãy phân tích cảnh trước khi tạo prompt.")
    analysis = load_prompt_analysis(project)
    if not analysis:
        raise RuntimeError("Chưa phân tích. Hãy chạy phân tích nhân vật trước.")
    characters = analysis.get("characters") or []
    scene_map = analysis.get("sceneMap") or []
    story = str(analysis.get("storyContext") or "")
    setting = str(analysis.get("mainSetting") or "")
    char_block = _character_block(characters)

    n = len(lines)
    size = max(1, int(batch_size or 8))
    prompts: list[str] = []
    for start in range(0, n, size):
        batch = lines[start:start + size]
        if callable(log):
            log(f"Tạo prompt đoạn {start // size + 1}/{(n + size - 1) // size} ({len(batch)} dòng)")
        ctx_blocks = []
        for offset, line in enumerate(batch):
            li = int(line.get("index") or (start + offset + 1))
            ctx_blocks.append(_line_context(li, str(line.get("text") or ""), _scene_for_line(scene_map, li)))
        user_msg = (
            f"{SYS_PROMPT_REALISTIC}\n\n"
            f"=== STORY ===\n{story}\nMain setting: {setting}\n\n"
            f"=== LOCKED CHARACTER DESCRIPTIONS (copy EXACTLY inside parentheses) ===\n{char_block}\n\n"
            f"=== GENERATE {len(batch)} PROMPTS, ONE PER LINE, IN ORDER ===\n" + "\n\n".join(ctx_blocks)
        )
        raw = _ai_call(settings, user_msg)
        prompts.extend(coerce_prompt_array(raw, len(batch)))

    prompts = [enforce_realistic_prompt(p) if p.strip() else "" for p in prompts[:n]]
    # Map prompts onto manifest assets in order (1 asset per line).
    for i, item in enumerate(manifest):
        item["prompt"] = prompts[i] if i < len(prompts) else ""
    _save_manifest(project, manifest)
    if callable(log):
        log(f"Đã tạo prompt cho {sum(1 for it in manifest if it.get('prompt'))}/{len(manifest)} cảnh.")
    return manifest
