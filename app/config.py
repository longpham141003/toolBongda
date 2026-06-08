from __future__ import annotations

import json
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PATH = APP_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "projects_dir": str(APP_DIR / "Projects"),
    "text_to_voice_root": str(APP_DIR / "magic_voice"),
    "text_to_voice_python": "",
    "text_to_voice_language": "en",
    "text_to_voice_voice": "factory_vien_male",
    "text_to_voice_mode": "standard",
    "text_to_voice_delivery": "dramatic",
    "text_to_voice_speed": 1.0,
    "chatterbox_exaggeration": 0.9,
    "chatterbox_cfg_weight": 0.5,
    "chatterbox_temperature": 0.8,
    "chatterbox_seed": 0,
    "chatterbox_min_p": 0.05,
    "chatterbox_top_p": 1.0,
    "chatterbox_repetition_penalty": 1.2,
    "text_to_voice_max_chars": 10000,
    "text_to_voice_timeout": 1800,
    "chatterbox_max_words": 40,
    "chatterbox_whisper_qa": True,
    "chatterbox_hf_home": str(APP_DIR / ".hf-cache"),
    "whisper_timing_enabled": True,
    "whisper_timing_model": "base",
    "whisper_timing_beam_size": 5,
    "scene_ai_enabled": True,
    "scene_min_seconds": 3.0,
    "scene_target_max_seconds": 10.0,
    "capcut_exe_path": "",
    "google_images_profile": str(APP_DIR / "chrome_google_images_profile"),
    "getty_images_profile": str(APP_DIR / "chrome_getty_images_profile"),
    "bing_images_profile": str(APP_DIR / "chrome_bing_images_profile"),
    "openai_api_key": "",
    "keyword_ai_model": "gpt-4.1-mini",
    "keyword_ai_provider": "auto",
    "gemini_api_key": "",
    "gemini_keyword_model": "gemini-2.5-flash",
    "gemini_vision_model": "gemini-2.5-flash",
    "image_ai_validation_enabled": True,
    "image_ai_min_score": 72,
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
    legacy_voice_root = r"C:\Users\longp\Downloads\SRT & Audio Vien\Chatterbox_Tool"
    if str(settings.get("text_to_voice_root") or "").strip() == legacy_voice_root:
        settings["text_to_voice_root"] = str(APP_DIR / "magic_voice")
    projects = Path(str(settings.get("projects_dir") or ""))
    if not projects.is_absolute():
        projects = APP_DIR / projects
    settings["projects_dir"] = str(projects)
    return settings


def save_settings(settings: dict) -> None:
    data = dict(DEFAULT_SETTINGS)
    data.update(settings or {})
    Path(str(data["projects_dir"])).mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
