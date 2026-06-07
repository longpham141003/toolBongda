from __future__ import annotations

import copy
import base64
import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus, urlparse

from .text_to_voice_queue import TextToVoiceRunner


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for", "from", "had",
    "has", "have", "he", "her", "hers", "him", "his", "i", "in", "into", "is", "it", "its",
    "me", "my", "of", "on", "or", "our", "she", "that", "the", "their", "them", "they", "this",
    "to", "was", "we", "were", "what", "when", "where", "which", "who", "with", "you", "your",
    "cua", "cho", "da", "dang", "de", "den", "do", "duoc", "la", "mot", "nhung", "noi", "qua",
    "rang", "sau", "tai", "the", "thi", "trong", "tu", "va", "voi",
}
GENERIC_IMAGE_TERMS = {
    "action", "athlete", "ball", "celebrity", "champion", "closeup", "documentary",
    "editorial", "famous", "football", "footballer", "game", "greatest", "image",
    "legend", "man", "match", "photo", "player", "portrait", "real", "scene",
    "soccer", "sport", "sports", "star", "team", "training", "world", "child",
    "children", "family", "skill", "skills", "agility", "dribbling", "passing",
    "playing",
}
SCENE_SHIFT_PREFIXES = (
    "after ", "afterward", "across ", "at dawn", "at night", "back at ", "back in ",
    "before ", "by morning", "days later", "elsewhere", "hours later", "inside ",
    "later ", "meanwhile", "moments later", "next ", "outside ", "suddenly",
    "that afternoon", "that evening", "that morning", "that night", "the next ",
    "then ", "when ", "while ",
)
CONTINUATION_PREFIXES = (
    "and ", "as ", "because ", "but ", "he ", "her ", "his ", "i ", "it ", "its ",
    "she ", "so ", "that ", "the ", "they ", "this ", "those ", "we ", "which ",
)
DEFAULT_IMAGE_ASPECT = 16 / 9
DEFAULT_IMAGE_ASPECT_TOLERANCE = 0.025
DEFAULT_IMAGE_MIN_WIDTH = 600
DEFAULT_IMAGE_MIN_HEIGHT = 330
DEFAULT_IMAGE_TARGET_WIDTH = 1920
DEFAULT_IMAGE_TARGET_HEIGHT = 1080


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _now() -> int:
    return int(time.time())


def _microseconds(seconds: float) -> int:
    return max(0, int(round(float(seconds) * 1_000_000)))


def _ascii_words(text: str) -> list[str]:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    return re.findall(r"[a-z0-9]+", value)


def _safe_name(text: str, fallback: str = "visual-project") -> str:
    words = _ascii_words(text)
    return "-".join(words[:10])[:72] or fallback


def read_json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def probe_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        try:
            import wave

            with wave.open(str(path), "rb") as source:
                return source.getnframes() / max(1, source.getframerate())
        except Exception:
            pass
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return max(0.0, float(result.stdout.strip() or 0.0))
    except Exception:
        return 0.0


def create_visual_project(projects_dir: Path, title: str, script: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    root = Path(projects_dir) / f"{stamp}_{_safe_name(title or script[:80])}"
    for folder in ("scripts", "voices", "assets", "assets/downloads", "logs", "capcut"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "script_final.txt").write_text(script.strip() + "\n", encoding="utf-8")
    write_json(
        root / "visual_project.json",
        {"version": 1, "title": title.strip(), "created_at": _now(), "script_final": "scripts/script_final.txt"},
    )
    return root


def generate_voice(project: Path, settings: dict, log: Callable[[str], None], stop_check=lambda: False) -> Path:
    script_path = project / "scripts" / "script_final.txt"
    output_path = project / "voices" / "voice.wav"
    runner = TextToVoiceRunner(settings, log=log, stop_check=stop_check)
    runner.start()
    try:
        runner.submit_file(script_path, "visual_pipeline", output_path)
    finally:
        runner.close()
    return output_path


def refine_timing_with_whisper(
    project: Path,
    settings: dict,
    log: Callable[[str], None] | None = None,
) -> dict:
    timing_path = project / "voices" / "voice.segments.json"
    if not bool(settings.get("whisper_timing_enabled", True)):
        return load_timing(project)

    audio_path = project / "voices" / "voice.wav"
    if not audio_path.exists():
        raise FileNotFoundError(f"Không tìm thấy voice để căn timing: {audio_path}")

    source_mtime = audio_path.stat().st_mtime_ns
    existing = read_json(timing_path, {})
    if (
        isinstance(existing, dict)
        and existing.get("engine") == "faster-whisper"
        and int(existing.get("source_audio_mtime_ns") or 0) == source_mtime
        and isinstance(existing.get("segments"), list)
        and existing.get("segments")
    ):
        if callable(log):
            log("Whisper timing: dùng lại kết quả đã căn theo voice.")
        return existing

    raw_python = str(settings.get("text_to_voice_python") or "").strip()
    python_path = Path(raw_python) if raw_python else Path(sys.executable)
    if not python_path.is_absolute():
        python_path = Path(__file__).resolve().parents[1] / python_path
    worker = Path(__file__).with_name("whisper_timing_cli.py")
    whisper_json = project / "voices" / "voice.whisper.json"
    whisper_srt = project / "voices" / "voice.whisper.srt"
    cmd = [
        str(python_path),
        str(worker),
        "--audio",
        str(audio_path),
        "--out-json",
        str(whisper_json),
        "--out-srt",
        str(whisper_srt),
        "--model",
        str(settings.get("whisper_timing_model") or "base"),
        "--language",
        str(settings.get("text_to_voice_language") or "en"),
        "--beam-size",
        str(max(1, int(settings.get("whisper_timing_beam_size") or 5))),
    ]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    hf_home = str(settings.get("chatterbox_hf_home") or "").strip()
    if hf_home:
        env["HF_HOME"] = hf_home
        env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    if callable(log):
        log("Whisper timing: đang nghe lại toàn bộ voice và căn timestamp...")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(300, int(settings.get("text_to_voice_timeout") or 1800)),
        env=env,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail[-1400:] or "Whisper timing failed.")
    data = read_json(whisper_json, {})
    if not isinstance(data, dict) or not data.get("segments"):
        raise RuntimeError("Whisper timing không tạo được segment.")
    script_path = project / "scripts" / "script_final.txt"
    script = script_path.read_text(encoding="utf-8", errors="replace").strip()
    aligned_segments = _align_script_sentences_to_whisper(script, data)
    if aligned_segments:
        data["raw_whisper_segments"] = data["segments"]
        data["segments"] = aligned_segments
        data["alignment"] = "script_text_to_whisper_words"
        data["duration"] = round(max(item["end"] for item in aligned_segments), 4)
        _write_srt(whisper_srt, aligned_segments)
    data["source_audio_mtime_ns"] = source_mtime
    data["srt_path"] = str(whisper_srt)
    write_json(whisper_json, data)
    write_json(timing_path, data)
    if callable(log):
        log(f"Whisper timing: đã tạo {len(data['segments'])} mốc thoại chính xác.")
    return data


