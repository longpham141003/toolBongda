"""
Comprehensive tests for app/web_server.py

Covers:
  - Job class unit tests
  - RuntimeState unit tests
  - All major API endpoints via FastAPI TestClient
"""
from __future__ import annotations

import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Module-level setup: permanently inject mocks into sys.modules BEFORE
# importing app.web_server, so the module stays in sys.modules and
# patch("app.web_server.*") works correctly during tests.
# ---------------------------------------------------------------------------

_visual_pipeline_mock = MagicMock()
_script_workflow_mock = MagicMock()
_text_to_voice_queue_mock = MagicMock()

# Provide realistic return values used during import or in tests
_visual_pipeline_mock.load_manifest.return_value = []
_visual_pipeline_mock.save_manifest.return_value = None
_visual_pipeline_mock.create_visual_project.return_value = Path("/fake/project")
_visual_pipeline_mock.build_asset_manifest.return_value = []
_visual_pipeline_mock.optimize_asset_keywords_with_ai.return_value = []
_visual_pipeline_mock.generate_voice.return_value = Path("/fake/voice.wav")
_visual_pipeline_mock.search_and_download_asset.return_value = {}
_visual_pipeline_mock.export_capcut_project.return_value = Path("/fake/capcut")
_visual_pipeline_mock._concise_match_query.return_value = ""

_script_workflow_mock.default_workflow_steps.return_value = []
_script_workflow_mock.normalize_workflow_steps.return_value = []
_script_workflow_mock.run_script_workflow.return_value = "Generated script"

_text_to_voice_queue_mock.chatterbox_voice_choices.return_value = []

# Permanently inject into sys.modules so app.web_server stays registered
sys.modules.setdefault("app.visual_pipeline", _visual_pipeline_mock)
sys.modules.setdefault("app.script_workflow", _script_workflow_mock)
sys.modules.setdefault("app.text_to_voice_queue", _text_to_voice_queue_mock)

import app.web_server as ws  # noqa: E402 – must be after patching
from fastapi.testclient import TestClient  # noqa: E402

# Use the HTTPException from the web_server module's own namespace to ensure
# we catch the same class that the server raises (avoids identity mismatch).
HTTPException = ws.HTTPException


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_runtime():
    """Reset the module-level RuntimeState singleton between every test."""
    ws.runtime.active_job_ids = {}
    ws.runtime.jobs = {}
    ws.runtime.pending_jobs_by_client = {}
    ws.runtime.current_projects = {}
    # current_project getter falls back to default_project (loaded from disk on
    # the host); clear it so "no project" tests are hermetic regardless of any
    # real project that exists on the machine running the suite.
    ws.runtime.default_project = None
    yield
    ws.runtime.active_job_ids = {}
    ws.runtime.jobs = {}
    ws.runtime.pending_jobs_by_client = {}
    ws.runtime.current_projects = {}
    ws.runtime.default_project = None


