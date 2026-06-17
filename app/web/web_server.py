from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from ..config import APP_DIR, load_settings, save_settings
from ..pipeline.script_workflow import default_workflow_steps, normalize_workflow_steps, repair_mojibake, run_script_workflow
from ..voice.text_to_voice_queue import (
    TextToVoiceRunner,
    _estimated_segments_from_text,
    _script_sentences_for_timing,
    kokoro_custom_voice_dir,
    kokoro_voice_choices,
    normalize_kokoro_language,
    warm_kokoro_server,
)
from ..voice.text_to_voice_cli import build_srt_from_segments
from ..pipeline.prompt_studio import analyze_story, apply_prompt_keywords, generate_line_prompts, load_prompt_analysis, save_prompt_analysis
from ..pipeline.subtitle_store import load_subtitle, save_subtitle
from ..pipeline.visual_pipeline import (
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
CURRENT_CLIENT_ID: ContextVar[str] = ContextVar("visual_client_id", default="default")


class ProjectCreateRequest(BaseModel):
    title: str = ""
    script: str
    category: str = ""
    series_path: str = ""
    flow_id: str = ""


class ProjectOpenRequest(BaseModel):
    path: str


class ProjectUpdateRequest(BaseModel):
    path: str
    title: str = ""


class ProjectDeleteRequest(BaseModel):
    path: str


class SeriesCreateRequest(BaseModel):
    title: str
    description: str = ""
    settings_overrides: dict[str, Any] = Field(default_factory=dict)
    default_flow_id: str = ""


class SeriesUpdateRequest(BaseModel):
    path: str
    title: str | None = None
    description: str | None = None
    settings_overrides: dict[str, Any] | None = None
    default_flow_id: str | None = None


class SeriesDeleteRequest(BaseModel):
    path: str


class FlowCreateRequest(BaseModel):
    name: str
    description: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)