def _script_sentences(script: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(script or "")).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])(?:[\"')\]]+)?\s+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _alignment_tokens(text: str) -> list[str]:
    return [
        word
        for word in _ascii_words(text)
        if word
    ]


def _align_script_sentences_to_whisper(script: str, timing: dict) -> list[dict]:
    sentences = _script_sentences(script)
    whisper_words = []
    for segment in timing.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        words = segment.get("words") if isinstance(segment.get("words"), list) else []
        if words:
            for word in words:
                token_text = str(word.get("text") or "").strip()
                tokens = _alignment_tokens(token_text)
                if not tokens:
                    continue
                whisper_words.append(
                    {
                        "token": tokens[0],
                        "start": float(word.get("start") or segment.get("start") or 0.0),
                        "end": float(word.get("end") or segment.get("end") or 0.0),
                    }
                )
        else:
            tokens = _alignment_tokens(str(segment.get("text") or ""))
            start = float(segment.get("start") or 0.0)
            end = max(start + 0.05, float(segment.get("end") or start))
            step = (end - start) / max(1, len(tokens))
            for index, token in enumerate(tokens):
                whisper_words.append(
                    {
                        "token": token,
                        "start": start + (index * step),
                        "end": start + ((index + 1) * step),
                    }
                )
    if not sentences or not whisper_words:
        return []

    script_tokens = []
    sentence_ranges = []
    for sentence in sentences:
        start = len(script_tokens)
        script_tokens.extend(_alignment_tokens(sentence))
        sentence_ranges.append((start, len(script_tokens)))
    if not script_tokens:
        return []

    whisper_tokens = [item["token"] for item in whisper_words]
    matcher = difflib.SequenceMatcher(None, script_tokens, whisper_tokens, autojunk=False)
    token_map: dict[int, int] = {}
    for script_start, whisper_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            token_map[script_start + offset] = whisper_start + offset

    def estimated_word_index(script_index: int) -> int:
        if script_index in token_map:
            return token_map[script_index]
        lower = [(key, value) for key, value in token_map.items() if key < script_index]
        upper = [(key, value) for key, value in token_map.items() if key > script_index]
        if lower and upper:
            low_key, low_value = max(lower)
            high_key, high_value = min(upper)
            ratio = (script_index - low_key) / max(1, high_key - low_key)
            return int(round(low_value + ((high_value - low_value) * ratio)))
        return int(round(script_index * len(whisper_words) / max(1, len(script_tokens))))

    aligned = []
    previous_end = 0.0
    for index, (sentence, (token_start, token_end)) in enumerate(zip(sentences, sentence_ranges), start=1):
        if token_end <= token_start:
            continue
        mapped = [
            token_map[token_index]
            for token_index in range(token_start, token_end)
            if token_index in token_map
        ]
        first_word = min(mapped) if mapped else estimated_word_index(token_start)
        last_word = max(mapped) if mapped else estimated_word_index(token_end - 1)
        first_word = max(0, min(first_word, len(whisper_words) - 1))
        last_word = max(first_word, min(last_word, len(whisper_words) - 1))
        start = max(previous_end, float(whisper_words[first_word]["start"]))
        end = max(start + 0.05, float(whisper_words[last_word]["end"]))
        aligned.append(
            {
                "text": sentence,
                "start": round(start, 4),
                "end": round(end, 4),
                "duration": round(end - start, 4),
                "script_sentence_index": index,
            }
        )
        previous_end = end
    return aligned


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def _write_srt(path: Path, segments: list[dict]) -> None:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{_srt_time(segment['start'])} --> {_srt_time(segment['end'])}\n{segment['text']}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def load_timing(project: Path) -> dict:
    timing_path = project / "voices" / "voice.segments.json"
    data = read_json(timing_path, {})
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise FileNotFoundError(f"Không tìm thấy timing voice: {timing_path}")
    return data


def _segment_start(item: dict) -> float:
    for key in ("start", "start_time", "begin"):
        if key in item:
            return float(item.get(key) or 0.0)
    return 0.0


def _segment_end(item: dict) -> float:
    for key in ("end", "end_time"):
        if key in item:
            return float(item.get(key) or 0.0)
    return _segment_start(item) + float(item.get("duration") or 0.0)


def normalize_voice_segments(timing: dict) -> list[dict]:
    result = []
    for index, raw in enumerate(timing.get("segments") or [], start=1):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        start = max(0.0, _segment_start(raw))
        end = max(start + 0.05, _segment_end(raw))
        if text:
            result.append({"sentence_index": index, "text": text, "start": start, "end": end})
    return result


def merge_segments_into_sentences(segments: list[dict]) -> list[dict]:
    sentences: list[dict] = []
    pending: list[dict] = []
    for segment in segments:
        pending.append(segment)
        text = str(segment["text"]).strip()
        if re.search(r"[.!?][\"')\]]?$", text):
            sentences.append(_sentence_from_segments(len(sentences) + 1, pending))
            pending = []
    if pending:
        sentences.append(_sentence_from_segments(len(sentences) + 1, pending))
    return sentences


def _sentence_from_segments(index: int, segments: list[dict]) -> dict:
    text = " ".join(str(item["text"]).strip() for item in segments)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text).strip()
    return {
        "sentence_index": index,
        "segment_indexes": [int(item["sentence_index"]) for item in segments],
        "text": text,
        "start": float(segments[0]["start"]),
        "end": float(segments[-1]["end"]),
    }


def _visual_tokens(text: str) -> set[str]:
    return {
        word for word in _ascii_words(text)
        if len(word) > 3 and word not in STOP_WORDS and not word.isdigit()
    }


def _proper_names(text: str) -> set[str]:
    names = re.findall(r"\b[A-Z][a-z]{2,}\b", str(text or ""))
    ignored = {"After", "Before", "Inside", "Later", "Meanwhile", "Outside", "Suddenly", "Then", "When", "While"}
    return {name.lower() for name in names if name not in ignored}


def _scene_break_reason(scene: list[dict], sentence: dict) -> str:
    if not scene:
        return ""
    text = str(sentence["text"]).strip()
    lowered = text.lower()
    current_start = float(scene[0]["start"])
    current_end = float(scene[-1]["end"])
    current_duration = current_end - current_start
    next_duration = float(sentence["end"]) - float(sentence["start"])

    if current_duration >= 10.0:
        return "long_scene_guard"
    if current_duration >= 4.0 and (float(sentence["end"]) - current_start) > 12.0:
        return "target_scene_duration"
    if lowered.startswith(SCENE_SHIFT_PREFIXES) and current_duration >= 4.0:
        return "transition"
    if len(scene) >= 4:
        return "scene_sentence_limit"

    current_text = " ".join(str(item["text"]) for item in scene)
    current_tokens = _visual_tokens(current_text)
    next_tokens = _visual_tokens(text)
    overlap = len(current_tokens & next_tokens) / max(1, min(len(current_tokens), len(next_tokens)))
    current_names = _proper_names(current_text)
    next_names = _proper_names(text)
    starts_as_continuation = lowered.startswith(CONTINUATION_PREFIXES)
    is_dialogue = bool(re.match(r"^[\"']", text))

    if current_duration < 5.0 or next_duration < 2.5:
        return ""
    if starts_as_continuation or is_dialogue or overlap >= 0.16 or bool(current_names & next_names):
        return ""
    if current_duration >= 8.0 and next_names and current_names and not (next_names & current_names):
        return "subject_change"
    if current_duration >= 10.0 and overlap < 0.08:
        return "visual_topic_change"
    return ""


def split_sentences_into_scenes(sentences: list[dict]) -> list[dict]:
    scenes: list[dict] = []
    current: list[dict] = []
    next_reason = "opening"
    for sentence in sentences:
        reason = _scene_break_reason(current, sentence)
        if reason:
            scenes.append({"sentences": current, "break_reason": next_reason})
            current = []
            next_reason = reason
        current.append(sentence)
    if current:
        scenes.append({"sentences": current, "break_reason": next_reason})
    return scenes


def keyword_for_text(text: str) -> str:
    words = [word for word in _ascii_words(text) if len(word) > 2 and word not in STOP_WORDS and not word.isdigit()]
    ranked: list[str] = []
    for word in words:
        if word not in ranked:
            ranked.append(word)
    return " ".join(ranked[:8]) or "cinematic documentary scene"


def _capitalized_phrases(text: str) -> list[str]:
    ignored = {
        "After", "As", "At", "Before", "For", "From", "He", "His", "In", "It", "Leaving",
        "One", "That", "The", "Their", "Together", "When",
    }
    phrases = []
    for match in re.findall(r"\b[A-Z][A-Za-z']*(?:\s+[A-Z][A-Za-z']*){0,4}\b", str(text or "")):
        words = match.split()
        if words and words[0] in ignored:
            continue
        cleaned = re.sub(r"'s\b", "", match).strip()
        if cleaned and cleaned not in phrases:
            phrases.append(cleaned)
    return phrases


def _clean_search_keyword(value: str) -> str:
    value = re.sub(r"[\"'`]+", "", str(value or ""))
    value = re.sub(r"\b(free|stock|photo|image|picture|real life|high quality|hd|4k)\b", " ", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" ,;:-")
    return value[:90]


def _is_generic_keyword(value: str, scene_text: str = "") -> bool:
    words = [word for word in _ascii_words(value) if word not in STOP_WORDS]
    if len(words) < 3:
        return True
    specific = [word for word in words if word not in GENERIC_IMAGE_TERMS and len(word) > 2]
    scene_specific = set(_ascii_words(scene_text)) - STOP_WORDS - GENERIC_IMAGE_TERMS
    if len(specific) < 2 and not (set(specific) & scene_specific):
        return True
    return False


def _local_getty_keywords(scene_text: str) -> list[str]:
    text = str(scene_text or "")
    lowered = text.lower()
    phrases = _capitalized_phrases(text)
    has_messi = "messi" in lowered
    result: list[str] = []

    def add(value: str) -> None:
        cleaned = _clean_search_keyword(value)
        if cleaned and cleaned not in result and not _is_generic_keyword(cleaned, text):
            result.append(cleaned)

    if has_messi:
        if "rosario" in lowered or "born" in lowered or "young" in lowered:
            add("Lionel Messi Newell's Old Boys young")
            add("Lionel Messi Rosario Argentina young")
        if "child" in lowered or "small" in lowered or "beginning" in lowered:
            add("Lionel Messi young Newells Old Boys")
        if "thirteen" in lowered or "academy" in lowered or "spain" in lowered or "barcelona" in lowered:
            add("Lionel Messi La Masia Barcelona youth")
        if "dribbl" in lowered or "passing" in lowered or "quick turns" in lowered:
            add("Lionel Messi Barcelona dribbling")
        if "defenders" in lowered or "change direction" in lowered:
            add("Lionel Messi Barcelona dribbles past defender")
        if "suarez" in lowered:
            add("Lionel Messi Luis Suarez Barcelona")
            add("Lionel Messi Luis Suarez celebration")
        if "antonela" in lowered or "family" in lowered or "sons" in lowered:
            add("Lionel Messi Antonela Roccuzzo family")
        if "world cup" in lowered or "2022" in lowered:
            add("Lionel Messi Argentina World Cup trophy 2022")
    if not result and phrases:
        add(" ".join(phrases[:2]))
    return result[:6]


def build_asset_manifest(
    project: Path,
    settings: dict | None = None,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    settings = settings or {}
    timing = load_timing(project)
    try:
        timing = refine_timing_with_whisper(project, settings, log=log)
    except Exception as exc:
        if callable(log):
            log(f"Whisper timing lỗi, dùng timing voice hiện tại: {exc}")
    segments = normalize_voice_segments(timing)
    if not segments:
        raise RuntimeError("Timing không có câu thoại.")
    sentences = merge_segments_into_sentences(segments)
    split_mode = "semantic_srt_scenes"
    try:
        assets = group_scenes_with_ai(project, sentences, settings, log=log)
        split_mode = "gemini_semantic_srt_scenes"
    except Exception as exc:
        if callable(log):
            log(f"Gemini chia cảnh lỗi, dùng bộ chia local: {exc}")
        scenes = split_sentences_into_scenes(sentences)
        assets = [
            _manifest_item(index, scene["sentences"], scene["break_reason"])
            for index, scene in enumerate(scenes, start=1)
        ]
    script_path = project / "scripts" / "script_final.txt"
    script = script_path.read_text(encoding="utf-8", errors="replace").strip()
    assets = _apply_match_search_context(assets, script)
    manifest_path = project / "assets" / "asset_manifest.json"
    write_json(
        manifest_path,
        {
            "version": 3,
            "split_mode": split_mode,
            "timing_engine": str(timing.get("engine") or "voice"),
            "source_segment_count": len(segments),
            "sentence_count": len(sentences),
            "scene_count": len(assets),
            "items": assets,
        },
    )
    return assets


def _infer_match_teams(script: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(script or "")).strip()
    patterns = (
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\s+(?:vs\.?|versus)\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\s+faced\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b[^.!?]{0,100}\bmatch against\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"^([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,2})\b[^.!?]{0,140}\bagainst\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            values = [re.sub(r"\s+", " ", match.group(index)).strip() for index in (1, 2)]
            if all(values) and values[0].lower() != values[1].lower():
                return values
    opponent = re.search(
        r"\bagainst\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        text,
    )
    leading = re.match(r"^([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,2})\b", text)
    if opponent and leading:
        return [leading.group(1).strip(), opponent.group(1).strip()]
    return []


def _scene_match_action(item: dict, teams: list[str]) -> tuple[str, str]:
    text = f"{item.get('sentence_text') or ''} {item.get('action_context') or ''}"
    lowered = text.lower()
    phrases = _capitalized_phrases(text)
    ignored = {
        "World Cup", "Les Bleus", "However", "The", "After", "Before", "In",
        "His", "By", "Every", "Maracana Stadium",
    }
    ignored.update(teams)
    candidates = [
        phrase for phrase in phrases
        if phrase not in ignored
        and not any(phrase.lower() == team.lower() for team in teams)
        and not phrase.lower().endswith("stadium")
    ]
    subject = next((phrase for phrase in candidates if len(phrase.split()) >= 2), "")
    if not subject:
        subject = next(iter(candidates), "")
    if any(term in lowered for term in ("goal", "scor", "equaliz", "finish", "comeback")):
        return subject, "goal celebration match action"
    if any(term in lowered for term in ("coach", "deschamps", "ancelotti", "warning", "substitution", "touchline")):
        return subject, "coach touchline match"
    if any(term in lowered for term in ("defend", "tackle", "attack", "penalty area")):
        return subject, "players competing match action"
    return subject, "players match action"


def _apply_match_search_context(items: list[dict], script: str) -> list[dict]:
    teams = _infer_match_teams(script)
    if len(teams) != 2:
        return items
    matchup = f"{teams[0]} {teams[1]}"
    score_words = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9",
    }
    score = ""
    score_match = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine)[ -](one|two|three|four|five|six|seven|eight|nine)\b",
        script,
        flags=re.I,
    )
    if score_match:
        score = f"{score_words[score_match.group(1).lower()]}-{score_words[score_match.group(2).lower()]}"
    stadium_match = re.search(
        r"\b([A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*){0,3}\s+Stadium)\b",
        script,
    )
    stadium = stadium_match.group(1).strip() if stadium_match else ""
    event_context = " ".join(value for value in (score, stadium) if value)
    for item in items:
        subject, action = _scene_match_action(item, teams)
        action_short = ""
        if "goal celebration" in action:
            action_short = "celebration"
        elif "coach touchline" in action:
            action_short = "touchline"
        elif "players competing" in action:
            action_short = "action"
        query = _clean_search_keyword(
            " ".join(value for value in (subject, matchup, score, action_short) if value)
        )
        if not query:
            query = f"{matchup} {score} match".strip()
        existing = item.get("google_queries") if isinstance(item.get("google_queries"), list) else []
        existing = [_clean_search_keyword(str(value)) for value in existing if _clean_search_keyword(str(value))]
        if "coach touchline" in action:
            event_variants = [
                f"{subject or 'coach'} {matchup} {score} touchline",
                f"{subject or 'coach'} {matchup} Maracana",
                f"{matchup} {score} coach bench",
            ]
        elif "goal celebration" in action:
            event_variants = [
                f"{subject} {matchup} {score} celebration",
                f"{matchup} {score} goal celebration",
                f"{matchup} {score} players celebrating",
            ]
        else:
            event_variants = [
                f"{subject} {matchup} {score} action",
                f"{matchup} {score} match action",
                f"{matchup} {stadium} match",
            ]
        normalized = []
        for value in [query, *event_variants, *existing]:
            value = _concise_match_query(value, item)
            if value and value not in normalized:
                normalized.append(value)
        item["visual_source_type"] = "match_photography"
        item["match_teams"] = teams
        item["google_queries"] = normalized[:4]
        item["sportsdb_queries"] = []
        item["keyword"] = normalized[0] if normalized else query
        item["ai_search_keyword"] = item["keyword"]
    return items


