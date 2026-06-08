from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import APP_DIR, load_settings, save_settings
from .script_workflow import default_workflow_steps, normalize_workflow_steps, run_script_workflow
from .text_to_voice_queue import TextToVoiceRunner, chatterbox_voice_choices
from .visual_pipeline import (
    _concise_match_query,
    IMAGE_SUFFIXES,
    VIDEO_SUFFIXES,
    attach_local_media_to_asset,
    build_asset_manifest,
    create_visual_project,
    export_capcut_project,
    generate_voice,
    load_manifest,
    optimize_asset_keywords_with_ai,
    save_manifest,
    search_and_download_asset,
)


WEB_DIST = APP_DIR / "webui" / "dist"
STATE_PATH = APP_DIR / ".webui_state"


class ProjectCreateRequest(BaseModel):
    title: str = ""
    script: str


class ProjectOpenRequest(BaseModel):
    path: str


class SettingsRequest(BaseModel):
    settings: dict[str, Any]


class ScriptRequest(BaseModel):
    script: str


class WorkflowRequest(BaseModel):
    source_input: str
    steps: list[dict[str, Any]]
    settings: dict[str, Any] | None = None


class VoicePreviewRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    text: str = ""


class ExportRequest(BaseModel):
    title: str = ""


class KeywordRequest(BaseModel):
    keyword: str


IMAGE_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm", ".mp4"}


def _normalize_workflow_presets(values: Any) -> list[dict[str, Any]]:
    presets: list[dict[str, Any]] = []
    if not isinstance(values, list):
        return presets
    for raw in values:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()[:80]
        if not name:
            continue
        preset_id = str(raw.get("id") or "").strip() or uuid.uuid4().hex[:10]
        presets.append(
            {
                "id": preset_id,
                "name": name,
                "description": str(raw.get("description") or "").strip()[:260],
                "steps": normalize_workflow_steps(raw.get("steps")) or default_workflow_steps(),
            }
        )
    return presets


class Job:
    def __init__(self, name: str, *, kind: str = "", asset_id: str = ""):
        self.id = uuid.uuid4().hex
        self.name = name
        self.kind = kind
        self.asset_id = asset_id
        self.status = "queued"
        self.queue_position = 0
        self.progress = 0
        self.determinate = False
        self.completed_units = 0
        self.total_units = 0
        self.current_label = ""
        self.logs: list[str] = []
        self.result: Any = None
        self.error = ""
        self.created_at = time.time()
        self.updated_at = self.created_at

    def log(self, message: str) -> None:
        text = str(message)
        self.logs.append(text)
        self.logs = self.logs[-500:]
        self.updated_at = time.time()

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "asset_id": self.asset_id,
            "status": self.status,
            "queue_position": self.queue_position,
            "progress": self.progress,
            "determinate": self.determinate,
            "completed_units": self.completed_units,
            "total_units": self.total_units,
            "current_label": self.current_label,
            "logs": self.logs,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RuntimeState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self.active_job_id: str | None = None
        self.pending_jobs: list[tuple[Job, Callable[[Job], Any]]] = []
        self.current_project = self._load_current_project()

    def _load_current_project(self) -> Path | None:
        try:
            path = Path(STATE_PATH.read_text(encoding="utf-8").strip())
            if (path / "scripts" / "script_final.txt").exists():
                return path
        except Exception:
            pass
        return None

    def set_project(self, project: Path) -> None:
        project = project.resolve()
        self.current_project = project
        STATE_PATH.write_text(str(project), encoding="utf-8")

    def require_project(self) -> Path:
        project = self.current_project
        if not project or not (project / "scripts" / "script_final.txt").exists():
            raise HTTPException(status_code=400, detail="Chưa chọn project. Hãy tạo hoặc mở project trước.")
        return project

    def _refresh_queue_positions(self) -> None:
        for index, (job, _callback) in enumerate(self.pending_jobs, start=1):
            job.queue_position = index
            job.updated_at = time.time()

    def _launch_job(self, job: Job, callback: Callable[[Job], Any]) -> None:
        self.active_job_id = job.id
        job.queue_position = 0

        def runner() -> None:
            job.status = "running"
            job.updated_at = time.time()
            try:
                job.result = callback(job)
                job.progress = 100
                job.status = "done"
            except Exception as exc:
                job.error = str(exc)
                job.log(f"LỖI: {exc}")
                job.status = "failed"
            finally:
                job.updated_at = time.time()
                next_job: tuple[Job, Callable[[Job], Any]] | None = None
                with self.lock:
                    if self.active_job_id == job.id:
                        self.active_job_id = None
                    if self.pending_jobs:
                        next_job = self.pending_jobs.pop(0)
                        self._refresh_queue_positions()
                    if next_job:
                        self._launch_job(*next_job)

        threading.Thread(target=runner, name=f"visual-job-{job.id[:8]}", daemon=True).start()

    def start_job(
        self,
        name: str,
        callback: Callable[[Job], Any],
        *,
        allow_queue: bool = False,
        kind: str = "",
        asset_id: str = "",
    ) -> Job:
        with self.lock:
            if self.active_job_id:
                active = self.jobs.get(self.active_job_id)
                if active and active.status in {"queued", "running"} and not allow_queue:
                    raise HTTPException(status_code=409, detail=f"Tác vụ '{active.name}' đang chạy.")
            if asset_id:
                duplicate = next(
                    (
                        job
                        for job in self.jobs.values()
                        if job.asset_id == asset_id and job.status in {"queued", "running"}
                    ),
                    None,
                )
                if duplicate:
                    return duplicate
            job = Job(name, kind=kind, asset_id=asset_id)
            self.jobs[job.id] = job
            if self.active_job_id:
                self.pending_jobs.append((job, callback))
                self._refresh_queue_positions()
            else:
                self._launch_job(job, callback)
        return job


