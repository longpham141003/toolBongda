# tests/test_subtitle_payload.py
from app.pipeline.subtitle_store import save_subtitle
from app.web.web_server import _project_payload


def _make_project(tmp_path):
    project = tmp_path / "video1"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "script_final.txt").write_text("Câu một. Câu hai.\n", encoding="utf-8")
    return project


def test_payload_without_subtitle(tmp_path):
    project = _make_project(tmp_path)
    payload = _project_payload(project)
    assert payload is not None
    assert payload["has_subtitle"] is False
    assert payload["subtitle_segments"] == []


def test_payload_with_subtitle(tmp_path):
    project = _make_project(tmp_path)
    save_subtitle(project, [{"start": 0.0, "end": 2.0, "text": "Câu một"}])
    payload = _project_payload(project)
    assert payload["has_subtitle"] is True
    assert len(payload["subtitle_segments"]) == 1
    assert payload["subtitle_segments"][0]["text"] == "Câu một"