def group_scenes_with_ai(
    project: Path,
    sentences: list[dict],
    settings: dict,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    if not bool(settings.get("scene_ai_enabled", True)):
        raise RuntimeError("AI scene grouping is disabled.")
    provider = str(settings.get("keyword_ai_provider") or "auto").strip().lower()
    gemini_key = str(settings.get("gemini_api_key") or "").strip()
    if provider == "openai":
        raise RuntimeError("Chia cảnh ngữ nghĩa hiện chỉ dùng Gemini.")
    if not gemini_key:
        raise RuntimeError("Chưa có Gemini API key.")

    script_path = project / "scripts" / "script_final.txt"
    script = script_path.read_text(encoding="utf-8", errors="replace").strip()
    payload = [
        {
            "sentence_index": int(item["sentence_index"]),
            "start": round(float(item["start"]), 4),
            "end": round(float(item["end"]), 4),
            "text": str(item["text"]),
        }
        for item in sentences
    ]
    if callable(log):
        log(f"Gemini scene: đang đọc toàn bộ SRT và gộp {len(sentences)} câu theo ngữ cảnh...")
    rows = _call_scene_ai_gemini(
        gemini_key,
        str(settings.get("gemini_keyword_model") or "gemini-2.5-flash"),
        script,
        payload,
        float(settings.get("scene_min_seconds") or 3.0),
        float(settings.get("scene_target_max_seconds") or 10.0),
    )
    groups = _validate_scene_groups(rows, sentences)
    assets = []
    for index, (row, grouped_sentences) in enumerate(groups, start=1):
        item = _manifest_item(
            index,
            grouped_sentences,
            str(row.get("break_reason") or ("opening" if index == 1 else "semantic_change")).strip(),
        )
        keyword = _clean_search_keyword(str(row.get("search_keyword") or ""))
        fallback_keywords = row.get("fallback_keywords") if isinstance(row.get("fallback_keywords"), list) else []
        google_queries = row.get("google_queries") if isinstance(row.get("google_queries"), list) else []
        sportsdb_queries = row.get("sportsdb_queries") if isinstance(row.get("sportsdb_queries"), list) else []
        if keyword and not _is_generic_keyword(keyword, item["sentence_text"]):
            item["keyword"] = keyword
            item["ai_search_keyword"] = keyword
        item["fallback_keywords"] = [
            value for value in (_clean_search_keyword(str(value)) for value in fallback_keywords)
            if value and not _is_generic_keyword(value, item["sentence_text"])
        ][:5]
        item["google_queries"] = [
            value for value in (_clean_search_keyword(str(value)) for value in google_queries) if value
        ][:8]
        item["sportsdb_queries"] = [
            value for value in (_clean_search_keyword(str(value)) for value in sportsdb_queries) if value
        ][:6]
        item["main_subject"] = str(row.get("main_subject") or "").strip()
        item["action_context"] = str(row.get("action_context") or "").strip()
        item["visual_intent"] = str(row.get("visual_intent") or "").strip()
        item["visual_source_type"] = str(row.get("visual_source_type") or "match_photography").strip()
        item["scene_analysis_source"] = "gemini"
        item["keyword_source"] = "gemini_scene"
        assets.append(item)
    if callable(log):
        log(f"Gemini scene: đã gộp thành {len(assets)} cảnh.")
    return assets


def _scene_prompt(
    script: str,
    sentences: list[dict],
    min_seconds: float,
    target_max_seconds: float,
) -> str:
    return (
        "You are a professional sports documentary editor and visual researcher.\n"
        "Read the full script and every timed SRT sentence before deciding scene boundaries.\n"
        "Group consecutive sentence indexes into coherent visual scenes.\n"
        "Scene rules:\n"
        "- Split when the main person, team, location, event, action, or time period changes.\n"
        "- Keep sentences that complete one idea together. Never cut in the middle of an idea.\n"
        f"- Prefer scenes around {min_seconds:g}-{target_max_seconds:g} seconds, but meaning is more important and longer scenes are allowed.\n"
        "- Every sentence must appear exactly once, in original order, with no gaps or overlap.\n"
        "- A scene must contain one continuous sentence_start..sentence_end range.\n"
        "- break_reason must clearly state what changed from the previous scene, such as subject_change, event_change, "
        "location_change, time_change, action_change, or continuation. First scene uses opening.\n"
        "- main_subject names the exact visible person/team/place/object.\n"
        "- action_context describes the visible action, event, location, and useful date/competition context.\n"
        "- This tool needs real editorial match photography, not thumbnails, title cards, posters, graphics, wallpapers, "
        "training photos, portraits, logos, badges, team artwork, or generic player photos.\n"
        "- For narration about a specific match, visual_source_type must be match_photography for every scene, including "
        "the introduction and conclusion. Keep visuals inside that same match.\n"
        "- search_keyword is a short 4-8 word Google Images query.\n"
        "- Every match query must include both teams/opponents when known and use a visible match moment: match action, "
        "goal, celebration, tackle, substitution, coach touchline, players after final whistle.\n"
        "- Avoid abstract/generic queries such as football player, greatest player, famous team, sports scene.\n"
        "- Return 3-5 specific fallback_keywords.\n"
        "- sportsdb_queries contain only exact player/team/stadium/event names.\n"
        "- google_queries contain person + both teams + score/action. Do not add filler such as editorial photo, players competing, visible context.\n"
        "Return strict JSON only with key scenes. Each scene must contain: sentence_start, sentence_end, "
        "break_reason, main_subject, action_context, visual_intent, visual_source_type, search_keyword, fallback_keywords, "
        "sportsdb_queries, google_queries.\n"
        'Exact schema example: {"scenes":[{"sentence_start":1,"sentence_end":2,"break_reason":"opening",'
        '"main_subject":"France and Ivory Coast","action_context":"players competing during the match",'
        '"visual_intent":"real match action","visual_source_type":"match_photography",'
        '"search_keyword":"France Ivory Coast match action editorial photo","fallback_keywords":[],'
        '"sportsdb_queries":[],"google_queries":["France Ivory Coast match action editorial photo"]}]}.\n\n'
        f"FULL SCRIPT:\n{script}\n\n"
        f"TIMED SRT SENTENCES:\n{json.dumps(sentences, ensure_ascii=False)}"
    )


def _call_scene_ai_gemini(
    api_key: str,
    model: str,
    script: str,
    sentences: list[dict],
    min_seconds: float,
    target_max_seconds: float,
) -> list[dict]:
    import requests

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _scene_prompt(script, sentences, min_seconds, target_max_seconds)}],
            }
        ],
        "generationConfig": {
            "temperature": 0.15,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "required": ["scenes"],
                "properties": {
                    "scenes": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "required": [
                                "sentence_start", "sentence_end", "break_reason", "main_subject",
                                "action_context", "visual_intent", "visual_source_type",
                                "search_keyword", "fallback_keywords", "sportsdb_queries", "google_queries",
                            ],
                            "properties": {
                                "sentence_start": {"type": "INTEGER"},
                                "sentence_end": {"type": "INTEGER"},
                                "break_reason": {"type": "STRING"},
                                "main_subject": {"type": "STRING"},
                                "action_context": {"type": "STRING"},
                                "visual_intent": {"type": "STRING"},
                                "visual_source_type": {"type": "STRING"},
                                "search_keyword": {"type": "STRING"},
                                "fallback_keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
                                "sportsdb_queries": {"type": "ARRAY", "items": {"type": "STRING"}},
                                "google_queries": {"type": "ARRAY", "items": {"type": "STRING"}},
                            },
                        },
                    }
                },
            },
        },
    }
    response = None
    errors = []
    for candidate_model in dict.fromkeys([model, "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"]):
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        if response.status_code < 400:
            break
        errors.append(f"{candidate_model}: HTTP {response.status_code}")
        if response.status_code not in {429, 500, 502, 503, 504}:
            break
    if response is None:
        raise RuntimeError("Gemini scene API không phản hồi.")
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini scene API lỗi ({', '.join(errors)}): {response.text[-600:]}")
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini scene API không trả về candidate.")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    content = "".join(str(part.get("text") or "") for part in parts).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    parsed = json.loads(content)
    rows = parsed.get("scenes") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        raise RuntimeError("Gemini scene API không trả về scenes list.")
    return rows


