from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeyEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QUrl

from ..config import load_settings, save_settings
from ..pipeline.script_workflow import default_workflow_steps, normalize_workflow_steps, run_script_workflow
from ..voice.text_to_voice_queue import DELIVERY_STYLES, LANGUAGES, kokoro_voice_choices
from ..pipeline.visual_pipeline import (
    build_asset_manifest,
    create_visual_project,
    export_capcut_project,
    generate_voice,
    load_manifest,
    save_manifest,
    search_and_download_asset,
    optimize_asset_keywords_with_ai,
)


class TaskThread(QThread):
    log = pyqtSignal(str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self.callback = callback

    def run(self):
        try:
            self.done.emit(self.callback(self.log.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


class ImageLightbox(QDialog):
    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(image_path.name)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setStyleSheet("QDialog { background: rgba(0, 0, 0, 235); }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_button = QPushButton("X")
        close_button.setFixedSize(42, 42)
        close_button.setStyleSheet(
            "QPushButton { color: white; background: rgba(40,40,40,210); border-radius: 21px; font-size: 20px; }"
            "QPushButton:hover { background: rgba(85,85,85,230); }"
        )
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.scene = QGraphicsScene(self)
        self.view = ZoomableImageView(self.scene)
        self.view.setStyleSheet("QGraphicsView { border: 0; background: transparent; }")
        pixmap = QPixmap(str(image_path))
        self.item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.item)
        self.scene.setSceneRect(self.item.boundingRect())
        layout.addWidget(self.view, 1)

        hint = QLabel("Cuộn chuột để zoom | Giữ chuột và kéo | Esc hoặc double-click để đóng")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #d1d5db; font-size: 13px; padding: 6px;")
        layout.addWidget(hint)

    def showEvent(self, event):
        super().showEvent(event)
        self.showFullScreen()
        self.view.fit_image()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.accept()


class ZoomableImageView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHints(self.renderHints())
        self.zoom_level = 0

    def fit_image(self):
        self.resetTransform()
        if not self.scene().sceneRect().isEmpty():
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_level = 0

    def wheelEvent(self, event: QWheelEvent):
        if event.angleDelta().y() > 0:
            factor = 1.2
            self.zoom_level += 1
        else:
            factor = 1 / 1.2
            self.zoom_level -= 1
        if self.zoom_level < 0:
            self.fit_image()
            return
        if self.zoom_level > 12:
            self.zoom_level = 12
            return
        self.scale(factor, factor)

    def mouseDoubleClickEvent(self, event):
        dialog = self.window()
        if isinstance(dialog, ImageLightbox):
            dialog.accept()
            return
        super().mouseDoubleClickEvent(event)


class ClickablePreview(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, image_path: str = "", parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Bấm để xem ảnh lớn")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_path:
            self.clicked.emit(self.image_path)
        super().mousePressEvent(event)


class VisualPipelineWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.project: Path | None = None
        self.worker: TaskThread | None = None
        self.setWindowTitle("Script -> Voice -> Asset -> CapCut")
        self.resize(1380, 900)
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        form = QFormLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Tên project")
        self.language_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.language_combo.addItem(label, code)
        language_index = self.language_combo.findData(str(self.settings.get("text_to_voice_language") or "en"))
        self.language_combo.setCurrentIndex(max(0, language_index))
        self.voice_combo = QComboBox()
        self.delivery_combo = QComboBox()
        for code, label in DELIVERY_STYLES.items():
            self.delivery_combo.addItem(label, code)
        delivery_index = self.delivery_combo.findData(str(self.settings.get("text_to_voice_delivery") or "dramatic"))
        self.delivery_combo.setCurrentIndex(max(0, delivery_index))
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setRange(0.5, 2.0)
        self.speed_input.setSingleStep(0.05)
        self.speed_input.setValue(float(self.settings.get("text_to_voice_speed") or 1.0))
        self.openai_key_input = QLineEdit(str(self.settings.get("openai_api_key") or ""))
        self.openai_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.gemini_key_input = QLineEdit(str(self.settings.get("gemini_api_key") or self.settings.get("openai_api_key") or ""))
        self.gemini_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.keyword_provider_combo = QComboBox()
        self.keyword_provider_combo.addItem("Auto", "auto")
        self.keyword_provider_combo.addItem("Gemini", "gemini")
        self.keyword_provider_combo.addItem("OpenAI", "openai")
        provider_index = self.keyword_provider_combo.findData(str(self.settings.get("keyword_ai_provider") or "auto"))
        self.keyword_provider_combo.setCurrentIndex(max(0, provider_index))
        self.keyword_model_input = QLineEdit(str(self.settings.get("keyword_ai_model") or "gpt-4.1-mini"))
        self.gemini_model_input = QLineEdit(str(self.settings.get("gemini_keyword_model") or "gemini-2.5-flash"))
        form.addRow("Tên project", self.title_input)
        form.addRow("Ngôn ngữ voice", self.language_combo)
        form.addRow("Giọng voice", self.voice_combo)
        form.addRow("Kiểu đọc", self.delivery_combo)
        form.addRow("Tốc độ", self.speed_input)
        form.addRow("AI provider", self.keyword_provider_combo)
        form.addRow("Gemini API key", self.gemini_key_input)
        form.addRow("Gemini model", self.gemini_model_input)
        form.addRow("OpenAI API key", self.openai_key_input)
        form.addRow("OpenAI model", self.keyword_model_input)
        layout.addLayout(form)
        self.language_combo.currentIndexChanged.connect(self.reload_voices)
        self.reload_voices()

        self.script_input = QTextEdit()
        self.script_input.setPlaceholderText("B0: Dán script final vào đây...")
        script_workflow_splitter = QSplitter(Qt.Orientation.Vertical)
        script_workflow_splitter.addWidget(self.script_input)
        script_workflow_splitter.addWidget(self._build_workflow_panel())
        script_workflow_splitter.setStretchFactor(0, 3)
        script_workflow_splitter.setStretchFactor(1, 2)
        script_workflow_splitter.setSizes([270, 230])
        layout.addWidget(script_workflow_splitter, 3)

        buttons = QHBoxLayout()
        self.create_button = QPushButton("B0 Tạo project")
        self.load_button = QPushButton("Mở project cũ")
        self.voice_button = QPushButton("B1 Tạo Kokoro Voice")
        self.analyze_button = QPushButton("B2 Tự chia cảnh theo SRT + keyword")
        self.search_all_button = QPushButton("B3 Tìm ảnh SportsDB/Google")
        self.retry_button = QPushButton("Tìm lại dòng đang chọn")
        self.approve_button = QPushButton("Duyệt / bỏ duyệt")
        self.capcut_button = QPushButton("B4 Xuất project CapCut")
        self.open_button = QPushButton("Mở thư mục project")
        for button in (
            self.create_button, self.load_button, self.voice_button, self.analyze_button, self.search_all_button,
            self.retry_button, self.approve_button, self.capcut_button, self.open_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["Preview", "Asset", "Câu", "Start", "End", "Lý do tách", "Keyword", "Trạng thái", "File", "Nguồn"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(2, 280)
        self.table.setColumnWidth(5, 130)
        self.table.setColumnWidth(6, 220)
        layout.addWidget(self.table, 4)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        layout.addWidget(self.log_box)

        self.create_button.clicked.connect(self.create_project)
        self.load_button.clicked.connect(self.load_project)
        self.voice_button.clicked.connect(self.create_voice)
        self.analyze_button.clicked.connect(self.analyze_assets)
        self.search_all_button.clicked.connect(self.search_all)
        self.retry_button.clicked.connect(self.retry_selected)
        self.approve_button.clicked.connect(self.toggle_approve)
        self.capcut_button.clicked.connect(self.export_capcut)
        self.open_button.clicked.connect(self.open_project)

    def _build_workflow_panel(self) -> QWidget:
        group = QGroupBox("Tạo script bằng AI Workflow (tùy chọn, kết quả sẽ đổ vào ô script phía trên)")
        layout = QVBoxLayout(group)

        self.workflow_input = QTextEdit()
        self.workflow_input.setPlaceholderText(
            "Nhập chủ đề, yêu cầu, dữ liệu thô hoặc thông tin nguồn. "
            "Có thể dùng {input} và {previous} trong prompt từng bước."
        )
        self.workflow_input.setPlainText(str(self.settings.get("script_workflow_input") or ""))
        self.workflow_input.setMaximumHeight(90)
        layout.addWidget(self.workflow_input)

        self.workflow_table = QTableWidget(0, 3)
        self.workflow_table.setHorizontalHeaderLabels(["Bật", "Tên bước", "Prompt / yêu cầu xử lý"])
        self.workflow_table.setColumnWidth(0, 55)
        self.workflow_table.setColumnWidth(1, 180)
        self.workflow_table.setColumnWidth(2, 850)
        self.workflow_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.workflow_table)

        buttons = QHBoxLayout()
        self.workflow_add_button = QPushButton("+ Thêm bước")
        self.workflow_remove_button = QPushButton("- Xóa bước")
        self.workflow_up_button = QPushButton("Lên")
        self.workflow_down_button = QPushButton("Xuống")
        self.workflow_reset_button = QPushButton("Workflow mẫu")
        self.workflow_run_button = QPushButton("Chạy Workflow → Script final")
        for button in (
            self.workflow_add_button,
            self.workflow_remove_button,
            self.workflow_up_button,
            self.workflow_down_button,
            self.workflow_reset_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.workflow_run_button)
        layout.addLayout(buttons)

        self.workflow_add_button.clicked.connect(self.add_workflow_step)
        self.workflow_remove_button.clicked.connect(self.remove_workflow_step)
        self.workflow_up_button.clicked.connect(lambda: self.move_workflow_step(-1))
        self.workflow_down_button.clicked.connect(lambda: self.move_workflow_step(1))
        self.workflow_reset_button.clicked.connect(self.reset_workflow_steps)
        self.workflow_run_button.clicked.connect(self.run_workflow)

        steps = normalize_workflow_steps(self.settings.get("script_workflow_steps"))
        self.set_workflow_steps(steps or default_workflow_steps())
        return group

    def workflow_steps(self) -> list[dict]:
        steps = []
        for row in range(self.workflow_table.rowCount()):
            enabled_item = self.workflow_table.item(row, 0)
            name_item = self.workflow_table.item(row, 1)
            prompt_item = self.workflow_table.item(row, 2)
            steps.append(
                {
                    "enabled": enabled_item is not None and enabled_item.checkState() == Qt.CheckState.Checked,
                    "name": name_item.text().strip() if name_item else f"Bước {row + 1}",
                    "prompt": prompt_item.text().strip() if prompt_item else "",
                }
            )
        return normalize_workflow_steps(steps)

    def set_workflow_steps(self, steps: list[dict]):
        self.workflow_table.setRowCount(0)
        for step in normalize_workflow_steps(steps):
            self._append_workflow_row(step)

    def _append_workflow_row(self, step: dict | None = None):
        step = step or {
            "enabled": True,
            "name": f"Bước {self.workflow_table.rowCount() + 1}",
            "prompt": "Mô tả rõ đầu ra bạn muốn AI tạo ở bước này.",
        }
        row = self.workflow_table.rowCount()
        self.workflow_table.insertRow(row)
        enabled = QTableWidgetItem()
        enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        enabled.setCheckState(Qt.CheckState.Checked if step.get("enabled", True) else Qt.CheckState.Unchecked)
        self.workflow_table.setItem(row, 0, enabled)
        self.workflow_table.setItem(row, 1, QTableWidgetItem(str(step.get("name") or f"Bước {row + 1}")))
        self.workflow_table.setItem(row, 2, QTableWidgetItem(str(step.get("prompt") or "")))
        self.workflow_table.setRowHeight(row, 52)

    def add_workflow_step(self):
        self._append_workflow_row()
        self.workflow_table.selectRow(self.workflow_table.rowCount() - 1)

    def remove_workflow_step(self):
        row = self.workflow_table.currentRow()
        if row >= 0:
            self.workflow_table.removeRow(row)

    def move_workflow_step(self, direction: int):
        row = self.workflow_table.currentRow()
        target = row + int(direction)
        if row < 0 or target < 0 or target >= self.workflow_table.rowCount():
            return
        steps = self.workflow_steps()
        steps[row], steps[target] = steps[target], steps[row]
        self.set_workflow_steps(steps)
        self.workflow_table.selectRow(target)

    def reset_workflow_steps(self):
        self.set_workflow_steps(default_workflow_steps())

    def run_workflow(self):
        source_input = self.workflow_input.toPlainText().strip()
        steps = self.workflow_steps()
        if not source_input:
            QMessageBox.warning(self, "Thiếu đầu vào", "Hãy nhập chủ đề/dữ liệu cho workflow.")
            return
        if not steps:
            QMessageBox.warning(self, "Thiếu workflow", "Hãy thêm ít nhất một bước workflow.")
            return
        self.save_api_settings()
        settings = dict(self.settings)
        self._run(
            lambda log: run_script_workflow(source_input, steps, settings, log=log),
            self._workflow_done,
        )

    def _workflow_done(self, script: str):
        self.script_input.setPlainText(str(script or "").strip())
        self.log("Workflow AI: đã đổ kết quả cuối vào ô script.")
        QMessageBox.information(self, "Workflow xong", "Đã tạo script final. Kiểm tra lại rồi bấm B0/B1.")

    def log(self, message: str):
        self.log_box.append(str(message))

    def save_api_settings(self):
        self.settings["text_to_voice_language"] = str(self.language_combo.currentData() or "en")
        self.settings["text_to_voice_voice"] = self.voice_combo.currentText().strip()
        self.settings["text_to_voice_delivery"] = str(self.delivery_combo.currentData() or "dramatic")
        self.settings["text_to_voice_speed"] = self.speed_input.value()
        self.settings["openai_api_key"] = self.openai_key_input.text().strip()
        self.settings["gemini_api_key"] = self.gemini_key_input.text().strip()
        self.settings["keyword_ai_provider"] = str(self.keyword_provider_combo.currentData() or "auto")
        self.settings["keyword_ai_model"] = self.keyword_model_input.text().strip() or "gpt-4.1-mini"
        self.settings["gemini_keyword_model"] = self.gemini_model_input.text().strip() or "gemini-2.5-flash"
        if hasattr(self, "workflow_table"):
            self.settings["script_workflow_steps"] = self.workflow_steps()
        if hasattr(self, "workflow_input"):
            self.settings["script_workflow_input"] = self.workflow_input.toPlainText()
        save_settings(self.settings)

    def reload_voices(self):
        language = str(self.language_combo.currentData() or "en")
        current = self.voice_combo.currentText().strip() or str(self.settings.get("text_to_voice_voice") or "")
        choices = kokoro_voice_choices(self.settings, language)
        self.voice_combo.clear()
        self.voice_combo.addItems(choices)
        index = self.voice_combo.findText(current)
        self.voice_combo.setCurrentIndex(index if index >= 0 else 0)

    def create_project(self):
        script = self.script_input.toPlainText().strip()
        if not script:
            QMessageBox.warning(self, "Thiếu script", "Hãy dán script final.")
            return
        self.save_api_settings()
        projects_dir = Path(str(self.settings.get("projects_dir") or "Projects"))
        self.project = create_visual_project(projects_dir, self.title_input.text(), script)
        self.log(f"Đã tạo project: {self.project}")

    def load_project(self):
        projects_dir = str(self.settings.get("projects_dir") or "")
        selected = QFileDialog.getExistingDirectory(self, "Chon project cu", projects_dir)
        if not selected:
            return
        project = Path(selected)
        script_path = project / "scripts" / "script_final.txt"
        if not script_path.exists():
            QMessageBox.warning(self, "Không đúng project", "Không tìm thấy scripts/script_final.txt.")
            return
        self.project = project
        self.title_input.setText(project.name)
        self.script_input.setPlainText(script_path.read_text(encoding="utf-8", errors="replace"))
        self.refresh_table()
        self.log(f"Đã mở project: {project}")

    def _ensure_project(self) -> bool:
        if self.project:
            return True
        QMessageBox.warning(self, "Chưa có project", "Hãy bấm B0 Tạo project trước.")
        return False

    def _run(self, callback, on_done=None):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Đang chạy", "Một tác vụ khác đang chạy.")
            return
        self.worker = TaskThread(callback, self)
        self.worker.log.connect(self.log)
        self.worker.failed.connect(self._task_failed)
        self.worker.done.connect(on_done or (lambda result: self.log("Đã xong.")))
        self.worker.finished.connect(self._task_finished)
        self._set_task_buttons_enabled(False)
        self.worker.start()

    def _task_failed(self, error: str):
        QMessageBox.critical(self, "Lỗi", error)
        self.log(f"LỖI: {error}")

    def _task_finished(self):
        self._set_task_buttons_enabled(True)
        if self.worker:
            self.worker.deleteLater()
        self.worker = None

    def _set_task_buttons_enabled(self, enabled: bool):
        for button in (
            self.create_button,
            self.load_button,
            self.voice_button,
            self.analyze_button,
            self.search_all_button,
            self.retry_button,
            self.capcut_button,
        ):
            button.setEnabled(enabled)
        if hasattr(self, "workflow_run_button"):
            self.workflow_run_button.setEnabled(enabled)
        self.retry_button.setText("Tìm lại dòng đang chọn" if enabled else "Đang xử lý...")

    def create_voice(self):
        if not self._ensure_project():
            return
        project = self.project
        current_script = self.script_input.toPlainText().strip()
        if not current_script:
            QMessageBox.warning(self, "Thiếu script", "Ô script đang rỗng.")
            return
        script_path = project / "scripts" / "script_final.txt"
        previous_script = script_path.read_text(encoding="utf-8", errors="replace").strip() if script_path.exists() else ""
        if current_script != previous_script:
            script_path.write_text(current_script + "\n", encoding="utf-8")
            self.log("B1: đã đồng bộ script hiện tại vào project.")
        self._run(lambda log: generate_voice(project, self.settings, log), lambda path: self.log(f"Voice: {path}"))

    def analyze_assets(self):
        if not self._ensure_project():
            return
        self.save_api_settings()
        project = self.project

        def task(log):
            items = build_asset_manifest(project, self.settings, log=log)
            log(f"Đã tự chia {len(items)} cảnh theo Whisper SRT + ngữ cảnh.")
            items = optimize_asset_keywords_with_ai(project, self.settings, log=log)
            return items

        self._run(task, lambda items: (self.refresh_table(), self.log(f"Đã tạo keyword cho {len(items)} cảnh.")))

    def search_all(self):
        if not self._ensure_project():
            return
        self.save_api_settings()
        project = self.project

        def task(log):
            items = load_manifest(project)
            for index, item in enumerate(items):
                if item.get("status") == "approved":
                    continue
                items[index] = search_and_download_asset(project, item, log, settings=self.settings)
                save_manifest(project, items)
            return items

        self._run(task, lambda _: self.refresh_table())

    def retry_selected(self):
        if not self._ensure_project():
            return
        row = self.table.currentRow()
        if row < 0:
            return
        self.save_api_settings()
        project = self.project
        asset_id = self.table.item(row, 1).text() if self.table.item(row, 1) else f"dòng {row + 1}"
        self.log(f"{asset_id}: bắt đầu tìm lại ảnh...")

        def task(log):
            items = load_manifest(project)
            if row >= len(items):
                raise RuntimeError("Dòng asset đã thay đổi. Hãy chọn lại.")
            items[row]["status"] = "pending"
            items[row] = search_and_download_asset(project, items[row], log, settings=self.settings)
            save_manifest(project, items)
            return items[row]

        self._run(task, self._retry_done)

    def _retry_done(self, item):
        self.refresh_table()
        status = str((item or {}).get("status") or "")
        error = str((item or {}).get("error") or "")
        if error and status == "downloaded":
            self.log(f"{item.get('asset_id')}: không có ảnh mới, đang giữ ảnh cũ. {error}")
        elif status == "downloaded":
            self.log(f"{item.get('asset_id')}: đã tìm lại xong.")
        else:
            self.log(f"{item.get('asset_id')}: tìm lại không thành công. {error}")

    def toggle_approve(self):
        if not self._ensure_project():
            return
        row = self.table.currentRow()
        if row < 0:
            return
        items = load_manifest(self.project)
        current = str(items[row].get("status") or "")
        items[row]["status"] = "downloaded" if current == "approved" else "approved"
        save_manifest(self.project, items)
        self.refresh_table()

    def refresh_table(self):
        if not self.project:
            return
        items = load_manifest(self.project)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            preview = ClickablePreview(str(item.get("local_path") or ""))
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            path = Path(str(item.get("local_path") or ""))
            if path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    preview.setPixmap(pixmap.scaled(140, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                    preview.clicked.connect(self.open_image_lightbox)
            self.table.setCellWidget(row, 0, preview)
            values = [
                item.get("asset_id"),
                f"{item.get('sentence_indexes')}: {item.get('sentence_text')}",
                item.get("start"),
                item.get("end"),
                item.get("scene_break_reason"),
                item.get("keyword"),
                item.get("status"),
                item.get("local_path"),
                item.get("source_page") or item.get("source_url"),
            ]
            for column, value in enumerate(values, start=1):
                self.table.setItem(row, column, QTableWidgetItem(str(value or "")))
            self.table.setRowHeight(row, 86)

    def open_image_lightbox(self, image_path: str):
        path = Path(str(image_path or ""))
        if not path.exists():
            QMessageBox.warning(self, "Không thấy ảnh", str(path))
            return
        ImageLightbox(path, self).exec()

    def export_capcut(self):
        if not self._ensure_project():
            return
        project = self.project
        title = self.title_input.text().strip() or project.name
        self._run(
            lambda log: export_capcut_project(project, title, install_to_capcut=True),
            lambda path: self._capcut_done(Path(path)),
        )

    def _capcut_done(self, path: Path):
        self.log(f"Đã xuất CapCut: {path}")
        opened = self.open_capcut_app()
        note = "Đã mở CapCut." if opened else "Không tự mở được CapCut, hãy mở thủ công."
        QMessageBox.information(self, "Đã xuất", f"Project đã nằm trong CapCut:\n{path}\n\n{note}\nNếu chưa thấy project, đóng hẳn CapCut rồi mở lại.")

    def open_capcut_app(self) -> bool:
        configured = str(self.settings.get("capcut_exe_path") or "").strip()
        candidates = []
        if configured:
            candidates.append(Path(configured))
        appdata = Path(os.environ.get("APPDATA") or "")
        if appdata:
            candidates.append(appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "CapCut" / "CapCut.lnk")
        for candidate in candidates:
            if candidate.exists():
                try:
                    os.startfile(str(candidate))
                    self.log(f"Đã mở CapCut: {candidate}")
                    return True
                except Exception as exc:
                    self.log(f"Không mở được CapCut qua {candidate}: {exc}")
        try:
            subprocess.Popen(
                ["explorer.exe", "shell:AppsFolder\\d:.bytedance.capcut.apps.8.5.0.3590.capcut.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.log("Đã gọi CapCut qua AppsFolder.")
            return True
        except Exception as exc:
            self.log(f"Không mở được CapCut: {exc}")
            return False

    def open_project(self):
        if self.project:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project)))


def main() -> int:
    app = QApplication(sys.argv)
    window = VisualPipelineWindow()
    window.show()
    return app.exec()