runtime = RuntimeState()
app = FastAPI(title="Visual CapCut Studio API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _project_payload(project: Path | None) -> dict[str, Any] | None:
    if not project:
        return None
    script_path = project / "scripts" / "script_final.txt"
    if not script_path.exists():
        return None
    manifest = load_manifest(project)
    for item in manifest:
        if str(item.get("visual_source_type") or "").lower() == "match_photography":
            concise = _concise_match_query(str(item.get("keyword") or ""), item)
            if concise:
                item["keyword"] = concise
                item["ai_search_keyword"] = concise
        local_path = Path(str(item.get("local_path") or ""))
        if local_path.is_file():
            item["media_version"] = f"{item.get('sha256') or ''}-{local_path.stat().st_mtime_ns}"
    voice_path = project / "voices" / "voice.wav"
    manifest_path = project / "assets" / "asset_manifest.json"
    script_mtime = script_path.stat().st_mtime
    voice_mtime = voice_path.stat().st_mtime if voice_path.exists() else 0
    manifest_mtime = manifest_path.stat().st_mtime if manifest_path.exists() else 0
    has_voice = voice_path.exists() and voice_mtime >= script_mtime
    has_scenes = bool(manifest) and manifest_mtime >= voice_mtime and has_voice
    capcut_dir = project / "capcut"
    capcut_files = [path for path in capcut_dir.rglob("*") if path.is_file()] if capcut_dir.exists() else []
    capcut_mtime = max((path.stat().st_mtime for path in capcut_files), default=0)
    has_capcut_export = bool(capcut_files) and capcut_mtime >= manifest_mtime and has_scenes
    return {
        "path": str(project),
        "name": project.name,
        "script": script_path.read_text(encoding="utf-8", errors="replace"),
        "has_voice": has_voice,
        "voice_path": str(voice_path) if has_voice else "",
        "has_scenes": has_scenes,
        "asset_count": len(manifest),
        "downloaded_count": sum(1 for item in manifest if item.get("local_path")),
        "approved_count": sum(1 for item in manifest if item.get("status") == "approved"),
        "has_capcut_export": has_capcut_export,
        "assets": manifest,
    }


def _public_settings() -> dict[str, Any]:
    settings = load_settings()
    steps = normalize_workflow_steps(settings.get("script_workflow_steps"))
    settings["script_workflow_steps"] = steps or default_workflow_steps()
    presets = _normalize_workflow_presets(settings.get("workflow_presets"))
    if not presets:
        presets = _normalize_workflow_presets(load_settings().get("workflow_presets"))
    settings["workflow_presets"] = presets
    return settings


def _save_partial_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "projects_dir",
        "text_to_voice_language",
        "text_to_voice_voice",
        "text_to_voice_mode",
        "text_to_voice_delivery",
        "text_to_voice_speed",
        "chatterbox_exaggeration",
        "chatterbox_cfg_weight",
        "chatterbox_temperature",
        "chatterbox_seed",
        "chatterbox_min_p",
        "chatterbox_top_p",
        "chatterbox_repetition_penalty",
        "chatterbox_max_words",
        "chatterbox_whisper_qa",
        "openai_api_key",
        "keyword_ai_model",
        "keyword_ai_provider",
        "gemini_api_key",
        "gemini_keyword_model",
        "gemini_vision_model",
        "image_ai_validation_enabled",
        "image_ai_min_score",
        "script_workflow_input",
        "script_workflow_steps",
        "workflow_presets",
        "active_workflow_id",
        "text_to_voice_root",
        "text_to_voice_python",
        "whisper_timing_enabled",
        "whisper_timing_model",
        "scene_ai_enabled",
        "scene_min_seconds",
        "scene_target_max_seconds",
        "capcut_exe_path",
        "image_min_width",
        "image_min_height",
        "image_enhance_enabled",
        "image_target_width",
        "image_target_height",
    }
    settings = load_settings()
    for key, value in values.items():
        if key in allowed:
            settings[key] = value
    if "script_workflow_steps" in values:
        settings["script_workflow_steps"] = normalize_workflow_steps(values["script_workflow_steps"])
    if "workflow_presets" in values:
        settings["workflow_presets"] = _normalize_workflow_presets(values["workflow_presets"])
    save_settings(settings)
    return settings