def _validate_scene_groups(
    rows: list[dict],
    sentences: list[dict],
) -> list[tuple[dict, list[dict]]]:
    by_index = {int(item["sentence_index"]): item for item in sentences}
    expected = list(range(1, len(sentences) + 1))
    used = []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Gemini scene có dòng không hợp lệ.")
        indexes = row.get("sentence_indexes") if isinstance(row.get("sentence_indexes"), list) else []
        start_value = (
            row.get("sentence_start")
            if row.get("sentence_start") is not None
            else row.get("start_sentence", row.get("start_index"))
        )
        end_value = (
            row.get("sentence_end")
            if row.get("sentence_end") is not None
            else row.get("end_sentence", row.get("end_index"))
        )
        if indexes and (start_value is None or end_value is None):
            start_value = min(int(value) for value in indexes)
            end_value = max(int(value) for value in indexes)
        start = int(start_value) if start_value is not None else 0
        end = int(end_value) if end_value is not None else 0
        if start < 1 or end < start or end > len(sentences):
            raise RuntimeError(f"Gemini scene range không hợp lệ: {start}-{end}.")
        indexes = list(range(start, end + 1))
        used.extend(indexes)
        result.append((row, [by_index[index] for index in indexes]))
    if used != expected:
        raise RuntimeError("Gemini scene không bao phủ đúng tất cả câu SRT theo thứ tự.")
    return result


def _manifest_item(index: int, sentences: list[dict], break_reason: str) -> dict:
    text = " ".join(str(item["text"]) for item in sentences).strip()
    start = float(sentences[0]["start"])
    end = float(sentences[-1]["end"])
    return {
        "asset_id": f"asset_{index:04d}",
        "sentence_indexes": [int(item["sentence_index"]) for item in sentences],
        "srt_segment_indexes": [
            int(segment_index)
            for sentence in sentences
            for segment_index in sentence["segment_indexes"]
        ],
        "sentence_text": text,
        "scene_break_reason": break_reason,
        "start": round(start, 4),
        "end": round(end, 4),
        "duration": round(max(0.05, end - start), 4),
        "keyword": keyword_for_text(text),
        "search_attempt": 0,
        "status": "pending",
        "source_url": "",
        "source_page": "",
        "local_path": "",
        "thumbnail_url": "",
    }


def load_manifest(project: Path) -> list[dict]:
    data = read_json(project / "assets" / "asset_manifest.json", {})
    return list(data.get("items") or []) if isinstance(data, dict) else []


def save_manifest(project: Path, items: list[dict]) -> None:
    write_json(project / "assets" / "asset_manifest.json", {"version": 1, "items": items})


def optimize_asset_keywords_with_ai(
    project: Path,
    settings: dict,
    log: Callable[[str], None] | None = None,
    chunk_size: int = 18,
) -> list[dict]:
    provider = str(settings.get("keyword_ai_provider") or "auto").strip().lower()
    openai_key = str(settings.get("openai_api_key") or "").strip()
    gemini_key = str(settings.get("gemini_api_key") or "").strip() or openai_key
    if provider == "auto":
        if openai_key.startswith("sk-"):
            provider = "openai"
        elif gemini_key:
            provider = "gemini"
    api_key = openai_key if provider == "openai" else gemini_key
    if not api_key:
        if callable(log):
            log("AI keyword: chưa có API key, dùng keyword local.")
        return load_manifest(project)

    items = load_manifest(project)
    if not items:
        return items
    if all(
        item.get("scene_analysis_source") == "gemini"
        and item.get("keyword_source") == "gemini_scene"
        and item.get("keyword")
        for item in items
    ):
        if callable(log):
            log("AI keyword: Gemini đã tạo keyword ngay khi chia cảnh, không gọi lại API.")
        return items
    for item in items:
        item.setdefault("keyword_local", item.get("keyword") or "")

    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        payload = [
            {
                "asset_id": item.get("asset_id"),
                "scene_text": item.get("sentence_text"),
                "timing": f"{item.get('start')} - {item.get('end')}",
                "local_keyword": item.get("keyword"),
            }
            for item in chunk
        ]
        if callable(log):
            log(f"AI keyword: tối ưu {start + 1}-{start + len(chunk)}/{len(items)}")
        try:
            if provider == "gemini":
                result = _call_keyword_ai_gemini(api_key, str(settings.get("gemini_keyword_model") or "gemini-2.5-flash"), payload)
            else:
                if not api_key.startswith("sk-"):
                    raise RuntimeError("OpenAI key phải bắt đầu bằng sk-. Nếu dùng key AQ..., hãy chọn provider Gemini.")
                result = _call_keyword_ai_openai(api_key, str(settings.get("keyword_ai_model") or "gpt-4.1-mini"), payload)
        except Exception as exc:
            if callable(log):
                log(f"AI keyword lỗi, giữ keyword/query fallback nội bộ: {exc}")
            break
        by_id = {str(row.get("asset_id") or ""): row for row in result}
        for item in chunk:
            row = by_id.get(str(item.get("asset_id") or ""))
            if not row:
                continue
            local_keywords = _local_getty_keywords(str(item.get("sentence_text") or ""))
            search_keyword = _clean_search_keyword(str(row.get("search_keyword") or "").strip())
            fallbacks = row.get("fallback_keywords") if isinstance(row.get("fallback_keywords"), list) else []
            fallbacks = [_clean_search_keyword(str(value).strip()) for value in fallbacks if str(value).strip()]
            sportsdb_queries = row.get("sportsdb_queries") if isinstance(row.get("sportsdb_queries"), list) else []
            google_queries = row.get("google_queries") if isinstance(row.get("google_queries"), list) else []
            fallbacks = [
                value for value in fallbacks
                if value and not _is_generic_keyword(value, str(item.get("sentence_text") or ""))
            ]
            if _is_generic_keyword(search_keyword, str(item.get("sentence_text") or "")):
                search_keyword = local_keywords[0] if local_keywords else str(item.get("keyword") or "")
            merged_fallbacks = []
            for value in [*fallbacks, *local_keywords]:
                if value and value != search_keyword and value not in merged_fallbacks:
                    merged_fallbacks.append(value)
            if search_keyword:
                item["keyword"] = search_keyword
                item["ai_search_keyword"] = search_keyword
            if merged_fallbacks:
                item["fallback_keywords"] = merged_fallbacks[:5]
            item["sportsdb_queries"] = [_clean_search_keyword(value) for value in sportsdb_queries if _clean_search_keyword(value)][:6]
            item["google_queries"] = [_clean_search_keyword(value) for value in google_queries if _clean_search_keyword(value)][:8]
            item["visual_intent"] = str(row.get("visual_intent") or "").strip()
            item["keyword_source"] = provider
    script_path = project / "scripts" / "script_final.txt"
    if script_path.exists():
        script = script_path.read_text(encoding="utf-8", errors="replace").strip()
        items = _apply_match_search_context(items, script)
    save_manifest(project, items)
    return items


def _keyword_prompt(scenes: list[dict]) -> str:
    prompt = (
        "You create sports visual asset search plans for video B-roll.\n"
        "For each scene, understand the real visual meaning and return precise English search phrases.\n"
        "Rules:\n"
        "- Target these sources in order: TheSportsDB, then Google Images via Playwright.\n"
        "- Main search_keyword must be 4-8 words and read like a normal Google Images search.\n"
        "- Prefer exact visible moment: person + club/country/event + action/time.\n"
        "- For a specific match, return only real match photography from that match. Never request portraits, training, "
        "logos, artwork, thumbnails, posters, title cards, wallpapers, previews, reaction videos, or highlight thumbnails.\n"
        "- Include both opponents in every specific-match query when known.\n"
        "- Bad: football player, soccer, sports, family man, greatest player, real life action scene.\n"
        "- Good: Lionel Messi Barcelona dribbling, Lionel Messi Luis Suarez Barcelona, Lionel Messi Argentina World Cup trophy 2022.\n"
        "- Do not include abstract filler words like known, considered, important, history, famous.\n"
        "- If a real public figure/team/event is mentioned, keep the name.\n"
        "- sportsdb_queries: exact player/team/stadium/event names only, no long sentences.\n"
        "- google_queries: person + both opponents + score or one action word. Never append editorial photo.\n"
        "- Include 3-5 fallback_keywords, all specific enough for image search.\n"
        "- For each item return: asset_id, visual_intent, search_keyword, fallback_keywords, sportsdb_queries, google_queries.\n"
        "- Output only valid JSON with key items.\n\n"
        f"Scenes JSON:\n{json.dumps({'items': scenes}, ensure_ascii=False)}"
    )
    return prompt


def _parse_keyword_ai_json(content: str) -> list[dict]:
    content = str(content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    parsed = json.loads(content)
    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        raise RuntimeError("Keyword AI không trả về items list.")
    return items


def _call_keyword_ai_openai(api_key: str, model: str, scenes: list[dict]) -> list[dict]:
    import requests

    prompt = _keyword_prompt(scenes)
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 2400,
        },
        timeout=90,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI keyword API lỗi {response.status_code}: {response.text[-600:]}")
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    return _parse_keyword_ai_json(content)


def _call_keyword_ai_gemini(api_key: str, model: str, scenes: list[dict]) -> list[dict]:
    import requests

    prompt = _keyword_prompt(scenes)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    response = None
    errors = []
    for candidate_model in dict.fromkeys([model, "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"]):
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{candidate_model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        if response.status_code < 400:
            break
        errors.append(f"{candidate_model}: HTTP {response.status_code}")
        if response.status_code not in {429, 500, 502, 503, 504}:
            break
    if response is None:
        raise RuntimeError("Gemini keyword API không phản hồi.")
    if response.status_code >= 400:
        raise RuntimeError(f"Gemini keyword API lỗi ({', '.join(errors)}): {response.text[-600:]}")
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini keyword API không trả về candidate.")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    content = "".join(str(part.get("text") or "") for part in parts)
    return _parse_keyword_ai_json(content)


def _image_filter_settings(settings: dict | None = None) -> dict:
    settings = settings or {}
    aspect_width = float(settings.get("image_aspect_width") or 16)
    aspect_height = float(settings.get("image_aspect_height") or 9)
    return {
        "aspect": aspect_width / max(1.0, aspect_height),
        "tolerance": max(0.001, float(settings.get("image_aspect_tolerance") or DEFAULT_IMAGE_ASPECT_TOLERANCE)),
        "min_width": max(320, int(settings.get("image_min_width") or DEFAULT_IMAGE_MIN_WIDTH)),
        "min_height": max(180, int(settings.get("image_min_height") or DEFAULT_IMAGE_MIN_HEIGHT)),
        "target_width": max(320, int(settings.get("image_target_width") or DEFAULT_IMAGE_TARGET_WIDTH)),
        "target_height": max(180, int(settings.get("image_target_height") or DEFAULT_IMAGE_TARGET_HEIGHT)),
        "enhance_enabled": bool(settings.get("image_enhance_enabled", True)),
    }


def _is_target_aspect(width: int, height: int, settings: dict | None = None) -> bool:
    if width <= 0 or height <= 0:
        return False
    options = _image_filter_settings(settings)
    ratio = width / height
    return abs(ratio - float(options["aspect"])) <= float(options["tolerance"])


def _valid_crawled_images(
    folder: Path,
    excluded_hashes: set[str] | None = None,
    excluded_dhashes: set[int] | None = None,
    query: str = "",
    settings: dict | None = None,
    min_keyword_score: int = 0,
) -> list[Path]:
    from PIL import Image

    excluded_hashes = excluded_hashes or set()
    excluded_dhashes = excluded_dhashes or set()
    options = _image_filter_settings(settings)
    query_tokens = {
        token for token in _ascii_words(query)
        if len(token) > 2 and token not in STOP_WORDS
    }
    candidates: list[tuple[int, int, int, Path]] = []
    for path in folder.rglob("*"):
        if not path.is_file() or path.stat().st_size < 2048:
            continue
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
            if width < int(options["min_width"]) or height < int(options["min_height"]):
                continue
            if not _is_target_aspect(width, height, settings):
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in excluded_hashes:
                continue
            perceptual = _image_dhash(path)
            if perceptual is not None and any((perceptual ^ old).bit_count() <= 6 for old in excluded_dhashes):
                continue
            metadata_path = path.with_suffix(path.suffix + ".json")
            metadata = read_json(metadata_path, {}) if metadata_path.exists() else {}
            searchable_text = " ".join(
                [
                    path.stem,
                    str(metadata.get("title") or ""),
                    str(metadata.get("url") or ""),
                    str(metadata.get("page") or ""),
                ]
            )
            candidate_tokens = set(_ascii_words(searchable_text))
            keyword_score = len(query_tokens & candidate_tokens)
            if keyword_score < int(min_keyword_score):
                continue
            ratio_error = int(abs((width / height) - float(options["aspect"])) * 10000)
            candidates.append((keyword_score, -ratio_error, width * height, path))
        except Exception:
            continue
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [path for _score, _ratio, _area, path in candidates]


def _gemini_image_payload(path: Path) -> tuple[str, str]:
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGB")
        image.thumbnail((1280, 1280), getattr(Image, "Resampling", Image).LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=86, optimize=True)
    return "image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii")