class FlowUpdateRequest(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None
    steps: list[dict[str, Any]] | None = None


class FlowDeleteRequest(BaseModel):
    id: str


class SettingsRequest(BaseModel):
    settings: dict[str, Any]


class ScriptRequest(BaseModel):
    script: str


class SrtPreviewRequest(BaseModel):
    script: str
    language: str | None = None
    speed: float | None = None


class SubtitleRequest(BaseModel):
    segments: list[dict] = []


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


class PromptAnalysisRequest(BaseModel):
    analysis: dict[str, Any] = {}


class PromptEditRequest(BaseModel):
    prompt: str = ""



def _normalize_workflow_presets(values: Any) -> list[dict[str, Any]]:
    presets: list[dict[str, Any]] = []
    if not isinstance(values, list):
        return presets
    for raw in values:
        if not isinstance(raw, dict):
            continue
        name = repair_mojibake(raw.get("name")).strip()[:80]
        if not name:
            continue
        preset_id = str(raw.get("id") or "").strip() or uuid.uuid4().hex[:10]
        presets.append(
            {
                "id": preset_id,
                "name": name,
                "description": repair_mojibake(raw.get("description")).strip()[:260],
                "steps": normalize_workflow_steps(raw.get("steps")) or default_workflow_steps(),
            }
        )
    return presets


class Job:
    def __init__(self, name: str, *, kind: str = "", asset_id: str = "", client_id: str = "default"):
        self.id = uuid.uuid4().hex
        self.name = name
        self.kind = kind
        self.asset_id = asset_id
        self.client_id = client_id
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
        self.cancel_requested = False

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
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class RuntimeState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self.active_job_ids: dict[str, str] = {}
        self.pending_jobs_by_client: dict[str, list[tuple[Job, Callable[[Job], Any]]]] = {}
        self.current_projects: dict[str, Path] = {}
        self.default_project = self._load_current_project()

    @property
    def client_id(self) -> str:
        return CURRENT_CLIENT_ID.get() or "default"

    @property
    def active_job_id(self) -> str | None:
        return self.active_job_ids.get(self.client_id)

    @property
    def pending_jobs(self) -> list[tuple[Job, Callable[[Job], Any]]]:
        return self.pending_jobs_by_client.setdefault(self.client_id, [])

    @property
    def current_project(self) -> Path | None:
        return self.current_projects.get(self.client_id, self.default_project)

    @current_project.setter
    def current_project(self, project: Path | None) -> None:
        if project is None:
            self.current_projects.pop(self.client_id, None)
        else:
            self.current_projects[self.client_id] = project

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
        self.current_projects[self.client_id] = project
        STATE_PATH.write_text(str(project), encoding="utf-8")

    def require_project(self) -> Path:
        project = self.current_project
        if not project or not (project / "scripts" / "script_final.txt").exists():
            raise HTTPException(status_code=400, detail="Chưa chọn project. Hãy tạo hoặc mở project trước.")
        return project

    def _refresh_queue_positions(self, client_id: str) -> None:
        for index, (job, _callback) in enumerate(self.pending_jobs_by_client.get(client_id, []), start=1):
            job.queue_position = index
            job.updated_at = time.time()

    def _launch_job(self, job: Job, callback: Callable[[Job], Any]) -> None:
        client_id = job.client_id
        self.active_job_ids[client_id] = job.id
        job.queue_position = 0

        def runner() -> None:
            job.status = "running"
            job.updated_at = time.time()
            try:
                job.result = callback(job)
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.current_label = "Đã dừng tác vụ"
                else:
                    job.progress = 100
                    job.status = "done"
            except Exception as exc:
                if job.cancel_requested:
                    job.log("Đã dừng tác vụ.")
                    job.status = "cancelled"
                    job.current_label = "Đã dừng tác vụ"
                else:
                    job.error = str(exc)
                    job.log(f"LỖI: {exc}")
                    job.status = "failed"
            finally:
                job.updated_at = time.time()
                next_job: tuple[Job, Callable[[Job], Any]] | None = None
                with self.lock:
                    if self.active_job_ids.get(client_id) == job.id:
                        self.active_job_ids.pop(client_id, None)
                    pending = self.pending_jobs_by_client.get(client_id, [])
                    if pending:
                        next_job = pending.pop(0)
                        self._refresh_queue_positions(client_id)
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
        client_id = self.client_id
        with self.lock:
            active_job_id = self.active_job_ids.get(client_id)
            if active_job_id:
                active = self.jobs.get(active_job_id)
                if active and active.status in {"queued", "running"} and not allow_queue:
                    raise HTTPException(status_code=409, detail=f"Tác vụ '{active.name}' đang chạy.")
            if asset_id:
                duplicate = next(
                    (
                        job
                        for job in self.jobs.values()
                        if job.client_id == client_id
                        and job.asset_id == asset_id
                        and job.status in {"queued", "running"}
                    ),
                    None,
                )
                if duplicate:
                    return duplicate
            job = Job(name, kind=kind, asset_id=asset_id, client_id=client_id)
            self.jobs[job.id] = job
            if active_job_id:
                self.pending_jobs_by_client.setdefault(client_id, []).append((job, callback))
                self._refresh_queue_positions(client_id)
            else:
                self._launch_job(job, callback)
        return job

    def cancel_current(self, clear_project: bool = False) -> Job | None:
        client_id = self.client_id
        with self.lock:
            active = self.jobs.get(self.active_job_ids.get(client_id, ""))
            if active and active.status in {"queued", "running"}:
                active.cancel_requested = True
                active.current_label = "Đang dừng tác vụ..."
                active.log("Người dùng yêu cầu dừng tác vụ.")
                active.updated_at = time.time()
                # UI action "Back home" must behave like a fresh start. Some
                # voice engines can only notice cancellation after a subprocess
                # returns, so remove the active lock immediately and let the old
                # worker finish in the background without blocking the new flow.
                if clear_project:
                    self.active_job_ids.pop(client_id, None)
            pending = self.pending_jobs_by_client.get(client_id, [])
            for job, _callback in pending:
                job.cancel_requested = True
                job.status = "cancelled"
                job.current_label = "Đã hủy khỏi hàng đợi"
                job.log("Đã hủy khỏi hàng đợi.")
                job.updated_at = time.time()
            pending.clear()
            if clear_project:
                self.current_projects.pop(client_id, None)
                self.default_project = None
                try:
                    STATE_PATH.unlink()
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
            return active


runtime = RuntimeState()
app = FastAPI(title="Visual CapCut Studio API", version="2.0")


@app.middleware("http")
async def bind_client_session(request: Request, call_next):
    client_id = re.sub(r"[^a-zA-Z0-9_-]", "", request.headers.get("X-Visual-Client") or "default")[:80] or "default"
    token = CURRENT_CLIENT_ID.set(client_id)
    try:
        return await call_next(request)
    finally:
        CURRENT_CLIENT_ID.reset(token)


@app.on_event("startup")
def warm_voice_engine_on_startup() -> None:
    threading.Thread(
        target=warm_kokoro_server,
        args=(load_settings(),),
        name="kokoro-warmup",
        daemon=True,
    ).start()
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
    timing_path = project / "voices" / "voice.segments.json"
    manifest_path = project / "assets" / "asset_manifest.json"
    script_mtime = script_path.stat().st_mtime
    voice_mtime = voice_path.stat().st_mtime if voice_path.exists() else 0
    timing_mtime = timing_path.stat().st_mtime if timing_path.exists() else 0
    manifest_mtime = manifest_path.stat().st_mtime if manifest_path.exists() else 0
    timing_segments = []
    if timing_path.exists() and timing_mtime >= script_mtime:
        try:
            timing_data = json.loads(timing_path.read_text(encoding="utf-8-sig"))
            if isinstance(timing_data, dict) and isinstance(timing_data.get("segments"), list):
                timing_segments = [item for item in timing_data.get("segments") or [] if isinstance(item, dict) and str(item.get("text") or "").strip()]
        except Exception:
            timing_segments = []
    subtitle_json = project / "scripts" / "subtitle.json"
    subtitle_mtime = subtitle_json.stat().st_mtime if subtitle_json.exists() else 0
    upstream_mtime = max(script_mtime, subtitle_mtime)
    has_voice = voice_path.exists() and voice_mtime >= upstream_mtime and bool(timing_segments)
    has_scenes = bool(manifest) and manifest_mtime >= voice_mtime and has_voice
    capcut_dir = project / "capcut"
    capcut_files = [path for path in capcut_dir.rglob("*") if path.is_file()] if capcut_dir.exists() else []
    capcut_mtime = max((path.stat().st_mtime for path in capcut_files), default=0)
    has_capcut_export = bool(capcut_files) and capcut_mtime >= manifest_mtime and has_scenes
    meta = {}
    try:
        meta = json.loads((project / "visual_project.json").read_text(encoding="utf-8"))
    except Exception:
        meta = {}
    display_name = str(meta.get("title") or "").strip() or project.name
    parent_category = "" if project.parent.name == "Projects" else project.parent.name
    category = str(meta.get("category") or parent_category).strip()
    subtitle_segments = load_subtitle(project)
    return {
        "path": str(project),
        "name": display_name,
        "folder_name": project.name,
        "category": category,
        "script": script_path.read_text(encoding="utf-8", errors="replace"),
        "has_voice": has_voice,
        "voice_path": str(voice_path) if has_voice else "",
        "has_scenes": has_scenes,
        "asset_count": len(manifest),
        "downloaded_count": sum(1 for item in manifest if item.get("local_path")),
        "approved_count": sum(1 for item in manifest if item.get("status") == "approved"),
        "has_capcut_export": has_capcut_export,
        # Physical artifact presence, ignoring staleness. Lets the UI tell apart
        # "never made" (todo) from "made but invalidated by an upstream edit"
        # (needs redo), so a script change doesn't look like a dead end.
        "voice_exists": voice_path.exists() and timing_path.exists(),
        "scenes_exist": manifest_path.exists(),
        "export_exists": bool(capcut_files),
        "has_subtitle": subtitle_json.exists() and bool(subtitle_segments),
        "subtitle_segments": subtitle_segments,
        "assets": manifest,
    }


def _read_series_meta(series_dir: Path) -> dict[str, Any]:
    defaults: dict[str, Any] = {"version": 1, "title": series_dir.name, "description": "", "created_at": 0, "settings_overrides": {}, "default_flow_id": ""}
    try:
        raw = json.loads((series_dir / "project.json").read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            defaults.update({k: v for k, v in raw.items() if k in defaults})
    except Exception:
        pass
    return defaults


def _write_series_meta(series_dir: Path, meta: dict[str, Any]) -> None:
    series_dir.mkdir(parents=True, exist_ok=True)
    (series_dir / "project.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _flows_path() -> Path:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects")).resolve()
    return projects_dir.parent / "flows.json"


def _load_flows() -> list[dict[str, Any]]:
    path = _flows_path()
    if not path.exists():
        return _bootstrap_flows()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("flows") or []
    except Exception:
        return []


def _save_flows(flows: list[dict[str, Any]]) -> None:
    path = _flows_path()
    path.write_text(json.dumps({"version": 1, "flows": flows}, ensure_ascii=False, indent=2), encoding="utf-8")


def _bootstrap_flows() -> list[dict[str, Any]]:
    """Migrate workflow_presets from settings → flows.json on first run, or create defaults."""
    import time as _time
    settings = load_settings()
    presets = settings.get("workflow_presets") or []
    flows: list[dict[str, Any]] = []
    for p in presets:
        if isinstance(p, dict) and p.get("name"):
            flows.append({
                "id": str(p.get("id") or uuid.uuid4().hex[:8]),
                "name": repair_mojibake(p.get("name", "")).strip()[:80],
                "description": repair_mojibake(p.get("description", "")).strip()[:260],
                "steps": normalize_workflow_steps(p.get("steps")) or default_workflow_steps(),
                "created_at": int(_time.time()),
            })
    if not flows:
        flows = [{
            "id": "default",
            "name": "Flow mặc định",
            "description": "Phân tích đề tài, lập dàn ý, viết script",
            "steps": default_workflow_steps(),
            "created_at": int(_time.time()),
        }]
    _save_flows(flows)
    return flows


def _series_payload(series_dir: Path, all_projects: list[dict[str, Any]]) -> dict[str, Any]:
    meta = _read_series_meta(series_dir)
    videos = [p for p in all_projects if p.get("category") == series_dir.name]
    latest = max((p.get("updated_at") or 0 for p in videos), default=meta.get("created_at") or 0)
    return {
        "path": str(series_dir),
        "title": meta.get("title") or series_dir.name,
        "description": meta.get("description") or "",
        "created_at": meta.get("created_at") or 0,
        "settings_overrides": meta.get("settings_overrides") or {},
        "default_flow_id": meta.get("default_flow_id") or "",
        "video_count": len(videos),
        "latest_updated_at": latest,
        "is_virtual": False,
        "videos": videos,
    }


def _build_series_list(projects_dir: Path, all_projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    if not projects_dir.exists():
        return series
    for child in projects_dir.iterdir():
        if not child.is_dir():
            continue
        if (child / "scripts" / "script_final.txt").exists():
            continue
        series.append(_series_payload(child, all_projects))
    orphans = [p for p in all_projects if not p.get("category")]
    if orphans:
        latest_orphan = max((p.get("updated_at") or 0 for p in orphans), default=0)
        series.append({
            "path": "",
            "title": "Chưa phân nhóm",
            "description": "",
            "created_at": 0,
            "settings_overrides": {},
            "video_count": len(orphans),
            "latest_updated_at": latest_orphan,
            "is_virtual": True,
            "videos": orphans,
        })
    series.sort(key=lambda s: s["latest_updated_at"], reverse=True)
    return series


def _public_settings() -> dict[str, Any]:
    settings = load_settings()
    steps = normalize_workflow_steps(settings.get("script_workflow_steps"))
    settings["script_workflow_steps"] = steps or default_workflow_steps()
    presets = _normalize_workflow_presets(settings.get("workflow_presets"))
    if not presets:
        presets = _normalize_workflow_presets(load_settings().get("workflow_presets"))
    settings["workflow_presets"] = presets
    profiles = settings.get("voice_clone_profiles")
    if not isinstance(profiles, list):
        profiles = []
    profiles = [
        item for item in profiles
        if isinstance(item, dict)
        and str(item.get("path") or "").strip()
        and Path(str(item.get("path"))).is_file()
    ]
    legacy_raw = str(settings.get("voice_clone_reference_path") or "").strip()
    legacy_ref = Path(legacy_raw) if legacy_raw else None
    if legacy_ref is not None and legacy_ref.is_file() and not any(Path(str(item.get("path") or "")) == legacy_ref for item in profiles):
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
    default_id = str(settings.get("voice_clone_default_id") or "")
    default_profile = next((item for item in profiles if str(item.get("id") or "") == default_id), None)
    if default_profile and not str(settings.get("voice_clone_reference_path") or "").strip():
        settings["voice_clone_reference_path"] = str(default_profile.get("path") or "")
        settings["voice_clone_reference_name"] = str(default_profile.get("name") or "")
    return settings


def _save_partial_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "projects_dir",
        "text_to_voice_language",
        "text_to_voice_voice",
        "text_to_voice_delivery",
        "text_to_voice_speed",
        "text_to_voice_max_chars",
        "openai_api_key",
        "keyword_ai_model",
        "keyword_ai_provider",
        "kiro_api_key",
        "kiro_api_base",
        "kiro_keyword_model",
        "claude_api_key",
        "claude_keyword_model",
        "gemini_api_key",
        "gemini_keyword_model",
        "gemini_vision_model",
        "image_ai_validation_enabled",
        "image_ai_min_score",
        "image_search_parallel_jobs",
        "script_workflow_input",
        "script_workflow_steps",
        "workflow_presets",
        "active_workflow_id",
        "text_to_voice_root",
        "text_to_voice_python",
        "voice_clone_enabled",
        "voice_clone_engine",
        "voice_clone_reference_path",
        "voice_clone_reference_name",
        "voice_clone_preview_url",
        "voice_clone_profiles",
        "voice_clone_default_id",
        "voice_clone_max_chars",
        "voice_clone_timeout",
        "voice_clone_setup_timeout",
        "magicvoice_root",
        "magicvoice_steps",
        "magicvoice_dtype",
        "magicvoice_device",
        "magicvoice_batch_size",
        "whisper_python",
        "whisper_timing_enabled",
        "whisper_timing_model",
        "scene_ai_enabled",
        "scene_min_seconds",
        "scene_target_max_seconds",
        "scene_hard_max_seconds",
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
    if "text_to_voice_speed" in values:
        try:
            settings["text_to_voice_speed"] = max(0.5, min(2.0, float(values["text_to_voice_speed"])))
        except (TypeError, ValueError):
            settings["text_to_voice_speed"] = 1.0
    if "magicvoice_steps" in values:
        try:
            settings["magicvoice_steps"] = max(8, min(16, int(values["magicvoice_steps"])))
        except (TypeError, ValueError):
            settings["magicvoice_steps"] = 16
    if "magicvoice_batch_size" in values:
        try:
            settings["magicvoice_batch_size"] = 1
        except (TypeError, ValueError):
            settings["magicvoice_batch_size"] = 1
    if "voice_clone_max_chars" in values:
        try:
            clone_chars = int(values["voice_clone_max_chars"])
            settings["voice_clone_max_chars"] = 480 if clone_chars >= 900 else max(280, min(clone_chars, 720))
        except (TypeError, ValueError):
            settings["voice_clone_max_chars"] = 480
    if "magicvoice_dtype" in values:
        dtype = str(values.get("magicvoice_dtype") or "auto").strip().lower()
        settings["magicvoice_dtype"] = "auto" if dtype in {"", "float16", "fp16"} else dtype
    for key, lo, hi, default, cast in (
        ("scene_min_seconds", 1.0, 60.0, 3.0, float),
        ("scene_target_max_seconds", 1.0, 120.0, 10.0, float),
        ("scene_hard_max_seconds", 1.0, 600.0, 15.0, float),
        ("image_target_width", 16, 7680, 1920, int),
        ("image_target_height", 16, 7680, 1080, int),
    ):
        if key in values:
            try:
                settings[key] = max(lo, min(hi, cast(float(values[key]))))
            except (TypeError, ValueError):
                settings[key] = default
    # Keep the scene-length window coherent: shortest must not exceed target.
    try:
        if float(settings.get("scene_min_seconds", 3)) > float(settings.get("scene_target_max_seconds", 10)):
            settings["scene_min_seconds"] = settings["scene_target_max_seconds"]
    except (TypeError, ValueError):
        pass
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
            "id": "kokoro_voice",
            "label": "Kokoro TTS đã nằm trong tool",
            "ok": (voice_root / "app.py").is_file(),
            "detail": str(voice_root),
        }
    )
    raw_python = str(settings.get("text_to_voice_python") or "").strip()
    python_path = Path(raw_python) if raw_python else voice_root / ".venv" / "Scripts" / "python.exe"
    if not raw_python:
        python_path = voice_root / ".venv" / "Scripts" / "python.exe"
    elif not python_path.is_absolute():
        python_path = APP_DIR / python_path
    setup_path = voice_root / "setup.ps1"
    checks.append(
        {
            "id": "voice_python",
            "label": "Python tạo voice",
            "ok": python_path.is_file() or setup_path.is_file(),
            "detail": str(python_path) if python_path.is_file() else f"Chưa có .venv, sẽ tự cài lần đầu bằng {setup_path}",
        }
    )
    checks.append(
        {
            "id": "ai_api",
            "label": "API key AI",
            "ok": any(
                bool(str(settings.get(key) or "").strip())
                for key in ("kiro_api_key", "claude_api_key", "gemini_api_key", "openai_api_key")
            ),
            "detail": "Dùng để hiểu nội dung, chia cảnh và tạo keyword hình ảnh.",
        }
    )
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


