from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .text_to_voice_cli import (
    combine_wavs,
    is_voice_segment_text,
    sanitize_text_for_tts,
    shift_segment_timing,
    split_text_for_text_to_voice,
)


KOKORO_LANGUAGE_CODES = {
    "en": "a",
    "en-gb": "b",
    "es": "e",
    "fr": "f",
    "hi": "h",
    "it": "i",
    "ja": "j",
    "pt": "p",
    "zh": "z",
}

LANGUAGES = {
    "en": "American English",
    "en-gb": "British English",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "pt": "Brazilian Portuguese",
    "zh": "Mandarin Chinese",
}

KOKORO_VOICES = {
    "en": [
        "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore",
        "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky", "am_adam",
        "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
        "am_puck", "am_santa",
    ],
    "en-gb": ["bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel", "bm_fable", "bm_george", "bm_lewis"],
    "es": ["ef_dora", "em_alex", "em_santa"],
    "fr": ["ff_siwis"],
    "hi": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"],
    "it": ["if_sara", "im_nicola"],
    "ja": ["jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro", "jm_kumo"],
    "pt": ["pf_dora", "pm_alex", "pm_santa"],
    "zh": ["zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi", "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang"],
}


def normalize_kokoro_language(language: str | None) -> tuple[str, str | None]:
    code = str(language or "en").strip().lower()
    aliases = {"a": "en", "b": "en-gb", "e": "es", "f": "fr", "h": "hi", "i": "it", "j": "ja", "p": "pt", "z": "zh"}
    code = aliases.get(code, code)
    if code in KOKORO_LANGUAGE_CODES:
        return code, None
    return "en", f"Kokoro chưa hỗ trợ ngôn ngữ '{code}'. Tool đã chuyển về American English."


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