def _vision_sidecar(path: Path) -> Path:
    digest = hashlib.sha1(path.name.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return path.parent / f"_vision_{digest}.json"


def _rank_images_with_gemini(
    candidates: list[Path],
    item: dict,
    settings: dict | None,
    log: Callable[[str], None] | None = None,
) -> list[tuple[Path, dict]]:
    import requests

    settings = settings or {}
    api_key = str(settings.get("gemini_api_key") or "").strip()
    enabled = bool(settings.get("image_ai_validation_enabled", True))
    if not enabled or not api_key:
        if enabled and log:
            log(f"{item.get('asset_id')}: chưa có Gemini API key, chỉ chấm theo metadata.")
        return [(path, {"accepted": True, "score": 0, "reason": "metadata-only"}) for path in candidates]

    primary_model = str(settings.get("gemini_vision_model") or settings.get("gemini_keyword_model") or "gemini-2.5-flash")
    models = list(
        dict.fromkeys(
            [
                primary_model,
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash-lite",
            ]
        )
    )
    minimum_score = max(1, min(100, int(settings.get("image_ai_min_score") or 72)))
    teams = [str(value) for value in item.get("match_teams") or [] if str(value).strip()]
    inferred_subject, _inferred_action = _scene_match_action(item, teams)
    subject = str(item.get("main_subject") or inferred_subject or "").strip()
    sentence = str(item.get("sentence_text") or "").strip()
    keyword = str(item.get("keyword") or "").strip()
    action = str(item.get("action_context") or "").strip()
    required_person = (
        subject
        if len(subject.split()) >= 2
        and " and " not in subject.lower()
        and not subject.lower().endswith((" players", " team", " squad"))
        and not any(subject.lower() == team.lower() for team in teams)
        else ""
    )
    parts: list[dict] = [
        {
            "text": (
                "You are a strict visual editor selecting real sports photography for one narration scene. "
                "Evaluate every candidate image itself, not just its filename. Reject an image when the requested "
                "named person is absent or a different player is shown, when it is a different match/team/event, "
                "or when it is a thumbnail, poster, graphic, collage, scoreboard, logo, or low-information image. "
                "For a coach/touchline scene, the named coach must be visibly present. If a required named person "
                "is absent, accepted MUST be false even if the image broadly supports another sentence. "
                "For an action/celebration "
                "scene, the requested player or clearly relevant teams/action must be visible. Do not infer identity "
                "only from shirt color. When required teams/event are provided, reject club kits, other national "
                "teams, old tournaments, or unrelated matches even when the named player is correct. "
                "Return JSON only: {\"items\":[{\"index\":1,\"accepted\":true,"
                "\"score\":0-100,\"visible_subject\":\"...\",\"reason\":\"...\"}]}. "
                f"Accept only scores >= {minimum_score}.\n"
                f"Scene narration: {sentence}\n"
                f"Required main subject: {subject or 'no single named person'}\n"
                f"Required teams/event: {', '.join(teams) or 'use narration and keyword'}\n"
                f"Required action/context: {action}\n"
                f"Search keyword: {keyword}"
            )
        }
    ]
    included: list[Path] = []
    for index, path in enumerate(candidates[:6], start=1):
        metadata = read_json(path.with_suffix(path.suffix + ".json"), {})
        parts.append(
            {
                "text": (
                    f"Candidate {index}. Source title: {metadata.get('title') or path.stem}. "
                    f"Source page: {metadata.get('page') or ''}"
                )
            }
        )
        mime_type, encoded = _gemini_image_payload(path)
        parts.append({"inline_data": {"mime_type": mime_type, "data": encoded}})
        included.append(path)
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }
    response = None
    model = primary_model
    errors = []
    for candidate_model in models:
        model = candidate_model
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        if response.status_code < 400:
            break
        errors.append(f"{model}: HTTP {response.status_code}")
        if response.status_code not in {429, 500, 502, 503, 504}:
            break
    if response is None or response.status_code >= 400:
        detail = response.text[-500:] if response is not None else "không có response"
        raise RuntimeError(f"Gemini Vision không khả dụng ({', '.join(errors)}): {detail}")
    data = response.json()
    response_parts = ((((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or [])
    content = "".join(str(part.get("text") or "") for part in response_parts)
    parsed = json.loads(content)
    rows = parsed.get("items") if isinstance(parsed, dict) else parsed
    rows = rows if isinstance(rows, list) else []
    decisions: list[tuple[Path, dict]] = []
    for index, path in enumerate(included, start=1):
        row = next((value for value in rows if int(value.get("index") or 0) == index), {})
        score = max(0, min(100, int(row.get("score") or 0)))
        accepted = bool(row.get("accepted")) and score >= minimum_score
        visible_subject = str(row.get("visible_subject") or "")
        metadata = read_json(path.with_suffix(path.suffix + ".json"), {})
        metadata_text = f"{metadata.get('url') or ''} {metadata.get('page') or ''} {metadata.get('title') or ''}".lower()
        if "ytimg.com" in metadata_text or "youtube" in metadata_text:
            accepted = False
            score = min(score, 20)
            row["reason"] = "YouTube thumbnail/graphic bị chặn."
        if required_person:
            required_tokens = [
                token for token in _ascii_words(required_person)
                if len(token) > 2 and token not in STOP_WORDS
            ]
            visible_tokens = set(_ascii_words(f"{visible_subject} {row.get('reason') or ''}"))
            surname = required_tokens[-1] if required_tokens else ""
            if surname and surname not in visible_tokens:
                accepted = False
                score = min(score, 40)
                row["reason"] = (
                    f"Không nhìn thấy đúng người bắt buộc {required_person}. "
                    f"{row.get('reason') or ''}"
                ).strip()
        decision = {
            "accepted": accepted,
            "score": score,
            "visible_subject": visible_subject,
            "reason": str(row.get("reason") or ""),
            "model": model,
        }
        write_json(_vision_sidecar(path), decision)
        if log:
            state = "đạt" if accepted else "loại"
            log(f"{item.get('asset_id')}: Gemini Vision {state} ảnh {index} ({score}/100) - {decision['reason']}")
        decisions.append((path, decision))
    decisions.sort(key=lambda value: int(value[1].get("score") or 0), reverse=True)
    return [value for value in decisions if value[1].get("accepted")]


def _image_dhash(path: Path) -> int | None:
    try:
        from PIL import Image

        resampling = getattr(Image, "Resampling", Image).LANCZOS
        with Image.open(path) as image:
            pixels = list(image.convert("L").resize((9, 8), resampling).getdata())
        value = 0
        for row in range(8):
            offset = row * 9
            for column in range(8):
                value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
        return value
    except Exception:
        return None


def _crawled_image_rejection_summary(folder: Path, settings: dict | None = None) -> str:
    from PIL import Image

    options = _image_filter_settings(settings)
    total = 0
    small = 0
    wrong_ratio = 0
    samples = []
    for path in folder.rglob("*"):
        if not path.is_file() or path.stat().st_size < 2048:
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except Exception:
            continue
        total += 1
        ratio = width / max(1, height)
        if width < int(options["min_width"]) or height < int(options["min_height"]):
            small += 1
        elif abs(ratio - float(options["aspect"])) > float(options["tolerance"]):
            wrong_ratio += 1
        if len(samples) < 4:
            samples.append(f"{width}x{height}={ratio:.3f}")
    if total <= 0:
        return "không tải được file ảnh nào"
    parts = [f"{total} ảnh"]
    if wrong_ratio:
        parts.append(f"{wrong_ratio} sai tỉ lệ 16:9")
    if small:
        parts.append(f"{small} quá nhỏ")
    if samples:
        parts.append("mau " + ", ".join(samples))
    return "; ".join(parts)


def _enhance_image_without_crop(source: Path, target: Path, settings: dict | None = None) -> tuple[int, int]:
    from PIL import Image, ImageEnhance, ImageFilter

    options = _image_filter_settings(settings)
    with Image.open(source) as image:
        image = image.convert("RGB")
        if not _is_target_aspect(int(image.width), int(image.height), settings):
            raise RuntimeError(f"Ảnh không đúng 16:9: {image.width}x{image.height}")
        target_width = int(options["target_width"])
        target_height = int(options["target_height"])
        target_ratio = target_width / target_height
        image_ratio = image.width / image.height
        if abs(image_ratio - target_ratio) > float(options["tolerance"]):
            target_height = int(round(target_width / image_ratio))
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        if image.width != target_width or image.height != target_height:
            image = image.resize((target_width, target_height), resampling)
        if bool(options["enhance_enabled"]):
            image = ImageEnhance.Contrast(image).enhance(1.04)
            image = ImageEnhance.Sharpness(image).enhance(1.15)
            image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=130, threshold=3))
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, "JPEG", quality=95, subsampling=0, optimize=True)
        return int(image.width), int(image.height)


