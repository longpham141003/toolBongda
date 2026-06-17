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
