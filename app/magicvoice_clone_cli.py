from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


def _normalize_instruct(text: str | None) -> str | None:
    value = (text or "").strip()
    return value or None


def _to_tensor(result):
    import numpy as np
    import torch

    if isinstance(result, np.ndarray):
        item = result
    elif isinstance(result, (list, tuple)):
        item = result[0]
    else:
        item = result
    if isinstance(item, np.ndarray):
        item = torch.from_numpy(item.copy())
    if hasattr(item, "dim") and item.dim() == 1:
        item = item.unsqueeze(0)
    return item


FOREIGN_NAME_PRONUNCIATIONS = {
    "World Cup": "Uân Cúp",
    "Los Angeles": "Lót An-giơ-lét",
    "Paraguay": "Pa-ra-goay",
    "Mauricio Pochettino": "Mau-ri-xi-ô Pô-chét-ti-nô",
    "Folarin Balogun": "Fô-la-rin Ba-lô-gun",
    "Weston McKennie": "Oét-tơn Mắc-Ken-ni",
    "Gio Reyna": "Giô Rây-na",
    "Christian Pulisic": "Crít-chi-an Pu-li-sích",
}


def _prepare_spoken_text(text: str) -> str:
    """Apply speech-only hints while leaving the saved script unchanged."""
    spoken = str(text or "")
    for original, pronunciation in sorted(FOREIGN_NAME_PRONUNCIATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        spoken = re.sub(rf"\b{re.escape(original)}\b", pronunciation, spoken, flags=re.IGNORECASE)
    return spoken


def _prepare_reference_audio(ref: Path) -> Path:
    """Cache the clearest 3-10 second speech region from a long clone sample."""
    try:
        import soundfile as sf

        audio, sample_rate = sf.read(ref, dtype="float32", always_2d=True)
        duration = len(audio) / max(1, sample_rate)
        if duration <= 10.5:
            return ref

        prepared = ref.with_name(f"{ref.stem}.prepared.wav")
        metadata = ref.with_name(f"{ref.stem}.prepared.json")
        signature = {"size": int(ref.stat().st_size), "mtime_ns": int(ref.stat().st_mtime_ns)}
        if prepared.is_file() and metadata.is_file():
            cached = json.loads(metadata.read_text(encoding="utf-8"))
            if cached.get("source") == signature:
                return prepared

        from faster_whisper import WhisperModel

        model = WhisperModel("base", device="cpu", compute_type="int8")
        raw_segments, _ = model.transcribe(
            str(ref),
            language="vi",
            beam_size=3,
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=True,
        )
        candidates = []
        for segment in raw_segments:
            words = [word for word in segment.words or [] if str(word.word or "").strip()]
            start = max(0.0, float(segment.start or 0.0))
            end = min(duration, float(segment.end or start))
            segment_duration = end - start
            if segment_duration < 2.5:
                continue
            probabilities = [float(word.probability or 0.0) for word in words]
            confidence = sum(probabilities) / max(1, len(probabilities))
            length_bonus = min(segment_duration, 7.0) * 0.012
            candidates.append((confidence + length_bonus, start, end, str(segment.text or "").strip(), confidence))
        if not candidates:
            return ref

        _, start, end, transcript, confidence = max(candidates, key=lambda item: item[0])
        if end - start > 9.5:
            end = start + 9.5
        start = max(0.0, start - 0.12)
        end = min(duration, end + 0.18)
        clip = audio[int(start * sample_rate) : int(end * sample_rate)]
        if clip.shape[1] > 1:
            clip = clip.mean(axis=1, keepdims=True)
        sf.write(prepared, clip, sample_rate)
        metadata.write_text(
            json.dumps(
                {
                    "source": signature,
                    "start": round(start, 4),
                    "end": round(end, 4),
                    "confidence": round(confidence, 4),
                    "transcript": transcript,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Prepared clone reference: {start:.2f}-{end:.2f}s, confidence {confidence:.3f}")
        return prepared
    except Exception as exc:
        print(f"Reference preparation skipped: {exc}")
        return ref


def _split_natural_phrases(text: str, max_chars: int = 260) -> list[tuple[str, float]]:
    """Identify sentence/clause boundaries and the pause expected after each one."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    phrases: list[tuple[str, float]] = []
    paragraphs = [re.sub(r"\s+", " ", item).strip() for item in re.split(r"\n\s*\n", normalized) if item.strip()]

    def append_phrase(value: str, pause: float) -> None:
        value = re.sub(r"\s+", " ", value).strip()
        if value:
            phrases.append((value, pause))

    for paragraph_index, paragraph in enumerate(paragraphs):
        sentences = [item.strip() for item in re.split(r"(?<=[.!?。！？])\s+", paragraph) if item.strip()]
        for sentence_index, sentence in enumerate(sentences):
            units = [sentence]
            if len(sentence) > max_chars:
                units = [item.strip() for item in re.split(r"(?<=[,;:，；：])\s+", sentence) if item.strip()]

            expanded: list[str] = []
            for unit in units:
                if len(unit) <= max_chars:
                    expanded.append(unit)
                    continue
                words = unit.split()
                current: list[str] = []
                current_len = 0
                for word in words:
                    extra = len(word) + (1 if current else 0)
                    if current and current_len + extra > max_chars:
                        expanded.append(" ".join(current).rstrip(".!?;:, ") + ",")
                        current = [word]
                        current_len = len(word)
                    else:
                        current.append(word)
                        current_len += extra
                if current:
                    expanded.append(" ".join(current))

            for unit_index, unit in enumerate(expanded):
                is_last_unit = unit_index == len(expanded) - 1
                is_last_sentence = sentence_index == len(sentences) - 1
                is_last_paragraph = paragraph_index == len(paragraphs) - 1
                word_count = max(1, len(re.findall(r"\w+", unit, flags=re.UNICODE)))
                if not is_last_unit:
                    pause = 0.14 + min(0.08, word_count * 0.003)
                elif is_last_sentence and not is_last_paragraph:
                    pause = 0.58 + min(0.16, word_count * 0.006)
                elif unit.rstrip().endswith(("!", "?", "！", "？")):
                    pause = 0.34 + min(0.12, word_count * 0.005)
                elif unit.rstrip().endswith((".", "。")):
                    # Alternate the cadence slightly so consecutive sentences do not
                    # all land with the same synthetic pause.
                    cadence = (sentence_index % 3) * 0.045
                    pause = 0.31 + cadence + min(0.10, word_count * 0.004)
                elif unit.rstrip().endswith((",", ";", ":", "，", "；", "：")):
                    pause = 0.13 + min(0.08, word_count * 0.003)
                else:
                    pause = 0.27 + min(0.08, word_count * 0.003)
                append_phrase(unit, pause)

    if phrases:
        last_text, _ = phrases[-1]
        phrases[-1] = (last_text, 0.12)
    return phrases


def _pause_seconds(detected_pause: float, args) -> float:
    if detected_pause >= 0.55:
        return detected_pause * max(0.5, float(args.paragraph_pause) / 0.65)
    if detected_pause <= 0.24:
        return detected_pause * max(0.5, float(args.clause_pause) / 0.18)
    return detected_pause * max(0.5, float(args.sentence_pause) / 0.42)


def _combine_generated_phrases(audios, phrases: list[tuple[str, float]], sample_rate: int, args):
    import numpy as np
    import torch

    parts = []
    for index, audio in enumerate(audios):
        tensor = _to_tensor(audio)
        if tensor is None:
            raise RuntimeError(f"MagicVoice không trả về audio cho câu {index + 1}.")
        if tensor.dim() == 1:
            tensor = tensor.unsqueeze(0)
        if tensor.shape[0] > 1:
            tensor = tensor.mean(dim=0, keepdim=True)
        tensor = _trim_trailing_silence(tensor.cpu(), sample_rate)
        parts.append(tensor)
        if index < len(audios) - 1:
            pause_count = max(1, int(sample_rate * _pause_seconds(phrases[index][1], args)))
            # Keep a tiny room-noise floor instead of digital zero.
            noise = np.random.default_rng(42 + index).normal(0.0, 0.000025, pause_count).astype("float32")
            parts.append(torch.from_numpy(noise).unsqueeze(0).to(dtype=tensor.dtype))
    if not parts:
        raise RuntimeError("MagicVoice không tạo được câu thoại nào.")
    parts.append(torch.zeros((1, int(sample_rate * 0.14)), dtype=parts[0].dtype))
    return torch.cat(parts, dim=1)


def _trim_trailing_silence(tensor, sample_rate: int):
    """Remove only generated tail silence; retain a short natural release."""
    import torch

    if tensor.shape[1] < int(sample_rate * 0.25):
        return tensor
    mono = tensor.detach().float().abs().mean(dim=0)
    frame = max(1, int(sample_rate * 0.02))
    hop = max(1, int(sample_rate * 0.01))
    if mono.numel() < frame:
        return tensor
    frames = mono.unfold(0, frame, hop).mean(dim=1)
    peak = max(float(frames.max().item()), 1e-6)
    threshold = max(0.00035, peak * 0.006)
    voiced = torch.nonzero(frames > threshold, as_tuple=False).flatten()
    if not voiced.numel():
        return tensor
    # Preserve 120 ms after the last voiced frame so final consonants are safe.
    keep = min(tensor.shape[1], int(voiced[-1].item()) * hop + frame + int(sample_rate * 0.12))
    return tensor[:, :keep]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate cloned voice with MagicVoice / OmniVoice")
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--ref-text-file", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--steps", type=int, default=16)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="float16")
    parser.add_argument("--instruct", default="")
    parser.add_argument("--sentence-pause", type=float, default=0.28)
    parser.add_argument("--clause-pause", type=float, default=0.12)
    parser.add_argument("--paragraph-pause", type=float, default=0.43)
    parser.add_argument("--clarity-speed", type=float, default=0.96)
    parser.add_argument("--language", default="vi")
    parser.add_argument("--batch-size", type=int, default=3)
    args = parser.parse_args()

    text = Path(args.text_file).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        raise ValueError("Text rỗng.")
    ref = Path(args.ref)
    if not ref.is_file():
        raise FileNotFoundError(f"Không thấy audio mẫu clone: {ref}")
    ref = _prepare_reference_audio(ref)

    import torch
    import torchaudio
    from omnivoice import OmniVoice as MagicVoice

    device = args.device.strip().lower()
    if device in {"", "auto"}:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype_name = args.dtype.strip().lower()
    if device == "cpu" and dtype_name in {"float16", "bfloat16"}:
        dtype_name = "float32"
    dtype = {
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }.get(dtype_name, torch.float32)

    print(f"Loading MagicVoice model on {device} ({dtype_name})...")
    model = MagicVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)
    torch.manual_seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)

    phrases = _split_natural_phrases(text)
    if not phrases:
        raise ValueError("Text rỗng sau khi xử lý.")
    ref_text = None
    if str(args.ref_text_file or "").strip():
        ref_text_path = Path(args.ref_text_file)
        if ref_text_path.is_file():
            ref_text = ref_text_path.read_text(encoding="utf-8", errors="replace").strip() or None
    clone_prompt = model.create_voice_clone_prompt(str(ref), ref_text=ref_text)
    phrase_texts = [_prepare_spoken_text(phrase) for phrase, _ in phrases]
    generated_audios = []
    batch_size = max(1, min(int(args.batch_size or 3), 8))
    base_speed = float(args.speed or 1.0) * max(0.85, min(1.05, float(args.clarity_speed)))
    for batch_start in range(0, len(phrase_texts), batch_size):
        batch_texts = phrase_texts[batch_start : batch_start + batch_size]
        batch_speeds = [base_speed * (0.985 + ((batch_start + index) % 3) * 0.012) for index in range(len(batch_texts))]
        kwargs = {
            "text": batch_texts,
            "language": [str(args.language or "vi")] * len(batch_texts),
            "voice_clone_prompt": [clone_prompt] * len(batch_texts),
            "speed": batch_speeds,
            "num_step": max(16, int(args.steps)),
            "guidance_scale": 2.0,
            # Preserve consonant attacks at sentence starts. OmniVoice's edge
            # post-processing can trim Vietnamese initial sounds too tightly.
            "postprocess_output": False,
        }
        try:
            with torch.inference_mode():
                batch_result = model.generate(**kwargs)
        except TypeError as exc:
            message = str(exc).lower()
            if "unexpected keyword" not in message and "got an unexpected" not in message:
                raise
            kwargs.pop("guidance_scale", None)
            with torch.inference_mode():
                batch_result = model.generate(**kwargs)
        generated_audios.extend(batch_result)
        print(f"Generated sentences {batch_start + 1}-{batch_start + len(batch_texts)}/{len(phrase_texts)}")

    tensor = _combine_generated_phrases(generated_audios, phrases, 24000, args)
    print(f"Joined {len(phrases)} complete sentences with natural pauses.")
    peak = tensor.abs().max()
    if peak > 0.95:
        tensor = tensor * (0.891 / peak)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out), tensor.cpu(), 24000)
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