def _ai_upscale_if_configured(source: Path, work_dir: Path, settings: dict | None = None) -> Path:
    settings = settings or {}
    if not bool(settings.get("image_ai_upscale_enabled", False)):
        return source
    exe_path = Path(str(settings.get("realesrgan_exe_path") or ""))
    if not exe_path.exists():
        return source
    output = work_dir / f"{source.stem}_realesrgan.png"
    command = [
        str(exe_path),
        "-i",
        str(source),
        "-o",
        str(output),
        "-n",
        str(settings.get("realesrgan_model") or "realesrgan-x4plus"),
        "-s",
        str(int(settings.get("realesrgan_scale") or 2)),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=240, check=False)
        if result.returncode == 0 and output.exists() and output.stat().st_size > 2048:
            return output
    except Exception:
        pass
    return source


def _retry_queries(item: dict, attempt: int) -> list[str]:
    keyword = _clean_search_keyword(str(item.get("keyword") or "").strip())
    sentence = str(item.get("sentence_text") or "").strip()
    ai_fallbacks = item.get("fallback_keywords") if isinstance(item.get("fallback_keywords"), list) else []
    ai_fallbacks = [_clean_search_keyword(str(value).strip()) for value in ai_fallbacks if str(value).strip()]
    local_fallbacks = _local_getty_keywords(sentence)
    queries = [keyword, *ai_fallbacks, *local_fallbacks]
    queries = [
        query for query in queries
        if query and not _is_generic_keyword(query, sentence)
    ]
    deduped = list(dict.fromkeys(queries))
    if attempt <= 1:
        return deduped[:6]
    rotated = deduped[1:] + deduped[:1]
    return rotated[:6] or deduped[:6]


def _source_queries(item: dict, key: str, fallback: list[str]) -> list[str]:
    values = item.get(key) if isinstance(item.get(key), list) else []
    values = [_clean_search_keyword(str(value)) for value in values if _clean_search_keyword(str(value))]
    values.extend(fallback)
    values.extend(_retry_queries(item, 1))
    concise = [_concise_match_query(value, item) for value in values if value]
    return list(dict.fromkeys(value for value in concise if value))[:4]


def _concise_match_query(value: str, item: dict) -> str:
    query = _clean_search_keyword(value)
    if not query:
        return ""
    removable_phrases = (
        "players competing", "match action", "game action", "editorial photography",
        "editorial photo", "editoria photo", "sports photography", "real photo",
        "after final whistle", "team lineup match",
    )
    for phrase in removable_phrases:
        query = re.sub(rf"\b{re.escape(phrase)}\b", " ", query, flags=re.I)
    banned_words = (
        "thumbnail", "poster", "wallpaper", "graphic", "logo", "badge", "training",
        "portrait", "preview", "highlights", "reaction", "photo", "editorial", "ed",
    )
    query = " ".join(
        word for word in query.split()
        if word.lower() not in banned_words and not word.lower().startswith("editori")
    )
    query = re.sub(r"\s+", " ", query).strip()
    words = query.split()
    if len(words) > 9:
        query = " ".join(words[:9])
    return query[:120]


def _match_photo_query(value: str, item: dict) -> str:
    return _concise_match_query(value, item)


def _is_match_photography_item(item: dict) -> bool:
    source_type = str(item.get("visual_source_type") or "").strip().lower()
    if source_type == "match_photography":
        return True
    text = " ".join(
        str(item.get(key) or "")
        for key in ("sentence_text", "action_context", "visual_intent", "keyword")
    ).lower()
    match_terms = (
        " vs ", "match", "goal", "scoring", "equaliz", "victory", "defeat",
        "minute", "half-time", "halftime", "penalty area", "comeback", "substitution",
    )
    return sum(term in text for term in match_terms) >= 2


def _safe_download_ext(url: str, content_type: str = "") -> str:
    suffix = Path(urlparse(str(url or "")).path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    return ".jpg"


def _download_image_url(url: str, folder: Path, index: int, prefix: str) -> Path | None:
    import requests

    if not str(url or "").startswith("http"):
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/145 Safari/537.36",
    }
    try:
        response = requests.get(url, headers=headers, timeout=18)
        if response.status_code != 200:
            return None
        content_type = response.headers.get("content-type", "").lower()
        if content_type and not content_type.startswith("image/"):
            return None
        data = response.content
        if len(data) < 2048:
            return None
        ext = _safe_download_ext(url, content_type)
        path = folder / f"{prefix}_{index:04d}{ext}"
        path.write_bytes(data)
        return path
    except Exception:
        return None


def _fetch_sportsdb_images(folder: Path, queries: list[str], count: int = 10) -> int:
    import requests

    folder.mkdir(parents=True, exist_ok=True)
    endpoints = [
        ("player", "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php?p={query}"),
        ("team", "https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t={query}"),
        ("event", "https://www.thesportsdb.com/api/v1/json/3/searchevents.php?e={query}"),
    ]
    image_keys = (
        "strThumb", "strCutout", "strRender", "strFanart1", "strFanart2", "strFanart3",
        "strFanart4", "strBanner", "strPoster", "strBadge", "strLogo", "strStadiumThumb",
    )
    downloaded = 0
    seen: set[str] = set()
    for query in queries:
        for prefix, template in endpoints:
            if downloaded >= count:
                return downloaded
            try:
                response = requests.get(template.format(query=quote_plus(query)), timeout=15)
                if response.status_code != 200:
                    continue
                data = response.json()
            except Exception:
                continue
            rows = []
            for value in data.values():
                if isinstance(value, list):
                    rows.extend(row for row in value if isinstance(row, dict))
            for row in rows:
                for key in image_keys:
                    url = str(row.get(key) or "")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    if _download_image_url(url, folder, downloaded + 1, prefix):
                        downloaded += 1
                        if downloaded >= count:
                            return downloaded
    return downloaded


def _fetch_wikimedia_images(folder: Path, queries: list[str], count: int = 10) -> int:
    import requests

    folder.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    seen: set[str] = set()
    for query in queries:
        if downloaded >= count:
            break
        try:
            response = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrnamespace": 6,
                    "gsrsearch": query,
                    "gsrlimit": 12,
                    "prop": "imageinfo",
                    "iiprop": "url|mime|size|extmetadata",
                    "iiurlwidth": 1920,
                },
                timeout=18,
            )
            if response.status_code != 200:
                continue
            pages = ((response.json().get("query") or {}).get("pages") or {}).values()
        except Exception:
            continue
        for page in pages:
            infos = page.get("imageinfo") if isinstance(page, dict) else None
            if not infos:
                continue
            info = infos[0]
            mime = str(info.get("mime") or "")
            if not mime.startswith("image/"):
                continue
            meta = info.get("extmetadata") or {}
            license_short = str((meta.get("LicenseShortName") or {}).get("value") or "")
            if license_short and "fair use" in license_short.lower():
                continue
            url = str(info.get("thumburl") or info.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            if _download_image_url(url, folder, downloaded + 1, "commons"):
                downloaded += 1
                if downloaded >= count:
                    return downloaded
    return downloaded


def _fetch_google_images(
    project: Path,
    folder: Path,
    queries: list[str],
    count: int = 12,
    excluded_urls: set[str] | None = None,
    excluded_dhashes: set[int] | None = None,
    skip_results: int = 0,
) -> int:
    worker_path = Path(__file__).with_name("google_images_worker.py")
    downloaded = 0
    target_count = max(1, min(6, int(count)))
    for query_index, query in enumerate(queries[:4], start=1):
        if downloaded >= target_count:
            break
        query_target = min(2, target_count - downloaded)
        query_dir = folder / f"google_{query_index:02d}"
        query_dir.mkdir(parents=True, exist_ok=True)
        run_logs = []
        for worker_attempt in range(2):
            request_path = query_dir / f"_request_{worker_attempt + 1}.json"
            profile_path = (
                ""
                if worker_attempt == 0
                else str(Path(__file__).resolve().parents[1] / "chrome_google_images_profile")
            )
            write_json(
                request_path,
                {
                    "query": query,
                    "output": str(query_dir),
                    "count": query_target,
                    "profile": profile_path,
                    "headed": True,
                    "exclude_urls": sorted(excluded_urls or set()),
                    "exclude_dhashes": sorted(excluded_dhashes or set()),
                    "skip_results": skip_results + worker_attempt,
                },
            )
            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(worker_path),
                        "--request-json",
                        str(request_path),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=70,
                    check=False,
                )
                run_logs.append(
                    f"attempt={worker_attempt + 1} returncode={result.returncode}\n"
                    f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                )
            except Exception as exc:
                run_logs.append(f"attempt={worker_attempt + 1} error={exc}")
            image_files = [
                path
                for path in query_dir.glob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ]
            if len(image_files) >= query_target:
                break
            time.sleep(0.7)
        (query_dir / "_worker.log").write_text("\n\n".join(run_logs), encoding="utf-8")
        downloaded += len(
            [
                path
                for path in query_dir.glob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ]
        )
    return downloaded


def crawl_image_candidates(
    project: Path,
    item: dict,
    attempt: int,
    count: int = 6,
    settings: dict | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[Path, int, str, dict]:
    attempt_dir = project / "assets" / "candidates" / str(item["asset_id"]) / f"attempt_{attempt:02d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    excluded_hashes = {
        str(value).strip()
        for value in item.get("rejected_hashes") or []
        if str(value).strip()
    }
    excluded_dhashes = {
        int(value)
        for value in item.get("rejected_dhashes") or []
        if str(value).strip()
    }
    excluded_urls = {
        str(value).strip()
        for value in item.get("rejected_urls") or []
        if str(value).strip()
    }
    for existing in load_manifest(project):
        if str(existing.get("asset_id") or "") == str(item.get("asset_id") or ""):
            continue
        digest = str(existing.get("sha256") or "").strip()
        if digest:
            excluded_hashes.add(digest)
        existing_path_text = str(existing.get("local_path") or "").strip()
    errors: list[str] = []

    match_photography = _is_match_photography_item(item)
    sportsdb_queries = _source_queries(item, "sportsdb_queries", [])
    google_queries = _source_queries(item, "google_queries", [])
    if match_photography:
        google_queries = [
            _match_photo_query(query, item)
            for query in google_queries
            if _match_photo_query(query, item)
        ]
        match_teams = [str(value) for value in item.get("match_teams") or [] if str(value).strip()]
        scene_subject, scene_action = _scene_match_action(item, match_teams)
        if scene_subject:
            context_word = "coach touchline" if "coach touchline" in scene_action else (
                "celebration" if "goal celebration" in scene_action else "match action"
            )
            focused_query = _concise_match_query(
                " ".join(
                    value
                    for value in (
                        scene_subject,
                        match_teams[0] if match_teams else "",
                        context_word,
                    )
                    if value
                ),
                item,
            )
            if focused_query and focused_query not in google_queries:
                google_queries = [google_queries[0], focused_query, *google_queries[1:]]
        tiers = [
            (
                "Google match photography",
                "google_match",
                google_queries,
                2,
                lambda folder, queries: _fetch_google_images(
                    project,
                    folder,
                    queries,
                    count=6,
                    excluded_urls=excluded_urls,
                    excluded_dhashes=excluded_dhashes,
                    skip_results=0,
                ),
            ),
        ]
    else:
        tiers = [
            ("TheSportsDB", "sportsdb", sportsdb_queries, 0, lambda folder, queries: _fetch_sportsdb_images(folder, queries, count=max(8, int(count)))),
            (
                "Google Images",
                "google",
                google_queries,
                2,
                lambda folder, queries: _fetch_google_images(
                    project,
                    folder,
                    queries,
                    count=6,
                    excluded_urls=excluded_urls,
                    excluded_dhashes=excluded_dhashes,
                    skip_results=0,
                ),
            ),
        ]
    for source_name, folder_name, queries, min_score, fetcher in tiers:
        if not queries:
            continue
        source_dir = attempt_dir / folder_name
        downloaded = fetcher(source_dir, queries)
        query_text = queries[0]
        effective_min_score = (
            0
            if match_photography
            and bool((settings or {}).get("image_ai_validation_enabled", True))
            and bool(str((settings or {}).get("gemini_api_key") or "").strip())
            else min_score
        )
        candidates = _valid_crawled_images(
            source_dir,
            excluded_hashes,
            excluded_dhashes,
            query=query_text,
            settings=settings,
            min_keyword_score=effective_min_score,
        )
        if candidates:
            ranked = _rank_images_with_gemini(candidates, item, settings, log=log)
            if not ranked:
                errors.append(f"{source_name}: Gemini Vision loại tất cả {len(candidates)} ảnh")
                continue
            candidate, vision_decision = ranked[0]
            metadata_path = candidate.with_suffix(candidate.suffix + ".json")
            metadata = read_json(metadata_path, {}) if metadata_path.exists() else {}
            metadata["vision"] = vision_decision
            return candidate, len(candidates), f"{source_name}: {query_text}", metadata
        rejection_summary = _crawled_image_rejection_summary(source_dir, settings=settings)
        errors.append(f"{source_name} tải {downloaded} file nhưng không có ảnh 16:9 hợp lệ ({rejection_summary})")
    raise RuntimeError("Không tìm được ảnh mới. " + "; ".join(errors[-3:]))