def _search_assets_parallel(
    project: Path,
    items: list[dict[str, Any]],
    settings: dict[str, Any],
    job: Job,
    *,
    initial_completed: int = 0,
) -> list[dict[str, Any]]:
    pending = [(index, item) for index, item in enumerate(items) if item.get("status") != "approved"]
    if not pending:
        return items
    max_workers = max(1, min(4, int(settings.get("image_search_parallel_jobs") or 3), len(pending)))
    job.log(f"Tìm media song song {max_workers} cảnh/lượt.")

    def search_one(index: int, item: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        return index, search_and_download_asset(project, dict(item), job.log, settings=settings)

    finished = 0
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="asset-search") as executor:
        futures = {executor.submit(search_one, index, item): index for index, item in pending}
        for future in as_completed(futures):
            if job.cancel_requested:
                for queued in futures:
                    queued.cancel()
                raise RuntimeError("Stopped.")
            index = futures[future]
            try:
                _, result = future.result()
                items[index] = result
            except Exception as exc:
                items[index]["status"] = "error"
                items[index]["error"] = str(exc)
                job.log(f"{items[index].get('asset_id')}: {exc}")
            finished += 1
            job.completed_units = initial_completed + finished
            job.progress = min(99, round((job.completed_units / max(1, job.total_units)) * 100))
            job.current_label = f"Đã tìm media {finished}/{len(pending)} cảnh"
            save_manifest(project, items)
            job.result = {
                "items": items,
                "project": _project_payload(project),
                "last_asset_id": items[index].get("asset_id"),
            }
    return items


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "active_job_id": runtime.active_job_id}


