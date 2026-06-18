# Regression: the bundled CapCut template lives at repo-root capcut_template/, so
# _find_capcut_template must resolve it via APP_DIR (parents[2]), not parents[1] (app/).
# Before the fix, with no CapCut drafts the bundled template was never found and export
# raised "Không tìm thấy draft CapCut hợp lệ...".
import sys
import types
from pathlib import Path
import unittest.mock as mock

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

with mock.patch.dict(
    sys.modules,
    {"app.voice.text_to_voice_queue": types.ModuleType("app.voice.text_to_voice_queue")},
):
    sys.modules["app.voice.text_to_voice_queue"].TextToVoiceRunner = mock.MagicMock()  # type: ignore[attr-defined]
    from app.pipeline import visual_pipeline as vp


def test_find_capcut_template_falls_back_to_bundled(tmp_path):
    # capcut_root that does not exist (user has no CapCut drafts).
    fake_capcut_root = tmp_path / "no-capcut" / "com.lveditor.draft"
    found = vp._find_capcut_template(fake_capcut_root)
    assert found == repo_root / "capcut_template"
    assert (found / "draft_content.json").is_file()
    assert (found / "draft_meta_info.json").is_file()