def search_and_download_asset(
    project: Path,
    item: dict,
    log: Callable[[str], None],
    settings: dict | None = None,
    reject_current: bool = False,
) -> dict:
    if reject_current:
        rejected_hashes = {
            str(value).strip() for value in item.get("rejected_hashes") or [] if str(value).strip()
        }
        rejected_dhashes = {
            int(value) for value in item.get("rejected_dhashes") or [] if str(value).strip()
        }
        rejected_urls = {
            str(value).strip() for value in item.get("rejected_urls") or [] if str(value).strip()
        }
        for key in ("sha256", "raw_sha256"):
            digest = str(item.get(key) or "").strip()
            if digest:
                rejected_hashes.add(digest)
        for key in ("local_path", "raw_local_path", "candidate_path"):
            path_text = str(item.get(key) or "").strip()
            path = Path(path_text) if path_text else None
            if path and path.is_file():
                rejected_hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
                perceptual = _image_dhash(path)
                if perceptual is not None:
                    rejected_dhashes.add(perceptual)
        for key in ("source_url", "candidate_source_url"):
            source_url = str(item.get(key) or "").strip()
            if source_url:
                rejected_urls.add(source_url)
        item["rejected_hashes"] = sorted(rejected_hashes)
        item["rejected_dhashes"] = sorted(rejected_dhashes)
        item["rejected_urls"] = sorted(rejected_urls)
        item["rejected_current_path"] = str(item.get("local_path") or "")
        log(
            f"{item['asset_id']}: đã gắn cờ ảnh cũ "
            f"({len(rejected_dhashes)} perceptual hash, {len(rejected_urls)} URL bị chặn)."
        )
    if _is_match_photography_item(item):
        concise_keyword = _concise_match_query(str(item.get("keyword") or ""), item)
        if concise_keyword:
            item["keyword"] = concise_keyword
            item["ai_search_keyword"] = concise_keyword
        existing_queries = item.get("google_queries") if isinstance(item.get("google_queries"), list) else []
        concise_queries = [
            _concise_match_query(str(value), item)
            for value in [concise_keyword, *existing_queries]
        ]
        item["google_queries"] = list(dict.fromkeys(value for value in concise_queries if value))[:4]
    attempt = int(item.get("search_attempt") or 0) + 1
    try:
        candidate, candidate_count, matched_query, candidate_metadata = crawl_image_candidates(
            project, item, attempt, settings=settings, log=log
        )
        suffix = candidate.suffix.lower() if candidate.suffix.lower() in IMAGE_SUFFIXES else ".jpg"
        downloads_dir = project / "assets" / "downloads"
        raw_dir = downloads_dir / "raw"
        raw_target = raw_dir / f"{item['asset_id']}{suffix}"
        target = downloads_dir / f"{item['asset_id']}_16x9.jpg"
        for old_path in list(downloads_dir.glob(f"{item['asset_id']}.*")) + list(raw_dir.glob(f"{item['asset_id']}.*")):
            if old_path.is_file():
                old_path.unlink(missing_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, raw_target)
        upscale_source = _ai_upscale_if_configured(raw_target, raw_dir, settings=settings)
        width, height = _enhance_image_without_crop(upscale_source, target, settings=settings)
        item.update(
            {
                "search_attempt": attempt,
                "status": "downloaded",
                "source_url": "",
                "source_page": matched_query,
                "candidate_source_url": str(candidate_metadata.get("url") or ""),
                "candidate_source_page": str(candidate_metadata.get("page") or ""),
                "candidate_source_title": str(candidate_metadata.get("title") or ""),
                "image_ai_validation": candidate_metadata.get("vision") or {},
                "thumbnail_url": "",
                "local_path": str(target),
                "raw_local_path": str(raw_target),
                "upscale_source_path": str(upscale_source),
                "candidate_path": str(candidate),
                "candidate_count": candidate_count,
                "matched_query": matched_query,
                "image_width": width,
                "image_height": height,
                "image_processing": "16:9-filtered,no-crop,optional-realesrgan,resize-sharpen",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "raw_sha256": hashlib.sha256(raw_target.read_bytes()).hexdigest(),
                "error": "",
            }
        )
        log(f"{item['asset_id']}: tải {candidate_count} ảnh 16:9 bằng {matched_query}, chọn {target.name} ({width}x{height})")
    except Exception as exc:
        old_path_text = str(item.get("local_path") or "").strip()
        old_path = Path(old_path_text) if old_path_text else None
        reusable = None
        if (
            not reject_current
            and not (old_path and old_path.is_file())
            and _is_match_photography_item(item)
            and not bool((settings or {}).get("image_ai_validation_enabled", True))
        ):
            match_teams = {str(value).lower() for value in item.get("match_teams") or [] if str(value).strip()}
            for existing in load_manifest(project):
                existing_path_text = str(existing.get("local_path") or "").strip()
                existing_path = Path(existing_path_text) if existing_path_text else None
                existing_teams = {
                    str(value).lower() for value in existing.get("match_teams") or [] if str(value).strip()
                }
                if (
                    str(existing.get("asset_id") or "") != str(item.get("asset_id") or "")
                    and existing_path
                    and existing_path.is_file()
                    and (not match_teams or existing_teams == match_teams)
                ):
                    reusable = (existing, existing_path)
                    break
        if reusable:
            existing, existing_path = reusable
            downloads_dir = project / "assets" / "downloads"
            target = downloads_dir / f"{item['asset_id']}_16x9.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(existing_path, target)
            width, height = _image_size(target)
            item.update(
                {
                    "search_attempt": attempt,
                    "status": "downloaded",
                    "source_page": f"Reused from {existing.get('asset_id')}",
                    "local_path": str(target),
                    "candidate_path": str(existing_path),
                    "matched_query": f"Reused same-match image from {existing.get('asset_id')}",
                    "image_width": width,
                    "image_height": height,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "reused_from_asset": str(existing.get("asset_id") or ""),
                    "error": f"Không có ảnh 16:9 mới; đã dùng lại ảnh dùng tràn. {exc}",
                }
            )
            log(f"{item['asset_id']}: không có ảnh 16:9 mới, dùng lại ảnh dùng tràn từ {existing.get('asset_id')}.")
            return item
        item.update(
            {
                "search_attempt": attempt,
                "status": "error" if reject_current else ("downloaded" if old_path and old_path.is_file() else "error"),
                "local_path": "" if reject_current else str(item.get("local_path") or ""),
                "error": str(exc),
            }
        )
    return item


