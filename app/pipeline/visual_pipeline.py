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
import uuid
import unicodedata
from pathlib import Path
from typing import Callable
from urllib.parse import quote_plus, urlparse

from ..voice.text_to_voice_queue import TextToVoiceRunner
from .subtitle_store import load_subtitle, save_subtitle

from keyword_engine import domain_pack as _dp


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
_VISION_QUOTA_PAUSE_UNTIL = 0.0
_AI_PROVIDER_PAUSE_UNTIL: dict[str, float] = {"gemini": 0.0, "claude": 0.0, "kiro": 0.0}

_AI_PROVIDER_LABELS = {"kiro": "Kiro", "openai": "OpenAI", "claude": "Claude", "gemini": "Gemini"}

# Tokens that mark a provider error as a quota/billing problem rather than a
# transient or request bug. Such errors mean the user must top up credit or
# switch provider, so we surface a clear message and pause the provider.
_AI_QUOTA_ERROR_TOKENS = (
    "billing", "insufficient", "quota", "out of credit", "no credit",
    "payment", "exceeded", "balance",
)


def _is_quota_error(status: int, body: str) -> bool:
    if status in (402, 429):
        return True
    lowered = str(body or "").lower()
    return any(token in lowered for token in _AI_QUOTA_ERROR_TOKENS)


def _ai_provider_error(provider: str, status: int, body: str) -> RuntimeError:
    """Build a clear, actionable error for a failed AI HTTP call. Quota/billing
    failures get a localized hint to top up or switch provider instead of the
    raw server blob, which the UI surfaces verbatim to the user."""
    label = _AI_PROVIDER_LABELS.get(provider, provider or "AI")
    detail = str(body or "")[-300:]
    if _is_quota_error(status, body):
        return RuntimeError(
            f"{label} từ chối vì hết quota hoặc lỗi thanh toán (HTTP {status}). "
            f"Hãy nạp thêm credit cho tài khoản {label} hoặc thêm key AI khác trong Cài đặt. "
            f"Chi tiết: {detail}"
        )
    return RuntimeError(f"{label} API lỗi {status}: {str(body or '')[-600:]}")


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
    try:
        import soundfile as sf

        info = sf.info(str(path))
        if info.samplerate and info.frames:
            return max(0.0, float(info.frames) / float(info.samplerate))
    except Exception:
        pass
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