def _cancel_jobs_payload(clear_project: bool = False) -> dict[str, Any]:
    active = runtime.cancel_current(clear_project=clear_project)
    return {
        "ok": True,
        "cancelled_job": active.payload() if active else None,
        "active_job_id": runtime.active_job_id,
    }


@app.post("/api/jobs/cancel")
def cancel_jobs(clear_project: bool = False) -> dict[str, Any]:
    return _cancel_jobs_payload(clear_project=clear_project)


@app.get("/api/jobs/cancel")
def cancel_jobs_get(clear_project: bool = False) -> dict[str, Any]:
    return _cancel_jobs_payload(clear_project=clear_project)


@app.get("/api/state")
def state() -> dict[str, Any]:
    settings = _public_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects"))
    projects = []
    categories = []
    if projects_dir.exists():
        project_roots = []
        for path in projects_dir.rglob("scripts/script_final.txt"):
            project_roots.append(path.parents[1])
        for path in sorted(set(project_roots), key=lambda value: value.stat().st_mtime, reverse=True):
            payload = _project_payload(path)
            if payload:
                projects.append(
                    {
                        "path": str(path),
                        "name": payload["name"],
                        "folder_name": path.name,
                        "category": payload.get("category") or "",
                        "updated_at": path.stat().st_mtime,
                    }
                )
        categories = sorted({item["category"] for item in projects if item.get("category")})
    active = runtime.jobs.get(runtime.active_job_id or "")
    queued = [job.payload() for job, _callback in runtime.pending_jobs]
    live_jobs = ([active.payload()] if active else []) + queued
    series = _build_series_list(projects_dir, projects)
    return {
        "settings": settings,
        "project": _project_payload(runtime.current_project),
        "projects": projects[:100],
        "categories": categories,
        "series": series,
        "flows": _load_flows(),
        "active_job": active.payload() if active else None,
        "queued_jobs": queued,
        "jobs": live_jobs,
    }


