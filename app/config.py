from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PATH = APP_DIR / "settings.json"


def default_projects_dir() -> Path:
    return Path.home() / "Videos" / "VisualCapCutStudio" / "Projects"


def _expand_config_path(value: str | Path | None) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path()
    return Path(os.path.expandvars(raw)).expanduser()


DEFAULT_SETTINGS = {
    "projects_dir": str(default_projects_dir()),
    "text_to_voice_root": str(APP_DIR / "kokoro-tts-local"),
    "text_to_voice_python": "",
    "text_to_voice_language": "en",
    "text_to_voice_voice": "af_heart",
    "text_to_voice_delivery": "dramatic",
    "text_to_voice_speed": 1.0,
    "text_to_voice_max_chars": 10000,
    "text_to_voice_timeout": 1800,
    "voice_clone_enabled": False,
    "voice_clone_engine": "magicvoice",
    "voice_clone_reference_path": "",
    "voice_clone_reference_name": "",
    "voice_clone_preview_url": "",
    "voice_clone_profiles": [],
    "voice_clone_default_id": "",
    "voice_clone_max_chars": 480,
    "voice_clone_timeout": 3600,
    "voice_clone_setup_timeout": 3600,
    "magicvoice_root": str(APP_DIR / "magic_voice"),
    "magicvoice_steps": 16,
    "magicvoice_sentence_pause": 0.28,
    "magicvoice_clause_pause": 0.12,
    "magicvoice_paragraph_pause": 0.43,
    "magicvoice_clarity_speed": 0.96,
    "magicvoice_batch_size": 1,
    "magicvoice_dtype": "auto",
    "magicvoice_device": "auto",
    "whisper_python": sys.executable,
    "whisper_timing_enabled": True,
    "whisper_timing_model": "base",
    "whisper_timing_beam_size": 5,
    "scene_ai_enabled": True,
    "scene_min_seconds": 4.0,
    "scene_target_max_seconds": 25.0,
    "scene_hard_max_seconds": 45.0,
    "capcut_exe_path": "",
    "google_images_profile": str(APP_DIR / "chrome_google_images_profile"),
    "getty_images_profile": str(APP_DIR / "chrome_getty_images_profile"),
    "bing_images_profile": str(APP_DIR / "chrome_bing_images_profile"),
    "openai_api_key": "",
    "keyword_ai_model": "gpt-4.1-mini",
    "keyword_ai_provider": "auto",
    "kiro_api_key": "",
    "kiro_api_base": "https://xapi.labpinky.com/v1",
    "kiro_keyword_model": "kr/claude-opus-4.8",
    "claude_api_key": "",
    "claude_keyword_model": "claude-sonnet-4-20250514",
    "gemini_api_key": "",
    "gemini_keyword_model": "gemini-2.5-flash",
    "gemini_vision_model": "gemini-2.5-flash",
    "image_ai_validation_enabled": True,
    "image_ai_min_score": 55,
    "image_search_parallel_jobs": 1,
    "script_workflow_input": "",
    "script_workflow_steps": [
        {
            "enabled": True,
            "name": "Phân tích đề tài",
            "prompt": (
                "Analyze the topic/source. Identify the audience, angle, key facts, named entities, "
                "timeline, and the strongest visual moments. Do not write the final script yet."
            ),
        },
        {
            "enabled": True,
            "name": "Lập dàn ý",
            "prompt": (
                "Turn the analysis into a coherent video outline with a strong opening, logical body, "
                "specific events, and a concise conclusion. Remove repetition."
            ),
        },
        {
            "enabled": True,
            "name": "Viết script final",
            "prompt": (
                "Write the final voice-over script in natural English. Use complete spoken sentences, "
                "keep factual names and events specific, and output only the narration. Do not include "
                "headings, notes, visual instructions, or workflow commentary."
            ),
        },
    ],
    "active_workflow_id": "general-video",
    "workflow_presets": [
        {
            "id": "general-video",
            "name": "Video tổng hợp",
            "description": "Dùng cho tin tức, thể thao, lịch sử, khoa học và các chủ đề phổ thông.",
            "steps": [
                {
                    "enabled": True,
                    "name": "Hiểu chủ đề",
                    "prompt": (
                        "Analyze the source and identify the audience, angle, verified facts, named "
                        "entities, timeline, and strongest visual moments. Do not write the final script yet."
                    ),
                },
                {
                    "enabled": True,
                    "name": "Lập dàn ý",
                    "prompt": (
                        "Create a coherent video outline with a clear opening, logical body, specific "
                        "events, and a concise conclusion. Remove repetition."
                    ),
                },
                {
                    "enabled": True,
                    "name": "Viết lời đọc cuối",
                    "prompt": (
                        "Write the final natural voice-over script. Output narration only, without "
                        "headings, notes, citations, or visual instructions."
                    ),
                },
            ],
        }
    ],
    "image_aspect_width": 16,
    "image_aspect_height": 9,
    "image_aspect_tolerance": 0.025,
    "image_min_width": 600,
    "image_min_height": 330,
    "image_enhance_enabled": True,
    "image_target_width": 1920,
    "image_target_height": 1080,
    "image_ai_upscale_enabled": False,
    "realesrgan_exe_path": "",
    "realesrgan_model": "realesrgan-x4plus",
    "realesrgan_scale": 2,
}