def _timing_payload(project: Path) -> dict[str, Any]:
    timing_path = project / "voices" / "voice.segments.json"
    whisper_srt = project / "voices" / "voice.whisper.srt"
    timing = {}
    if timing_path.exists():
        try:
            import json

            timing = json.loads(timing_path.read_text(encoding="utf-8-sig"))
        except Exception:
            timing = {}
    return {
        "timing_path": str(timing_path) if timing_path.exists() else "",
        "srt_path": str(whisper_srt) if whisper_srt.exists() else "",
        "srt": whisper_srt.read_text(encoding="utf-8", errors="replace") if whisper_srt.exists() else "",
        "segments": timing.get("segments") if isinstance(timing, dict) and isinstance(timing.get("segments"), list) else [],
        "scenes": load_manifest(project),
    }


def _preflight_payload() -> dict[str, Any]:
    settings = load_settings()
    checks = []

    voice_root = Path(str(settings.get("text_to_voice_root") or ""))
    if not voice_root.is_absolute():
        voice_root = APP_DIR / voice_root
    checks.append(
        {
            "id": "magic_voice",
            "label": "Magic Voice đã nằm trong tool",
            "ok": (voice_root / "app.py").is_file() and (voice_root / "modules" / "model_manager.py").is_file(),
            "detail": str(voice_root),
        }
    )
    raw_python = str(settings.get("text_to_voice_python") or "").strip()
    python_path = Path(raw_python) if raw_python else APP_DIR / "chatterbox-venv" / "Scripts" / "python.exe"
    if not raw_python:
        python_path = APP_DIR / "chatterbox-venv" / "Scripts" / "python.exe"
    elif not python_path.is_absolute():
        python_path = APP_DIR / python_path
    checks.append({"id": "voice_python", "label": "Python tạo voice", "ok": python_path.is_file(), "detail": str(python_path)})
    checks.append({"id": "gemini", "label": "Gemini API key", "ok": bool(str(settings.get("gemini_api_key") or "").strip()), "detail": "Dùng để viết script, tạo keyword và kiểm ảnh."})
    checks.append({"id": "capcut_template", "label": "Mẫu CapCut", "ok": (APP_DIR / "capcut_template" / "draft_content.json").is_file(), "detail": str(APP_DIR / "capcut_template")})
    checks.append({"id": "projects", "label": "Thư mục project", "ok": Path(str(settings.get("projects_dir") or "")).exists(), "detail": str(settings.get("projects_dir") or "")})
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def _sync_script(project: Path, script: str) -> None:
    value = script.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Script đang rỗng.")
    (project / "scripts").mkdir(parents=True, exist_ok=True)
    script_path = project / "scripts" / "script_final.txt"
    current = script_path.read_text(encoding="utf-8", errors="replace").strip() if script_path.exists() else ""
    if current != value:
        script_path.write_text(value + "\n", encoding="utf-8")