@app.get("/api/voices")
def voices(language: str = "en") -> dict[str, Any]:
    settings = load_settings()
    normalized_language, warning = normalize_kokoro_language(language)
    items = kokoro_voice_choices(settings, normalized_language)
    return {
        "items": items,
        "language": normalized_language,
        "warning": warning,
        "options": [
            {
                "value": item,
                "label": Path(item).stem if str(item).lower().endswith(".pt") else item,
                "custom": str(item).lower().endswith(".pt"),
            }
            for item in items
        ],
    }


@app.post("/api/voices/upload")
async def upload_kokoro_voice(file: UploadFile = File(...), language: str = "en") -> dict[str, Any]:
    settings = load_settings()
    normalized_language, warning = normalize_kokoro_language(language)
    filename = Path(file.filename or "custom_voice.pt").name
    if not filename.lower().endswith(".pt"):
        raise HTTPException(
            status_code=400,
            detail="Kokoro không clone từ mp3/wav. Chỉ có thể import voice embedding dạng .pt.",
        )
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).stem).strip("._-") or "custom_voice"
    target_dir = kokoro_custom_voice_dir(settings, normalized_language)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{stem}.pt"
    suffix = 1
    while target.exists():
        target = target_dir / f"{stem}_{suffix}.pt"
        suffix += 1
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    items = kokoro_voice_choices(settings, normalized_language)
    return {
        "ok": True,
        "voice": str(target.resolve()),
        "label": target.stem,
        "language": normalized_language,
        "warning": warning,
        "options": [
            {
                "value": item,
                "label": Path(item).stem if str(item).lower().endswith(".pt") else item,
                "custom": str(item).lower().endswith(".pt"),
            }
            for item in items
        ],
    }