def _replace_file_windows(source: Path, target: Path, retries: int = 60, delay: float = 0.5) -> None:
    """Replace target with source on Windows, tolerating file-in-use locks (WinError 5/32).

    Strategy per attempt:
      1. Try direct copy2 over target (works when reader opened with write-share).
      2. If that fails, unlink target then copy2 (works when target is deletable).
      3. Retry up to `retries` times with `delay` seconds between attempts.
    Source is cleaned up via the caller's finally block if it can't be deleted here.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        # Strategy 1: overwrite in-place (avoids needing delete rights on target).
        try:
            shutil.copy2(str(source), str(target))
            source.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            last_exc = exc

        # Strategy 2: delete target first, then copy.
        try:
            target.unlink(missing_ok=True)
            shutil.copy2(str(source), str(target))
            source.unlink(missing_ok=True)
            return
        except PermissionError as exc:
            last_exc = exc

        time.sleep(delay)
    raise PermissionError(str(last_exc)) from last_exc


def generate_voice(project: Path, settings: dict, log: Callable[[str], None], stop_check=lambda: False) -> Path:
    lines = load_subtitle(project)
    if not lines:
        raise RuntimeError("Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước khi tạo giọng đọc.")
    output_path = project / "voices" / "voice.wav"
    temporary_path = output_path.with_name(f"voice.{uuid.uuid4().hex}.working.wav")
    runner = TextToVoiceRunner(settings, log=log, stop_check=stop_check)
    runner.start()
    try:
        runner.submit_lines(lines, "visual_pipeline", temporary_path)
        if stop_check():
            raise RuntimeError("Stopped.")
        replacements = [
            (temporary_path, output_path),
            (temporary_path.with_suffix(".segments.json"), output_path.with_suffix(".segments.json")),
            (temporary_path.with_suffix(".srt"), output_path.with_suffix(".srt")),
            (temporary_path.with_suffix(".ttv.meta.json"), output_path.with_suffix(".ttv.meta.json")),
        ]
        for source, target in replacements:
            if source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                _replace_file_windows(source, target)
        # Ghi đè timing ước tính trong subtitle.json bằng timing thật vừa đo.
        measured = read_json(output_path.with_suffix(".segments.json"), {})
        measured_segments = measured.get("segments") if isinstance(measured, dict) else None
        if isinstance(measured_segments, list) and measured_segments:
            save_subtitle(project, measured_segments)
        # save_subtitle vừa ghi lại subtitle.json; rename ở trên giữ mtime cũ của file
        # tạm nên voice.wav có thể CŨ HƠN subtitle.json. Bump mtime voice về "now" để
        # voice luôn mới hơn subtitle — nếu không _project_payload coi voice là stale
        # (has_voice=False) và không sang được bước Prompt.
        now = time.time()
        for path in (output_path, output_path.with_suffix(".segments.json"), output_path.with_suffix(".srt")):
            if path.exists():
                os.utime(path, (now, now))
        # A new voice means the old scene/timing-to-asset mapping is no longer
        # trustworthy. Force the next analyze-search run to rebuild scenes.
        (project / "assets" / "asset_manifest.json").unlink(missing_ok=True)
    finally:
        runner.close()
        temporary_path.unlink(missing_ok=True)
        temporary_path.with_suffix(".segments.json").unlink(missing_ok=True)
        temporary_path.with_suffix(".srt").unlink(missing_ok=True)
        temporary_path.with_suffix(".ttv.meta.json").unlink(missing_ok=True)
    return output_path


def voice_signature(project: Path) -> dict[str, int]:
    signature: dict[str, int] = {}
    for key, path in (
        ("voice", project / "voices" / "voice.wav"),
        ("timing", project / "voices" / "voice.segments.json"),
    ):
        if path.exists():
            stat = path.stat()
            signature[f"{key}_mtime_ns"] = int(stat.st_mtime_ns)
            signature[f"{key}_size"] = int(stat.st_size)
        else:
            signature[f"{key}_mtime_ns"] = 0
            signature[f"{key}_size"] = 0
    return signature


def _manifest_matches_current_voice(project: Path, data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    stored = data.get("voice_signature")
    current = voice_signature(project)
    if isinstance(stored, dict):
        return all(int(stored.get(key) or 0) == int(value or 0) for key, value in current.items())
    # Compatibility for older manifests: accept them only while their file is
    # newer than the voice. New voice generation deletes old manifests anyway.
    manifest_path = project / "assets" / "asset_manifest.json"
    voice_path = project / "voices" / "voice.wav"
    if not manifest_path.exists() or not voice_path.exists():
        return False
    return manifest_path.stat().st_mtime_ns >= voice_path.stat().st_mtime_ns


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

    raw_python = str(settings.get("whisper_python") or "").strip()
    python_path = Path(raw_python) if raw_python else Path(sys.executable)
    if not python_path.is_absolute():
        python_path = Path(__file__).resolve().parents[1] / python_path
    if not python_path.is_file():
        if callable(log):
            log(f"Whisper timing: Python đã cấu hình không còn tồn tại, tự dùng {sys.executable}.")
        python_path = Path(sys.executable)
    worker = Path(__file__).parent.parent / "voice" / "whisper_timing_cli.py"
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
    hf_home = str(settings.get("whisper_hf_home") or "").strip()
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


def _timing_needs_repair(segments: list[dict], audio_duration: float) -> tuple[bool, str]:
    if not segments:
        return True, "bị rỗng"
    if audio_duration <= 2.0:
        return False, ""
    starts = [float(item.get("start") or 0.0) for item in segments]
    ends = [float(item.get("end") or 0.0) for item in segments]
    timing_duration = max(ends, default=0.0)
    if timing_duration < audio_duration * 0.7 or timing_duration > audio_duration * 1.3:
        return True, "sai thời lượng"
    gaps = [
        max(0.0, starts[index] - ends[index - 1])
        for index in range(1, len(segments))
    ]
    max_gap = max(gaps, default=0.0)
    # Faster-Whisper can occasionally return one huge silent gap for cloned voices.
    # That breaks scene grouping, so prefer a proportional script estimate.
    if max_gap > max(4.0, audio_duration * 0.18):
        return True, "có khoảng trống timestamp bất thường"
    very_short = sum(1 for item in segments if (float(item.get("end") or 0.0) - float(item.get("start") or 0.0)) < 0.35)
    if len(segments) >= 4 and very_short / len(segments) > 0.45:
        return True, "có quá nhiều câu bị căn dưới 0.35 giây"
    return False, ""


def estimate_timing_from_script(project: Path, timing: dict | None = None) -> dict:
    script_path = project / "scripts" / "script_final.txt"
    audio_path = project / "voices" / "voice.wav"
    script = script_path.read_text(encoding="utf-8", errors="replace").strip()
    sentences = _script_sentences(script)
    if not sentences:
        return timing or {}
    duration = float((timing or {}).get("duration") or 0.0)
    audio_duration = probe_duration(audio_path) if audio_path.exists() else 0.0
    if audio_duration > 0 and (duration <= 0 or duration < audio_duration * 0.7 or duration > audio_duration * 1.3):
        duration = audio_duration
    duration = max(0.5, duration)
    weights = [max(1, len(re.findall(r"\S+", sentence))) for sentence in sentences]
    total_weight = max(1, sum(weights))
    segments: list[dict] = []
    cursor = 0.0
    for index, (sentence, weight) in enumerate(zip(sentences, weights), start=1):
        if index == len(sentences):
            end = duration
        else:
            end = min(duration, cursor + duration * (weight / total_weight))
        end = max(cursor + 0.05, end)
        segments.append(
            {
                "text": sentence,
                "start": round(cursor, 4),
                "end": round(end, 4),
                "duration": round(end - cursor, 4),
                "script_sentence_index": index,
                "timing_source": "estimated_from_script",
            }
        )
        cursor = end
    repaired = dict(timing or {})
    repaired.update(
        {
            "audio": str(audio_path),
            "duration": round(duration, 4),
            "engine": str(repaired.get("engine") or "estimated"),
            "timing_source": "estimated_from_script",
            "segments": segments,
        }
    )
    write_json(project / "voices" / "voice.segments.json", repaired)
    return repaired


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

    if current_duration >= 25.0:
        return "long_scene_guard"
    if current_duration >= 6.0 and (float(sentence["end"]) - current_start) > 25.0:
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
    if current_duration >= 18.0 and overlap < 0.08:
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
    # Build a natural noun phrase: lead with capitalized proper-noun phrases,
    # then append a few salient remaining content words. Google Images favours
    # natural noun phrases over a flat bag-of-words.
    ranked: list[str] = []
    seen: set[str] = set()

    def _add(token: str) -> None:
        key = token.lower()
        if key and key not in seen:
            ranked.append(token)
            seen.add(key)

    for phrase in _capitalized_phrases(text):
        for word in phrase.split():
            if len(ranked) >= 8:
                break
            stripped = re.sub(r"[^A-Za-z0-9]", "", word)
            if len(stripped) > 2 and stripped.lower() not in STOP_WORDS and not stripped.isdigit():
                _add(stripped)

    for word in _ascii_words(text):
        if len(ranked) >= 8:
            break
        if len(word) > 2 and word not in STOP_WORDS and not word.isdigit():
            _add(word)

    return " ".join(ranked[:8]) or "cinematic documentary scene"


def _capitalized_phrases(text: str) -> list[str]:
    ignored = {
        "After", "As", "At", "Before", "For", "From", "He", "His", "In", "It", "Leaving",
        "One", "That", "The", "Their", "They", "This", "Those", "Together", "When",
        "Now", "But", "Every", "What", "With",
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


def _dedupe_query_words(value: str) -> str:
    words: list[str] = []
    seen: set[str] = set()
    for word in str(value or "").split():
        key = re.sub(r"[^A-Za-z0-9-]", "", word).lower()
        if not key or key in STOP_WORDS or key in seen:
            continue
        words.append(word)
        seen.add(key)
    return _clean_search_keyword(" ".join(words))


def _dedupe_query_parts(*values: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_search_keyword(str(value or ""))
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        parts.append(cleaned)
        seen.add(key)
    return _dedupe_query_words(" ".join(parts))


def _is_generic_keyword(value: str, scene_text: str = "") -> bool:
    words = [word for word in _ascii_words(value) if word not in STOP_WORDS]
    if len(words) < 2:
        return True
    specific = [word for word in words if word not in GENERIC_IMAGE_TERMS and len(word) > 2]
    scene_specific = set(_ascii_words(scene_text)) - STOP_WORDS - GENERIC_IMAGE_TERMS
    # A strong scene-specific proper noun rescues short-but-meaningful queries
    # (e.g. "Messi celebration", "Maracana Stadium"): if there are >=2 non-stop
    # words and at least one specific word that also appears in the scene text,
    # the query is NOT generic.
    if len(words) >= 2 and (set(specific) & scene_specific):
        return False
    if len(words) < 3:
        return True
    if len(specific) < 2 and not (set(specific) & scene_specific):
        return True
    return False


def _local_getty_keywords(scene_text: str, pack=None) -> list[str]:
    """Build editorial-style local keywords generically from proper nouns in the
    scene text. No domain literals: extract capitalized phrases, combine the
    strongest 1-2 with a neutral context word, filtered by _is_generic_keyword."""
    text = str(scene_text or "")
    phrases = _capitalized_phrases(text)
    result: list[str] = []

    def add(value: str) -> None:
        cleaned = _clean_search_keyword(value)
        if cleaned and cleaned not in result and not _is_generic_keyword(cleaned, text):
            result.append(cleaned)

    action_hint = _scene_action_hint({"sentence_text": text}, pack)
    context_word = action_hint or "editorial"
    if phrases:
        # Strongest proper-noun phrase + neutral context word.
        add(" ".join([phrases[0], context_word]))
        if len(phrases) >= 2:
            add(" ".join(phrases[:2]))
            add(" ".join([phrases[0], phrases[1], context_word]))
    return result[:6]


def build_asset_manifest(
    project: Path,
    settings: dict | None = None,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    settings = settings or {}
    # The SRT/timing is already produced when the voice is created
    # (voices/voice.segments.json), so use it directly instead of re-running the
    # heavy Whisper alignment. Each SRT sentence becomes one scene; its keyword
    # is generated per sentence and grounded in the project context downstream.
    timing = load_timing(project)
    # SP2: voice generated per subtitle line carries real measured timing; never
    # let Whisper re-alignment or the repair heuristic overwrite it.
    is_measured = str(timing.get("timing_source") or "").lower() == "measured"
    if not is_measured and bool(settings.get("whisper_timing_enabled", False)):
        try:
            timing = refine_timing_with_whisper(project, settings, log=log)
        except Exception as exc:
            if callable(log):
                log(f"Whisper timing lỗi, dùng timing voice hiện tại: {exc}")
    segments = normalize_voice_segments(timing)
    audio_path = project / "voices" / "voice.wav"
    audio_duration = probe_duration(audio_path) if audio_path.exists() else 0.0
    timing_is_invalid, timing_invalid_reason = _timing_needs_repair(segments, audio_duration)
    if timing_is_invalid and not is_measured:
        timing = estimate_timing_from_script(project, timing)
        segments = normalize_voice_segments(timing)
        if segments and callable(log):
            log(f"Timing voice {timing_invalid_reason}, đã tự căn lại theo thời lượng WAV để tiếp tục phân cảnh.")
    if not segments:
        raise RuntimeError("Timing không có câu thoại.")
    if is_measured:
        # SP3: one scene per subtitle line — do not merge lines into sentences.
        sentences = [
            {
                "sentence_index": seg["sentence_index"],
                "text": seg["text"],
                "start": seg["start"],
                "end": seg["end"],
                "segment_indexes": [seg["sentence_index"]],
            }
            for seg in segments
        ]
    else:
        sentences = merge_segments_into_sentences(segments)
    # One scene per SRT sentence (no separate scene-grouping AI round).
    split_mode = "srt_line_scenes" if is_measured else "srt_sentence_scenes"
    assets = [
        _manifest_item(index, [sentence], "opening" if index == 1 else "sentence")
        for index, sentence in enumerate(sentences, start=1)
    ]
    if callable(log):
        log(f"Đã lấy {len(assets)} câu từ SRT giọng đọc để tạo keyword theo từng câu.")
    script_path = project / "scripts" / "script_final.txt"
    script = script_path.read_text(encoding="utf-8", errors="replace").strip()
    video_context = _load_or_build_video_context(project, script, settings, log=log) if script else _build_local_video_context("")
    pack = _resolve_pack(script, video_context, settings=settings, project=project, log=log)
    assets = _apply_script_visual_context(assets, script, video_context, pack)
    manifest_path = project / "assets" / "asset_manifest.json"
    write_json(
        manifest_path,
        {
            "version": 3,
            "voice_signature": voice_signature(project),
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
        r"\bhelp\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b[^.!?]{0,50}\b(?:defeat|beat)\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b[^.!?]{0,30}\b(?:defeat|beat|defeated|beat)\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b[^.!?]{0,100}\bmatch against\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b[^.!?]{0,80}\b(?:defeated|beat|lost to|drew with)\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b[^.!?]{0,100}\b(?:won|wins|win)\s+(?:over|against)\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
        r"\b([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b[^.!?]{0,100}\b(?:three nil|two nil|one nil|3-0|2-0|1-0)\s+(?:win|victory)\s+(?:over|against)\s+([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*){0,3})\b",
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


def _extract_year_competition(script: str) -> str:
    """Scan the script for a 4-digit year and a known competition/round phrase.

    Returns a concise descriptor like "2022 World Cup final" or "" if nothing
    is found. Dependency-free, used to enrich image-search queries.
    """
    text = str(script or "")
    lowered = text.lower()
    parts: list[str] = []

    year_match = re.search(r"\b(?:19|20)\d{2}\b", text)
    if year_match:
        parts.append(year_match.group(0))

    competitions = (
        ("world cup", "World Cup"),
        ("champions league", "Champions League"),
        ("europa league", "Europa League"),
        ("premier league", "Premier League"),
        ("la liga", "La Liga"),
        ("serie a", "Serie A"),
        ("bundesliga", "Bundesliga"),
        ("ligue 1", "Ligue 1"),
        ("copa america", "Copa America"),
        ("copa del rey", "Copa del Rey"),
        ("nations league", "Nations League"),
        ("fa cup", "FA Cup"),
        ("euros", "Euros"),
        ("european championship", "European Championship"),
        ("euro", "Euros"),
        ("friendly", "friendly"),
    )
    for needle, canonical in competitions:
        if needle in lowered:
            parts.append(canonical)
            break

    for round_needle, round_label in (
        ("semi-final", "semi-final"),
        ("semifinal", "semi-final"),
        ("quarter-final", "quarter-final"),
        ("quarterfinal", "quarter-final"),
        ("final", "final"),
    ):
        if round_needle in lowered:
            parts.append(round_label)
            break

    return " ".join(parts).strip()


def _is_football_script(script: str) -> bool:
    # Domain detection is config-driven: the football vocabulary/entity list now
    # lives in packs/football.yaml (detect block), not hardcoded here.
    return _dp.detect_domain(script) == "football"


def _global_visual_context(script: str) -> str:
    teams = _infer_match_teams(script)
    # Use generic named-entity extraction instead of a hardcoded name list.
    names = _extract_named_entities_from_script(script)
    # Domain is config-driven (packs/*.yaml detect block), not hardcoded to a
    # single topic. Any detected domain produces a topic-locked global hint; the
    # domain label is derived, never literal "football".
    domain = _dp.detect_domain(script)
    if domain:
        subject = " and ".join(teams) if len(teams) == 2 else ", ".join(names[:4]) or "the main subject"
        return (
            f"{domain.capitalize()} video about {subject}. Use real photography of these subjects connected to this "
            "topic. Avoid flags, logos, badges, wallpapers, title cards, thumbnails, and generic graphics."
        )
    return "Use visuals that match the full script topic. Avoid logos, title cards, thumbnails, wallpapers, and unrelated generic images."


def _item_in_detected_domain(item: dict) -> bool:
    """True when the item belongs to a concrete (non-generic) domain video.

    Replaces the old substring check `"football video" in global_visual_context`
    with a structured signal so the behavior generalizes to every detected
    domain instead of being hardcoded to football.
    """
    domain = str(item.get("video_domain") or "").strip().lower()
    return bool(domain) and domain not in ("general", "generic")


def _scene_match_action(item: dict, teams: list[str], video_context: dict | None = None) -> tuple[str, str]:
    text = f"{item.get('sentence_text') or ''} {item.get('action_context') or ''}"
    lowered = text.lower()
    phrases = _capitalized_phrases(text)
    ignored = {
        "World Cup", "Les Bleus", "However", "The", "After", "Before", "In",
        "His", "By", "Every", "Maracana Stadium", "They", "Their", "This",
        "That", "Now", "But", "What", "With", "It", "Its",
    }
    ignored.update(teams)
    candidates = [
        phrase for phrase in phrases
        if phrase not in ignored
        and not any(phrase.lower() == team.lower() for team in teams)
        and not phrase.lower().endswith("stadium")
    ]
    # Drop scraped fragments not corroborated by the AI's English entities so a
    # non-English subject ("Nha") can never become the match subject.
    ai_words = _ai_entity_words(video_context)
    if ai_words:
        candidates = [phrase for phrase in candidates if set(_ascii_words(phrase)) & ai_words]
    subject = next((phrase for phrase in candidates if len(phrase.split()) >= 2), "")
    if not subject:
        subject = next(iter(candidates), "")
    if any(term in lowered for term in ("goal", "scor", "equaliz", "finish", "comeback")):
        return subject, "goal celebration match action"
    if any(term in lowered for term in ("coach", "manager", "warning", "substitution", "touchline", "bench")):
        return subject, "coach touchline match"
    if any(term in lowered for term in ("defend", "tackle", "attack", "penalty area")):
        return subject, "players competing match action"
    return subject, "players match action"


def _apply_match_search_context(items: list[dict], script: str) -> list[dict]:
    teams = _infer_match_teams(script)
    if len(teams) != 2:
        return items
    matchup = f"{teams[0]} {teams[1]}"
    event_tag = _extract_year_competition(script)
    stadium_match = re.search(
        r"\b([A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*){0,3}\s+Stadium)\b",
        script,
    )
    stadium = stadium_match.group(1).strip() if stadium_match else ""
    event_context = " ".join(value for value in (event_tag, stadium) if value)
    for item in items:
        subject, action = _scene_match_action(item, teams)
        action_short = ""
        if "goal celebration" in action:
            action_short = "celebration"
        elif "coach touchline" in action:
            action_short = "touchline"
        elif "players competing" in action:
            action_short = "action"
        query = _clean_search_keyword(_dedupe_query_parts(subject, matchup, event_tag, action_short))
        if not query:
            query = f"{matchup} {event_tag} match".strip()
        existing = item.get("google_queries") if isinstance(item.get("google_queries"), list) else []
        existing = [_clean_search_keyword(str(value)) for value in existing if _clean_search_keyword(str(value))]
        if "coach touchline" in action:
            event_variants = [
                _dedupe_query_parts(subject or "coach", matchup, event_tag, "touchline"),
                _dedupe_query_parts(subject or "coach", matchup, stadium),
                _dedupe_query_parts(matchup, event_tag, "coach bench"),
            ]
        elif "goal celebration" in action:
            event_variants = [
                _dedupe_query_parts(subject, matchup, event_tag, "celebration"),
                _dedupe_query_parts(matchup, event_tag, "goal celebration"),
                _dedupe_query_parts(matchup, event_tag, "players celebrating"),
            ]
        else:
            event_variants = [
                _dedupe_query_parts(subject, matchup, event_tag, "action"),
                _dedupe_query_parts(matchup, event_tag, "match action"),
                _dedupe_query_parts(matchup, stadium, "match"),
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


def _script_context_text(script: str, item: dict | None = None) -> str:
    item = item or {}
    return " ".join(
        str(value or "")
        for value in (
            script,
            item.get("sentence_text"),
            item.get("main_subject"),
            item.get("action_context"),
            item.get("visual_intent"),
        )
    )


def _strip_foreign_context_phrases(query: str, script: str, item: dict) -> str:
    """DEMOTE (not DELETE) unknown proper nouns.

    Per the domain-pack refactor we stop dropping name-like words that are not in
    the script/context/subject. Such a name is KEPT (it may be a correct,
    narrower entity the engine simply did not see in the surrounding text). We
    still drop stop words and dedupe the query, but proper nouns survive.
    """
    value = _clean_search_keyword(query)
    if not value:
        return ""
    kept_words = []
    for word in value.split():
        normalized = re.sub(r"[^A-Za-z0-9-]", "", word).lower()
        if not normalized or normalized in STOP_WORDS:
            continue
        kept_words.append(word)
    cleaned = " ".join(kept_words)
    return _dedupe_query_words(cleaned)


def _contextual_match_query(item: dict, script: str, teams: list[str], video_context: dict | None = None) -> str:
    if len(teams) != 2:
        return ""
    event_tag = _extract_year_competition(script)
    subject, action = _scene_match_action(item, teams, video_context)
    if not subject:
        subject = str(item.get("main_subject") or "").strip()
    if subject.lower() in {team.lower() for team in teams}:
        subject = ""
    action_short = "touchline" if "coach touchline" in action else "celebration" if "goal celebration" in action else "match action"
    return _concise_match_query(_dedupe_query_parts(subject, teams[0], teams[1], event_tag, action_short), item)


def _video_context_cache_path(project: Path) -> Path:
    return project / "scripts" / "video_context.ai.json"


def _extract_named_entities_from_script(script: str, limit: int = 12) -> list[str]:
    entities: list[str] = []
    ignored = {
        "The", "A", "An", "In", "On", "At", "After", "Before", "Meanwhile",
        "However", "Later", "Then", "This", "That", "These", "Those", "It",
        "They", "We", "He", "She", "World Cup", "Champions League",
    }
    for phrase in _capitalized_phrases(script):
        cleaned = re.sub(r"\s+", " ", phrase).strip()
        if (
            not cleaned
            or cleaned in ignored
            or cleaned.lower() in {value.lower() for value in entities}
        ):
            continue
        entities.append(cleaned)
        if len(entities) >= limit:
            break
    return entities


def _build_local_video_context(script: str) -> dict:
    teams = _infer_match_teams(script)
    # Domain is config-driven: whatever packs/*.yaml detect (or none -> general).
    domain = _dp.detect_domain(script) or "general"
    entities = _extract_named_entities_from_script(script)
    topic = "general narrated video"
    if len(teams) == 2:
        topic = f"{teams[0]} vs {teams[1]}"
    elif entities:
        topic = ", ".join(entities[:3])
    visual_boundaries = [
        "stay inside the real subject of the script",
        "use real photography tied to the actual subjects and event of the script",
        "avoid logos, flags, thumbnails, posters, title cards, and unrelated generic images",
    ]
    # Forbidden contexts come from the resolved domain pack (packs/*.yaml), never
    # hardcoded per topic. The football pack supplies football-specific avoids;
    # any other domain supplies its own; unknown -> generic pack defaults. This is
    # the local AI-failed fallback, so no AI caller is used (file/generic only).
    pack = _dp.resolve_domain_pack(script, {"video_domain": domain}, ai_caller=None)
    forbidden = list(_dp.forbidden_for(pack)) or [
        "tourism",
        "architecture unrelated to script",
        "country flags unless explicitly requested",
        "posters, thumbnails, graphics, collages",
    ]
    return {
        "video_topic": topic,
        "video_domain": domain,
        "main_entities": entities[:8],
        "match_teams": teams,
        "secondary_entities": entities[8:12],
        "visual_boundaries": visual_boundaries,
        "forbidden_contexts": forbidden,
        "source": "local_fallback",
    }


def _forbidden_contexts_text(pack=None) -> str:
    """Single source of truth for the 'avoid X' list used across prompts.
    Sourced from the pack's forbidden_contexts; defaults to the generic pack."""
    if pack is None:
        pack = _dp.load_generic_pack()
    items = _dp.forbidden_for(pack)
    if not items:
        items = _dp.forbidden_for(_dp.load_generic_pack())
    return ", ".join(items)