def _open_capcut(settings: dict[str, Any]) -> bool:
    configured = str(settings.get("capcut_exe_path") or "").strip()
    candidates = [Path(configured)] if configured else []
    appdata = Path(os.environ.get("APPDATA") or "")
    if appdata:
        candidates.append(appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "CapCut" / "CapCut.lnk")
    for candidate in candidates:
        if candidate.exists():
            os.startfile(str(candidate))
            return True
    return False


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "active_job_id": runtime.active_job_id}


@app.get("/api/state")
def state() -> dict[str, Any]:
    settings = _public_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects"))
    projects = []
    if projects_dir.exists():
        for path in sorted(projects_dir.iterdir(), key=lambda value: value.stat().st_mtime, reverse=True):
            if path.is_dir() and (path / "scripts" / "script_final.txt").exists():
                projects.append(
                    {
                        "path": str(path),
                        "name": path.name,
                        "updated_at": path.stat().st_mtime,
                    }
                )
    active = runtime.jobs.get(runtime.active_job_id or "")
    queued = [job.payload() for job, _callback in runtime.pending_jobs]
    live_jobs = ([active.payload()] if active else []) + queued
    return {
        "settings": settings,
        "project": _project_payload(runtime.current_project),
        "projects": projects[:100],
        "active_job": active.payload() if active else None,
        "queued_jobs": queued,
        "jobs": live_jobs,
    }


@app.get("/api/voices")
def voices(language: str = "en") -> dict[str, Any]:
    settings = load_settings()
    items = chatterbox_voice_choices(settings, language)
    return {"items": items, "options": [{"value": item, "label": item} for item in items]}


def _safe_voice_name(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^A-Za-z0-9_ -]+", "", normalized).strip().replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        raise HTTPException(status_code=400, detail="Tên giọng đang trống.")
    return normalized[:60]


def _convert_audio_to_wav(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".wav":
        shutil.copy2(source, target)
        return
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(source), "-ac", "1", "-ar", "24000", str(target)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not target.exists() or target.stat().st_size < 1024:
        detail = (result.stderr or result.stdout or "").strip()
        raise HTTPException(status_code=400, detail=f"Không chuyển được audio sang WAV. Cần cài ffmpeg hoặc upload file WAV sạch. {detail[-300:]}")


@app.post("/api/voices/clone")
async def clone_voice_native(
    name: str,
    gender: str = "male",
    language: str = "en",
    file: UploadFile = File(...),
) -> dict[str, Any]:
    settings = load_settings()
    voice_root = Path(str(settings.get("text_to_voice_root") or APP_DIR / "magic_voice"))
    if not voice_root.is_absolute():
        voice_root = APP_DIR / voice_root
    voice_dir = voice_root / "modules" / "voice_samples"
    if not voice_dir.exists():
        raise HTTPException(status_code=500, detail=f"Không thấy thư mục voice_samples: {voice_dir}")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="File không hợp lệ. Hãy upload WAV/MP3/M4A/WEBM/MP4 audio.")
    clean_name = _safe_voice_name(name)
    clean_gender = "female" if str(gender).lower().startswith("f") else "male"
    clean_lang = re.sub(r"[^a-z]", "", str(language or "en").lower()) or "en"
    final_stem = f"{clean_name}_{clean_gender}" + (f"_{clean_lang}" if clean_lang != "en" else "")
    target = voice_dir / f"{final_stem}.wav"
    if target.exists():
        raise HTTPException(status_code=409, detail=f"Giọng '{final_stem}' đã tồn tại. Hãy dùng tên khác.")

    temp_dir = voice_root / "tmp_uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid.uuid4().hex}{suffix}"
    try:
        with temp_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)
        _convert_audio_to_wav(temp_path, target)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
    choices = chatterbox_voice_choices(settings, clean_lang)
    return {"ok": True, "voice": final_stem, "items": choices, "options": [{"value": item, "label": item} for item in choices]}