@app.post("/api/voice-clone/reference")
async def upload_voice_clone_reference(
    file: UploadFile = File(...),
    name: str = Form(""),
    language: str = Form(""),
    country: str = Form(""),
    set_default: bool = Form(False),
) -> dict[str, Any]:
    settings = load_settings()
    filename = Path(file.filename or "reference.wav").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}:
        raise HTTPException(status_code=400, detail="File mẫu phải là audio: wav, mp3, m4a, flac, ogg hoặc webm.")
    profile_id = uuid.uuid4().hex[:12]
    display_name = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9À-ỹ._ -]+", " ", str(name or "").strip())).strip()
    if not display_name:
        display_name = Path(filename).stem[:48] or "Giọng clone"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", display_name).strip("._-") or "clone_voice"
    settings = load_settings()
    magic_root = Path(str(settings.get("magicvoice_root") or APP_DIR / "magic_voice"))
    if not magic_root.is_absolute():
        magic_root = APP_DIR / magic_root
    ref_dir = magic_root / "clone_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    target = ref_dir / f"{stem}_{profile_id}{suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    file_size = target.stat().st_size
    if file_size < 5000:
        target.unlink()
        raise HTTPException(
            status_code=400,
            detail="File audio quá nhỏ hoặc không hợp lệ. Vui lòng upload file audio ít nhất 2-3 giây (tối thiểu ~5KB)."
        )
    profiles = settings.get("voice_clone_profiles")
    if not isinstance(profiles, list):
        profiles = []
    profiles = [
        item for item in profiles
        if isinstance(item, dict) and Path(str(item.get("path") or "")).exists()
    ]
    profile = {
        "id": profile_id,
        "name": display_name,
        "language": str(language or "").strip() or str(settings.get("text_to_voice_language") or "vi"),
        "country": str(country or "").strip(),
        "path": str(target.resolve()),
        "file_name": filename,
        "created_at": int(time.time()),
    }
    profiles.insert(0, profile)
    default_id = profile_id if set_default or not settings.get("voice_clone_default_id") else str(settings.get("voice_clone_default_id") or "")
    settings.update(
        {
            "voice_clone_enabled": True,
            "voice_clone_engine": "magicvoice",
            "voice_clone_reference_path": str(target.resolve()),
            "voice_clone_reference_name": display_name,
            "voice_clone_preview_url": "",
            "voice_clone_profiles": profiles,
            "voice_clone_default_id": default_id,
        }
    )
    save_settings(settings)
    return {
        "ok": True,
        "settings": _public_settings(),
        "reference_path": str(target.resolve()),
        "reference_name": display_name,
        "profile": profile,
    }


@app.delete("/api/voice-clone/{profile_id}")
def delete_voice_clone(profile_id: str) -> dict[str, Any]:
    settings = load_settings()
    profiles = settings.get("voice_clone_profiles")
    if not isinstance(profiles, list):
        profiles = []
    target = next(
        (item for item in profiles if isinstance(item, dict) and str(item.get("id") or "") == profile_id),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy giọng clone.")
    # Remove the reference audio plus its cached .prepared.wav/.prepared.json siblings.
    ref_path = Path(str(target.get("path") or ""))
    if ref_path.name:
        for candidate in (
            ref_path,
            ref_path.with_name(f"{ref_path.stem}.prepared.wav"),
            ref_path.with_name(f"{ref_path.stem}.prepared.json"),
        ):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
    remaining = [
        item for item in profiles
        if isinstance(item, dict) and str(item.get("id") or "") != profile_id
    ]
    updates: dict[str, Any] = {"voice_clone_profiles": remaining}
    # If we just deleted the active clone, fall back off clone mode.
    if str(settings.get("voice_clone_reference_path") or "") == str(target.get("path") or ""):
        updates.update(
            {
                "voice_clone_enabled": False,
                "voice_clone_reference_path": "",
                "voice_clone_reference_name": "",
                "voice_clone_preview_url": "",
            }
        )
    if str(settings.get("voice_clone_default_id") or "") == profile_id:
        updates["voice_clone_default_id"] = ""
    settings.update(updates)
    save_settings(settings)
    return {"ok": True, "settings": _public_settings()}


@app.post("/api/settings")
def update_settings(request: SettingsRequest) -> dict[str, Any]:
    return {"settings": _save_partial_settings(request.settings)}


@app.get("/api/preflight")
def preflight() -> dict[str, Any]:
    return _preflight_payload()


@app.post("/api/projects")
def create_project(request: ProjectCreateRequest) -> dict[str, Any]:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects")).resolve()
    if request.series_path:
        series_dir = Path(request.series_path).resolve()
        try:
            series_dir.relative_to(projects_dir)
        except ValueError:
            raise HTTPException(status_code=400, detail="series_path nằm ngoài thư mục quản lý.")
        category = series_dir.name
        target_dir = series_dir
    else:
        category = re.sub(r"[\\/:*?\"<>|]+", " ", request.category or "").strip()
        target_dir = projects_dir / category if category else projects_dir
    project = create_visual_project(target_dir, request.title, request.script.strip())
    if category or request.flow_id:
        meta_path = project / "visual_project.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if category:
            meta["category"] = category
        if request.flow_id:
            meta["flow_id"] = request.flow_id
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    runtime.set_project(project)
    return {"project": _project_payload(project)}


@app.post("/api/projects/open")
def open_project(request: ProjectOpenRequest) -> dict[str, Any]:
    project = Path(request.path)
    if not (project / "scripts" / "script_final.txt").exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy project hợp lệ.")
    runtime.set_project(project)
    return {"project": _project_payload(project)}


@app.post("/api/projects/rename")
def rename_project(request: ProjectUpdateRequest) -> dict[str, Any]:
    project = Path(request.path)
    if not (project / "visual_project.json").exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy project hợp lệ.")
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Tên project không được rỗng.")
    meta_path = project / "visual_project.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["title"] = title
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if runtime.current_project and runtime.current_project.resolve() == project.resolve():
        runtime.set_project(project)
    return {"project": _project_payload(project)}


@app.post("/api/projects/delete")
def delete_project(request: ProjectDeleteRequest) -> dict[str, Any]:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects")).resolve()
    project = Path(request.path).resolve()
    try:
        project.relative_to(projects_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Project nằm ngoài thư mục quản lý.")
    if not (project / "scripts" / "script_final.txt").exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy project hợp lệ.")
    if runtime.current_project and runtime.current_project.resolve() == project:
        runtime.current_project = None
    shutil.rmtree(project)
    return {"ok": True}


@app.get("/api/series")
def list_series() -> dict[str, Any]:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects"))
    all_projects: list[dict[str, Any]] = []
    if projects_dir.exists():
        project_roots = []
        for path in projects_dir.rglob("scripts/script_final.txt"):
            project_roots.append(path.parents[1])
        for path in sorted(set(project_roots), key=lambda value: value.stat().st_mtime, reverse=True):
            payload = _project_payload(path)
            if payload:
                all_projects.append({
                    "path": str(path),
                    "name": payload["name"],
                    "folder_name": path.name,
                    "category": payload.get("category") or "",
                    "updated_at": path.stat().st_mtime,
                })
    return {"series": _build_series_list(projects_dir, all_projects)}


@app.post("/api/series")
def create_series(request: SeriesCreateRequest) -> dict[str, Any]:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects"))
    safe_name = re.sub(r"[\\/:*?\"<>|]+", " ", request.title or "").strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Tên Dự án không được rỗng.")
    series_dir = projects_dir / safe_name
    if series_dir.exists():
        raise HTTPException(status_code=409, detail=f"Dự án '{safe_name}' đã tồn tại.")
    meta = {
        "version": 1,
        "title": request.title.strip(),
        "description": request.description.strip(),
        "created_at": int(time.time()),
        "settings_overrides": request.settings_overrides or {},
        "default_flow_id": request.default_flow_id or "",
    }
    _write_series_meta(series_dir, meta)
    all_projects: list[dict[str, Any]] = []
    return {"series": _series_payload(series_dir, all_projects)}


@app.patch("/api/series")
def update_series(request: SeriesUpdateRequest) -> dict[str, Any]:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects")).resolve()
    series_dir = Path(request.path).resolve()
    try:
        series_dir.relative_to(projects_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dự án nằm ngoài thư mục quản lý.")
    if not series_dir.is_dir():
        raise HTTPException(status_code=404, detail="Không tìm thấy Dự án.")
    meta = _read_series_meta(series_dir)
    if request.title is not None:
        meta["title"] = request.title.strip()
    if request.description is not None:
        meta["description"] = request.description.strip()
    if request.settings_overrides is not None:
        existing = meta.get("settings_overrides") or {}
        existing.update(request.settings_overrides)
        meta["settings_overrides"] = existing
    if request.default_flow_id is not None:
        meta["default_flow_id"] = request.default_flow_id
    _write_series_meta(series_dir, meta)
    all_projects: list[dict[str, Any]] = []
    if projects_dir.exists():
        project_roots = []
        for path in projects_dir.rglob("scripts/script_final.txt"):
            project_roots.append(path.parents[1])
        for path in sorted(set(project_roots), key=lambda value: value.stat().st_mtime, reverse=True):
            payload = _project_payload(path)
            if payload:
                all_projects.append({
                    "path": str(path),
                    "name": payload["name"],
                    "folder_name": path.name,
                    "category": payload.get("category") or "",
                    "updated_at": path.stat().st_mtime,
                })
    return {"series": _series_payload(series_dir, all_projects)}


@app.delete("/api/series")
def delete_series(request: SeriesDeleteRequest) -> dict[str, Any]:
    settings = load_settings()
    projects_dir = Path(str(settings.get("projects_dir") or APP_DIR / "Projects")).resolve()
    series_dir = Path(request.path).resolve()
    try:
        series_dir.relative_to(projects_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dự án nằm ngoài thư mục quản lý.")
    if not series_dir.is_dir():
        raise HTTPException(status_code=404, detail="Không tìm thấy Dự án.")
    active = runtime.jobs.get(runtime.active_job_id or "")
    if active and runtime.current_project:
        try:
            runtime.current_project.resolve().relative_to(series_dir)
            raise HTTPException(status_code=400, detail="Đang có tác vụ đang chạy trong Dự án này.")
        except ValueError:
            pass
    if runtime.current_project:
        try:
            runtime.current_project.resolve().relative_to(series_dir)
            runtime.current_project = None
        except ValueError:
            pass
    shutil.rmtree(series_dir)
    return {"ok": True}


@app.get("/api/flows")
def get_flows() -> dict[str, Any]:
    return {"flows": _load_flows()}


@app.post("/api/flows")
def create_flow(request: FlowCreateRequest) -> dict[str, Any]:
    import time as _time
    flows = _load_flows()
    new_flow: dict[str, Any] = {
        "id": uuid.uuid4().hex[:8],
        "name": request.name.strip()[:80],
        "description": request.description.strip()[:260],
        "steps": normalize_workflow_steps(request.steps) if request.steps else default_workflow_steps(),
        "created_at": int(_time.time()),
    }
    flows.append(new_flow)
    _save_flows(flows)
    return {"flow": new_flow, "flows": flows}


@app.patch("/api/flows")
def update_flow(request: FlowUpdateRequest) -> dict[str, Any]:
    flows = _load_flows()
    updated: dict[str, Any] | None = None
    for i, f in enumerate(flows):
        if f["id"] == request.id:
            if request.name is not None:
                flows[i]["name"] = request.name.strip()[:80]
            if request.description is not None:
                flows[i]["description"] = request.description.strip()[:260]
            if request.steps is not None:
                flows[i]["steps"] = normalize_workflow_steps(request.steps)
            updated = flows[i]
            break
    if not updated:
        raise HTTPException(status_code=404, detail="Flow không tồn tại.")
    _save_flows(flows)
    return {"flow": updated, "flows": flows}


@app.delete("/api/flows")
def delete_flow(request: FlowDeleteRequest) -> dict[str, Any]:
    flows = _load_flows()
    flows = [f for f in flows if f["id"] != request.id]
    _save_flows(flows)
    return {"flows": flows}


@app.post("/api/projects/script")
def save_project_script(request: ScriptRequest) -> dict[str, Any]:
    project = runtime.require_project()
    _sync_script(project, request.script)
    return {"project": _project_payload(project)}


# Reading speed (words/second) used to ESTIMATE subtitle timing from text alone,
# before any voice is generated. Real timing is recomputed from the TTS audio
# later; this only powers the live SRT preview in Step 1.
_SRT_PREVIEW_WORDS_PER_SECOND = {"vi": 2.3, "en": 2.6, "en-gb": 2.6}


@app.post("/api/script/srt-preview")
def srt_preview(request: SrtPreviewRequest) -> dict[str, Any]:
    settings = load_settings()
    language = str(request.language or settings.get("text_to_voice_language") or "vi").strip().lower()
    try:
        speed = float(request.speed if request.speed is not None else settings.get("text_to_voice_speed") or 1.0)
    except (TypeError, ValueError):
        speed = 1.0
    speed = max(0.5, min(2.0, speed))
    sentences = _script_sentences_for_timing(request.script)
    if not sentences:
        return {"segments": [], "srt": "", "duration": 0.0, "words": 0, "sentences": 0, "estimated": True}
    words = sum(len(re.findall(r"\S+", sentence)) for sentence in sentences)
    base_wps = _SRT_PREVIEW_WORDS_PER_SECOND.get(language, 2.4)
    # Speaking time scaled by speed, plus a short pause between sentences so the
    # preview cadence mirrors MagicVoice's estimated timing.
    duration = words / max(0.1, base_wps * speed) + len(sentences) * 0.32
    segments = _estimated_segments_from_text(request.script, duration)
    return {
        "segments": segments,
        "srt": build_srt_from_segments(segments),
        "duration": round(duration, 3),
        "words": words,
        "sentences": len(sentences),
        "estimated": True,
    }


@app.post("/api/projects/subtitle")
def save_project_subtitle(request: SubtitleRequest) -> dict[str, Any]:
    project = runtime.require_project()
    save_subtitle(project, request.segments)
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

        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        script = run_script_workflow(request.source_input, request.steps, settings, log=workflow_log)
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        job.completed_units = job.total_units
        job.progress = 100
        return {"script": script}

    return {"job": runtime.start_job("AI Workflow", task).payload()}


@app.post("/api/voice")
def create_voice(request: ScriptRequest) -> dict[str, Any]:
    project = runtime.require_project()
    _sync_script(project, request.script)
    if not load_subtitle(project):
        raise HTTPException(status_code=400, detail="Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước khi tạo giọng đọc.")
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.determinate = True
        job.total_units = 100
        job.current_label = "Đang tạo voice và timing"
        seen_chunks: set[tuple[int, int]] = set()

        def voice_log(message: str) -> None:
            text = str(message or "")
            job.log(text)
            match = re.search(r"đoạn\s+(\d+)\s*/\s*(\d+)", text, flags=re.I)
            if match:
                current = max(1, int(match.group(1)))
                total = max(1, int(match.group(2)))
                seen_chunks.add((current, total))
                job.total_units = total
                job.completed_units = max(0, min(total, current - 1))
                chunk_progress = 0
                sampling = re.search(r"sampling\s+(\d+)%", text, flags=re.I)
                if sampling:
                    chunk_progress = max(0, min(99, int(sampling.group(1))))
                calculated_progress = round(((job.completed_units + chunk_progress / 100) / total) * 100)
                job.progress = max(job.progress, min(99, calculated_progress))
                job.current_label = f"Đang tạo voice đoạn {current}/{total}"
            elif "đã lưu audio" in text.lower():
                job.progress = 100
                job.current_label = "Đã tạo xong voice"

        path = generate_voice(project, settings, voice_log, stop_check=lambda: job.cancel_requested)
        job.completed_units = job.total_units
        job.progress = 100
        return {"voice_path": str(path), "project": _project_payload(project)}

    return {"job": runtime.start_job("B1 Kokoro Voice", task).payload()}


@app.post("/api/voice-preview")
def preview_voice(request: VoicePreviewRequest) -> dict[str, Any]:
    settings = load_settings()
    if isinstance(request.settings, dict):
        for key in (
            "text_to_voice_language",
            "text_to_voice_voice",
            "text_to_voice_delivery",
            "text_to_voice_speed",
            "text_to_voice_root",
            "text_to_voice_python",
            "voice_clone_enabled",
            "voice_clone_engine",
            "voice_clone_reference_path",
            "voice_clone_reference_name",
            "voice_clone_preview_url",
            "voice_clone_max_chars",
            "voice_clone_timeout",
            "voice_clone_setup_timeout",
            "magicvoice_root",
            "magicvoice_steps",
            "magicvoice_dtype",
            "magicvoice_device",
            "magicvoice_batch_size",
        ):
            if key in request.settings:
                settings[key] = request.settings[key]
        try:
            settings["magicvoice_batch_size"] = 1
        except (TypeError, ValueError):
            settings["magicvoice_batch_size"] = 1
        try:
            clone_chars = int(settings.get("voice_clone_max_chars") or 480)
            settings["voice_clone_max_chars"] = 480 if clone_chars >= 900 else max(280, min(clone_chars, 720))
        except (TypeError, ValueError):
            settings["voice_clone_max_chars"] = 480
        dtype = str(settings.get("magicvoice_dtype") or "auto").strip().lower()
        settings["magicvoice_dtype"] = "auto" if dtype in {"", "float16", "fp16"} else dtype
    sample = str(request.text or "").strip()
    requested_lang = str(settings.get("text_to_voice_language") or "en")
    normalized_lang, language_warning = normalize_kokoro_language(requested_lang)
    if normalized_lang != requested_lang:
        settings["text_to_voice_language"] = normalized_lang
    if not sample:
        sample = (
            "This is a voice preview for your video. Listen to the tone, emotion, pace, and clarity before creating the full narration."
            if normalized_lang == "en"
            else "This is a voice preview for your video. Listen to tone, emotion, pace, and clarity before creating the full narration."
        )
    if len(sample) > 500:
        sample = sample[:500]

    clone_warning = None
    if settings.get("voice_clone_enabled"):
        ref_path_str = str(settings.get("voice_clone_reference_path") or "").strip()
        if not ref_path_str or not Path(ref_path_str).exists():
            clone_warning = "Clone giọng đang bật nhưng chưa có file tham chiếu hợp lệ. Đã dùng Kokoro preset."

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
        "logs": ([language_warning] if language_warning else []) + ([clone_warning] if clone_warning else []) + logs[-8:],
        "language": normalized_lang,
        "warning": language_warning,
        "clone_warning": clone_warning,
    }


@app.post("/api/analyze")
def analyze() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.current_label = "Đang căn timing và chia cảnh"
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        items = build_asset_manifest(project, settings, log=job.log)
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        job.log(f"Đã chia {len(items)} cảnh theo Whisper SRT + ngữ cảnh.")
        job.current_label = "Đang tối ưu keyword bằng AI"
        items = optimize_asset_keywords_with_ai(project, settings, log=job.log)
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        return {"items": items, "project": _project_payload(project)}

    return {"job": runtime.start_job("B2 Phan tich canh", task).payload()}


@app.post("/api/analyze-story")
def analyze_story_endpoint() -> dict[str, Any]:
    project = runtime.require_project()
    if not load_subtitle(project):
        raise HTTPException(status_code=400, detail="Chưa có phụ đề. Hãy tạo & lưu phụ đề ở Bước 1 trước.")
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        analysis = analyze_story(project, settings, log=job.log)
        return {"analysis": analysis, "project": _project_payload(project)}

    return {"job": runtime.start_job("B2 Phan tich nhan vat", task).payload()}


@app.get("/api/prompt-analysis")
def get_prompt_analysis() -> dict[str, Any]:
    project = runtime.require_project()
    return {"analysis": load_prompt_analysis(project)}


@app.post("/api/prompt-analysis")
def save_prompt_analysis_endpoint(request: PromptAnalysisRequest) -> dict[str, Any]:
    project = runtime.require_project()
    saved = save_prompt_analysis(project, request.analysis)
    return {"analysis": saved}


@app.post("/api/generate-prompts")
def generate_prompts_endpoint() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        generate_line_prompts(project, settings, log=job.log)
        return {"project": _project_payload(project)}

    return {"job": runtime.start_job("B2 Tao prompt", task).payload()}


@app.post("/api/assets/{asset_id}/prompt")
def edit_asset_prompt(asset_id: str, request: PromptEditRequest) -> dict[str, Any]:
    project = runtime.require_project()
    items = load_manifest(project)
    found = False
    for item in items:
        if item.get("asset_id") == asset_id:
            item["prompt"] = request.prompt
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Không tìm thấy asset.")
    save_manifest(project, items)
    return {"project": _project_payload(project)}


@app.post("/api/analyze-search")
def analyze_and_search() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.determinate = True
        job.total_units = 2
        job.current_label = "Đang chia cảnh theo giọng đọc"
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        items = build_asset_manifest(project, settings, log=job.log)
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        job.log(f"Đã chia {len(items)} cảnh. Đang tối ưu từ khóa.")
        items = optimize_asset_keywords_with_ai(project, settings, log=job.log)
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        save_manifest(project, items)
        job.completed_units = 1
        job.progress = 50

        job.total_units = len(items) + 1
        job.current_label = f"Đang tìm media cho {len(items)} cảnh"
        items = _search_assets_parallel(project, items, settings, job, initial_completed=1)
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
        job.determinate = True
        job.total_units = len(items)
        items = _search_assets_parallel(project, items, settings, job)
        job.completed_units = job.total_units
        job.progress = 100
        job.current_label = "Đã xử lý xong tất cả asset"
        return {"items": items, "project": _project_payload(project)}

    return {"job": runtime.start_job("B3 Tim anh", task).payload()}


@app.post("/api/prompt-search")
def prompt_search() -> dict[str, Any]:
    project = runtime.require_project()
    settings = load_settings()

    def task(job: Job) -> dict[str, Any]:
        job.current_label = "Đang tạo keyword từ prompt"
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        apply_prompt_keywords(project, settings, log=job.log)
        items = load_manifest(project)
        job.determinate = True
        job.total_units = len(items)
        job.current_label = "Đang tìm ảnh theo keyword"
        items = _search_assets_parallel(project, items, settings, job)
        job.completed_units = job.total_units
        job.progress = 100
        job.current_label = "Đã tìm ảnh xong"
        return {"items": items, "project": _project_payload(project)}

    return {"job": runtime.start_job("B3 Tao keyword va tim anh", task).payload()}


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
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
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
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
        path = export_capcut_project(project, title, install_to_capcut=True)
        if job.cancel_requested:
            raise RuntimeError("Stopped.")
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


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that falls back to index.html for unknown paths.

    This enables BrowserRouter deep-link reloads: any GET that would otherwise
    return 404 from the static file store is served as the SPA entry point
    instead, letting the frontend router handle the path.
    """

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise
        if response.status_code == 404:
            return await super().get_response("index.html", scope)
        return response


if WEB_DIST.exists():
    app.mount("/", SPAStaticFiles(directory=WEB_DIST, html=True), name="webui")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")


if __name__ == "__main__":
    main()
