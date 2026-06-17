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