@app.post("/api/settings")
def update_settings(request: SettingsRequest) -> dict[str, Any]:
    return {"settings": _save_partial_settings(request.settings)}


@app.get("/api/preflight")
def preflight() -> dict[str, Any]:
    return _preflight_payload()


@app.post("/api/projects")
def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects"))
    project = create_visual_project(projects_dir, request.title, request.script.strip())
    runtime.set_project(project)
    return {"project": _project_payload(project)}


@app.post("/api/projects/open")
def open_project(request: ProjectOpenRequest) -> dict[str, Any]:
    project = Path(request.path)
    if not (project / "scripts" / "script_final.txt").exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy project hợp lệ.")
    runtime.set_project(project)
    return {"project": _project_payload(project)}


@app.post("/api/projects/script")
def save_project_script(request: ScriptRequest) -> dict[str, Any]:
    project = runtime.require_project()
    _sync_script(project, request.script)
    return {"project": _project_payload(project)}


@app.post("/api/workflow")
def run_workflow(request: WorkflowRequest) -> dict[str, Any]:
    settings = load_settings()
    if request.settings:
        settings = _save_partial_settings(request.settings)
    settings["script_workflow_input"] = request.source_input
    settings["script_workflow_steps"] = normalize_workflow_steps(request.steps)
    save_settings(settings)

    def task(job: Job) -> dict[str, Any]:
        active_steps = [step for step in normalize_workflow_steps(request.steps) if step.get("enabled")]
        job.determinate = True
        job.total_units = len(active_steps)

        def workflow_log(message: str) -> None:
            job.log(message)
            if "Workflow AI: đang chạy" in str(message):
                text = str(message)
                job.current_label = text.split(" - ", 1)[-1]
                try:
                    fraction = text.split("đang chạy ", 1)[1].split(" - ", 1)[0]
                    current = int(fraction.split("/", 1)[0])
                    job.completed_units = max(0, current - 1)
                    job.progress = round((job.completed_units / max(1, job.total_units)) * 100)
                except (IndexError, ValueError):
                    pass
            elif "Workflow AI: hoàn tất" in str(message):
                job.completed_units = job.total_units
                job.progress = 100

        script = run_script_workflow(request.source_input, request.steps, settings, log=workflow_log)
        job.completed_units = job.total_units
        job.progress = 100
        return {"script": script}

    return {"job": runtime.start_job("AI Workflow", task).payload()}


@app.post("/api/voice")
def create_voice(request: ScriptRequest) -> dict[str, Any]:
    project = runtime.require_project()
    _sync_script(project, request.script)
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.current_label = "Đang tạo voice và timing"
        path = generate_voice(project, settings, job.log)
        return {"voice_path": str(path), "project": _project_payload(project)}

    return {"job": runtime.start_job("B1 Magic Voice", task).payload()}