def _video_context_prompt(script: str, pack=None) -> str:
    return (
        "You are preparing image-search context for a video production tool.\n"
        "Read the FULL SCRIPT carefully and infer the real topic, domain, entities, and strict visual boundaries.\n"
        "Return JSON only with keys:\n"
        "- video_topic\n"
        "- video_domain\n"
        "- main_entities (array)\n"
        "- match_teams (array)\n"
        "- secondary_entities (array)\n"
        "- visual_boundaries (array)\n"
        "- forbidden_contexts (array)\n"
        "Rules:\n"
        "- Keep it factual and concise.\n"
        "- If this is a football match or football analysis, say so explicitly.\n"
        "- If match teams are known, include exactly those teams.\n"
        "- Do not invent people, countries, clubs, places, competitions, or storylines not present in the script.\n"
        "- visual_boundaries must tell downstream keyword generation what is allowed.\n"
        f"- forbidden_contexts must list what image directions should be blocked; always include: {_forbidden_contexts_text(pack)}.\n"
        "- Write video_topic, entities, and all output values in English (use international English spellings), even if the script is in another language.\n\n"
        f"FULL SCRIPT:\n{script}"
    )


def _resolve_keyword_provider(settings: dict | None) -> tuple[str, str, str]:
    settings = settings or {}
    provider = str(settings.get("keyword_ai_provider") or "auto").strip().lower()
    openai_key = str(settings.get("openai_api_key") or "").strip()
    kiro_key = str(settings.get("kiro_api_key") or "").strip()
    claude_key = str(settings.get("claude_api_key") or "").strip()
    gemini_key = str(settings.get("gemini_api_key") or "").strip()
    if provider == "auto":
        if kiro_key:
            provider = "kiro"
        elif openai_key.startswith("sk-"):
            provider = "openai"
        elif claude_key:
            provider = "claude"
        elif gemini_key:
            provider = "gemini"
        else:
            provider = ""
    if provider == "openai":
        return provider, openai_key, str(settings.get("keyword_ai_model") or "gpt-4.1-mini")
    if provider == "kiro":
        model = str(settings.get("kiro_keyword_model") or "kr/claude-opus-4.8").strip()
        if model in {
            "",
            "kiro/claude-sonnet-4.6",
            "Claude Sonnet 4.6 (Kiro)",
            "Claude Sonnet 4.6",
            "nghi/claude-sonnet-4.6",
            "nghi/claude-opus-4.8",
        }:
            model = "kr/claude-opus-4.8"
        return provider, kiro_key, model
    if provider == "claude":
        return provider, claude_key, str(settings.get("claude_keyword_model") or "claude-sonnet-4-20250514")
    if provider == "gemini":
        return provider, gemini_key, str(settings.get("gemini_keyword_model") or "gemini-2.5-flash")
    return provider, "", ""