def _terminate_process_tree(process: subprocess.Popen, timeout: float = 8.0) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=max(2, int(timeout)),
                check=False,
                **_win_hidden_kwargs(),
            )
            return
        except Exception:
            pass
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def text_to_voice_root(settings: dict) -> Path:
    raw = str(settings.get("text_to_voice_root") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path
    return Path(__file__).resolve().parents[1] / "kokoro-tts-local"


def text_to_voice_python(settings: dict, root: Path | None = None) -> Path:
    raw = str(settings.get("text_to_voice_python") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path
    root = root or text_to_voice_root(settings)
    if os.name == "nt":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def magicvoice_root(settings: dict) -> Path:
    raw = str(settings.get("magicvoice_root") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path
    return Path(__file__).resolve().parents[1] / "magic_voice"


def magicvoice_python(settings: dict, root: Path | None = None) -> Path:
    root = root or magicvoice_root(settings)
    raw = str(settings.get("magicvoice_python") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        return path
    candidates: list[Path] = []
    if os.name == "nt":
        candidates.extend(
            [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "python.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python310" / "python.exe",
                Path("C:/Python311/python.exe"),
                Path("C:/Python310/python.exe"),
                Path("C:/Program Files/Python311/python.exe"),
                Path("C:/Program Files/Python310/python.exe"),
                Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe",
                Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python310" / "python.exe",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path("py")


def bootstrap_magicvoice(settings: dict, log: Callable[[str], None] | None = None) -> tuple[Path, list[str]]:
    root = magicvoice_root(settings)
    python = magicvoice_python(settings, root)
    setup_script = root / "setup_visual_capcut.ps1" if os.name == "nt" else root / "setup.sh"
    if not setup_script.exists():
        raise FileNotFoundError(f"Không thấy bộ cài MagicVoice: {setup_script}")
    if python == Path("py"):
        for version_arg in ("-3.11", "-3.10"):
            probe = subprocess.run(["py", version_arg, "-c", "import omnivoice, soundfile"], capture_output=True, text=True, check=False, **_win_hidden_kwargs())
            if probe.returncode == 0:
                return root, ["py", version_arg]
    elif python.is_file():
        probe = subprocess.run([str(python), "-c", "import omnivoice, soundfile"], capture_output=True, text=True, check=False, **_win_hidden_kwargs())
        if probe.returncode == 0:
            return root, [str(python)]
    if callable(log):
        log("Lần đầu dùng clone giọng: đang cài MagicVoice local. Bước này có thể lâu vì cần Python 3.11, Torch và OmniVoice.")
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(setup_script)]
    else:
        cmd = ["sh", str(setup_script)]
    result = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1800, int(settings.get("voice_clone_setup_timeout") or 3600)),
        check=False,
        **_win_hidden_kwargs(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Cài MagicVoice thất bại. {detail[-2000:]}")
    python = magicvoice_python(settings, root)
    if python == Path("py"):
        for version_arg in ("-3.11", "-3.10"):
            probe = subprocess.run(["py", version_arg, "-c", "import omnivoice, soundfile"], capture_output=True, text=True, check=False, **_win_hidden_kwargs())
            if probe.returncode == 0:
                if callable(log):
                    log("Đã cài xong MagicVoice local.")
                return root, ["py", version_arg]
    elif python.is_file():
        probe = subprocess.run([str(python), "-c", "import omnivoice, soundfile"], capture_output=True, text=True, check=False, **_win_hidden_kwargs())
        if probe.returncode == 0:
            if callable(log):
                log("Đã cài xong MagicVoice local.")
            return root, [str(python)]
    raise FileNotFoundError("Cài MagicVoice xong nhưng vẫn thiếu thư viện clone giọng cần thiết.")


def kokoro_custom_voice_dir(settings: dict, language: str = "en") -> Path:
    root = text_to_voice_root(settings)
    normalized, _ = normalize_kokoro_language(language)
    return root / "custom_voices" / normalized


def bootstrap_text_to_voice(settings: dict, log: Callable[[str], None] | None = None) -> tuple[Path, Path]:
    root = text_to_voice_root(settings)
    python = text_to_voice_python(settings, root)
    if python.exists():
        return root, python
    setup_script = root / "setup.ps1" if os.name == "nt" else root / "setup.sh"
    if not root.exists():
        raise FileNotFoundError(f"Không thấy thư mục Kokoro: {root}")
    if not (root / "app.py").exists():
        raise FileNotFoundError(f"Không thấy Kokoro app.py trong: {root}")
    if not setup_script.exists():
        raise FileNotFoundError(f"Không thấy Python venv của Kokoro: {python}. Không có file setup: {setup_script}")
    if callable(log):
        log("Lần đầu dùng Kokoro trên máy này: đang cài môi trường voice local...")
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(setup_script)]
    else:
        cmd = ["sh", str(setup_script)]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(900, int(settings.get("text_to_voice_timeout") or 1800)),
        env=env,
        check=False,
        **_win_hidden_kwargs(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Cài Kokoro local thất bại. {detail[-1600:]}")
    if not python.exists():
        raise FileNotFoundError(f"Cài Kokoro xong nhưng vẫn không thấy Python venv: {python}")
    if callable(log):
        log("Đã cài xong môi trường Kokoro local.")
    return root, python


def validate_text_to_voice(settings: dict) -> tuple[Path, Path]:
    root = text_to_voice_root(settings)
    python = text_to_voice_python(settings, root)
    if not root.exists():
        raise FileNotFoundError(f"Không thấy thư mục Text to Voice: {root}")
    if not (root / "app.py").exists():
        raise FileNotFoundError(f"Không thấy Kokoro app.py trong: {root}")
    if not python.exists():
        return bootstrap_text_to_voice(settings)
    return root, python


def kokoro_voice_choices(settings: dict, language: str = "en") -> list[str]:
    normalized, _ = normalize_kokoro_language(language)
    voices = list(KOKORO_VOICES.get(normalized) or KOKORO_VOICES["en"])
    custom_dir = kokoro_custom_voice_dir(settings, normalized)
    if custom_dir.exists():
        voices.extend(str(path.resolve()) for path in sorted(custom_dir.glob("*.pt")))
    return voices


def _clone_reference_path(settings: dict) -> Path | None:
    raw = str(settings.get("voice_clone_reference_path") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path if path.is_file() else None


def _script_sentences_for_timing(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])(?:[\"')\]]+)?\s+", normalized)
    return [part.strip() for part in parts if is_voice_segment_text(part)]


def _estimated_segments_from_text(text: str, duration: float) -> list[dict]:
    sentences = _script_sentences_for_timing(text)
    if not sentences:
        return []
    total_duration = max(0.5, float(duration or 0.0))
    weights = [max(1, len(re.findall(r"\S+", sentence))) for sentence in sentences]
    total_weight = max(1, sum(weights))
    segments: list[dict] = []
    cursor = 0.0
    for index, (sentence, weight) in enumerate(zip(sentences, weights), start=1):
        if index == len(sentences):
            end = total_duration
        else:
            end = min(total_duration, cursor + total_duration * (weight / total_weight))
        end = max(cursor + 0.05, end)
        segments.append(
            {
                "text": sentence,
                "start": round(cursor, 4),
                "end": round(end, 4),
                "duration": round(end - cursor, 4),
                "script_sentence_index": index,
                "timing_source": "estimated_magicvoice",
            }
        )
        cursor = end
    return segments


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
    root = text_to_voice_root(settings)
    python = text_to_voice_python(settings, root)
    if not python.exists():
        root, python = bootstrap_text_to_voice(settings, log=log)
    else:
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


def _kokoro_generate(settings: dict, payload: dict, timeout_seconds: int) -> dict:
    request = Request(
        f"{text_to_voice_url(settings)}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(30, int(timeout_seconds))) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = str(json.loads(detail).get("error") or detail)
        except Exception:
            pass
        raise RuntimeError(detail) from exc
    except (URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"Không kết nối được Kokoro local: {exc}") from exc
    if not isinstance(result, dict) or not result.get("path"):
        raise RuntimeError("Kokoro local không trả về file audio.")
    return result


def warm_kokoro_server(settings: dict, log: Callable[[str], None] | None = None) -> None:
    ensure_text_to_voice_server(settings, log=log)
    language, _ = normalize_kokoro_language(settings.get("text_to_voice_language"))
    voices = kokoro_voice_choices(settings, language)
    voice = str(settings.get("text_to_voice_voice") or "")
    if voice not in voices:
        voice = voices[0]
    try:
        result = _kokoro_generate(
            settings,
            {
                "text": "Kokoro is ready.",
                "lang": KOKORO_LANGUAGE_CODES[language],
                "voice": voice,
                "speed": 1.0,
                "prefix": "preview",
                "delivery": "plain",
            },
            timeout_seconds=180,
        )
        Path(str(result.get("path") or "")).unlink(missing_ok=True)
        if callable(log):
            log("Kokoro đã được làm nóng và sẵn sàng.")
    except Exception as exc:
        if callable(log):
            log(f"Kokoro chưa làm nóng được: {exc}")


class TextToVoiceRunner:
    def __init__(self, settings: dict, log: Callable[[str], None], stop_check: Callable[[], bool]):
        self.settings = settings
        self.log = log
        self.stop_check = stop_check
        self.root: Path | None = None
        self.python: Path | None = None
        self._last_sampling_log = ""

    def start(self) -> None:
        if bool(self.settings.get("voice_clone_enabled")) and _clone_reference_path(self.settings):
            self.root = text_to_voice_root(self.settings)
            self.python = text_to_voice_python(self.settings, self.root)
            self.log("MagicVoice clone mode: dùng audio mẫu để clone giọng tiếng Việt/đa ngôn ngữ.")
            return
        self.root, self.python = validate_text_to_voice(self.settings)
        ensure_text_to_voice_server(self.settings, log=self.log)
        self.log(f"Kokoro TTS đã sẵn sàng: {self.root}")

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

        text_path = Path(text_path).resolve()
        output_path = Path(output_path).resolve()
        text = sanitize_text_for_tts(text_path.read_text(encoding="utf-8", errors="replace"))
        if not text:
            raise ValueError("Text rỗng.")
        requested_language = str(self.settings.get("text_to_voice_language") or "en").lower()
        language, language_warning = normalize_kokoro_language(requested_language)
        if language_warning:
            self.log(f"Text to Voice {label}: {language_warning}")
        max_chars = max(1000, min(int(self.settings.get("text_to_voice_max_chars") or 10000), 12000))
        chunks = split_text_for_text_to_voice(text, max_chars)
        chunk_estimate = len(chunks)

        cache_key = self._cache_key(text_path)
        if self._can_reuse_output(output_path, cache_key):
            self.log(f"Text to Voice {label}: dùng lại audio đã có {output_path.name}")
            return str(output_path)

        if bool(self.settings.get("voice_clone_enabled")):
            reference_path = _clone_reference_path(self.settings)
            if reference_path:
                return self._submit_file_magicvoice(text, label, output_path, cache_key, reference_path)
            self.log(f"Text to Voice {label}: clone giọng đang bật nhưng chưa có audio mẫu, dùng Kokoro preset.")

        voices = kokoro_voice_choices(self.settings, language)
        voice = str(self.settings.get("text_to_voice_voice") or "").strip()
        if voice not in voices:
            voice = voices[0]
            self.log(f"Text to Voice {label}: giọng cũ không thuộc Kokoro, tự chọn {voice}.")
        timeout_seconds = self._adaptive_timeout_seconds(chunk_estimate)
        self.log(
            f"Text to Voice {label}: chuẩn bị tạo khoảng {chunk_estimate} đoạn, timeout {round(timeout_seconds / 60)} phút."
        )
        generated_paths: list[Path] = []
        generated_results: list[dict] = []
        try:
            for index, chunk in enumerate(chunks, start=1):
                if self.stop_check():
                    raise RuntimeError("Stopped.")
                self.log(f"Text to Voice {label}: đang tạo đoạn {index}/{chunk_estimate}")
                result = _kokoro_generate(
                    self.settings,
                    {
                        "text": chunk,
                        "lang": KOKORO_LANGUAGE_CODES[language],
                        "voice": voice,
                        "speed": float(self.settings.get("text_to_voice_speed") or 1.0),
                        "prefix": "preview" if label == "preview" else "",
                        "delivery": str(self.settings.get("text_to_voice_delivery") or "dramatic"),
                    },
                    timeout_seconds=timeout_seconds,
                )
                source_path = Path(str(result["path"]))
                if not source_path.exists():
                    raise RuntimeError(f"Kokoro không tạo file: {source_path}")
                part_path = output_path.with_name(f"{output_path.stem}.part{index:03d}.wav")
                shutil.copy2(source_path, part_path)
                generated_paths.append(part_path)
                generated_results.append(result)

            if len(generated_paths) == 1:
                shutil.copy2(generated_paths[0], output_path)
                duration = float(generated_results[0].get("duration") or 0.0)
            else:
                duration = combine_wavs(generated_paths, output_path)

            combined_segments: list[dict] = []
            offset = 0.0
            for index, result in enumerate(generated_results):
                for segment in result.get("segments", []):
                    if isinstance(segment, dict) and is_voice_segment_text(str(segment.get("text") or "")):
                        combined_segments.append(shift_segment_timing(segment, offset))
                offset += float(result.get("duration") or 0.0)
                if index < len(generated_results) - 1:
                    offset += 0.25

            output_path.with_suffix(".segments.json").write_text(
                json.dumps(
                    {
                        "audio": str(output_path),
                        "duration": round(duration, 4),
                        "sampleRate": int(generated_results[0].get("sampleRate") or 24000),
                        "lang": KOKORO_LANGUAGE_CODES[language],
                        "voice": voice,
                        "speed": float(self.settings.get("text_to_voice_speed") or 1.0),
                        "delivery": str(self.settings.get("text_to_voice_delivery") or "dramatic"),
                        "engine": "kokoro-server",
                        "segments": combined_segments,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            for part_path in generated_paths:
                part_path.unlink(missing_ok=True)

        final_path = output_path
        parts = len(generated_results)
        suffix = f" ({parts} phần)" if parts > 1 else ""
        self._write_cache_meta(final_path, cache_key)
        self.log(f"Text to Voice {label}: đã lưu audio {final_path.name}{suffix}")
        return str(final_path)

    def _submit_file_magicvoice(self, text: str, label: str, output_path: Path, cache_key: dict, reference_path: Path) -> str:
        root, python_cmd = bootstrap_magicvoice(self.settings, log=self.log)
        max_chars = max(600, min(int(self.settings.get("voice_clone_max_chars") or 900), 1800))
        chunks = split_text_for_text_to_voice(text, max_chars)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        generated_paths: list[Path] = []
        timeout_seconds = max(900, int(self.settings.get("voice_clone_timeout") or 3600))
        try:
            for index, chunk in enumerate(chunks, start=1):
                if self.stop_check():
                    raise RuntimeError("Stopped.")
                part_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.wav")
                text_part_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.txt")
                stdout_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.stdout.log")
                stderr_path = output_path.with_name(f"{output_path.stem}.magicvoice{index:03d}.stderr.log")
                text_part_path.write_text(chunk, encoding="utf-8")
                self.log(f"Text to Voice {label}: MagicVoice đang clone đoạn {index}/{len(chunks)}")
                command = [
                    *python_cmd,
                    str(Path(__file__).resolve().parent / "magicvoice_clone_cli.py"),
                    "--text-file",
                    str(text_part_path),
                    "--ref",
                    str(reference_path),
                    "--out",
                    str(part_path),
                    "--steps",
                    str(int(self.settings.get("magicvoice_steps") or 16)),
                    "--speed",
                    str(float(self.settings.get("text_to_voice_speed") or 1.0)),
                    "--device",
                    str(self.settings.get("magicvoice_device") or "auto"),
                    "--dtype",
                    str(self.settings.get("magicvoice_dtype") or "float16"),
                    "--sentence-pause",
                    str(float(self.settings.get("magicvoice_sentence_pause") or 0.42)),
                    "--clause-pause",
                    str(float(self.settings.get("magicvoice_clause_pause") or 0.18)),
                    "--paragraph-pause",
                    str(float(self.settings.get("magicvoice_paragraph_pause") or 0.65)),
                    "--clarity-speed",
                    str(float(self.settings.get("magicvoice_clarity_speed") or 0.96)),
                ]
                with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout, stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
                    result = subprocess.run(
                        command,
                        cwd=str(Path(__file__).resolve().parents[1]),
                        stdout=stdout,
                        stderr=stderr,
                        text=True,
                        timeout=timeout_seconds,
                        check=False,
                        **_win_hidden_kwargs(),
                    )
                if result.returncode != 0 or not part_path.exists():
                    detail = ""
                    for path in (stderr_path, stdout_path):
                        if path.exists():
                            detail += "\n" + path.read_text(encoding="utf-8", errors="replace")[-1600:]
                    raise RuntimeError(f"MagicVoice clone thất bại ở đoạn {index}/{len(chunks)}.{detail}")
                generated_paths.append(part_path)
                text_part_path.unlink(missing_ok=True)

            if len(generated_paths) == 1:
                shutil.copy2(generated_paths[0], output_path)
                duration = 0.0
                try:
                    import wave
                    with wave.open(str(output_path), "rb") as wav:
                        duration = wav.getnframes() / max(1, wav.getframerate())
                except Exception:
                    pass
            else:
                duration = combine_wavs(generated_paths, output_path)
            estimated_segments = _estimated_segments_from_text(text, duration)

            output_path.with_suffix(".segments.json").write_text(
                json.dumps(
                    {
                        "audio": str(output_path),
                        "duration": round(float(duration), 4),
                        "sampleRate": 24000,
                        "lang": str(self.settings.get("text_to_voice_language") or "vi"),
                        "voice": str(reference_path),
                        "speed": 1.0,
                        "delivery": "magicvoice-clone",
                        "engine": "magicvoice",
                        "segments": estimated_segments,
                        "timing_source": "estimated_magicvoice",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        finally:
            for part_path in generated_paths:
                part_path.unlink(missing_ok=True)

        self._write_cache_meta(output_path, cache_key)
        self.log(f"Text to Voice {label}: đã lưu audio clone MagicVoice {output_path.name} ({len(chunks)} phần)")
        return str(output_path)

    def _adaptive_timeout_seconds(self, chunk_estimate: int) -> int:
        configured = max(300, int(self.settings.get("text_to_voice_timeout") or 1800))
        estimated = 180 + max(1, int(chunk_estimate)) * 300
        return max(configured, min(7200, estimated))

    @staticmethod
    def _estimate_chunk_count(text: str, max_words: int) -> int:
        words = re.findall(r"\S+", text or "")
        return max(1, (len(words) + max(1, max_words) - 1) // max(1, max_words))

    @staticmethod
    def _looks_english(text: str) -> bool:
        sample = " ".join(re.findall(r"[A-Za-z']+", text or "")[:250]).lower()
        if not sample:
            return False
        common = {
            "the",
            "and",
            "with",
            "from",
            "that",
            "their",
            "they",
            "this",
            "when",
            "into",
            "after",
            "before",
            "match",
            "team",
            "goal",
        }
        tokens = sample.split()
        if not tokens:
            return False
        hits = sum(1 for token in tokens if token in common)
        ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(1, len(text))
        return ascii_ratio > 0.92 and hits >= 4

    def _stream_progress_logs(
        self,
        stdout_path: Path,
        stderr_path: Path,
        stdout_offset: int,
        stderr_offset: int,
        label: str,
        last_chunk: str,
    ) -> tuple[int, int, str]:
        stdout_offset, stdout_text = self._read_new_text(stdout_path, stdout_offset)
        stderr_offset, stderr_text = self._read_new_text(stderr_path, stderr_offset)
        for line in stdout_text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            match = re.search(r"Kokoro chunk\s+(\d+)\s*/\s*(\d+)", clean, flags=re.I)
            if match:
                current, total = match.group(1), match.group(2)
                message = f"Text to Voice {label}: đang tạo đoạn {current}/{total}"
                if message != last_chunk:
                    self.log(message)
                    last_chunk = message
                continue
        del stderr_text
        return stdout_offset, stderr_offset, last_chunk

    @staticmethod
    def _read_new_text(path: Path, offset: int) -> tuple[int, str]:
        if not path.exists():
            return offset, ""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                text = handle.read()
                return handle.tell(), text
        except Exception:
            return offset, ""

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
            "voice": str(self.settings.get("text_to_voice_voice") or "af_heart"),
            "speed": str(float(self.settings.get("text_to_voice_speed") or 1.0)),
            "delivery": str(self.settings.get("text_to_voice_delivery") or "dramatic"),
            "max_chars": str(int(self.settings.get("text_to_voice_max_chars") or 10000)),
            "engine": "magicvoice" if bool(self.settings.get("voice_clone_enabled")) and _clone_reference_path(self.settings) else "kokoro",
            "voice_clone_reference_path": str(self.settings.get("voice_clone_reference_path") or ""),
            "voice_clone_engine": str(self.settings.get("voice_clone_engine") or ""),
            "segment_cleaner": "tts_clean_v9_magicvoice_natural_cadence",
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
            timing = json.loads(timing_path.read_text(encoding="utf-8"))
            if not isinstance(timing, dict) or not timing.get("segments"):
                return False
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