def _image_size(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 1920, 1080


def _capcut_root() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    return local / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


def _find_capcut_template(capcut_root: Path) -> Path:
    preferred = capcut_root / "test-export"
    bundled = Path(__file__).resolve().parents[1] / "capcut_template"
    capcut_candidates = [
        path for path in capcut_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ] if capcut_root.exists() else []
    portable_candidates = sorted(
        {
            path.parent
            for path in (Path(__file__).resolve().parents[1] / "Projects").rglob("draft_content.json")
            if (path.parent / "draft_meta_info.json").is_file()
        },
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    candidates = [preferred, *capcut_candidates, bundled, *portable_candidates]
    for candidate in candidates:
        if (candidate / "draft_content.json").exists() and (candidate / "draft_meta_info.json").exists():
            content = read_json(candidate / "draft_content.json", {})
            tracks = {str(track.get("type")): track for track in content.get("tracks") or []}
            materials = content.get("materials") or {}
            if (
                {"video", "audio"}.issubset(tracks)
                and tracks["video"].get("segments")
                and tracks["audio"].get("segments")
                and materials.get("videos")
                and materials.get("audios")
            ):
                return candidate
    raise FileNotFoundError(
        "Không tìm thấy draft CapCut hợp lệ trong CapCut hoặc Projects. "
        "Hãy tạo một project CapCut rỗng có 1 ảnh và 1 audio để làm template."
    )


CAPCUT_TIMELINE_ATTACHMENT_DEFAULTS = {
    "attachment_action_scene.json": {
        "action_scene": {"removed_segments": [], "segment_infos": []},
    },
    "attachment_gen_ai_info.json": {
        "gen_ai": {
            "ai_func_config": {
                "ai_common_configs": [],
                "ai_effect_configs": [],
                "ai_func_list": [],
                "aigc_generation_configs": [],
            },
            "cc_agent_info": {
                "agent_stringent_section_id_list": [],
                "agent_stringent_used_tool_list": [],
                "is_agent_stringent_used": False,
                "is_agent_used": False,
                "tool_list": [],
            },
            "id": "",
            "scene": "",
            "version": "1.0.0",
        },
    },
    "attachment_pc_timeline.json": {
        "reference_lines_config": {
            "horizontal_lines": [],
            "is_lock": False,
            "is_visible": False,
            "vertical_lines": [],
        },
        "safe_area_type": 0,
    },
    "attachment_plugin_draft.json": {
        "plugin_draft": {"plugin_segments": [], "version": "1.0.0"},
    },
    "attachment_script_video.json": {
        "script_video": {
            "attachment_valid": False,
            "language": "",
            "overdub_recover": [],
            "overdub_sentence_ids": [],
            "parts": [],
            "sync_subtitle": False,
            "translate_segments": [],
            "translate_type": "",
            "version": "1.0.0",
        },
    },
}


def _copy_file_with_retry(source: str, target: str, *, follow_symlinks: bool = True) -> str:
    last_error = None
    for attempt in range(12):
        try:
            return shutil.copy2(source, target, follow_symlinks=follow_symlinks)
        except FileNotFoundError as exc:
            last_error = exc
            time.sleep(0.15 * (attempt + 1))
    if last_error:
        raise last_error
    return target


def _ensure_capcut_timeline_attachments(draft: Path) -> None:
    timelines = draft / "Timelines"
    if not timelines.exists():
        return
    for timeline in timelines.iterdir():
        if not timeline.is_dir():
            continue
        attachment_dir = timeline / "common_attachment"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        for filename, default_data in CAPCUT_TIMELINE_ATTACHMENT_DEFAULTS.items():
            path = attachment_dir / filename
            if not path.is_file():
                write_json(path, default_data)


def _copy_capcut_template_snapshot(template: Path, portable: Path) -> None:
    last_error = None
    for attempt in range(4):
        if portable.exists():
            shutil.rmtree(portable)
        try:
            shutil.copytree(
                template,
                portable,
                copy_function=_copy_file_with_retry,
                ignore=lambda _folder, names: {
                    name for name in names if name in {"Timelines", "common_attachment"}
                },
            )
            return
        except (FileNotFoundError, shutil.Error, OSError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"Không copy được draft CapCut mẫu sau 4 lần thử: {last_error}")


def _slash_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _meta_material_item(media_path: Path, *, material_id: str, metetype: str, duration: int, width: int = 0, height: int = 0) -> dict:
    now = _now()
    return {
        "ai_group_type": "",
        "create_time": now,
        "duration": int(duration),
        "enter_from": 0,
        "extra_info": media_path.name,
        "file_Path": _slash_path(media_path),
        "height": int(height),
        "id": material_id.lower(),
        "import_time": now,
        "import_time_ms": int(time.time() * 1_000_000),
        "item_source": 1,
        "md5": "",
        "metetype": metetype,
        "roughcut_time_range": {"duration": int(duration) if metetype == "music" else -1, "start": 0 if metetype == "music" else -1},
        "sub_time_range": {"duration": -1, "start": -1},
        "type": 0,
        "width": int(width),
    }


def _build_draft_materials(video_materials: list[dict], audio_materials: list[dict]) -> list[dict]:
    values = []
    for audio in audio_materials:
        path = Path(str(audio.get("path") or ""))
        values.append(
            _meta_material_item(
                path,
                material_id=str(audio.get("local_material_id") or audio.get("id") or _uuid()),
                metetype="music",
                duration=int(audio.get("duration") or 0),
            )
        )
    for video in video_materials:
        path = Path(str(video.get("path") or ""))
        values.append(
            _meta_material_item(
                path,
                material_id=str(video.get("local_material_id") or video.get("id") or _uuid()),
                metetype="photo" if str(video.get("type") or "") == "photo" else "video",
                duration=5_000_000,
                width=int(video.get("width") or 0),
                height=int(video.get("height") or 0),
            )
        )
    return [{"type": 0, "value": values}, {"type": 1, "value": []}, {"type": 2, "value": []}, {"type": 3, "value": []}, {"type": 6, "value": []}, {"type": 7, "value": []}, {"type": 8, "value": []}]


def _material_id_index(materials: dict) -> dict[str, tuple[str, dict]]:
    index: dict[str, tuple[str, dict]] = {}
    for category, values in materials.items():
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, dict) and value.get("id"):
                index[str(value["id"])] = (category, value)
    return index


def _reset_material_lists(materials: dict) -> None:
    for key, value in list(materials.items()):
        if isinstance(value, list):
            materials[key] = []


def _clone_extra_material_refs(segment: dict, source_index: dict[str, tuple[str, dict]], target_materials: dict) -> None:
    refs = []
    for old_id in list(segment.get("extra_material_refs") or []):
        found = source_index.get(str(old_id))
        if not found:
            continue
        category, source = found
        cloned = copy.deepcopy(source)
        new_id = _uuid()
        cloned["id"] = new_id
        target_materials.setdefault(category, []).append(cloned)
        refs.append(new_id)
    segment["extra_material_refs"] = refs


def export_capcut_project(project: Path, title: str, install_to_capcut: bool = True) -> Path:
    items = [item for item in load_manifest(project) if Path(str(item.get("local_path") or "")).exists()]
    if not items:
        raise RuntimeError("Chưa có asset đã tải để dùng CapCut.")
    voice = project / "voices" / "voice.wav"
    if not voice.exists():
        raise FileNotFoundError(f"Thiếu voice: {voice}")

    capcut_root = _capcut_root()
    template = _find_capcut_template(capcut_root)
    draft_name = f"{time.strftime('%m%d-%H%M')}-{_safe_name(title, 'visual')}"[:80]
    portable = project / "capcut" / draft_name
    _copy_capcut_template_snapshot(template, portable)

    content = read_json(portable / "draft_content.json", {})
    meta = read_json(portable / "draft_meta_info.json", {})
    source_material_index = _material_id_index(content.get("materials") or {})
    draft_id = _uuid()
    voice_duration = probe_duration(voice) or max(float(item["end"]) for item in items)
    duration_seconds = max(max(float(item["end"]) for item in items), voice_duration)
    duration_us = _microseconds(duration_seconds)
    tracks = {str(track.get("type")): track for track in content.get("tracks") or []}
    video_track = tracks["video"]
    audio_track = tracks["audio"]
    video_segment_template = copy.deepcopy(video_track["segments"][0])
    audio_segment_template = copy.deepcopy(audio_track["segments"][0])
    video_material_template = copy.deepcopy(content["materials"]["videos"][0])
    audio_material_template = copy.deepcopy(content["materials"]["audios"][0])
    _reset_material_lists(content.setdefault("materials", {}))

    video_segments = []
    video_materials = []
    for index, item in enumerate(items):
        media_path = Path(str(item["local_path"]))
        visual_start = 0.0 if index == 0 else float(item["start"])
        visual_end = (
            float(items[index + 1]["start"])
            if index + 1 < len(items)
            else voice_duration
        )
        visual_duration = max(0.05, visual_end - visual_start)
        material_id = _uuid()
        segment = copy.deepcopy(video_segment_template)
        segment.update(
            {
                "id": _uuid(),
                "material_id": material_id,
                "source_timerange": {"start": 0, "duration": _microseconds(visual_duration)},
                "target_timerange": {"start": _microseconds(visual_start), "duration": _microseconds(visual_duration)},
            }
        )
        _clone_extra_material_refs(segment, source_material_index, content["materials"])
        if isinstance(segment.get("clip"), dict):
            segment["clip"]["scale"] = {"x": 1.0, "y": 1.0}
            segment["clip"]["transform"] = {"x": 0.0, "y": 0.0}
        material = copy.deepcopy(video_material_template)
        width, height = _image_size(media_path)
        material.update(
            {
                "id": material_id,
                "local_id": material_id.lower(),
                "local_material_id": material_id.lower(),
                "type": "photo" if media_path.suffix.lower() in IMAGE_SUFFIXES else "video",
                "path": _slash_path(media_path),
                "material_name": media_path.name,
                "duration": _microseconds(visual_duration) if media_path.suffix.lower() in VIDEO_SUFFIXES else 10_800_000_000,
                "width": width,
                "height": height,
            }
        )
        video_segments.append(segment)
        video_materials.append(material)

    audio_material_id = _uuid()
    audio_segment = copy.deepcopy(audio_segment_template)
    audio_segment.update(
        {
            "id": _uuid(),
            "material_id": audio_material_id,
            "source_timerange": {"start": 0, "duration": _microseconds(voice_duration)},
            "target_timerange": {"start": 0, "duration": _microseconds(voice_duration)},
        }
    )
    _clone_extra_material_refs(audio_segment, source_material_index, content["materials"])
    audio_material = copy.deepcopy(audio_material_template)
    audio_material.update(
        {
            "id": audio_material_id,
            "local_material_id": audio_material_id.lower(),
            "music_id": _uuid(),
            "name": voice.name,
            "path": _slash_path(voice),
            "duration": _microseconds(voice_duration),
        }
    )

    video_track["segments"] = video_segments
    audio_track["segments"] = [audio_segment]
    content["tracks"] = [video_track, audio_track]
    content["materials"]["videos"] = video_materials
    content["materials"]["audios"] = [audio_material]
    content.update(
        {
            "id": draft_id,
            "name": draft_name,
            "duration": max(duration_us, _microseconds(voice_duration)),
            "create_time": _now(),
            "update_time": _now(),
            "path": "",
        }
    )
    content["canvas_config"] = {"ratio": "16:9", "width": 1920, "height": 1080, "background": None}

    meta.update(
        {
            "draft_id": draft_id,
            "draft_name": draft_name,
            "draft_fold_path": str(portable),
            "draft_duration": content["duration"],
            "tm_duration": content["duration"],
            "draft_timeline_materials_size_": sum(Path(str(m.get("path") or "")).stat().st_size for m in video_materials + [audio_material] if Path(str(m.get("path") or "")).exists()),
            "draft_create_time": _now(),
            "draft_update_time": _now(),
            "draft_materials": _build_draft_materials(video_materials, [audio_material]),
        }
    )
    write_json(portable / "draft_content.json", content)
    write_json(portable / "draft_meta_info.json", meta)

    if not install_to_capcut:
        return portable
    installed = capcut_root / draft_name
    if installed.exists():
        shutil.rmtree(installed)
    shutil.copytree(portable, installed)
    installed_meta = read_json(installed / "draft_meta_info.json", {})
    installed_meta["draft_fold_path"] = str(installed)
    write_json(installed / "draft_meta_info.json", installed_meta)
    _register_capcut_draft(capcut_root, installed_meta)
    return installed


def _register_capcut_draft(capcut_root: Path, draft_meta: dict) -> None:
    root_meta_path = capcut_root / "root_meta_info.json"
    root_meta = read_json(root_meta_path, {"all_draft_store": []})
    stores = root_meta.setdefault("all_draft_store", [])
    draft_id = str(draft_meta.get("draft_id") or "")
    stores[:] = [item for item in stores if str(item.get("draft_id") or "") != draft_id]
    stores.insert(0, copy.deepcopy(draft_meta))
    backup = root_meta_path.with_suffix(".json.visual-pipeline.bak")
    if root_meta_path.exists() and not backup.exists():
        shutil.copy2(root_meta_path, backup)
    write_json(root_meta_path, root_meta)