def _pack_ai_caller(settings: dict | None, max_tokens: int = 1200):
    """Return a callable (prompt:str)->str dispatching to the configured AI
    provider, reusing the existing request helpers. Returns None when no
    provider/key is configured so the synthetic-pack tier is skipped.
    max_tokens is forwarded to the openai/kiro/claude branches; gemini has
    no cap so it is ignored there."""
    provider, api_key, model = _resolve_keyword_provider(settings)
    if not provider or not api_key:
        return None

    def _call(prompt: str) -> str:
        try:
            if provider == "kiro":
                return _call_openai_compatible_json(
                    provider="kiro",
                    api_key=api_key,
                    base_url=_kiro_api_base(settings),
                    model=model,
                    system="Return strict JSON only.",
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
            if provider == "openai":
                return _call_openai_compatible_json(
                    provider="openai",
                    api_key=api_key,
                    base_url="https://api.openai.com/v1",
                    model=model,
                    system="Return strict JSON only.",
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
            if provider == "claude":
                return _call_anthropic_compatible_json(
                    provider="claude",
                    api_key=api_key,
                    base_url="https://api.anthropic.com",
                    model=model,
                    system="Return strict JSON only.",
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
            if provider == "gemini":
                return _gemini_raw_text(api_key, model, prompt)
        except Exception:
            return ""
        return ""

    return _call


def _gemini_raw_text(api_key: str, model: str, prompt: str) -> str:
    """Send a raw prompt to Gemini and return the text (reuses the request
    pattern from _call_video_context_ai_gemini)."""
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get("gemini", 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get("gemini", 0.0):
        raise RuntimeError("Gemini đang tạm nghỉ vì hết quota.")
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL["gemini"] = time.time() + 900
        raise _ai_provider_error("gemini", response.status_code, response.text)
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    return "".join(str(part.get("text") or "") for part in parts)


def _resolve_pack(script, video_context, settings=None, project=None, log=None):
    """Single domain-pack resolution point used across the generation flow."""
    return _dp.resolve_domain_pack(
        script,
        video_context,
        settings=settings,
        project=project,
        ai_caller=_pack_ai_caller(settings),
        log=log,
    )


def _parse_video_context_json(content: str) -> dict:
    content = str(content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    data = json.loads(content)
    if not isinstance(data, dict):
        raise RuntimeError("Video context AI không trả về object.")
    return data


def _kiro_api_base(settings: dict | None = None) -> str:
    settings = settings or {}
    base = str(settings.get("kiro_api_base") or "https://xapi.labpinky.com/v1").strip().rstrip("/")
    if base in {"https://q.us-east-1.amazonaws.com", "https://api.nghimmo.com", "https://xapi.labpinky.com"}:
        base = "https://xapi.labpinky.com/v1"
    return base or "https://xapi.labpinky.com/v1"


def _anthropic_messages_url(base_url: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/messages"
    return f"{base}/v1/messages"


def _call_openai_compatible_json(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: int = 90,
) -> str:
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get(provider, 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get(provider, 0.0):
        raise RuntimeError(f"{provider} keyword/context đang tạm nghỉ vì hết quota.")
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL[provider] = time.time() + 900
        raise _ai_provider_error(provider, response.status_code, response.text)
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"{provider} API không trả về choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "".join(str(part.get("text") or part.get("content") or "") for part in content if isinstance(part, dict))
    return str(content or "")


def _call_anthropic_compatible_json(
    *,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: int = 90,
) -> str:
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get(provider, 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get(provider, 0.0):
        raise RuntimeError(f"{provider} keyword/context đang tạm nghỉ vì hết quota.")
    response = requests.post(
        _anthropic_messages_url(base_url),
        headers={
            "x-api-key": api_key,
            "Authorization": f"Bearer {api_key}",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL[provider] = time.time() + 900
        raise _ai_provider_error(provider, response.status_code, response.text)
    data = response.json()
    parts = data.get("content") or []
    if isinstance(parts, str):
        return parts
    return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))


def _call_video_context_ai_openai(api_key: str, model: str, script: str) -> dict:
    import requests

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": _video_context_prompt(script)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 1200,
        },
        timeout=90,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL["openai"] = time.time() + 900
        raise _ai_provider_error("openai", response.status_code, response.text)
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    return _parse_video_context_json(content)


def _call_video_context_ai_kiro(api_key: str, base_url: str, model: str, script: str) -> dict:
    content = _call_openai_compatible_json(
        provider="kiro",
        api_key=api_key,
        base_url=base_url,
        model=model,
        system="Return strict JSON only.",
        prompt=_video_context_prompt(script),
        max_tokens=1200,
        temperature=0.1,
        timeout=90,
    )
    return _parse_video_context_json(content)


def _call_video_context_ai_claude(api_key: str, model: str, script: str) -> dict:
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get("claude", 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get("claude", 0.0):
        raise RuntimeError("Claude keyword/context đang tạm nghỉ vì hết quota.")

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 1200,
            "temperature": 0.1,
            "system": "Return strict JSON only.",
            "messages": [{"role": "user", "content": _video_context_prompt(script)}],
        },
        timeout=90,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL["claude"] = time.time() + 900
        raise _ai_provider_error("claude", response.status_code, response.text)
    data = response.json()
    parts = data.get("content") or []
    content = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    return _parse_video_context_json(content)


def _call_video_context_ai_gemini(api_key: str, model: str, script: str) -> dict:
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get("gemini", 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get("gemini", 0.0):
        raise RuntimeError("Gemini keyword/context đang tạm nghỉ vì hết quota.")

    payload = {
        "contents": [{"role": "user", "parts": [{"text": _video_context_prompt(script)}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL["gemini"] = time.time() + 900
        raise _ai_provider_error("gemini", response.status_code, response.text)
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini video context API không trả về candidate.")
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    content = "".join(str(part.get("text") or "") for part in parts)
    return _parse_video_context_json(content)


def _normalize_video_context(data: dict, script: str) -> dict:
    local = _build_local_video_context(script)
    normalized = dict(local)
    if isinstance(data, dict):
        for key in ("video_topic", "video_domain"):
            value = str(data.get(key) or "").strip()
            if value:
                normalized[key] = value
        for key in ("main_entities", "match_teams", "secondary_entities", "visual_boundaries", "forbidden_contexts"):
            values = data.get(key)
            if isinstance(values, list):
                cleaned = []
                for value in values:
                    text = re.sub(r"\s+", " ", str(value or "")).strip()
                    if text and text not in cleaned:
                        cleaned.append(text)
                if cleaned:
                    normalized[key] = cleaned[:12]
    if len(normalized.get("match_teams") or []) != 2:
        inferred = _infer_match_teams(script)
        if len(inferred) == 2:
            normalized["match_teams"] = inferred
    normalized["source"] = str(data.get("source") or normalized.get("source") or "ai").strip() if isinstance(data, dict) else normalized.get("source")
    return normalized


def _load_or_build_video_context(
    project: Path,
    script: str,
    settings: dict | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    settings = settings or {}
    cache_path = _video_context_cache_path(project)
    script_hash = hashlib.sha256(str(script or "").encode("utf-8", errors="ignore")).hexdigest()
    provider, api_key, model = _resolve_keyword_provider(settings)
    cached = read_json(cache_path, {})
    if isinstance(cached, dict) and cached.get("script_hash") == script_hash and isinstance(cached.get("context"), dict):
        cached_context = cached["context"]
        cached_source = str(cached_context.get("source") or cached.get("provider") or "").strip().lower()
        cached_provider = str(cached.get("provider") or cached_source).strip().lower()
        # If the old cache was local fallback but the user now has an AI key,
        # try the configured provider again. Otherwise a bad first run can lock
        # every future keyword to weak local guesses.
        if not api_key or (
            cached_source != "local_fallback"
            and (not cached_provider or not provider or cached_provider == provider or cached_source == provider)
        ):
            return cached_context

    context = _build_local_video_context(script)
    try:
        if provider == "openai" and api_key.startswith("sk-"):
            if callable(log):
                log("AI keyword: đang đọc toàn bộ script để hiểu chủ đề video...")
            context = _normalize_video_context(
                _call_video_context_ai_openai(api_key, model, script),
                script,
            )
            context["source"] = "openai"
        elif provider == "kiro" and api_key:
            if callable(log):
                log("AI keyword: Kiro đang đọc toàn bộ script để hiểu chủ đề video...")
            context = _normalize_video_context(
                _call_video_context_ai_kiro(api_key, _kiro_api_base(settings), model, script),
                script,
            )
            context["source"] = "kiro"
        elif provider == "claude" and api_key:
            if callable(log):
                log("AI keyword: Claude đang đọc toàn bộ script để hiểu chủ đề video...")
            context = _normalize_video_context(
                _call_video_context_ai_claude(api_key, model, script),
                script,
            )
            context["source"] = "claude"
        elif provider == "gemini" and api_key:
            if callable(log):
                log("AI keyword: đang đọc toàn bộ script để hiểu chủ đề video...")
            context = _normalize_video_context(
                _call_video_context_ai_gemini(api_key, model, script),
                script,
            )
            context["source"] = "gemini"
    except Exception as exc:
        if callable(log):
            label = {"kiro": "Kiro", "openai": "OpenAI", "claude": "Claude", "gemini": "Gemini"}.get(provider, "AI")
            log(f"AI keyword: {label} không gọi được nên tạm dùng ngữ cảnh local. Kiểm tra key, model và endpoint. Lỗi: {exc}")
    write_json(
        cache_path,
        {
            "script_hash": script_hash,
            "updated_at": _now(),
            "provider": provider or "local",
            "context": context,
        },
    )
    return context


def _is_weak_match_query(query: str, teams: list[str]) -> bool:
    words = [word.lower() for word in _ascii_words(query)]
    if not words:
        return True
    team_words = {word.lower() for team in teams for word in _ascii_words(team)}
    useful = [word for word in words if word not in STOP_WORDS]
    specific = [word for word in useful if word not in team_words and word not in {"match", "action", "team", "football", "soccer"}]
    return len(specific) == 0 or len(useful) <= max(2, len(team_words) + 1)


def _query_mentions_both_teams(query: str, teams: list[str]) -> bool:
    if len(teams) != 2:
        return False
    query_words = set(_ascii_words(query))
    hits = 0
    for team in teams:
        team_words = set(_ascii_words(team))
        if team_words and query_words & team_words:
            hits += 1
    return hits == 2


def _query_is_specific_person_context(query: str, item: dict) -> bool:
    subject_words = set(_ascii_words(str(item.get("main_subject") or "")))
    query_words = set(_ascii_words(query))
    if len(subject_words) >= 2 and subject_words <= query_words:
        return True
    lowered = str(item.get("action_context") or "").lower()
    return any(term in lowered for term in ("coach", "touchline", "goalkeeper", "captain"))


def _diversify_scene_keywords(items: list[dict]) -> list[dict]:
    """Cross-scene diversity pass run after all per-scene keywords are decided.

    Enrichment can push many weak scenes toward the same generic matchup query
    (e.g. "Argentina Brazil match action"), causing the tool to fetch identical
    images for many scenes and the final video to repeat footage. This pass
    walks the items in order and, when a scene's primary keyword duplicates one
    already used, promotes the first unused alternative from its own
    google_queries / fallback_keywords to be the new primary.
    """

    def _norm(value) -> str:
        return " ".join(_ascii_words(str(value or "")))

    used_primary: set[str] = set()
    for item in items:
        primary = str(item.get("keyword") or "").strip()
        norm_primary = _norm(primary)
        # Skip items with no usable keyword; nothing to diversify.
        if not norm_primary:
            continue
        if norm_primary not in used_primary:
            used_primary.add(norm_primary)
            continue
        # Duplicate primary: look for an unused alternative from this item's own
        # google_queries[1:] then fallback_keywords.
        google_queries = item.get("google_queries")
        google_queries = google_queries if isinstance(google_queries, list) else []
        fallback_keywords = item.get("fallback_keywords")
        fallback_keywords = fallback_keywords if isinstance(fallback_keywords, list) else []
        alternatives = [str(v) for v in google_queries[1:]] + [str(v) for v in fallback_keywords]
        chosen = ""
        chosen_norm = ""
        for alt in alternatives:
            alt = alt.strip()
            norm_alt = _norm(alt)
            if norm_alt and norm_alt not in used_primary:
                chosen = alt
                chosen_norm = norm_alt
                break
        if chosen:
            item["keyword"] = chosen
            item["ai_search_keyword"] = chosen
            # Reorder google_queries so the chosen one is first, others after, deduped.
            reordered = [chosen]
            seen = {_norm(chosen)}
            for query in google_queries:
                norm_query = _norm(query)
                if norm_query and norm_query not in seen:
                    reordered.append(str(query))
                    seen.add(norm_query)
            item["google_queries"] = reordered
            used_primary.add(chosen_norm)
        else:
            # Degraded case: no unused alternative exists. Leave the item as-is
            # (it remains a known duplicate, which is acceptable). The normalized
            # primary is already in used_primary, so no further action is needed.
            used_primary.add(norm_primary)
    return items


def _apply_script_visual_context(items: list[dict], script: str, video_context: dict | None = None, pack=None) -> list[dict]:
    script = str(script or "")
    video_context = video_context or _build_local_video_context(script)
    if pack is None:
        pack = _resolve_pack(script, video_context)
    teams = [str(value).strip() for value in video_context.get("match_teams") or _infer_match_teams(script) if str(value).strip()]
    script_lower = script.lower()
    football_context = _is_football_script(script)
    global_context = _global_visual_context(script)
    for item in items:
        item_teams = [str(value).strip() for value in item.get("match_teams") or [] if str(value).strip()]
        local_teams = item_teams if len(item_teams) == 2 else teams
        item["global_visual_context"] = global_context
        item["video_topic"] = str(video_context.get("video_topic") or item.get("video_topic") or "").strip()
        item["video_domain"] = str(video_context.get("video_domain") or item.get("video_domain") or "").strip()
        raw_queries = []
        for key in ("keyword", "ai_search_keyword"):
            if item.get(key):
                raw_queries.append(str(item.get(key)))
        for key in ("google_queries", "fallback_keywords", "sportsdb_queries"):
            if isinstance(item.get(key), list):
                raw_queries.extend(str(value) for value in item.get(key) if str(value).strip())
        sanitized = []
        for query in raw_queries:
            query = _strip_foreign_context_phrases(query, script, item)
            if query and query not in sanitized:
                sanitized.append(query)
        is_match_context = (
            football_context
            and (
                len(local_teams) == 2
                or _is_match_photography_item(item)
                or any(term in str(item.get("sentence_text") or "").lower() for term in ("football", "match", "team", "world cup", "goal", "penalty", "midfield", "pressing", "coach", "wing"))
            )
            and (len(local_teams) != 2 or any(team.lower() in script_lower for team in local_teams) or len(item_teams) == 2)
        )
        if len(item_teams) == 2:
            is_match_context = True
        # Trust an AI-confirmed two-team matchup even when the local football
        # detector misses it (it only matches English keywords, so a Vietnamese
        # script reads as non-football). This routes the scene through the
        # match-query builder, which uses the AI's English team names instead of
        # scraped fragments.
        if _video_context_is_ai(video_context) and len(teams) == 2:
            is_match_context = True
        if is_match_context:
            if len(local_teams) == 2:
                item["match_teams"] = local_teams
                base_match_query = _concise_match_query(_dedupe_query_parts(local_teams[0], local_teams[1], "match action"), item)
                if base_match_query and base_match_query not in sanitized and (not sanitized or _is_weak_match_query(sanitized[0], local_teams)):
                    sanitized.insert(0, base_match_query)
            contextual = _contextual_match_query(item, script, local_teams, video_context)
            if contextual and contextual not in sanitized and (not sanitized or _is_weak_match_query(sanitized[0], local_teams)):
                sanitized.insert(0, contextual)
            if len(local_teams) == 2 and sanitized:
                enriched = []
                for query in sanitized:
                    candidate = query
                    # Only rewrite genuinely weak queries into the both-teams
                    # form. A strong single-subject query (one player/team plus
                    # an action) is a valid, well-tagged image search and is kept
                    # as-is so we don't shrink the result pool.
                    if _is_weak_match_query(candidate, local_teams) and not _query_is_specific_person_context(candidate, item):
                        candidate = _contextual_match_query(item, script, local_teams, video_context) or candidate
                    candidate = _concise_match_query(candidate, item)
                    if candidate and candidate not in enriched:
                        enriched.append(candidate)
                sanitized = enriched or sanitized
            if len(local_teams) == 2:
                stable_match_query = _concise_match_query(_dedupe_query_parts(local_teams[0], local_teams[1], "match action"), item)
                if stable_match_query and stable_match_query not in sanitized:
                    sanitized.append(stable_match_query)
            # Source routing decided by the pack (route_source), not hardcoded
            # football branches. The football pack keeps match_moment/tactical on
            # editorial photography and portrait/celebration on thesportsdb, so
            # this preserves existing football behavior while generalizing.
            scene_type, entity_type = _scene_type_and_entity(item, local_teams, pack)
            event_tag = _extract_year_competition(script)
            year = next((tok for tok in event_tag.split() if tok.isdigit()), "")
            route = _dp.route_source(
                entity_type,
                scene_type,
                pack,
                slots={
                    "video_year": year,
                    "competition_year": year,
                    "year": year,
                },
            )
            # Keep visual_source_type as match_photography so the download path
            # (_is_match_photography_item) is unchanged for football; route_source
            # only DECIDES whether sportsdb_queries get populated vs left empty.
            item["visual_source_type"] = "match_photography"
            # Recency: bind the web search to the pack's anchor year (e.g. the
            # competition year for football) so WC2026 queries don't pull 2018/
            # 2022 photos. Stored on the item; the download path converts it to a
            # Google Images date filter.
            date_min = str(route.filters.get("date_min") or "").strip()
            if date_min:
                item["search_date_min"] = date_min
            if route.source == "thesportsdb":
                item["sportsdb_queries"] = [value for value in sanitized[:4] if value]
            else:
                item["sportsdb_queries"] = []
            if not sanitized:
                subject, action = _scene_match_action(item, local_teams, video_context)
                # Derive the fallback generically from the scene/teams instead of
                # hardcoding a country/player so the tool generalizes to any topic.
                teams_subject = " ".join(local_teams[:2]) if len(local_teams) >= 2 else ""
                fallback_subject = (
                    subject
                    or str(item.get("main_subject") or "").strip()
                    or teams_subject
                    or str(video_context.get("video_topic") or "").strip()
                    or "football match"
                )
                fallback_action = "celebration" if "celebration" in action else "match action"
                parts = [fallback_subject, fallback_action]
                # Append a single team name only when the subject doesn't already
                # reference a team, to keep the query specific without duplication.
                if local_teams:
                    subject_lower = fallback_subject.lower()
                    if not any(team.lower() in subject_lower for team in local_teams):
                        parts.insert(1, local_teams[0])
                sanitized.append(_clean_search_keyword(" ".join(part for part in parts if part)))
        if not sanitized:
            sanitized.extend(_fallback_scene_keywords(item, script, video_context, pack))
        if sanitized:
            item["keyword"] = sanitized[0]
            item["ai_search_keyword"] = sanitized[0]
            item["google_queries"] = sanitized[:4]
            item["fallback_keywords"] = [value for value in sanitized[1:6] if value != sanitized[0]]
        item["script_context_checked"] = True
    items = _diversify_scene_keywords(items)
    return items


def group_scenes_with_ai(
    project: Path,
    sentences: list[dict],
    settings: dict,
    log: Callable[[str], None] | None = None,
) -> list[dict]:
    if not bool(settings.get("scene_ai_enabled", True)):
        raise RuntimeError("AI scene grouping is disabled.")
    provider, api_key, model = _resolve_keyword_provider(settings)
    gemini_key = str(settings.get("gemini_api_key") or "").strip()
    if provider == "openai":
        if gemini_key:
            provider = "gemini"
            api_key = gemini_key
            model = str(settings.get("gemini_keyword_model") or "gemini-2.5-flash")
        else:
            raise RuntimeError("Chia cảnh ngữ nghĩa hiện dùng Kiro, Claude hoặc Gemini.")
    if provider not in {"kiro", "claude", "gemini"} or not api_key:
        raise RuntimeError("Chưa có API key AI để chia cảnh.")

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
        label = {"kiro": "Kiro", "claude": "Claude", "gemini": "Gemini"}.get(provider, "AI")
        log(f"{label} scene: đang đọc toàn bộ SRT và gộp {len(sentences)} câu theo ngữ cảnh...")
    soft_min_seconds = max(3.0, float(settings.get("scene_min_seconds") or 4.0))
    soft_target_seconds = max(18.0, float(settings.get("scene_target_max_seconds") or 25.0))
    safety_max_seconds = max(45.0, float(settings.get("scene_hard_max_seconds") or 45.0))
    if provider == "kiro":
        rows = _call_scene_ai_kiro(
            api_key,
            _kiro_api_base(settings),
            model,
            script,
            payload,
            soft_min_seconds,
            soft_target_seconds,
        )
    elif provider == "claude":
        rows = _call_scene_ai_claude(
            api_key,
            model,
            script,
            payload,
            soft_min_seconds,
            soft_target_seconds,
        )
    else:
        rows = _call_scene_ai_gemini(
            api_key,
            model,
            script,
            payload,
            soft_min_seconds,
            soft_target_seconds,
        )
    groups = _validate_scene_groups(rows, sentences)
    groups = _enforce_scene_duration_limit(groups, safety_max_seconds)
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
        item["scene_analysis_source"] = provider
        item["keyword_source"] = f"{provider}_scene"
        assets.append(item)
    if callable(log):
        label = {"kiro": "Kiro", "claude": "Claude", "gemini": "Gemini"}.get(provider, "AI")
        log(f"{label} scene: đã gộp thành {len(assets)} cảnh.")
    return assets


def _scene_prompt(
    script: str,
    sentences: list[dict],
    min_seconds: float,
    target_max_seconds: float,
    pack=None,
) -> str:
    forbidden = _forbidden_contexts_text(pack)
    return (
        "You are a professional video editor and visual researcher.\n"
        "Read the full script and every timed SRT sentence before deciding scene boundaries.\n"
        f"GLOBAL TOPIC LOCK: {_global_visual_context(script)}\n"
        "Infer the video's topic and genre from the FULL SCRIPT. Do not force a sports interpretation unless the script is clearly about sports.\n"
        "Group consecutive sentence indexes into coherent visual scenes.\n"
        "Scene rules:\n"
        "- Primary goal: each scene should represent one clear visual idea that can be matched to one image/video asset.\n"
        "- Split only when the main person, team, location, event, action, tactical phase, emotion, or time period truly changes.\n"
        "- Keep sentences that complete one idea together. Never cut in the middle of an idea or one continuous tactical phase.\n"
        f"- Duration is a soft pacing hint, not a rule. Many scenes may be around {min_seconds:g}-{target_max_seconds:g} seconds, but use shorter or longer scenes when the visual idea requires it.\n"
        "- Do not split one continuous idea only because it is over a target duration.\n"
        "- If an idea is very long, split it only when the visual intent changes clearly, for example from isolated striker to opponent pressing, from coach reaction to player celebration, or from attack buildup to final shot.\n"
        "- Avoid tiny scenes unless a short sentence is a complete standalone visual moment.\n"
        "- Every sentence must appear exactly once, in original order, with no gaps or overlap.\n"
        "- A scene must contain one continuous sentence_start..sentence_end range.\n"
        "- break_reason must clearly state what changed from the previous scene, such as subject_change, event_change, "
        "location_change, time_change, action_change, or continuation. First scene uses opening.\n"
        "- main_subject names the exact visible person/team/place/object.\n"
        "- action_context describes the visible action, event, location, and useful date/competition context.\n"
        f"- This tool needs real useful visual assets. Avoid: {forbidden}, and any unrelated generic images.\n"
        "- For narration about a specific sports match, visual_source_type should be match_photography and visuals must stay inside that same match.\n"
        "- For non-sports narration, choose the appropriate visual_source_type and never invent sports teams/events.\n"
        "- search_keyword is a short 4-8 word Google Images query.\n"
        "- Every sports match query must include both teams/opponents when known and use a visible match moment: match action, "
        "goal, celebration, tackle, substitution, coach touchline, players after final whistle.\n"
        f"- For football narration, never use these as scene visuals: {forbidden}, national flags, federation logos, team badges.\n"
        "- Never introduce named people, countries, teams, places, or events that do not appear in the full script or scene.\n"
        "- Avoid abstract/generic queries such as football player, greatest player, famous team, sports scene.\n"
        "- Return 3-5 specific fallback_keywords.\n"
        "- sportsdb_queries contain only exact player/team/stadium/event names.\n"
        "- google_queries contain person + both teams + score/action. Do not add filler such as editorial photo, players competing, visible context.\n"
        "- All search_keyword, google_queries, fallback_keywords, and sportsdb_queries MUST be written in ENGLISH, even if the script is in another language. Use the internationally-recognized English spelling of names, teams, places, and competitions.\n"
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


def _call_scene_ai_kiro(
    api_key: str,
    base_url: str,
    model: str,
    script: str,
    sentences: list[dict],
    min_seconds: float,
    target_max_seconds: float,
) -> list[dict]:
    content = _call_openai_compatible_json(
        provider="kiro",
        api_key=api_key,
        base_url=base_url,
        model=model,
        system="Return strict JSON only.",
        prompt=_scene_prompt(script, sentences, min_seconds, target_max_seconds),
        max_tokens=3200,
        temperature=0.15,
        timeout=120,
    ).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    parsed = json.loads(content)
    rows = parsed.get("scenes") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        raise RuntimeError("Kiro scene API không trả về scenes list.")
    return rows


def _call_scene_ai_claude(
    api_key: str,
    model: str,
    script: str,
    sentences: list[dict],
    min_seconds: float,
    target_max_seconds: float,
) -> list[dict]:
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get("claude", 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get("claude", 0.0):
        raise RuntimeError("Claude keyword/context đang tạm nghỉ vì hết quota.")

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 3200,
            "temperature": 0.15,
            "system": "Return strict JSON only.",
            "messages": [
                {
                    "role": "user",
                    "content": _scene_prompt(script, sentences, min_seconds, target_max_seconds),
                }
            ],
        },
        timeout=120,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL["claude"] = time.time() + 900
        raise _ai_provider_error("claude", response.status_code, response.text)
    data = response.json()
    parts = data.get("content") or []
    content = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    parsed = json.loads(content)
    rows = parsed.get("scenes") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        raise RuntimeError("Claude scene API không trả về scenes list.")
    return rows


def _enforce_scene_duration_limit(
    groups: list[tuple[dict, list[dict]]],
    max_seconds: float = 45.0,
) -> list[tuple[dict, list[dict]]]:
    max_seconds = max(30.0, float(max_seconds or 45.0))
    min_seconds = min(4.0, max_seconds)
    # This is only a safety guard for broken AI output, not a pacing rule.
    soft_merge_max_seconds = max_seconds
    split_groups: list[tuple[dict, list[dict]]] = []
    for row, grouped in groups:
        if not grouped:
            continue
        duration = float(grouped[-1]["end"]) - float(grouped[0]["start"])
        if duration <= max_seconds or len(grouped) == 1:
            split_groups.append((row, grouped))
            continue
        chunk: list[dict] = []
        part = 1
        for sentence in grouped:
            if chunk:
                next_duration = float(sentence["end"]) - float(chunk[0]["start"])
                if next_duration > max_seconds:
                    next_row = dict(row)
                    next_row["break_reason"] = str(row.get("break_reason") or "duration_split") if part == 1 else "duration_split"
                    split_groups.append((next_row, chunk))
                    chunk = []
                    part += 1
            chunk.append(sentence)
        if chunk:
            next_row = dict(row)
            next_row["break_reason"] = str(row.get("break_reason") or "duration_split") if part == 1 else "duration_split"
            split_groups.append((next_row, chunk))

    merged: list[tuple[dict, list[dict]]] = []
    for row, grouped in split_groups:
        duration = float(grouped[-1]["end"]) - float(grouped[0]["start"])
        if merged and duration < min_seconds:
            prev_row, prev_grouped = merged[-1]
            combined_duration = float(grouped[-1]["end"]) - float(prev_grouped[0]["start"])
            if combined_duration <= max_seconds:
                merged[-1] = (prev_row, [*prev_grouped, *grouped])
                continue
        merged.append((row, grouped))

    changed = True
    while changed:
        changed = False
        output: list[tuple[dict, list[dict]]] = []
        index = 0
        while index < len(merged):
            row, grouped = merged[index]
            duration = float(grouped[-1]["end"]) - float(grouped[0]["start"])
            if duration < min_seconds and index + 1 < len(merged):
                next_row, next_grouped = merged[index + 1]
                combined_duration = float(next_grouped[-1]["end"]) - float(grouped[0]["start"])
                if combined_duration <= soft_merge_max_seconds:
                    output.append((row, [*grouped, *next_grouped]))
                    index += 2
                    changed = True
                    continue
            output.append((row, grouped))
            index += 1
        merged = output
    if len(merged) >= 2:
        last_row, last_grouped = merged[-1]
        last_duration = float(last_grouped[-1]["end"]) - float(last_grouped[0]["start"])
        prev_row, prev_grouped = merged[-2]
        combined_duration = float(last_grouped[-1]["end"]) - float(prev_grouped[0]["start"])
        if last_duration < min_seconds and combined_duration <= soft_merge_max_seconds:
            merged[-2] = (prev_row, [*prev_grouped, *last_grouped])
            merged.pop()
    return merged


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
        "prompt": "",
        "search_attempt": 0,
        "status": "pending",
        "source_url": "",
        "source_page": "",
        "local_path": "",
        "thumbnail_url": "",
    }


def load_manifest(project: Path) -> list[dict]:
    data = read_json(project / "assets" / "asset_manifest.json", {})
    if not isinstance(data, dict) or not _manifest_matches_current_voice(project, data):
        return []
    return list(data.get("items") or [])


def save_manifest(project: Path, items: list[dict]) -> None:
    data = read_json(project / "assets" / "asset_manifest.json", {})
    if not isinstance(data, dict) or not _manifest_matches_current_voice(project, data):
        data = {}
    data.update(
        {
            "version": max(3, int(data.get("version") or 3)),
            "voice_signature": voice_signature(project),
            "scene_count": len(items),
            "items": items,
        }
    )
    write_json(project / "assets" / "asset_manifest.json", data)


def attach_local_media_to_asset(project: Path, asset_id: str, source: Path, settings: dict | None = None) -> dict:
    items = load_manifest(project)
    index = next((i for i, item in enumerate(items) if item.get("asset_id") == asset_id), -1)
    if index < 0:
        raise FileNotFoundError(f"Không tìm thấy cảnh {asset_id}.")
    if not source.is_file():
        raise FileNotFoundError(f"Không tìm thấy file media: {source}")

    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES and suffix not in VIDEO_SUFFIXES:
        raise RuntimeError("File không hợp lệ. Chỉ nhận ảnh JPG/PNG/WEBP/BMP/AVIF hoặc video MP4/MOV/MKV/WEBM/AVI.")

    manual_dir = project / "assets" / "downloads" / "manual"
    manual_dir.mkdir(parents=True, exist_ok=True)
    item = items[index]
    if suffix in IMAGE_SUFFIXES:
        raw_target = manual_dir / f"{asset_id}_manual_raw{suffix}"
        shutil.copy2(source, raw_target)
        target = manual_dir / f"{asset_id}_manual_16x9.jpg"
        width, height = _enhance_image_without_crop(raw_target, target, settings)
        local_path = target
        raw_path = raw_target
        media_kind = "image"
    else:
        target = manual_dir / f"{asset_id}_manual{suffix}"
        shutil.copy2(source, target)
        width, height = _image_size(target)
        local_path = target
        raw_path = target
        media_kind = "video"

    item.update(
        {
            "status": "downloaded",
            "visual_source_type": "local_upload",
            "source_page": "Người dùng tải lên",
            "source_url": "",
            "thumbnail_url": "",
            "local_path": str(local_path),
            "raw_local_path": str(raw_path),
            "image_width": width,
            "image_height": height,
            "sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(),
            "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            "image_ai_validation": {
                "accepted": True,
                "score": 100,
                "visible_subject": "Media do người dùng chọn",
                "reason": "Bỏ qua kiểm tra AI vì người dùng đã tự tải media cho cảnh này.",
                "model": "manual",
            },
            "media_kind": media_kind,
            "error": "",
        }
    )
    save_manifest(project, items)
    return item


def optimize_asset_keywords_with_ai(
    project: Path,
    settings: dict,
    log: Callable[[str], None] | None = None,
    chunk_size: int = 8,
) -> list[dict]:
    provider, api_key, model = _resolve_keyword_provider(settings)
    script_path = project / "scripts" / "script_final.txt"
    script = script_path.read_text(encoding="utf-8", errors="replace").strip() if script_path.exists() else ""
    video_context = _load_or_build_video_context(project, script, settings, log=log) if script else _build_local_video_context("")
    pack = _resolve_pack(script, video_context, settings=settings, project=project, log=log)
    if callable(log) and script:
        topic = str(video_context.get("video_topic") or "").strip()
        teams = ", ".join(str(value) for value in video_context.get("match_teams") or [] if str(value).strip())
        if topic:
            log(f"AI keyword: đã hiểu chủ đề video là {topic}{f' ({teams})' if teams else ''}.")
    if not api_key:
        if callable(log):
            log("AI keyword: chưa có API key, dùng keyword local.")
        items = load_manifest(project)
        if script:
            items = _apply_script_visual_context(items, script, video_context, pack)
            save_manifest(project, items)
        return items

    items = load_manifest(project)
    if not items:
        return items
    if script:
        items = _apply_script_visual_context(items, script, video_context, pack)
    for item in items:
        item.setdefault("keyword_local", item.get("keyword") or "")
    global_context = _global_visual_context(script)

    def _build_payload(start: int, chunk: list[dict]) -> list[dict]:
        payload = []
        for offset, item in enumerate(chunk):
            absolute_index = start + offset
            previous_item = items[absolute_index - 1] if absolute_index > 0 else {}
            next_item = items[absolute_index + 1] if absolute_index + 1 < len(items) else {}
            payload.append(
                {
                    "asset_id": item.get("asset_id"),
                    "scene_text": item.get("sentence_text"),
                    "previous_scene_text": previous_item.get("sentence_text", ""),
                    "next_scene_text": next_item.get("sentence_text", ""),
                    "timing": f"{item.get('start')} - {item.get('end')}",
                    "local_keyword": item.get("keyword"),
                    "global_visual_context": item.get("global_visual_context") or global_context,
                    "video_topic": video_context.get("video_topic"),
                    "video_domain": video_context.get("video_domain"),
                    "video_main_entities": video_context.get("main_entities") or [],
                    "video_visual_boundaries": video_context.get("visual_boundaries") or [],
                    "video_forbidden_contexts": video_context.get("forbidden_contexts") or [],
                    "main_subject": item.get("main_subject"),
                    "action_context": item.get("action_context"),
                    "visual_intent": item.get("visual_intent"),
                    "visual_source_type": item.get("visual_source_type"),
                    "match_teams": item.get("match_teams") if isinstance(item.get("match_teams"), list) else [],
                }
            )
        return payload

    def _call_keyword_ai(payload: list[dict]) -> list[dict]:
        if provider == "gemini":
            return _call_keyword_ai_gemini(api_key, model, payload, script)
        if provider == "kiro":
            return _call_keyword_ai_kiro(api_key, _kiro_api_base(settings), model, payload, script)
        if provider == "claude":
            return _call_keyword_ai_claude(api_key, model, payload, script)
        if not api_key.startswith("sk-"):
            raise RuntimeError("OpenAI key phải bắt đầu bằng sk-. Nếu dùng key AQ..., hãy chọn provider Gemini.")
        return _call_keyword_ai_openai(api_key, model, payload, script)

    chunks = [(start, items[start : start + chunk_size]) for start in range(0, len(items), chunk_size)]
    try:
        configured_workers = int(settings.get("image_search_parallel_jobs") or 0)
    except (TypeError, ValueError):
        configured_workers = 0
    max_workers = max(1, min(4, configured_workers or 4, len(chunks) or 1))

    # Run the per-chunk AI calls concurrently (HTTP-bound); apply the results in
    # the main thread so item mutation stays serialized. One chunk failing keeps
    # that chunk's local fallback without blocking the others.
    results_by_idx: dict[int, tuple[list[dict], list[dict]]] = {}
    if max_workers <= 1 or len(chunks) <= 1:
        for idx, (start, chunk) in enumerate(chunks):
            if callable(log):
                log(f"AI keyword: tối ưu {start + 1}-{start + len(chunk)}/{len(items)}")
            try:
                results_by_idx[idx] = (chunk, _call_keyword_ai(_build_payload(start, chunk)))
            except Exception as exc:
                if callable(log):
                    log(f"AI keyword lỗi, giữ keyword/query fallback nội bộ: {exc}")
    else:
        import concurrent.futures as _cf

        if callable(log):
            log(f"AI keyword: tối ưu {len(items)} câu theo {len(chunks)} nhóm (song song x{max_workers})...")

        def _process(job: tuple[int, int, list[dict]]):
            idx, start, chunk = job
            return idx, chunk, _call_keyword_ai(_build_payload(start, chunk))

        jobs = [(idx, start, chunk) for idx, (start, chunk) in enumerate(chunks)]
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for future in _cf.as_completed([executor.submit(_process, job) for job in jobs]):
                try:
                    idx, chunk, result = future.result()
                    results_by_idx[idx] = (chunk, result)
                except Exception as exc:
                    if callable(log):
                        log(f"AI keyword lỗi 1 nhóm, giữ fallback nội bộ: {exc}")

    for idx in sorted(results_by_idx):
        chunk, result = results_by_idx[idx]
        by_id = {str(row.get("asset_id") or ""): row for row in result}
        for item in chunk:
            row = by_id.get(str(item.get("asset_id") or ""))
            if not row:
                continue
            _apply_keyword_ai_row(item, row, provider, script, video_context, pack)
    if script:
        items = _apply_script_visual_context(items, script, video_context, pack)
    save_manifest(project, items)
    return items


def _keyword_prompt(scenes: list[dict], script: str = "", pack=None) -> str:
    video_context = _build_local_video_context(script)
    forbidden = _forbidden_contexts_text(pack)
    prompt = (
        "You create visual asset search plans for a video production tool.\n"
        f"GLOBAL TOPIC LOCK: {_global_visual_context(script)}\n"
        f"VIDEO TOPIC SUMMARY: {json.dumps(video_context, ensure_ascii=False)}\n"
        "First read the FULL SCRIPT completely to understand what the video is about. Treat this as the hard boundary for all visual keywords.\n"
        "Then process EACH SCENE separately. Combine the scene narration with the full-script topic lock and the provided previous/next scene only to disambiguate context.\n"
        "Do not mix in people, countries, teams, places, brands, events, or topics that are not present in the full script or that scene context.\n"
        "Rules:\n"
        "- The tool can use structured sources and Google Images via Playwright.\n"
        "- Main search_keyword must be 4-8 words and read like a normal Google Images search typed by a human.\n"
        "- Prefer exact visible subject + event/location/action/time.\n"
        "- If the scene narration names a specific person/player/coach, main_subject MUST be that name, not a generic role. Example: if the sentence says Peri crosses from the right, use main_subject='Peri' and keyword like 'Peri Spain Cape Verde right wing cross'.\n"
        "- Generic subjects like 'Spain winger', 'Cape Verde national football team', 'players', 'team', or 'attacker' are only allowed when the scene has no named person.\n"
        "- Do not use pronouns or vague words from the sentence as entities. Replace They/He/This with the real subject from the full script.\n"
        "- Do not borrow a named entity from another scene unless it is also the correct subject of this scene.\n"
        "- If the script is about a specific sports match, queries must stay inside that match and include both opponents when known.\n"
        "- If match_teams are provided, prefer including both teams for wide match shots, but a query built around one named player/coach/team from that same match is equally valid. Do not force both team names onto a strong single-subject query.\n"
        "- For football scripts, every query must stay around the football topic, the named national teams, named players, match preparation, match action, celebration, coaching, or tournament context.\n"
        "- For football scripts, do not use SportsDB logo/badge/flag-style visuals as scene assets; prefer Google match/team/player photography.\n"
        "- If the script is not sports, do not invent sports terms or sports sources.\n"
        f"- Never request these unless the scene specifically asks for them: {forbidden}, collages, or unrelated generic images.\n"
        "- Bad: football player, soccer, sports, famous, real life action scene, dramatic background.\n"
        "- Good examples depend on context (subject + event/place/time): a named athlete lifting a trophy at a specific tournament and year; NASA Artemis moon rocket launch; Roman Empire marble statue; iPhone factory assembly line.\n"
        "- Do not include abstract filler words like known, considered, important, history, famous, editorial photo, real life, visible context.\n"
        "- Prefer a search phrase a real person would type into Google Images.\n"
        "- Never output malformed phrases that start with a pronoun (e.g. 'They TeamA TeamB') or contain duplicated words (e.g. 'TeamA TeamA TeamB').\n"
        "- Each scene must stay in its own lane. Do not use a player, team, or place from another scene unless that exact entity is also correct for the current scene.\n"
        "- If a real public figure/team/event is mentioned, keep the name.\n"
        "- sportsdb_queries: only for sports entities; otherwise return an empty list.\n"
        "- google_queries: exact subject/context/action, no invented entities and no filler. Put the most specific named-person query first.\n"
        "- Write search_keyword, google_queries, fallback_keywords, and sportsdb_queries in ENGLISH (use the internationally-recognized English spelling of names, teams, places, and competitions), even if the script is in another language.\n"
        "- Include 3-5 fallback_keywords, all specific enough for image search.\n"
        "- For each item return: asset_id, visual_intent, main_subject, action_context, search_keyword, fallback_keywords, sportsdb_queries, google_queries.\n"
        "- Output only valid JSON with key items.\n\n"
        f"FULL SCRIPT:\n{script}\n\n"
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
    for item in items:
        if isinstance(item, dict) and not item.get("asset_id"):
            for typo_key in ("aset_id", "assetid", "asset"):
                if item.get(typo_key):
                    item["asset_id"] = item.get(typo_key)
                    break
    return items


def _call_keyword_ai_openai(api_key: str, model: str, scenes: list[dict], script: str = "") -> list[dict]:
    import requests

    prompt = _keyword_prompt(scenes, script)
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
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL["openai"] = time.time() + 900
        raise _ai_provider_error("openai", response.status_code, response.text)
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    return _parse_keyword_ai_json(content)


def _call_keyword_ai_kiro(api_key: str, base_url: str, model: str, scenes: list[dict], script: str = "") -> list[dict]:
    content = _call_openai_compatible_json(
        provider="kiro",
        api_key=api_key,
        base_url=base_url,
        model=model,
        system="Return strict JSON only.",
        prompt=_keyword_prompt(scenes, script),
        max_tokens=2400,
        temperature=0.2,
        timeout=90,
    )
    return _parse_keyword_ai_json(content)


def _call_keyword_ai_claude(api_key: str, model: str, scenes: list[dict], script: str = "") -> list[dict]:
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get("claude", 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get("claude", 0.0):
        raise RuntimeError("Claude keyword/context đang tạm nghỉ vì hết quota.")

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2400,
            "temperature": 0.2,
            "system": "Return strict JSON only.",
            "messages": [{"role": "user", "content": _keyword_prompt(scenes, script)}],
        },
        timeout=90,
    )
    if response.status_code >= 400:
        if _is_quota_error(response.status_code, response.text):
            _AI_PROVIDER_PAUSE_UNTIL["claude"] = time.time() + 900
        raise _ai_provider_error("claude", response.status_code, response.text)
    data = response.json()
    parts = data.get("content") or []
    content = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    return _parse_keyword_ai_json(content)


def _call_keyword_ai_gemini(api_key: str, model: str, scenes: list[dict], script: str = "") -> list[dict]:
    import requests

    if _AI_PROVIDER_PAUSE_UNTIL.get("gemini", 0.0) and time.time() < _AI_PROVIDER_PAUSE_UNTIL.get("gemini", 0.0):
        raise RuntimeError("Gemini keyword/context đang tạm nghỉ vì hết quota.")

    prompt = _keyword_prompt(scenes, script)
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
        if response.status_code == 429:
            _AI_PROVIDER_PAUSE_UNTIL["gemini"] = time.time() + 900
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


def _scene_entities(item: dict) -> list[str]:
    entities = []
    for key in ("main_subject", "scene_title", "keyword", "ai_search_keyword"):
        value = re.sub(r"\s+", " ", str(item.get(key) or "")).strip()
        if value:
            entities.extend(_capitalized_phrases(value))
    sentence_text = str(item.get("sentence_text") or "")
    entities.extend(_capitalized_phrases(sentence_text))
    cleaned = []
    ignored = {"The", "This", "That", "They", "He", "She", "It", "World Cup"}
    for entity in entities:
        if entity in ignored:
            continue
        if len(entity.split()) == 1 and entity.lower().endswith(("ian", "ese")):
            continue
        if entity not in cleaned:
            cleaned.append(entity)
    return cleaned[:8]


def _scene_action_hint(item: dict, pack=None) -> str:
    """Resolve a short visual action descriptor from the scene text.

    Domain knowledge lives in the pack's action_lexicon (consumed via
    _dp.resolve_action); when no pack matches, fall back to a neutral generic
    descriptor derived from the text, or "" when nothing is obvious."""
    text = " ".join(
        str(item.get(key) or "")
        for key in ("action_context", "visual_intent", "sentence_text")
    ).strip()
    if pack is not None:
        hint = _dp.resolve_action(text, pack)
        if hint:
            return hint
    # Generic neutral fallback: derive a 1-2 word action from obvious English
    # cues in the text; otherwise return empty (no domain assumptions).
    lowered = text.lower()
    generic_cues = (
        ("celebrat", "celebration"),
        ("speech", "speaking"),
        ("interview", "interview"),
        ("crowd", "crowd"),
        ("walk", "walking"),
        ("meeting", "meeting"),
    )
    for needle, descriptor in generic_cues:
        if needle in lowered:
            return descriptor
    return ""


def _scene_type_and_entity(item: dict, teams: list[str], pack=None) -> tuple[str, str]:
    """Map a scene to a (scene_type, entity_type) pair generically, used for
    pack-driven source routing. Keep this mapping small and domain-neutral."""
    action_hint = _scene_action_hint(item, pack).lower()
    main_subject = str(item.get("main_subject") or "").strip()
    has_named_subject = bool(main_subject) and not _is_generic_visual_subject(main_subject, teams)
    two_teams = len(teams) == 2
    entity_type = "team" if (two_teams and not has_named_subject) else ("player" if has_named_subject else "team")
    if "celebrat" in action_hint:
        scene_type = "celebration"
    elif two_teams:
        scene_type = "match_moment"
    elif has_named_subject:
        scene_type = "portrait"
    else:
        scene_type = "general"
    return scene_type, entity_type


def _is_generic_visual_subject(subject: str, teams: list[str] | None = None) -> bool:
    value = re.sub(r"\s+", " ", str(subject or "")).strip().lower()
    if not value:
        return True
    teams = [str(team or "").strip().lower() for team in teams or [] if str(team or "").strip()]
    if value in teams:
        return True
    generic_terms = {
        "team", "teams", "players", "player", "football team", "national football team",
        "squad", "attacker", "defender", "winger", "midfielder", "striker",
        "spanish winger", "spain winger", "cape verde national football team",
    }
    if value in generic_terms:
        return True
    return any(term in value for term in (" national football team", " team", " players", " winger", " attacker", " defender"))


def _scene_named_subject_candidates(item: dict, teams: list[str] | None = None) -> list[str]:
    teams = [str(team or "").strip() for team in teams or [] if str(team or "").strip()]
    ignored = {
        "The", "This", "That", "They", "He", "She", "It", "Its", "Their", "His", "Her",
        "World Cup", "However", "But", "Then", "Now", "Every", "First", "Second",
        "Tiếng", "Đối", "Phút", "Họ", "Cơ", "Cape Verde", "Spain",
    }
    ignored.update(teams)
    text = " ".join(
        str(item.get(key) or "")
        for key in ("sentence_text", "action_context", "visual_intent", "scene_title", "main_subject")
    )
    candidates: list[str] = []
    for phrase in _capitalized_phrases(text):
        phrase = re.sub(r"\s+", " ", phrase).strip(" ,.;:-")
        if not phrase or phrase in ignored:
            continue
        if any(phrase.lower() == team.lower() for team in teams):
            continue
        if phrase.lower().endswith((" stadium", " league", " cup")):
            continue
        if _is_generic_visual_subject(phrase, teams):
            continue
        if phrase not in candidates:
            candidates.append(phrase)
    return candidates[:5]


def _video_context_is_ai(video_context: dict | None) -> bool:
    """True when video_context came from an AI provider (not the local proper-
    noun fallback). Only then can we trust its entities as reliable ENGLISH."""
    source = str((video_context or {}).get("source") or "").strip().lower()
    return bool(source) and source != "local_fallback"


def _ai_entity_words(video_context: dict | None) -> set[str]:
    """ASCII word set of the AI-inferred ENGLISH entities (match_teams,
    main_entities, secondary_entities). Used to reject proper-noun fragments
    scraped from a non-English script — e.g. 'Nha' from 'Bồ Đào Nha' or 'Tuy'
    from 'Tuy nhiên' — while keeping real names the AI also recognized
    ('Cristiano Ronaldo'). Returns empty when the context is not AI-sourced."""
    if not _video_context_is_ai(video_context):
        return set()
    words: set[str] = set()
    for key in ("match_teams", "main_entities", "secondary_entities"):
        for value in (video_context or {}).get(key) or []:
            words.update(word for word in _ascii_words(value) if len(word) > 1)
    return words


def _lock_scene_named_subject(item: dict, script: str, video_context: dict | None = None) -> str:
    teams = [str(value).strip() for value in item.get("match_teams") or (video_context or {}).get("match_teams") or _infer_match_teams(script) if str(value).strip()]
    candidates = _scene_named_subject_candidates(item, teams)
    # On non-English scripts, proper-noun scraping pulls capitalized fragments
    # ("Nha", "Tuy") that are not real subjects. When the AI gave us reliable
    # English entities, keep only candidates corroborated by that set so a
    # fragment can never become the locked subject.
    ai_words = _ai_entity_words(video_context)
    if ai_words:
        candidates = [c for c in candidates if set(_ascii_words(c)) & ai_words]
    current = str(item.get("main_subject") or "").strip()
    if candidates and _is_generic_visual_subject(current, teams):
        item["main_subject"] = candidates[0]
        return candidates[0]
    return current or (candidates[0] if candidates else "")


def _scene_primary_query(item: dict, script: str, video_context: dict | None = None, pack=None) -> str:
    teams = [str(value).strip() for value in item.get("match_teams") or (video_context or {}).get("match_teams") or _infer_match_teams(script) if str(value).strip()]
    subject = _lock_scene_named_subject(item, script, video_context)
    action_hint = _scene_action_hint(item, pack)
    if subject and not _is_generic_visual_subject(subject, teams):
        if len(teams) == 2:
            return _concise_match_query(_dedupe_query_parts(subject, teams[0], teams[1], action_hint), item)
        return _clean_search_keyword(_dedupe_query_parts(subject, action_hint))
    if len(teams) == 2:
        return _concise_match_query(_dedupe_query_parts(teams[0], teams[1], action_hint), item)
    return ""


def _fallback_scene_keywords(item: dict, script: str, video_context: dict | None = None, pack=None) -> list[str]:
    video_context = video_context or {}
    match_teams = [str(value).strip() for value in item.get("match_teams") or video_context.get("match_teams") or [] if str(value).strip()]
    match_teams = list(dict.fromkeys(match_teams))[:2]
    primary_query = _scene_primary_query(item, script, video_context, pack)
    entities = _scene_entities(item)
    main_subject = str(item.get("main_subject") or "").strip()
    if main_subject and main_subject not in entities:
        entities.insert(0, main_subject)
    action_hint = _scene_action_hint(item, pack)
    candidates: list[str] = []

    def add_candidate(*parts: str) -> None:
        query = _concise_match_query(_dedupe_query_parts(*parts), item) if _is_football_script(script) else _clean_search_keyword(_dedupe_query_parts(*parts))
        query = _strip_foreign_context_phrases(query, script, item)
        if not query or _is_generic_keyword(query, str(item.get("sentence_text") or "")):
            return
        if query not in candidates:
            candidates.append(query)

    if primary_query:
        add_candidate(primary_query)
    if len(match_teams) == 2:
        # Two subject entities + a (pack-resolved) action descriptor. The action
        # is generic now — no hardcoded football action strings.
        if main_subject and main_subject.lower() not in {team.lower() for team in match_teams}:
            add_candidate(main_subject, match_teams[0], match_teams[1], action_hint)
        add_candidate(match_teams[0], match_teams[1], action_hint)
    else:
        seed_entities = entities[:2] or list(video_context.get("main_entities") or [])[:2]
        for entity in seed_entities:
            add_candidate(entity, action_hint)
        topic = str(video_context.get("video_topic") or "").strip()
        if topic:
            add_candidate(topic, action_hint)
    if not candidates and pack is not None:
        # Last resort: pack-driven safe fallback templates so a new domain still
        # gets a non-empty, on-topic, slot-filled keyword.
        event_tag = _extract_year_competition(script)
        year = next((tok for tok in event_tag.split() if tok.isdigit()), "")
        competition = event_tag.replace(year, "").strip() if year else event_tag
        subject = (
            main_subject
            or (entities[0] if entities else "")
            or str(video_context.get("video_topic") or "").strip()
        )
        slots = {
            "subject": subject,
            "topic": str(video_context.get("video_topic") or "").strip(),
            "year": year,
            "competition": competition,
            "team": match_teams[0] if match_teams else "",
            "venue": str(item.get("venue") or "").strip(),
        }
        for value in _dp.safe_fallback(slots, pack):
            cleaned = _clean_search_keyword(value)
            if cleaned and cleaned not in candidates:
                candidates.append(cleaned)
    return candidates[:6]


def _score_scene_query(query: str, item: dict, script: str, video_context: dict | None = None, pack=None) -> int:
    query_words = set(_ascii_words(query))
    if not query_words:
        return -999
    score = 0
    sentence_text = str(item.get("sentence_text") or "")
    scene_entities = [value.lower() for value in _scene_entities(item)]
    match_teams = [str(value).strip().lower() for value in item.get("match_teams") or (video_context or {}).get("match_teams") or [] if str(value).strip()]
    main_subject_words = set(_ascii_words(str(item.get("main_subject") or "")))
    named_subject = _lock_scene_named_subject(item, script, video_context)
    named_subject_words = set(_ascii_words(named_subject))
    if named_subject_words and not _is_generic_visual_subject(named_subject, match_teams):
        if query_words & named_subject_words:
            score += 55
        else:
            score -= 70
    if scene_entities:
        if any(token in " ".join(scene_entities) for token in query_words):
            score += 20
    if main_subject_words and query_words & main_subject_words:
        score += 25
    if len(match_teams) == 2:
        team_hits = 0
        for team in match_teams:
            team_words = set(_ascii_words(team))
            if team_words and query_words & team_words:
                team_hits += 1
        score += 18 * team_hits
        if team_hits == 0:
            score -= 40
    # Generic action bonus: any word of the (pack-resolved) action descriptor
    # that also appears in the query earns a small bonus.
    action_hint = _scene_action_hint(item, pack)
    action_words = set(_ascii_words(action_hint)) - STOP_WORDS
    if action_words and (action_words & query_words):
        score += 12
    if _is_generic_keyword(query, sentence_text):
        score -= 35
    if len(query_words) < 3:
        score -= 15
    if len(query_words) > 10:
        score -= 10
    if isinstance(video_context, dict):
        forbidden = [str(value).lower() for value in video_context.get("forbidden_contexts") or [] if str(value).strip()]
        lowered = query.lower()
        if any(term in lowered for term in forbidden if len(term) >= 4):
            score -= 100
    return score


def _sanitize_ai_query_for_context(value: str, item: dict, script: str, video_context: dict | None = None) -> str:
    cleaned = _clean_search_keyword(str(value or ""))
    if not cleaned:
        return ""
    cleaned = _strip_foreign_context_phrases(cleaned, script, item)
    if cleaned and isinstance(video_context, dict):
        forbidden = [str(value).lower() for value in video_context.get("forbidden_contexts") or [] if str(value).strip()]
        lowered = cleaned.lower()
        if any(term in lowered for term in forbidden if len(term) >= 4):
            return ""
    if not cleaned or _is_generic_keyword(cleaned, str(item.get("sentence_text") or "")):
        return ""
    return cleaned


def _apply_keyword_ai_row(item: dict, row: dict, provider: str, script: str = "", video_context: dict | None = None, pack=None) -> dict:
    if pack is None:
        pack = _resolve_pack(script, video_context)
    item["visual_intent"] = str(row.get("visual_intent") or item.get("visual_intent") or "").strip()
    item["main_subject"] = str(row.get("main_subject") or item.get("main_subject") or "").strip()
    item["action_context"] = str(row.get("action_context") or item.get("action_context") or "").strip()
    if isinstance(video_context, dict):
        item["video_topic"] = str(video_context.get("video_topic") or item.get("video_topic") or "").strip()
        item["video_domain"] = str(video_context.get("video_domain") or item.get("video_domain") or "").strip()
    primary_query = _scene_primary_query(item, script, video_context, pack)
    local_keywords = _local_getty_keywords(str(item.get("sentence_text") or ""), pack)
    fallback_context_keywords = _fallback_scene_keywords(item, script, video_context, pack)
    search_keyword = _sanitize_ai_query_for_context(str(row.get("search_keyword") or "").strip(), item, script, video_context)
    fallbacks = row.get("fallback_keywords") if isinstance(row.get("fallback_keywords"), list) else []
    fallbacks = [_sanitize_ai_query_for_context(str(value).strip(), item, script, video_context) for value in fallbacks if str(value).strip()]
    sportsdb_queries = row.get("sportsdb_queries") if isinstance(row.get("sportsdb_queries"), list) else []
    google_queries = row.get("google_queries") if isinstance(row.get("google_queries"), list) else []
    fallbacks = [
        value for value in fallbacks
        if value and not _is_generic_keyword(value, str(item.get("sentence_text") or ""))
    ]
    if _is_generic_keyword(search_keyword, str(item.get("sentence_text") or "")):
        search_keyword = fallback_context_keywords[0] if fallback_context_keywords else local_keywords[0] if local_keywords else str(item.get("keyword") or "")
    merged_fallbacks = []
    for value in [primary_query, *fallbacks, *fallback_context_keywords, *local_keywords]:
        if value and value != search_keyword and value not in merged_fallbacks:
            merged_fallbacks.append(value)
    ranked_queries = [value for value in [search_keyword, *merged_fallbacks] if value]
    ranked_queries = list(dict.fromkeys(ranked_queries))
    ranked_queries.sort(key=lambda value: _score_scene_query(value, item, script, video_context, pack), reverse=True)
    search_keyword = ranked_queries[0] if ranked_queries else ""
    merged_fallbacks = [value for value in ranked_queries[1:] if value != search_keyword]
    if search_keyword:
        item["keyword"] = search_keyword
        item["ai_search_keyword"] = search_keyword
    if merged_fallbacks:
        item["fallback_keywords"] = merged_fallbacks[:5]
    item["sportsdb_queries"] = [_sanitize_ai_query_for_context(value, item, script, video_context) for value in sportsdb_queries]
    item["sportsdb_queries"] = [value for value in item["sportsdb_queries"] if value][:6]
    item["google_queries"] = [_sanitize_ai_query_for_context(value, item, script, video_context) for value in google_queries]
    item["google_queries"] = [value for value in item["google_queries"] if value][:8]
    if primary_query and primary_query not in item["google_queries"]:
        item["google_queries"].insert(0, primary_query)
    if not item["google_queries"]:
        item["google_queries"] = [value for value in [search_keyword, *merged_fallbacks] if value][:4]
    item["google_queries"] = list(dict.fromkeys(item["google_queries"]))
    item["google_queries"].sort(key=lambda value: _score_scene_query(value, item, script, video_context, pack), reverse=True)
    item["sportsdb_queries"] = list(dict.fromkeys(item["sportsdb_queries"]))
    item["keyword_source"] = provider
    item["keyword_ai_scene_refreshed"] = True
    return item


def refresh_asset_keyword_with_ai(
    project: Path,
    item: dict,
    settings: dict | None,
    log: Callable[[str], None] | None = None,
) -> dict:
    settings = settings or {}
    provider, api_key, model = _resolve_keyword_provider(settings)
    if not api_key:
        return item
    script_path = project / "scripts" / "script_final.txt"
    script = script_path.read_text(encoding="utf-8", errors="replace").strip() if script_path.exists() else ""
    video_context = _load_or_build_video_context(project, script, settings, log=log) if script else _build_local_video_context("")
    pack = _resolve_pack(script, video_context, settings=settings, project=project, log=log)
    payload = [
        {
            "asset_id": item.get("asset_id"),
            "scene_text": item.get("sentence_text"),
            "timing": f"{item.get('start')} - {item.get('end')}",
            "video_topic": video_context.get("video_topic"),
            "video_domain": video_context.get("video_domain"),
            "video_main_entities": video_context.get("main_entities") or [],
            "video_visual_boundaries": video_context.get("visual_boundaries") or [],
            "video_forbidden_contexts": video_context.get("forbidden_contexts") or [],
            "main_subject": item.get("main_subject"),
            "action_context": item.get("action_context"),
            "visual_intent": item.get("visual_intent"),
            "current_keyword": item.get("keyword"),
            "match_teams": item.get("match_teams") if isinstance(item.get("match_teams"), list) else video_context.get("match_teams") or [],
        }
    ]
    try:
        if provider == "gemini":
            rows = _call_keyword_ai_gemini(api_key, model, payload, script)
        elif provider == "kiro":
            rows = _call_keyword_ai_kiro(api_key, _kiro_api_base(settings), model, payload, script)
        elif provider == "claude":
            rows = _call_keyword_ai_claude(api_key, model, payload, script)
        else:
            if not api_key.startswith("sk-"):
                raise RuntimeError("OpenAI key phải bắt đầu bằng sk-.")
            rows = _call_keyword_ai_openai(api_key, model, payload, script)
        row = next((value for value in rows if str(value.get("asset_id") or "") == str(item.get("asset_id") or "")), rows[0] if rows else None)
        if row:
            item = _apply_keyword_ai_row(item, row, provider, script, video_context, pack)
            item = _apply_script_visual_context([item], script, video_context, pack)[0]
            if callable(log):
                log(f"{item.get('asset_id')}: AI tạo keyword mới: {item.get('keyword')}")
    except Exception as exc:
        if callable(log):
            log(f"{item.get('asset_id')}: AI keyword lỗi, dùng fallback nội bộ: {exc}")
    return item


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
    require_target_aspect: bool = True,
) -> list[Path]:
    from PIL import Image

    bad_visual_terms = (
        "thumbnail", "youtube", "ytimg", "highlights", "highlight", "full match",
        "replay", "watch live", "livestream", "live stream", "preview", "prediction",
        "lineup", "line-up", "starting xi", "vs poster", "match poster", "wallpaper",
        "graphic", "template", "banner", "cover", "scorecard",
        "tactical analysis", "analysis", "fox sports", "sportv", "maxresdefault",
        "hqdefault", "shorts", "live score",
    )
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
            if require_target_aspect and not _is_target_aspect(width, height, settings):
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
            if any(term in searchable_text.lower() for term in bad_visual_terms):
                continue
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


def _metadata_ranked_images(candidates: list[Path], reason: str) -> list[tuple[Path, dict]]:
    return [
        (
            path,
            {
                "accepted": True,
                "score": 0,
                "reason": reason,
                "fallback": True,
                "validation_mode": "metadata",
            },
        )
        for path in candidates
    ]


def _rank_images_with_gemini(
    candidates: list[Path],
    item: dict,
    settings: dict | None,
    log: Callable[[str], None] | None = None,
    accepted_only: bool = True,
) -> list[tuple[Path, dict]]:
    import requests

    global _VISION_QUOTA_PAUSE_UNTIL
    settings = settings or {}
    api_key = str(settings.get("gemini_api_key") or "").strip()
    enabled = bool(settings.get("image_ai_validation_enabled", True))
    if not enabled or not api_key:
        if enabled and log:
            log(f"{item.get('asset_id')}: chưa có Gemini API key, chỉ chấm theo metadata.")
        return _metadata_ranked_images(candidates, "metadata-only")
    if _VISION_QUOTA_PAUSE_UNTIL and time.time() < _VISION_QUOTA_PAUSE_UNTIL:
        return _metadata_ranked_images(
            candidates,
            "Gemini Vision đang hết quota, tool tạm chọn ảnh theo metadata. Nếu ảnh chưa đúng hãy bấm Tìm lại hoặc Tải media thay thế.",
        )

    primary_model = str(settings.get("gemini_vision_model") or settings.get("gemini_keyword_model") or "gemini-2.5-flash")
    models = [primary_model]
    minimum_score = max(1, min(100, int(settings.get("image_ai_min_score") or 55)))
    if _item_in_detected_domain(item) or _is_match_photography_item(item):
        minimum_score = min(minimum_score, 55)
    teams = [str(value) for value in item.get("match_teams") or [] if str(value).strip()]
    inferred_subject, _inferred_action = _scene_match_action(item, teams)
    subject = str(item.get("main_subject") or inferred_subject or "").strip()
    sentence = str(item.get("sentence_text") or "").strip()
    keyword = str(item.get("keyword") or "").strip()
    action = str(item.get("action_context") or "").strip()
    global_context = str(item.get("global_visual_context") or "").strip()
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
                "Use source title/page as supporting evidence: if the title/page clearly names a different subject "
                "or misses the required named person/action, lower the score unless the image itself clearly proves it. "
                "Reject national flags, federation logos, team badges, emblems, flat icons, and low-information symbolic images "
                "unless the narration explicitly asks for a flag/logo explanation. "
                "Return JSON only: {\"items\":[{\"index\":1,\"accepted\":true,"
                "\"score\":0-100,\"visible_subject\":\"...\",\"reason\":\"...\"}]}. "
                f"Accept only scores >= {minimum_score}.\n"
                f"Full video topic/context: {global_context}\n"
                f"Scene narration: {sentence}\n"
                f"Required main subject: {subject or 'no single named person'}\n"
                f"Required teams/event: {', '.join(teams) or 'use narration and keyword'}\n"
                f"Required action/context: {action}\n"
                f"Search keyword: {keyword}"
            )
        }
    ]
    included: list[Path] = []
    for index, path in enumerate(candidates[:8], start=1):
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
            timeout=18,
        )
        if response.status_code < 400:
            break
        errors.append(f"{model}: HTTP {response.status_code}")
        if response.status_code == 429:
            _VISION_QUOTA_PAUSE_UNTIL = time.time() + 3600
            if log:
                log(
                    f"{item.get('asset_id')}: Gemini Vision hết quota; "
                    "tool sẽ tạm chọn ảnh theo metadata, có thể bấm Tìm lại nếu ảnh chưa đúng."
                )
            return _metadata_ranked_images(
                candidates,
                "Gemini Vision hết quota, đã chuyển sang chọn ảnh thường. Nếu ảnh chưa đúng hãy bấm Tìm lại.",
            )
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
    return [value for value in decisions if value[1].get("accepted")] if accepted_only else decisions


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
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    options = _image_filter_settings(settings)
    with Image.open(source) as image:
        image = image.convert("RGB")
        target_width = int(options["target_width"])
        target_height = int(options["target_height"])
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        if not _is_target_aspect(int(image.width), int(image.height), settings):
            background = ImageOps.fit(image, (target_width, target_height), method=resampling)
            background = background.filter(ImageFilter.GaussianBlur(radius=max(18, target_width // 80)))
            background = ImageEnhance.Brightness(background).enhance(0.48)
            foreground = ImageOps.contain(image, (target_width, target_height), method=resampling)
            x = (target_width - foreground.width) // 2
            y = (target_height - foreground.height) // 2
            background.paste(foreground, (x, y))
            image = background
        elif image.width != target_width or image.height != target_height:
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
        "players competing", "game action", "editorial photography",
        "editorial photo", "editoria photo", "sports photography", "real photo",
        "after final whistle", "team lineup match",
    )
    for phrase in removable_phrases:
        query = re.sub(rf"\b{re.escape(phrase)}\b", " ", query, flags=re.I)
    # Strip standalone numeric match scores (e.g. "3-0", "2-1"); image databases
    # are not indexed by scores.
    query = re.sub(r"\b\d+[-–]\d+\b", " ", query)
    banned_words = (
        "thumbnail", "poster", "wallpaper", "graphic", "logo", "badge", "preview",
        "photo",
    )
    query = " ".join(
        word for word in query.split()
        if word.lower() not in banned_words
    )
    query = _dedupe_query_words(re.sub(r"\s+", " ", query).strip())
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
        "strFanart4", "strStadiumThumb",
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


def _google_tbs(date_min: str) -> str:
    """Convert a 'YYYY-MM-DD' or 'YYYY' anchor into a Google Images date filter
    (tbs=cdr:1,cd_min:MM/DD/YYYY). Returns '' when no usable year is present."""
    value = str(date_min or "").strip()
    if not value:
        return ""
    match = re.match(r"^(\d{4})(?:-(\d{1,2})-(\d{1,2}))?$", value)
    if not match:
        return ""
    year = match.group(1)
    month = match.group(2) or "1"
    day = match.group(3) or "1"
    return f"cdr:1,cd_min:{int(month):02d}/{int(day):02d}/{year}"


def _fetch_google_images(
    project: Path,
    folder: Path,
    queries: list[str],
    count: int = 12,
    excluded_urls: set[str] | None = None,
    excluded_dhashes: set[int] | None = None,
    skip_results: int = 0,
    settings: dict | None = None,
    tbs: str = "",
) -> int:
    worker_path = Path(__file__).parent.parent / "images" / "google_images_worker.py"
    downloaded = 0
    target_count = max(1, min(12, int(count)))
    configured_profile = str((settings or {}).get("google_images_profile") or "").strip()
    default_profile = str(Path(__file__).resolve().parents[1] / "chrome_google_images_profile")
    profile_path = configured_profile or default_profile
    captcha_seen = False
    network_seen = False
    for query_index, query in enumerate(queries[:3], start=1):
        if downloaded >= target_count:
            break
        query_target = min(4, target_count - downloaded)
        query_dir = folder / f"google_{query_index:02d}"
        query_dir.mkdir(parents=True, exist_ok=True)
        run_logs = []
        for worker_attempt in range(2):
            if captcha_seen:
                break
            request_path = query_dir / f"_request_{worker_attempt + 1}.json"
            attempt_profile = "" if worker_attempt == 0 else profile_path
            write_json(
                request_path,
                {
                    "query": query,
                    "output": str(query_dir),
                    "count": query_target,
                    "profile": attempt_profile,
                    "headed": False,
                    "exclude_urls": sorted(excluded_urls or set()),
                    "exclude_dhashes": sorted(excluded_dhashes or set()),
                    "skip_results": skip_results + worker_attempt,
                    "tbs": str(tbs or ""),
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
                    timeout=25,
                    check=False,
                )
                run_logs.append(
                    f"attempt={worker_attempt + 1} returncode={result.returncode}\n"
                    f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                )
                try:
                    worker_data = json.loads(str(result.stdout or "").strip())
                    if isinstance(worker_data, dict) and worker_data.get("captcha"):
                        captcha_seen = True
                    if isinstance(worker_data, dict) and worker_data.get("network_error"):
                        network_seen = True
                except Exception:
                    if "captcha" in str(result.stdout or "").lower() or "unusual traffic" in str(result.stdout or "").lower():
                        captcha_seen = True
                    if "err_name_not_resolved" in str(result.stderr or "").lower() or "net::err" in str(result.stderr or "").lower():
                        network_seen = True
            except Exception as exc:
                run_logs.append(f"attempt={worker_attempt + 1} error={exc}")
                if "timed out" in str(exc).lower():
                    network_seen = True
            image_files = [
                path
                for path in query_dir.glob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ]
            if len(image_files) >= query_target:
                break
            if captcha_seen:
                break
            time.sleep(0.2)
        (query_dir / "_worker.log").write_text("\n\n".join(run_logs), encoding="utf-8")
        downloaded += len(
            [
                path
                for path in query_dir.glob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            ]
        )
    if downloaded <= 0 and captcha_seen:
        return -1
    if downloaded <= 0 and network_seen:
        return -2
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
        existing_path = Path(existing_path_text) if existing_path_text else None
        if existing_path and existing_path.is_file():
            perceptual = _image_dhash(existing_path)
            if perceptual is not None:
                excluded_dhashes.add(perceptual)
    errors: list[str] = []

    match_photography = _is_match_photography_item(item)
    sportsdb_queries = _source_queries(item, "sportsdb_queries", [])
    google_queries = _source_queries(item, "google_queries", [])
    # Recency anchor (e.g. competition year for football) -> Google date filter.
    image_tbs = _google_tbs(str(item.get("search_date_min") or ""))
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
                    count=4,
                    excluded_urls=excluded_urls,
                    excluded_dhashes=excluded_dhashes,
                    skip_results=0,
                    settings=settings,
                    tbs=image_tbs,
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
                    count=10,
                    excluded_urls=excluded_urls,
                    excluded_dhashes=excluded_dhashes,
                    skip_results=0,
                    settings=settings,
                    tbs=image_tbs,
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
        used_aspect_fallback = False
        if not candidates:
            candidates = _valid_crawled_images(
                source_dir,
                excluded_hashes,
                excluded_dhashes,
                query=query_text,
                settings=settings,
                min_keyword_score=0,
                require_target_aspect=False,
            )
            used_aspect_fallback = bool(candidates)
        if candidates:
            vision_required = (
                bool((settings or {}).get("image_ai_validation_enabled", True))
                and bool(str((settings or {}).get("gemini_api_key") or "").strip())
                and (
                    match_photography
                    or _item_in_detected_domain(item)
                )
            )
            try:
                ranked = _rank_images_with_gemini(
                    candidates,
                    item,
                    settings,
                    log=log,
                    accepted_only=not vision_required,
                )
            except Exception as exc:
                ranked = []
                if log:
                    if vision_required:
                        log(f"{item.get('asset_id')}: Gemini Vision chậm/lỗi ({exc}); sẽ dùng ảnh dự phòng nếu có.")
                    else:
                        log(f"{item.get('asset_id')}: Gemini Vision chậm/lỗi ({exc}); dùng ảnh dự phòng.")
            if not ranked:
                candidate = candidates[0]
                vision_decision = {
                    "accepted": True,
                    "score": 0,
                    "reason": (
                        "Gemini Vision không chọn được ảnh đủ điểm; dùng ứng viên tốt nhất "
                        "để tránh thiếu media. Người dùng có thể bấm Tìm lại nếu chưa phù hợp."
                    ),
                    "fallback": True,
                }
                if log:
                    log(f"{item.get('asset_id')}: Gemini loại toàn bộ; dùng ảnh dự phòng tốt nhất.")
            else:
                candidate, vision_decision = ranked[0]
                if vision_required and not vision_decision.get("accepted"):
                    vision_decision = {
                        **vision_decision,
                        "accepted": True,
                        "fallback": True,
                        "reason": (
                            f"AI chấm dưới ngưỡng nhưng dùng ảnh điểm cao nhất để tránh thiếu media. "
                            f"{vision_decision.get('reason') or ''}"
                        ).strip(),
                    }
                    if log:
                        log(f"{item.get('asset_id')}: dùng ảnh điểm cao nhất dù dưới ngưỡng ({vision_decision.get('score')}/100).")
            metadata_path = candidate.with_suffix(candidate.suffix + ".json")
            metadata = read_json(metadata_path, {}) if metadata_path.exists() else {}
            metadata["vision"] = vision_decision
            metadata["aspect_fallback"] = used_aspect_fallback
            return candidate, len(candidates), f"{source_name}: {query_text}", metadata
        if downloaded < 0:
            if downloaded == -1:
                errors.append(
                    f"{source_name}: Google đang bắt captcha/chặn Playwright. "
                    "Hãy chờ vài phút hoặc mở Chrome profile Google Images để xác thực, tool sẽ thử lại bằng keyword đã tạo."
                )
            else:
                errors.append(
                    f"{source_name}: lỗi mạng/DNS hoặc Google phản hồi quá chậm, chưa tải được file ảnh nào."
                )
            continue
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
    if reject_current or not item.get("keyword_ai_scene_refreshed"):
        item = refresh_asset_keyword_with_ai(project, item, settings, log)
    if not item.get("prompt_keyword_locked"):
        script_path = project / "scripts" / "script_final.txt"
        if script_path.exists():
            script_text = script_path.read_text(encoding="utf-8", errors="replace").strip()
            if script_text:
                item = _apply_script_visual_context([item], script_text)[0]
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
                "image_processing": "16:9-preferred,aspect-fallback-letterbox,optional-realesrgan,resize-sharpen",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "raw_sha256": hashlib.sha256(raw_target.read_bytes()).hexdigest(),
                "error": "",
            }
        )
        aspect_note = "ưu tiên 16:9" if not candidate_metadata.get("aspect_fallback") else "dùng tỷ lệ dự phòng và đặt vào khung 16:9"
        log(f"{item['asset_id']}: tải {candidate_count} ảnh ({aspect_note}) bằng {matched_query}, chọn {target.name} ({width}x{height})")
    except Exception as exc:
        old_path_text = str(item.get("local_path") or "").strip()
        old_path = Path(old_path_text) if old_path_text else None
        reusable = None
        if (
            _is_match_photography_item(item)
            and (reject_current or not (old_path and old_path.is_file()))
        ):
            match_teams = {str(value).lower() for value in item.get("match_teams") or [] if str(value).strip()}
            rejected_hashes = {
                str(value).strip() for value in item.get("rejected_hashes") or [] if str(value).strip()
            }
            rejected_dhashes = {
                int(value) for value in item.get("rejected_dhashes") or [] if str(value).strip()
            }
            rejected_current_path = str(item.get("rejected_current_path") or "").strip()
            for existing in load_manifest(project):
                existing_path_text = str(existing.get("local_path") or "").strip()
                existing_path = Path(existing_path_text) if existing_path_text else None
                existing_teams = {
                    str(value).lower() for value in existing.get("match_teams") or [] if str(value).strip()
                }
                if str(existing.get("asset_id") or "") == str(item.get("asset_id") or ""):
                    continue
                if not existing_path or not existing_path.is_file():
                    continue
                if rejected_current_path and str(existing_path) == rejected_current_path:
                    continue
                if match_teams and existing_teams and existing_teams != match_teams:
                    continue
                try:
                    digest = hashlib.sha256(existing_path.read_bytes()).hexdigest()
                except Exception:
                    digest = ""
                if digest and digest in rejected_hashes:
                    continue
                perceptual = _image_dhash(existing_path)
                if perceptual is not None and any((perceptual ^ old).bit_count() <= 6 for old in rejected_dhashes):
                    continue
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
                    "error": f"Google chưa tải được ảnh mới; đã dùng tạm ảnh cùng trận từ {existing.get('asset_id')}. {exc}",
                }
            )
            log(f"{item['asset_id']}: Google chưa tải được ảnh mới, dùng tạm ảnh cùng trận từ {existing.get('asset_id')}.")
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
    # Repo root (== config.APP_DIR) is parents[2]: app/pipeline/visual_pipeline.py →
    # toolBongda/. parents[1] is the app/ package, where capcut_template/Projects do
    # NOT live, so the bundled template was never found and export always failed when
    # the user had no CapCut drafts.
    app_root = Path(__file__).resolve().parents[2]
    bundled = app_root / "capcut_template"
    capcut_candidates = [
        path for path in capcut_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ] if capcut_root.exists() else []
    portable_candidates = sorted(
        {
            path.parent
            for path in (app_root / "Projects").rglob("draft_content.json")
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