def load_settings() -> dict:
    data = {}
    try:
        parsed = json.loads(SETTINGS_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        pass
    settings = dict(DEFAULT_SETTINGS)
    settings.update(data)
    old_kiro_model = str(settings.get("kiro_keyword_model") or "").strip()
    if old_kiro_model in {
        "",
        "kiro/claude-sonnet-4.6",
        "Claude Sonnet 4.6 (Kiro)",
        "Claude Sonnet 4.6",
        "nghi/claude-sonnet-4.6",
        "nghi/claude-opus-4.8",
    }:
        settings["kiro_keyword_model"] = "kr/claude-opus-4.8"
    if str(settings.get("kiro_api_base") or "").strip().rstrip("/") in {
        "https://q.us-east-1.amazonaws.com",
        "https://api.nghimmo.com",
        "https://xapi.labpinky.com",
    }:
        settings["kiro_api_base"] = "https://xapi.labpinky.com/v1"
    try:
        settings["text_to_voice_speed"] = max(0.5, min(2.0, float(settings.get("text_to_voice_speed") or 1.0)))
    except (TypeError, ValueError):
        settings["text_to_voice_speed"] = 1.0
    try:
        settings["magicvoice_steps"] = max(8, min(16, int(settings.get("magicvoice_steps") or 16)))
    except (TypeError, ValueError):
        settings["magicvoice_steps"] = 16
    try:
        settings["magicvoice_batch_size"] = 1
    except (TypeError, ValueError):
        settings["magicvoice_batch_size"] = 1
    try:
        clone_chars = int(settings.get("voice_clone_max_chars") or 480)
        settings["voice_clone_max_chars"] = 480 if clone_chars >= 900 else max(280, min(clone_chars, 720))
    except (TypeError, ValueError):
        settings["voice_clone_max_chars"] = 480
    if str(settings.get("magicvoice_dtype") or "").strip().lower() in {"", "float16", "fp16"}:
        settings["magicvoice_dtype"] = "auto"
    try:
        if float(settings.get("scene_target_max_seconds") or 0) <= 10.0:
            settings["scene_target_max_seconds"] = 25.0
        if float(settings.get("scene_hard_max_seconds") or 0) <= 15.0:
            settings["scene_hard_max_seconds"] = 45.0
    except (TypeError, ValueError):
        settings["scene_target_max_seconds"] = 25.0
        settings["scene_hard_max_seconds"] = 45.0
    for deprecated_key in (
        "text_to_voice_mode",
        "chatterbox_exaggeration",
        "chatterbox_cfg_weight",
        "chatterbox_temperature",
        "chatterbox_seed",
        "chatterbox_min_p",
        "chatterbox_top_p",
        "chatterbox_repetition_penalty",
        "chatterbox_max_words",
        "chatterbox_whisper_qa",
        "chatterbox_hf_home",
        "koko" + "clone_root",
    ):
        settings.pop(deprecated_key, None)
    old_clone_engine = "koko" + "clone"
    if str(settings.get("voice_clone_engine") or "").strip().lower() in {"", old_clone_engine}:
        settings["voice_clone_engine"] = "magicvoice"
    profiles = settings.get("voice_clone_profiles")
    if not isinstance(profiles, list):
        profiles = []
    profiles = [
        item for item in profiles
        if isinstance(item, dict)
        and str(item.get("path") or "").strip()
        and _expand_config_path(item.get("path")).is_file()
    ]
    legacy_raw = str(settings.get("voice_clone_reference_path") or "").strip()
    legacy_ref = _expand_config_path(legacy_raw)
    if legacy_raw and legacy_ref.is_file() and not any(_expand_config_path(item.get("path")).resolve() == legacy_ref.resolve() for item in profiles):
        legacy_name = str(settings.get("voice_clone_reference_name") or legacy_ref.stem).strip() or legacy_ref.stem
        legacy_profile = {
            "id": uuid.uuid5(uuid.NAMESPACE_URL, str(legacy_ref.resolve())).hex[:12],
            "name": legacy_name,
            "language": str(settings.get("text_to_voice_language") or "vi"),
            "country": "",
            "path": str(legacy_ref.resolve()),
            "file_name": legacy_ref.name,
            "created_at": int(legacy_ref.stat().st_mtime),
        }
        profiles.insert(0, legacy_profile)
        settings["voice_clone_default_id"] = legacy_profile["id"]
    settings["voice_clone_profiles"] = profiles
    configured_voice_root = str(settings.get("text_to_voice_root") or "").strip().lower()
    configured_voice_root_path = _expand_config_path(settings.get("text_to_voice_root"))
    if configured_voice_root_path and not configured_voice_root_path.is_absolute():
        configured_voice_root_path = APP_DIR / configured_voice_root_path
    if (
        not configured_voice_root
        or "chatterbox" in configured_voice_root
        or configured_voice_root.endswith("\\magic_voice")
        or not (configured_voice_root_path / "app.py").is_file()
    ):
        settings["text_to_voice_root"] = str(APP_DIR / "kokoro-tts-local")
        settings["text_to_voice_python"] = ""
    configured_voice_python = _expand_config_path(settings.get("text_to_voice_python"))
    if configured_voice_python and not configured_voice_python.is_absolute():
        configured_voice_python = APP_DIR / configured_voice_python
    if configured_voice_python and not configured_voice_python.is_file():
        settings["text_to_voice_python"] = ""
    configured_magic_root = _expand_config_path(settings.get("magicvoice_root"))
    if configured_magic_root and not configured_magic_root.is_absolute():
        configured_magic_root = APP_DIR / configured_magic_root
    if not (
        (configured_magic_root / "setup_visual_capcut.ps1").is_file()
        or (configured_magic_root / "setup.sh").is_file()
    ):
        settings["magicvoice_root"] = str(APP_DIR / "magic_voice")
        settings["magicvoice_python"] = ""
    if str(settings.get("text_to_voice_voice") or "").strip() not in {
        "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore",
        "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky", "am_adam",
        "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
        "am_puck", "am_santa", "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
        "bm_daniel", "bm_fable", "bm_george", "bm_lewis", "ef_dora", "em_alex",
        "em_santa", "ff_siwis", "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
        "if_sara", "im_nicola", "jf_alpha", "jf_gongitsune", "jf_nezumi",
        "jf_tebukuro", "jm_kumo", "pf_dora", "pm_alex", "pm_santa", "zf_xiaobei",
        "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi",
        "zm_yunxia", "zm_yunyang",
    }:
        settings["text_to_voice_voice"] = "af_heart"
    projects = _expand_config_path(settings.get("projects_dir"))
    repo_projects = (APP_DIR / "Projects").resolve()
    if not projects or str(projects).strip() in {".", "Projects"}:
        projects = default_projects_dir()
    elif not projects.is_absolute():
        projects = default_projects_dir().parent / projects
    try:
        if projects.resolve() == repo_projects:
            projects = default_projects_dir()
    except Exception:
        pass
    projects.mkdir(parents=True, exist_ok=True)
    settings["projects_dir"] = str(projects)
    return settings


def save_settings(settings: dict) -> None:
    data = dict(DEFAULT_SETTINGS)
    data.update(settings or {})
    try:
        data["text_to_voice_speed"] = max(0.5, min(2.0, float(data.get("text_to_voice_speed") or 1.0)))
    except (TypeError, ValueError):
        data["text_to_voice_speed"] = 1.0
    try:
        data["magicvoice_steps"] = max(8, min(16, int(data.get("magicvoice_steps") or 16)))
    except (TypeError, ValueError):
        data["magicvoice_steps"] = 16
    try:
        data["magicvoice_batch_size"] = 1
    except (TypeError, ValueError):
        data["magicvoice_batch_size"] = 1
    try:
        clone_chars = int(data.get("voice_clone_max_chars") or 480)
        data["voice_clone_max_chars"] = 480 if clone_chars >= 900 else max(280, min(clone_chars, 720))
    except (TypeError, ValueError):
        data["voice_clone_max_chars"] = 480
    if str(data.get("magicvoice_dtype") or "").strip().lower() in {"", "float16", "fp16"}:
        data["magicvoice_dtype"] = "auto"
    projects = _expand_config_path(data.get("projects_dir")) or default_projects_dir()
    if not projects.is_absolute():
        projects = default_projects_dir().parent / projects
    data["projects_dir"] = str(projects)
    projects.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