@pytest.fixture()
def client():
    return TestClient(ws.app, raise_server_exceptions=False)


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal valid project directory structure."""
    scripts = tmp_path / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "script_final.txt").write_text("Hello world\n", encoding="utf-8")
    return tmp_path


# ===========================================================================
# Job class unit tests
# ===========================================================================

class TestJobInit:
    def test_default_status_is_queued(self):
        job = ws.Job("test-job")
        assert job.status == "queued"

    def test_default_progress_is_zero(self):
        job = ws.Job("test-job")
        assert job.progress == 0

    def test_default_logs_is_empty_list(self):
        job = ws.Job("test-job")
        assert job.logs == []

    def test_default_error_is_empty_string(self):
        job = ws.Job("test-job")
        assert job.error == ""

    def test_id_is_hex_string(self):
        job = ws.Job("test-job")
        assert isinstance(job.id, str)
        assert len(job.id) == 32  # uuid4().hex

    def test_name_stored(self):
        job = ws.Job("my-name")
        assert job.name == "my-name"

    def test_kind_default_empty(self):
        job = ws.Job("test-job")
        assert job.kind == ""

    def test_asset_id_default_empty(self):
        job = ws.Job("test-job")
        assert job.asset_id == ""

    def test_kind_and_asset_id_set(self):
        job = ws.Job("test", kind="asset_retry", asset_id="abc123")
        assert job.kind == "asset_retry"
        assert job.asset_id == "abc123"

    def test_created_at_set(self):
        before = time.time()
        job = ws.Job("test-job")
        after = time.time()
        assert before <= job.created_at <= after

    def test_result_is_none(self):
        job = ws.Job("test-job")
        assert job.result is None

    def test_queue_position_default_zero(self):
        job = ws.Job("test-job")
        assert job.queue_position == 0

    def test_determinate_default_false(self):
        job = ws.Job("test-job")
        assert job.determinate is False


class TestJobLog:
    def test_log_appends_message(self):
        job = ws.Job("test")
        job.log("hello")
        assert "hello" in job.logs

    def test_log_multiple_messages(self):
        job = ws.Job("test")
        job.log("a")
        job.log("b")
        assert job.logs == ["a", "b"]

    def test_log_trims_to_500(self):
        job = ws.Job("test")
        for i in range(600):
            job.log(str(i))
        assert len(job.logs) == 500
        # Most recent 500 should survive
        assert job.logs[-1] == "599"
        assert job.logs[0] == "100"

    def test_log_converts_to_string(self):
        job = ws.Job("test")
        job.log(42)
        assert job.logs[0] == "42"

    def test_log_updates_updated_at(self):
        job = ws.Job("test")
        old_time = job.updated_at
        time.sleep(0.02)
        job.log("x")
        assert job.updated_at > old_time

    def test_log_exactly_500_stays_at_500(self):
        job = ws.Job("test")
        for i in range(500):
            job.log(str(i))
        assert len(job.logs) == 500


class TestJobPayload:
    def test_payload_returns_dict(self):
        job = ws.Job("test")
        result = job.payload()
        assert isinstance(result, dict)

    def test_payload_contains_required_keys(self):
        job = ws.Job("test")
        result = job.payload()
        required = {"id", "name", "kind", "asset_id", "status", "queue_position",
                    "progress", "determinate", "completed_units", "total_units",
                    "current_label", "logs", "result", "error", "created_at", "updated_at"}
        assert required.issubset(result.keys())

    def test_payload_reflects_state(self):
        job = ws.Job("test", kind="k", asset_id="aid")
        job.status = "running"
        job.progress = 50
        job.log("step1")
        p = job.payload()
        assert p["status"] == "running"
        assert p["progress"] == 50
        assert "step1" in p["logs"]
        assert p["kind"] == "k"
        assert p["asset_id"] == "aid"

    def test_payload_id_matches_job_id(self):
        job = ws.Job("test")
        assert job.payload()["id"] == job.id

    def test_payload_error_reflects_set_error(self):
        job = ws.Job("test")
        job.error = "something went wrong"
        assert job.payload()["error"] == "something went wrong"


# ===========================================================================
# RuntimeState unit tests
# ===========================================================================

class TestRuntimeStateStartJob:
    def test_start_job_returns_job(self):
        callback = MagicMock(return_value="done")
        job = ws.runtime.start_job("test", callback)
        assert isinstance(job, ws.Job)
        assert job.id in ws.runtime.jobs

    def test_start_job_launches_thread(self):
        done = threading.Event()

        def callback(job):
            done.set()
            return "ok"

        ws.runtime.start_job("test", callback)
        assert done.wait(timeout=2), "Job thread never ran"

    def test_start_job_raises_409_when_active_no_queue(self):
        """When a job is active and allow_queue=False, raises 409."""
        # Manually set an active job
        active = ws.Job("blocker")
        active.status = "running"
        ws.runtime.jobs[active.id] = active
        ws.runtime.active_job_ids[ws.runtime.client_id] = active.id

        with pytest.raises(HTTPException) as exc_info:
            ws.runtime.start_job("new-job", MagicMock(), allow_queue=False)
        assert exc_info.value.status_code == 409

    def test_start_job_queues_when_active_and_allow_queue_true(self):
        """When active job exists and allow_queue=True, job is queued."""
        blocker_done = threading.Event()
        release = threading.Event()

        def blocker_cb(job):
            blocker_done.set()
            release.wait(timeout=2)
            return "blocker done"

        # Start a blocking job
        ws.runtime.start_job("blocker", blocker_cb)
        blocker_done.wait(timeout=2)

        # Start a queueable job
        queued = ws.runtime.start_job("queued", MagicMock(return_value="q"), allow_queue=True)
        assert len(ws.runtime.pending_jobs) == 1
        assert ws.runtime.pending_jobs[0][0].id == queued.id

        # Let blocker finish
        release.set()

    def test_start_job_returns_existing_for_duplicate_asset_id(self):
        """If same asset_id is already queued/running, return existing job."""
        # Create a running job for asset_id "a1"
        existing = ws.Job("existing", asset_id="a1")
        existing.status = "running"
        ws.runtime.jobs[existing.id] = existing
        ws.runtime.active_job_ids[ws.runtime.client_id] = existing.id

        returned = ws.runtime.start_job(
            "new", MagicMock(), allow_queue=True, asset_id="a1"
        )
        assert returned.id == existing.id

    def test_job_status_becomes_done_on_success(self):
        done_event = threading.Event()

        def cb(job):
            done_event.set()
            return {"ok": True}

        job = ws.runtime.start_job("test", cb)
        done_event.wait(timeout=2)
        time.sleep(0.05)  # let runner finalise status
        assert job.status == "done"
        assert job.result == {"ok": True}

    def test_job_status_becomes_failed_on_exception(self):
        done_event = threading.Event()

        def cb(job):
            done_event.set()
            raise ValueError("boom")

        job = ws.runtime.start_job("test", cb)
        done_event.wait(timeout=2)
        time.sleep(0.05)
        assert job.status == "failed"
        assert "boom" in job.error

    def test_active_job_id_cleared_after_job_completes(self):
        done_event = threading.Event()

        def cb(job):
            done_event.set()
            return "done"

        ws.runtime.start_job("test", cb)
        done_event.wait(timeout=2)
        time.sleep(0.05)
        assert ws.runtime.active_job_id is None


class TestRuntimeStateRequireProject:
    def test_require_project_raises_400_when_no_project(self):
        ws.runtime.current_project = None
        with pytest.raises(HTTPException) as exc_info:
            ws.runtime.require_project()
        assert exc_info.value.status_code == 400

    def test_require_project_raises_400_when_script_missing(self, tmp_path):
        ws.runtime.current_project = tmp_path  # no scripts/script_final.txt
        with pytest.raises(HTTPException) as exc_info:
            ws.runtime.require_project()
        assert exc_info.value.status_code == 400

    def test_require_project_returns_path_when_valid(self, project_dir):
        ws.runtime.current_project = project_dir
        result = ws.runtime.require_project()
        assert result == project_dir


class TestRuntimeStateSetProject:
    def test_set_project_updates_current_project(self, project_dir, tmp_path):
        state_file = tmp_path / ".webui_state"
        with patch.object(ws, "STATE_PATH", state_file):
            ws.runtime.set_project(project_dir)
        assert ws.runtime.current_project == project_dir.resolve()

    def test_set_project_writes_state_file(self, project_dir, tmp_path):
        state_file = tmp_path / ".webui_state"
        with patch.object(ws, "STATE_PATH", state_file):
            ws.runtime.set_project(project_dir)
        assert state_file.exists()
        assert str(project_dir.resolve()) in state_file.read_text(encoding="utf-8")

    def test_set_project_resolves_path(self, project_dir, tmp_path):
        state_file = tmp_path / ".webui_state"
        with patch.object(ws, "STATE_PATH", state_file):
            ws.runtime.set_project(project_dir)
        assert ws.runtime.current_project.is_absolute()


# ===========================================================================
# API endpoint tests
# ===========================================================================

class TestHealthEndpoint:
    def test_health_returns_ok_true(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_health_returns_active_job_id_null_when_idle(self, client):
        r = client.get("/api/health")
        assert r.json()["active_job_id"] is None

    def test_health_returns_active_job_id_when_running(self, client):
        job = ws.Job("running-job")
        job.status = "running"
        ws.runtime.jobs[job.id] = job
        ws.runtime.active_job_ids[ws.runtime.client_id] = job.id

        r = client.get("/api/health")
        assert r.json()["active_job_id"] == job.id


class TestStateEndpoint:
    def test_state_returns_200(self, client):
        with patch("app.web_server._public_settings", return_value={"projects_dir": "/tmp/no-exist", "script_workflow_steps": []}):
            r = client.get("/api/state")
        assert r.status_code == 200

    def test_state_contains_required_keys(self, client):
        with patch("app.web_server._public_settings", return_value={"projects_dir": "/tmp/no-exist", "script_workflow_steps": []}):
            r = client.get("/api/state")
        data = r.json()
        for key in ("settings", "project", "projects", "active_job", "queued_jobs", "jobs"):
            assert key in data

    def test_state_project_is_null_when_no_project(self, client):
        with patch("app.web_server._public_settings", return_value={"projects_dir": "/tmp/no-exist", "script_workflow_steps": []}):
            r = client.get("/api/state")
        assert r.json()["project"] is None

    def test_state_jobs_list_is_empty_when_idle(self, client):
        with patch("app.web_server._public_settings", return_value={"projects_dir": "/tmp/no-exist", "script_workflow_steps": []}):
            r = client.get("/api/state")
        assert r.json()["jobs"] == []

    def test_state_projects_is_list(self, client):
        with patch("app.web_server._public_settings", return_value={"projects_dir": "/tmp/no-exist", "script_workflow_steps": []}):
            r = client.get("/api/state")
        assert isinstance(r.json()["projects"], list)


class TestSettingsEndpoint:
    def test_post_settings_returns_200(self, client):
        fake_settings = {"projects_dir": "/tmp", "script_workflow_steps": []}
        with patch("app.web_server.load_settings", return_value=dict(fake_settings)), \
             patch("app.web_server.save_settings"):
            r = client.post("/api/settings", json={"settings": {"text_to_voice_language": "vi"}})
        assert r.status_code == 200

    def test_post_settings_ignores_unknown_fields(self, client):
        fake_settings = {"projects_dir": "/tmp", "script_workflow_steps": []}
        with patch("app.web_server.load_settings", return_value=dict(fake_settings)), \
             patch("app.web_server.save_settings") as mock_save:
            r = client.post("/api/settings", json={"settings": {"totally_unknown_key": "value"}})
        assert r.status_code == 200
        # Unknown key should NOT be in saved settings
        if mock_save.called:
            saved = mock_save.call_args[0][0]
            assert "totally_unknown_key" not in saved

    def test_post_settings_returns_settings_key(self, client):
        fake_settings = {"projects_dir": "/tmp", "script_workflow_steps": []}
        with patch("app.web_server.load_settings", return_value=dict(fake_settings)), \
             patch("app.web_server.save_settings"):
            r = client.post("/api/settings", json={"settings": {}})
        assert "settings" in r.json()

    def test_post_settings_updates_allowed_field(self, client):
        fake_settings = {"projects_dir": "/tmp", "text_to_voice_language": "en", "script_workflow_steps": []}
        with patch("app.web_server.load_settings", return_value=dict(fake_settings)), \
             patch("app.web_server.save_settings") as mock_save:
            client.post("/api/settings", json={"settings": {"text_to_voice_language": "vi"}})
        if mock_save.called:
            saved = mock_save.call_args[0][0]
            assert saved.get("text_to_voice_language") == "vi"

    def _save_and_get(self, client, payload):
        fake_settings = {"projects_dir": "/tmp", "script_workflow_steps": []}
        with patch("app.web_server.load_settings", return_value=dict(fake_settings)), \
             patch("app.web_server.save_settings") as mock_save:
            client.post("/api/settings", json={"settings": payload})
        assert mock_save.called
        return mock_save.call_args[0][0]

    def test_post_settings_rejects_zero_video_dimensions(self, client):
        # Clearing the field on the UI sends 0; backend must clamp away from 0.
        saved = self._save_and_get(client, {"image_target_width": 0, "image_target_height": 0})
        assert saved["image_target_width"] >= 16
        assert saved["image_target_height"] >= 16

    def test_post_settings_clamps_oversized_dimensions(self, client):
        saved = self._save_and_get(client, {"image_target_width": 99999})
        assert saved["image_target_width"] == 7680

    def test_post_settings_recovers_from_invalid_number(self, client):
        saved = self._save_and_get(client, {"scene_min_seconds": "abc"})
        assert saved["scene_min_seconds"] == 3.0

    def test_post_settings_keeps_scene_window_coherent(self, client):
        # min must not exceed target after clamping.
        saved = self._save_and_get(client, {"scene_min_seconds": 30, "scene_target_max_seconds": 8})
        assert saved["scene_min_seconds"] <= saved["scene_target_max_seconds"]


class TestProjectsCreateEndpoint:
    def test_create_project_returns_200(self, client, tmp_path):
        project_path = tmp_path / "MyProject"
        project_path.mkdir()
        (project_path / "scripts").mkdir()
        (project_path / "scripts" / "script_final.txt").write_text("hello\n")

        state_file = tmp_path / ".state"
        with patch("app.web_server.load_settings", return_value={"projects_dir": str(tmp_path), "script_workflow_steps": []}), \
             patch("app.web_server.create_visual_project", return_value=project_path), \
             patch("app.web_server.load_manifest", return_value=[]), \
             patch.object(ws, "STATE_PATH", state_file):
            r = client.post("/api/projects", json={"title": "My Project", "script": "hello world"})

        assert r.status_code == 200
        assert "project" in r.json()

    def test_create_project_calls_create_visual_project(self, client, tmp_path):
        project_path = tmp_path / "MyProject"
        project_path.mkdir()
        (project_path / "scripts").mkdir()
        (project_path / "scripts" / "script_final.txt").write_text("hello\n")

        state_file = tmp_path / ".state"
        with patch("app.web_server.load_settings", return_value={"projects_dir": str(tmp_path), "script_workflow_steps": []}), \
             patch("app.web_server.create_visual_project", return_value=project_path) as mock_create, \
             patch("app.web_server.load_manifest", return_value=[]), \
             patch.object(ws, "STATE_PATH", state_file):
            client.post("/api/projects", json={"title": "Title", "script": "Script text"})

        mock_create.assert_called_once()

    def test_create_project_sets_runtime_project(self, client, tmp_path):
        project_path = tmp_path / "MyProject"
        project_path.mkdir()
        (project_path / "scripts").mkdir()
        (project_path / "scripts" / "script_final.txt").write_text("hello\n")

        state_file = tmp_path / ".state"
        with patch("app.web_server.load_settings", return_value={"projects_dir": str(tmp_path), "script_workflow_steps": []}), \
             patch("app.web_server.create_visual_project", return_value=project_path), \
             patch("app.web_server.load_manifest", return_value=[]), \
             patch.object(ws, "STATE_PATH", state_file):
            client.post("/api/projects", json={"title": "T", "script": "Script"})

        assert ws.runtime.current_project is not None


class TestProjectsOpenEndpoint:
    def test_open_project_valid_path_returns_200(self, client, project_dir, tmp_path):
        state_file = tmp_path / ".state"
        with patch("app.web_server.load_manifest", return_value=[]), \
             patch.object(ws, "STATE_PATH", state_file):
            r = client.post("/api/projects/open", json={"path": str(project_dir)})
        assert r.status_code == 200
        assert "project" in r.json()

    def test_open_project_invalid_path_returns_404(self, client, tmp_path):
        bad_path = tmp_path / "nonexistent"
        r = client.post("/api/projects/open", json={"path": str(bad_path)})
        assert r.status_code == 404

    def test_open_project_sets_runtime_project(self, client, project_dir, tmp_path):
        state_file = tmp_path / ".state"
        with patch("app.web_server.load_manifest", return_value=[]), \
             patch.object(ws, "STATE_PATH", state_file):
            client.post("/api/projects/open", json={"path": str(project_dir)})
        assert ws.runtime.current_project == project_dir.resolve()


class TestProjectsScriptEndpoint:
    def test_save_script_returns_400_when_no_project(self, client):
        r = client.post("/api/projects/script", json={"script": "hello"})
        assert r.status_code == 400

    def test_save_script_returns_400_when_empty_script(self, client, project_dir):
        ws.runtime.current_project = project_dir
        with patch("app.web_server.load_manifest", return_value=[]):
            r = client.post("/api/projects/script", json={"script": "   "})
        assert r.status_code == 400

    def test_save_script_writes_file(self, client, project_dir):
        ws.runtime.current_project = project_dir
        with patch("app.web_server.load_manifest", return_value=[]):
            r = client.post("/api/projects/script", json={"script": "New script content"})
        assert r.status_code == 200
        saved = (project_dir / "scripts" / "script_final.txt").read_text(encoding="utf-8")
        assert "New script content" in saved

    def test_save_script_returns_project_key(self, client, project_dir):
        ws.runtime.current_project = project_dir
        with patch("app.web_server.load_manifest", return_value=[]):
            r = client.post("/api/projects/script", json={"script": "content"})
        assert "project" in r.json()

    def test_save_script_does_not_write_when_unchanged(self, client, project_dir):
        ws.runtime.current_project = project_dir
        existing = (project_dir / "scripts" / "script_final.txt").read_text(encoding="utf-8").strip()
        with patch("app.web_server.load_manifest", return_value=[]):
            r = client.post("/api/projects/script", json={"script": existing})
        assert r.status_code == 200


class TestGetJobEndpoint:
    def test_get_job_returns_job_payload(self, client):
        job = ws.Job("test-job")
        ws.runtime.jobs[job.id] = job
        r = client.get(f"/api/jobs/{job.id}")
        assert r.status_code == 200
        data = r.json()
        assert "job" in data
        assert data["job"]["id"] == job.id

    def test_get_job_returns_404_for_unknown_id(self, client):
        r = client.get("/api/jobs/nonexistent-id-xyz")
        assert r.status_code == 404

    def test_get_job_payload_contains_status(self, client):
        job = ws.Job("status-test")
        job.status = "running"
        ws.runtime.jobs[job.id] = job
        r = client.get(f"/api/jobs/{job.id}")
        assert r.json()["job"]["status"] == "running"

    def test_get_job_payload_contains_all_fields(self, client):
        job = ws.Job("full-test", kind="test_kind", asset_id="x99")
        job.log("log message")
        ws.runtime.jobs[job.id] = job
        payload = client.get(f"/api/jobs/{job.id}").json()["job"]
        assert payload["name"] == "full-test"
        assert payload["kind"] == "test_kind"
        assert payload["asset_id"] == "x99"
        assert "log message" in payload["logs"]


class TestApproveAssetEndpoint:
    def test_approve_asset_toggles_to_approved(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [{"asset_id": "a1", "status": "downloaded", "local_path": str(project_dir / "file.jpg")}]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            r = client.post("/api/assets/a1/approve")
        assert r.status_code == 200
        assert mock_save.called
        saved_items = mock_save.call_args[0][1]
        item = next(i for i in saved_items if i["asset_id"] == "a1")
        assert item["status"] == "approved"

    def test_approve_asset_toggles_back_to_downloaded(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [{"asset_id": "a1", "status": "approved", "local_path": str(project_dir / "file.jpg")}]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            r = client.post("/api/assets/a1/approve")
        assert r.status_code == 200
        saved_items = mock_save.call_args[0][1]
        item = next(i for i in saved_items if i["asset_id"] == "a1")
        assert item["status"] == "downloaded"

    def test_approve_asset_returns_400_when_no_project(self, client):
        r = client.post("/api/assets/a1/approve")
        assert r.status_code == 400

    def test_approve_asset_returns_404_for_unknown_asset(self, client, project_dir):
        ws.runtime.current_project = project_dir
        with patch("app.web_server.load_manifest", return_value=[]):
            r = client.post("/api/assets/unknown-asset/approve")
        assert r.status_code == 404

    def test_approve_asset_returns_project_in_response(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [{"asset_id": "a2", "status": "downloaded", "local_path": "/f"}]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest"), \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            r = client.post("/api/assets/a2/approve")
        assert "project" in r.json()


class TestKeywordEndpoint:
    def test_update_keyword_sets_keyword(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [{"asset_id": "a2", "status": "downloaded", "keyword": "old keyword"}]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            r = client.post("/api/assets/a2/keyword", json={"keyword": "new keyword"})
        assert r.status_code == 200
        saved = mock_save.call_args[0][1]
        item = next(i for i in saved if i["asset_id"] == "a2")
        assert item["keyword"] == "new keyword"
        assert item["ai_search_keyword"] == "new keyword"

    def test_update_keyword_strips_whitespace(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [{"asset_id": "a3", "status": "downloaded", "keyword": ""}]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            r = client.post("/api/assets/a3/keyword", json={"keyword": "  padded  "})
        saved = mock_save.call_args[0][1]
        item = next(i for i in saved if i["asset_id"] == "a3")
        assert item["keyword"] == "padded"

    def test_update_keyword_returns_400_when_no_project(self, client):
        r = client.post("/api/assets/a3/keyword", json={"keyword": "kw"})
        assert r.status_code == 400

    def test_update_keyword_returns_404_for_unknown_asset(self, client, project_dir):
        ws.runtime.current_project = project_dir
        with patch("app.web_server.load_manifest", return_value=[]):
            r = client.post("/api/assets/unknown/keyword", json={"keyword": "kw"})
        assert r.status_code == 404

    def test_update_keyword_syncs_ai_search_keyword(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [{"asset_id": "a4", "status": "downloaded", "keyword": "old"}]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            client.post("/api/assets/a4/keyword", json={"keyword": "updated"})
        saved = mock_save.call_args[0][1]
        item = next(i for i in saved if i["asset_id"] == "a4")
        assert item["ai_search_keyword"] == item["keyword"]


class TestApproveAllEndpoint:
    def test_approve_all_approves_downloaded_assets(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [
            {"asset_id": "x1", "status": "downloaded", "local_path": "/fake/file1.jpg"},
            {"asset_id": "x2", "status": "downloaded", "local_path": "/fake/file2.jpg"},
            {"asset_id": "x3", "status": "pending",    "local_path": ""},
        ]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            r = client.post("/api/assets/approve-all")
        assert r.status_code == 200
        assert mock_save.called
        saved = mock_save.call_args[0][1]
        statuses = {i["asset_id"]: i["status"] for i in saved}
        assert statuses["x1"] == "approved"
        assert statuses["x2"] == "approved"
        # x3 has no local_path so should NOT be approved
        assert statuses["x3"] != "approved"

    def test_approve_all_skips_already_approved(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [
            {"asset_id": "y1", "status": "approved", "local_path": "/fake/file.jpg"},
        ]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            r = client.post("/api/assets/approve-all")
        assert r.status_code == 200
        saved = mock_save.call_args[0][1]
        assert saved[0]["status"] == "approved"  # unchanged

    def test_approve_all_returns_400_when_no_project(self, client):
        r = client.post("/api/assets/approve-all")
        assert r.status_code == 400

    def test_approve_all_skips_assets_without_local_path(self, client, project_dir):
        ws.runtime.current_project = project_dir
        manifest = [
            {"asset_id": "z1", "status": "pending", "local_path": ""},
        ]
        with patch("app.web_server.load_manifest", return_value=manifest), \
             patch("app.web_server.save_manifest") as mock_save, \
             patch("app.web_server._project_payload", return_value={"path": str(project_dir)}):
            client.post("/api/assets/approve-all")
        saved = mock_save.call_args[0][1]
        assert saved[0]["status"] == "pending"  # not changed since no local_path


class TestMediaEndpoint:
    def test_media_returns_403_for_path_outside_projects_dir(self, client, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("secret")

        with patch("app.web_server.load_settings", return_value={"projects_dir": str(projects_dir)}):
            r = client.get(f"/api/media?path={outside_file}")
        assert r.status_code == 403

    def test_media_returns_404_for_missing_file(self, client, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        missing = projects_dir / "nonexistent.mp4"

        with patch("app.web_server.load_settings", return_value={"projects_dir": str(projects_dir)}):
            r = client.get(f"/api/media?path={missing}")
        assert r.status_code == 404

    def test_media_returns_200_for_valid_file(self, client, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        media_file = projects_dir / "image.png"
        media_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with patch("app.web_server.load_settings", return_value={"projects_dir": str(projects_dir)}):
            r = client.get(f"/api/media?path={media_file}")
        assert r.status_code == 200

    def test_media_has_no_cache_headers(self, client, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        media_file = projects_dir / "video.mp4"
        media_file.write_bytes(b"\x00" * 50)

        with patch("app.web_server.load_settings", return_value={"projects_dir": str(projects_dir)}):
            r = client.get(f"/api/media?path={media_file}")
        assert r.headers.get("cache-control", "").startswith("no-store")


# ===========================================================================
# SPA fallback (SPAStaticFiles) tests
# ===========================================================================

class TestSPAFallback:
    """Tests that unknown paths fall back to index.html (SPA deep-link support).

    These tests only run when WEB_DIST/index.html is present (it is committed
    to the repository under webui/dist/index.html).
    """

    def _skip_if_no_dist(self):
        """Skip the test if the dist directory/index.html is not available."""
        if not ws.WEB_DIST.exists() or not (ws.WEB_DIST / "index.html").exists():
            pytest.skip("webui/dist/index.html not present – skipping SPA fallback tests")

    @pytest.fixture(autouse=True)
    def _auto_skip_if_no_dist(self):
        """Automatically skip all tests in this class when dist is absent."""
        self._skip_if_no_dist()

    def test_deep_link_returns_200(self, client):
        """GET on an unknown deep path must return 200 (not 404)."""
        self._skip_if_no_dist()
        r = client.get("/du-an/bat-ky")
        assert r.status_code == 200

    def test_deep_link_serves_spa_html(self, client):
        """The body served for an unknown deep path must be the SPA index.html."""
        self._skip_if_no_dist()
        r = client.get("/du-an/bat-ky")
        body = r.text.lower()
        assert "<!doctype html" in body or '<div id="root"' in body

    def test_another_unknown_path_returns_spa(self, client):
        """A second unrelated deep path also returns the SPA."""
        self._skip_if_no_dist()
        r = client.get("/video/x/giong-doc")
        assert r.status_code == 200
        body = r.text.lower()
        assert "<!doctype html" in body or '<div id="root"' in body

    def test_index_html_itself_returns_200(self, client):
        """The real index.html asset is still served normally."""
        self._skip_if_no_dist()
        r = client.get("/index.html")
        assert r.status_code == 200

    def test_api_state_not_shadowed_by_spa(self, client):
        """API routes defined before the static mount must not be affected."""
        self._skip_if_no_dist()
        with patch("app.web_server._public_settings", return_value={
            "projects_dir": "/tmp/no-exist",
            "script_workflow_steps": [],
        }):
            r = client.get("/api/state")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/json")
        # Must be JSON, not HTML
        data = r.json()
        assert "settings" in data

    def test_real_asset_serves_true_content(self, client):
        """A real built JS asset must be served as-is, not replaced by the SPA HTML fallback."""
        assets_dir = ws.WEB_DIST / "assets"
        js_files = list(assets_dir.glob("*.js")) if assets_dir.is_dir() else []
        if not js_files:
            pytest.skip("No *.js files found under webui/dist/assets/ – skipping asset content test")
        asset_name = js_files[0].name
        r = client.get(f"/assets/{asset_name}")
        assert r.status_code == 200
        body = r.text
        # The body must NOT be the SPA HTML entry point
        assert "<div id=\"root\"" not in body, "Asset response looks like SPA HTML (contains <div id=\"root\")"
        assert not body.lstrip().lower().startswith("<!doctype"), "Asset response looks like SPA HTML (starts with <!doctype)"