@app.post("/api/voice-preview")
def preview_voice(request: VoicePreviewRequest) -> dict[str, Any]:
    settings = load_settings()
    if isinstance(request.settings, dict):
        for key in (
            "text_to_voice_language",
            "text_to_voice_voice",
            "text_to_voice_mode",
            "text_to_voice_delivery",
            "text_to_voice_speed",
            "chatterbox_exaggeration",
            "chatterbox_cfg_weight",
            "chatterbox_temperature",
            "chatterbox_seed",
            "chatterbox_min_p",
            "chatterbox_top_p",
            "chatterbox_repetition_penalty",
            "chatterbox_max_words",
            "chatterbox_whisper_qa",
            "text_to_voice_root",
            "text_to_voice_python",
        ):
            if key in request.settings:
                settings[key] = request.settings[key]
    sample = str(request.text or "").strip()
    if not sample:
        lang = str(settings.get("text_to_voice_language") or "en")
        sample = (
            "This is a voice preview for your video. Listen to the tone, emotion, pace, and clarity before creating the full narration."
            if lang == "en"
            else "Đây là đoạn nghe thử giọng cho video của bạn. Hãy nghe chất giọng, cảm xúc, nhịp đọc và độ rõ trước khi tạo bản đọc đầy đủ."
        )
    if len(sample) > 500:
        sample = sample[:500]

    preview_dir = APP_DIR / ".voice_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    text_path = preview_dir / "preview.txt"
    output_path = preview_dir / f"preview_{uuid.uuid4().hex}.wav"
    text_path.write_text(sample, encoding="utf-8")

    logs: list[str] = []
    runner = TextToVoiceRunner(settings, logs.append, lambda: False)
    try:
        runner.start()
        result_path = runner.submit_file(text_path, "preview", output_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Không tạo được nghe thử giọng: {exc}") from exc
    finally:
        runner.close()
    return {
        "ok": True,
        "path": result_path,
        "url": f"/api/media?path={quote(result_path, safe='')}",
        "logs": logs[-8:],
    }


@app.post("/api/analyze")
def analyze() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.current_label = "Đang căn timing và chia cảnh"
        items = build_asset_manifest(project, settings, log=job.log)
        job.log(f"Đã chia {len(items)} cảnh theo Whisper SRT + ngữ cảnh.")
        job.current_label = "Đang tối ưu keyword bằng AI"
        items = optimize_asset_keywords_with_ai(project, settings, log=job.log)
        return {"items": items, "project": _project_payload(project)}

    return {"job": runtime.start_job("B2 Phan tich canh", task).payload()}


@app.post("/api/analyze-search")
def analyze_and_search() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.determinate = True
        job.total_units = 2
        job.current_label = "Đang chia cảnh theo giọng đọc"
        items = build_asset_manifest(project, settings, log=job.log)
        job.log(f"Đã chia {len(items)} cảnh. Đang tối ưu từ khóa.")
        items = optimize_asset_keywords_with_ai(project, settings, log=job.log)
        save_manifest(project, items)
        job.completed_units = 1
        job.progress = 50

        total = max(1, len(items))
        job.total_units = len(items) + 1
        for index, item in enumerate(items):
            job.completed_units = index + 1
            job.progress = round((job.completed_units / max(1, job.total_units)) * 100)
            job.current_label = f"Đang tìm media cho cảnh {index + 1}/{len(items)}"
            if item.get("status") != "approved":
                items[index] = search_and_download_asset(project, item, job.log, settings=settings)
                save_manifest(project, items)
            job.result = {"items": items, "project": _project_payload(project), "last_asset_id": items[index].get("asset_id")}
        job.completed_units = job.total_units
        job.progress = 100
        job.current_label = "Đã chuẩn bị xong cảnh và media"
        return {"items": items, "project": _project_payload(project), "timing": _timing_payload(project)}

    return {"job": runtime.start_job("B2+B3 Chia canh va tim media", task).payload()}


@app.post("/api/search")
def search_all() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        items = load_manifest(project)
        total = max(1, len(items))
        job.determinate = True
        job.total_units = len(items)
        for index, item in enumerate(items):
            job.completed_units = index
            job.progress = round((index / total) * 100)
            job.current_label = f"Đang xử lý {item.get('asset_id') or f'asset {index + 1}'}"
            if item.get("status") != "approved":
                items[index] = search_and_download_asset(project, item, job.log, settings=settings)
                save_manifest(project, items)
            job.completed_units = index + 1
            job.progress = round(((index + 1) / total) * 100)
            job.result = {
                "items": items,
                "project": _project_payload(project),
                "last_asset_id": items[index].get("asset_id"),
            }
        job.current_label = "Đã xử lý xong tất cả asset"
        return {"items": items, "project": _project_payload(project)}

    return {"job": runtime.start_job("B3 Tim anh", task).payload()}


@app.post("/api/assets/{asset_id}/retry")
def retry_asset(asset_id: str) -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        items = load_manifest(project)
        index = next((i for i, item in enumerate(items) if item.get("asset_id") == asset_id), -1)
        if index < 0:
            raise RuntimeError(f"Không tìm thấy {asset_id}.")
        job.determinate = True
        job.total_units = 1
        job.current_label = f"Đang tìm lại {asset_id}"
        items[index]["status"] = "pending"
        items[index] = search_and_download_asset(
            project,
            items[index],
            job.log,
            settings=settings,
            reject_current=True,
        )
        save_manifest(project, items)
        job.completed_units = 1
        job.progress = 100
        return {"item": items[index], "project": _project_payload(project)}

    return {
        "job": runtime.start_job(
            f"Tìm lại {asset_id}",
            task,
            allow_queue=True,
            kind="asset_retry",
            asset_id=asset_id,
        ).payload()
    }


@app.post("/api/assets/{asset_id}/approve")
def approve_asset(asset_id: str) -> dict[str, Any]:
    project = runtime.require_project()
    items = load_manifest(project)
    item = next((value for value in items if value.get("asset_id") == asset_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy {asset_id}.")
    item["status"] = "downloaded" if item.get("status") == "approved" else "approved"
    save_manifest(project, items)
    return {"project": _project_payload(project)}


@app.post("/api/assets/{asset_id}/keyword")
def update_asset_keyword(asset_id: str, request: KeywordRequest) -> dict[str, Any]:
    project = runtime.require_project()
    items = load_manifest(project)
    item = next((value for value in items if value.get("asset_id") == asset_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy {asset_id}.")
    item["keyword"] = request.keyword.strip()
    item["ai_search_keyword"] = item["keyword"]
    save_manifest(project, items)
    return {"project": _project_payload(project)}


@app.post("/api/assets/{asset_id}/upload")
async def upload_asset_media(asset_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    project = runtime.require_project()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_SUFFIXES and suffix not in VIDEO_SUFFIXES:
        raise HTTPException(status_code=400, detail="File không hợp lệ. Hãy chọn ảnh hoặc video.")
    temp_dir = project / "assets" / "uploads_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{asset_id}_{uuid.uuid4().hex}{suffix}"
    try:
        with temp_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)
        item = attach_local_media_to_asset(project, asset_id, temp_path, load_settings())
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
    return {"item": item, "project": _project_payload(project)}


@app.post("/api/assets/approve-all")
def approve_all_assets() -> dict[str, Any]:
    project = runtime.require_project()
    items = load_manifest(project)
    for item in items:
        if item.get("status") != "approved" and item.get("local_path"):
            item["status"] = "approved"
    save_manifest(project, items)
    return {"project": _project_payload(project)}


@app.post("/api/export")
def export_project(request: ExportRequest) -> dict[str, Any]:
    project = runtime.require_project()
    title = request.title.strip() or project.name

    def task(job: Job) -> dict[str, Any]:
        job.current_label = "Đang tạo và cài đặt draft CapCut"
        job.log("Đang tạo project CapCut...")
        path = export_capcut_project(project, title, install_to_capcut=True)
        opened = _open_capcut(load_settings())
        job.log("Đã mở CapCut." if opened else "Không tự mở được CapCut.")
        return {"capcut_path": str(path), "opened": opened}

    return {"job": runtime.start_job("B4 Xuất CapCut", task).payload()}


@app.post("/api/project/open-folder")
def open_project_folder() -> dict[str, Any]:
    project = runtime.require_project()
    os.startfile(str(project))
    return {"ok": True}


@app.get("/api/project/timing")
def project_timing() -> dict[str, Any]:
    project = runtime.require_project()
    return _timing_payload(project)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = runtime.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
    return {"job": job.payload()}


@app.get("/api/media")
def media(path: str) -> FileResponse:
    file_path = Path(path).resolve()
    projects_dir = Path(str(load_settings().get("projects_dir") or APP_DIR / "Projects")).resolve()
    preview_dir = (APP_DIR / ".voice_preview").resolve()
    try:
        file_path.relative_to(projects_dir)
    except ValueError:
        try:
            file_path.relative_to(preview_dir)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Đường dẫn media không hợp lệ.") from exc
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy media.")
    media_type = "audio/wav" if file_path.suffix.lower() == ".wav" else None
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="webui")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
