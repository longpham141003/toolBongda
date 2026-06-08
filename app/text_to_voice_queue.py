from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen


LANGUAGES = {
    "en": "English",
    "vi": "Vietnamese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "pt": "Portuguese",
    "zh": "Chinese",
}

VOICES = {"en": ["Default"], "vi": ["Default"]}

DELIVERY_STYLES = {
    "plain": "Mặc định",
    "natural": "Tự nhiên",
    "expressive": "Nhẹ nhàng",
    "dramatic": "Diễn cảm",
    "heavy_drama": "Heavy Drama",
    "storytelling": "Kể chuyện",
    "calm": "Điềm tĩnh",
}


def _win_hidden_kwargs() -> dict:
    if os.name != "nt":
        return {}
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        return {"startupinfo": si, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    except Exception:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def text_to_voice_root(settings: dict) -> Path:
    raw = str(settings.get("text_to_voice_root") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path
    return Path(__file__).resolve().parents[1] / "magic_voice"


def text_to_voice_python(settings: dict, root: Path | None = None) -> Path:
    raw = str(settings.get("text_to_voice_python") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path
    root = root or text_to_voice_root(settings)
    bundled = Path(__file__).resolve().parents[1] / "chatterbox-venv"
    if os.name == "nt" and (bundled / "Scripts" / "python.exe").exists():
        return bundled / "Scripts" / "python.exe"
    if os.name == "nt":
        return root / "venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def validate_text_to_voice(settings: dict) -> tuple[Path, Path]:
    root = text_to_voice_root(settings)
    python = text_to_voice_python(settings, root)
    if not root.exists():
        raise FileNotFoundError(f"Không thấy thư mục Text to Voice: {root}")
    if not (root / "modules" / "model_manager.py").exists():
        raise FileNotFoundError(f"Không thấy Chatterbox modules trong: {root}")
    if not python.exists():
        raise FileNotFoundError(
            f"Không thấy Python venv của Chatterbox: {python}. Hãy chạy 1_CAI_DAT.bat."
        )
    return root, python


def chatterbox_voice_choices(settings: dict, language: str = "en") -> list[str]:
    root = text_to_voice_root(settings)
    voice_dir = root / "modules" / "voice_samples"
    choices = ["Default"]
    if not voice_dir.exists():
        return choices
    for path in sorted(voice_dir.glob("*.wav"), key=lambda value: value.name.lower()):
        stem = path.stem
        if language == "en":
            suffixes = tuple(f"_{code}" for code in LANGUAGES if code != "en")
            if stem.endswith(suffixes):
                continue
        elif not stem.endswith(f"_{language}"):
            continue
        choices.append(stem)
    return choices


def text_to_voice_url(settings: dict) -> str:
    host = str(settings.get("text_to_voice_host") or "127.0.0.1")
    port = int(settings.get("text_to_voice_port") or 7860)
    return f"http://{host}:{port}"


def is_text_to_voice_server_ready(settings: dict) -> bool:
    try:
        with urlopen(text_to_voice_url(settings), timeout=1.5) as response:
            return int(response.status or 0) == 200
    except (URLError, OSError, ValueError):
        return False


def wait_for_text_to_voice_server(settings: dict, timeout_seconds: int = 30) -> bool:
    deadline = time.time() + int(timeout_seconds)
    while time.time() < deadline:
        if is_text_to_voice_server_ready(settings):
            return True
        time.sleep(0.4)
    return False


def text_to_voice_parallel_jobs(settings: dict, fallback: int = 8) -> int:
    raw = settings.get("text_to_voice_parallel_jobs")
    if raw in (None, ""):
        raw = fallback
    try:
        count = int(str(raw).strip())
    except Exception:
        count = int(fallback or 8)
    return max(1, min(count, 20))


def ensure_text_to_voice_server(settings: dict, log: Callable[[str], None] | None = None) -> str:
    root, python = validate_text_to_voice(settings)
    url = text_to_voice_url(settings)
    if is_text_to_voice_server_ready(settings):
        if callable(log):
            log(f"Text to Voice UI đã sẵn sàng: {url}")
        return url

    log_path = root / "ui-server.log"
    err_path = root / "ui-server.err.log"
    cmd = [
        str(python),
        str(root / "app.py"),
        "--host",
        str(settings.get("text_to_voice_host") or "127.0.0.1"),
        "--port",
        str(int(settings.get("text_to_voice_port") or 7860)),
    ]
    if callable(log):
        log(f"Khởi động Text to Voice UI: {url}")
    process_env = os.environ.copy()
    process_env["PYTHONUTF8"] = "1"
    process_env["PYTHONIOENCODING"] = "utf-8"
    with log_path.open("a", encoding="utf-8") as stdout, err_path.open("a", encoding="utf-8") as stderr:
        subprocess.Popen(cmd, cwd=str(root), stdout=stdout, stderr=stderr, env=process_env, **_win_hidden_kwargs())

    if not wait_for_text_to_voice_server(settings, timeout_seconds=45):
        raise RuntimeError(f"Text to Voice UI chưa sẵn sàng ở {url}. Xem log: {err_path}")
    return url


class TextToVoiceRunner:
    def __init__(self, settings: dict, log: Callable[[str], None], stop_check: Callable[[], bool]):
        self.settings = settings
        self.log = log
        self.stop_check = stop_check
        self.root: Path | None = None
        self.python: Path | None = None

    def start(self) -> None:
        self.root, self.python = validate_text_to_voice(self.settings)
        self.log(f"Chatterbox TTS đã sẵn sàng: {self.root}")

    def close(self) -> None:
        return None

    def submit_chapter(self, chapter_index: int, text_path: str, output_path: str) -> str:
        text_file = Path(text_path)
        text = text_file.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("Text chapter rỗng.")

        output = Path(output_path)
        if output.suffix.lower() != ".wav":
            output = output.with_suffix(".wav")
        output.parent.mkdir(parents=True, exist_ok=True)

        label = f"chapter_{int(chapter_index):02d}"
        self.log(f"Text to Voice {label}: tạo audio ({len(text)} ký tự)")
        return self.submit_file(text_file, label, output)

    def submit_file(self, text_path: Path, label: str, output_path: Path) -> str:
        if self.root is None or self.python is None:
            raise RuntimeError("Text to Voice runner chưa start.")
        if self.stop_check():
            raise RuntimeError("Stopped.")

        cache_key = self._cache_key(text_path)
        if self._can_reuse_output(output_path, cache_key):
            self.log(f"Text to Voice {label}: dùng lại audio đã có {output_path.name}")
            return str(output_path)

        cli_path = Path(__file__).with_name("chatterbox_voice_cli.py")
        cmd = [
            str(self.python),
            str(cli_path),
            "--root",
            str(self.root),
            "--input",
            str(text_path),
            "--out",
            str(output_path),
            "--lang",
            str(self.settings.get("text_to_voice_language") or "en"),
            "--voice",
            str(self.settings.get("text_to_voice_voice") or "Default"),
            "--mode",
            str(self.settings.get("text_to_voice_mode") or "standard"),
            "--speed",
            str(float(self.settings.get("text_to_voice_speed") or 1.0)),
            "--delivery",
            str(self.settings.get("text_to_voice_delivery") or "dramatic"),
            "--max-words",
            str(int(self.settings.get("chatterbox_max_words") or 40)),
            "--exaggeration",
            str(float(self.settings.get("chatterbox_exaggeration") or -1.0)),
            "--cfg-weight",
            str(float(self.settings.get("chatterbox_cfg_weight") or 0.5)),
            "--temperature",
            str(float(self.settings.get("chatterbox_temperature") or 0.8)),
            "--seed",
            str(int(self.settings.get("chatterbox_seed") or 0)),
            "--min-p",
            str(float(self.settings.get("chatterbox_min_p") or 0.05)),
            "--top-p",
            str(float(self.settings.get("chatterbox_top_p") or 1.0)),
            "--repetition-penalty",
            str(float(self.settings.get("chatterbox_repetition_penalty") or 1.2)),
        ]
        if not bool(self.settings.get("chatterbox_whisper_qa", True)):
            cmd.append("--disable-qa")
        timeout_seconds = int(self.settings.get("text_to_voice_timeout") or 1800)
        stdout_path = output_path.with_suffix(".ttv.stdout.log")
        stderr_path = output_path.with_suffix(".ttv.stderr.log")
        stdout_file = stdout_path.open("w", encoding="utf-8")
        stderr_file = stderr_path.open("w", encoding="utf-8")
        process_env = os.environ.copy()
        process_env["PYTHONUTF8"] = "1"
        process_env["PYTHONIOENCODING"] = "utf-8"
        hf_home = str(self.settings.get("chatterbox_hf_home") or "").strip()
        if hf_home:
            process_env["HF_HOME"] = hf_home
            process_env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            process_env["HF_HUB_OFFLINE"] = "1"
        process = subprocess.Popen(
            cmd,
            cwd=str(self.root),
            stdout=stdout_file,
            stderr=stderr_file,
            env=process_env,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_win_hidden_kwargs(),
        )

        deadline = time.time() + timeout_seconds
        last_log = 0.0
        try:
            while process.poll() is None:
                if self.stop_check():
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise RuntimeError("Stopped.")
                if time.time() > deadline:
                    process.kill()
                    raise RuntimeError(f"Timeout tạo Text to Voice: {label}")
                if time.time() - last_log >= 20:
                    self.log(f"Text to Voice {label}: đang tạo audio...")
                    last_log = time.time()
                time.sleep(0.5)
        finally:
            stdout_file.close()
            stderr_file.close()

        stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        if process.returncode != 0:
            detail = (stderr or stdout or "").strip()
            raise RuntimeError(detail[-1400:] or f"Text to Voice thất bại với exit code {process.returncode}")

        result = self._parse_result(stdout)
        final_path = Path(str(result.get("output") or output_path))
        if not final_path.exists():
            raise RuntimeError(f"Text to Voice không tạo file output: {final_path}")
        parts = int(result.get("parts") or 1)
        suffix = f" ({parts} phần)" if parts > 1 else ""
        self._write_cache_meta(final_path, cache_key)
        self.log(f"Text to Voice {label}: đã lưu audio {final_path.name}{suffix}")
        return str(final_path)

    @staticmethod
    def _parse_result(stdout: str) -> dict:
        for line in reversed(str(stdout or "").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        return {}

    def _cache_key(self, text_path: Path) -> dict:
        stat = text_path.stat()
        return {
            "text_path": str(text_path.resolve()),
            "text_size": int(stat.st_size),
            "text_mtime_ns": int(stat.st_mtime_ns),
            "language": str(self.settings.get("text_to_voice_language") or "en"),
            "voice": str(self.settings.get("text_to_voice_voice") or "Default"),
            "mode": str(self.settings.get("text_to_voice_mode") or "standard"),
            "speed": str(float(self.settings.get("text_to_voice_speed") or 1.0)),
            "delivery": str(self.settings.get("text_to_voice_delivery") or "dramatic"),
            "exaggeration": str(float(self.settings.get("chatterbox_exaggeration") or -1.0)),
            "cfg_weight": str(float(self.settings.get("chatterbox_cfg_weight") or 0.5)),
            "temperature": str(float(self.settings.get("chatterbox_temperature") or 0.8)),
            "seed": str(int(self.settings.get("chatterbox_seed") or 0)),
            "max_chars": str(int(self.settings.get("text_to_voice_max_chars") or 10000)),
            "segment_cleaner": "tts_clean_v5",
        }

    @staticmethod
    def _can_reuse_output(output_path: Path, cache_key: dict) -> bool:
        meta_path = output_path.with_suffix(".ttv.meta.json")
        timing_path = output_path.with_suffix(".segments.json")
        if (
            not output_path.exists()
            or output_path.stat().st_size <= 1024
            or not meta_path.exists()
            or not timing_path.exists()
        ):
            return False
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return data == cache_key
        except Exception:
            return False

    @staticmethod
    def _write_cache_meta(output_path: Path, cache_key: dict) -> None:
        try:
            output_path.with_suffix(".ttv.meta.json").write_text(
                json.dumps(cache_key, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


class TextToVoiceQueue:
    def __init__(
        self,
        settings: dict,
        log: Callable[[str], None],
        status: Callable[[int, str, str], None],
        max_workers: int | None = None,
    ):
        self.settings = settings
        self.log = log
        self.status = status
        self.max_workers = text_to_voice_parallel_jobs(settings, fallback=max_workers or 8)
        self.jobs: queue.Queue[dict | None] = queue.Queue()
        self.stop_requested = False
        self.finish_requested = False
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.is_alive():
            return
        self.stop_requested = False
        self.finish_requested = False
        self.threads = []
        self.log(f"Text to Voice song song: {self.max_workers} voice worker")
        for index in range(1, self.max_workers + 1):
            thread = threading.Thread(
                target=self._run_worker,
                args=(index,),
                name=f"text-to-voice-worker-{index}",
                daemon=True,
            )
            self.threads.append(thread)
            thread.start()

    def enqueue(self, chapter_index: int, text_path: str, output_path: str) -> None:
        self.jobs.put({"chapter_index": int(chapter_index), "text_path": str(text_path), "output_path": str(output_path)})

    def finish_when_empty(self) -> None:
        if self.finish_requested:
            return
        self.finish_requested = True
        for _ in range(max(1, len(self.threads) or self.max_workers)):
            self.jobs.put(None)

    def stop(self) -> None:
        self.stop_requested = True
        for _ in range(max(1, len(self.threads) or self.max_workers)):
            self.jobs.put(None)

    def is_alive(self) -> bool:
        return any(thread.is_alive() for thread in self.threads)

    def _run_worker(self, worker_index: int) -> None:
        runner = TextToVoiceRunner(self.settings, log=self.log, stop_check=lambda: self.stop_requested)
        started = False
        try:
            while not self.stop_requested:
                job = self.jobs.get()
                if job is None:
                    break
                chapter_index = int(job.get("chapter_index") or 0)
                try:
                    if not started:
                        runner.start()
                        started = True
                    self.status(chapter_index, "running", f"Đang tạo Text to Voice worker {worker_index}")
                    detail = runner.submit_chapter(
                        chapter_index,
                        str(job.get("text_path") or ""),
                        str(job.get("output_path") or ""),
                    )
                    self.status(chapter_index, "done", detail)
                except Exception as exc:
                    self.status(chapter_index, "error", str(exc))
                    self.log(f"Text to Voice lỗi chapter {chapter_index:02d}: {exc}")
        finally:
            if started:
                runner.close()
