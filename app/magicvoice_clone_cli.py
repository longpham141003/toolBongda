from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def _normalize_instruct(text: str | None) -> str | None:
    value = (text or "").strip()
    return value or None


def _to_tensor(result):
    import numpy as np
    import torch

    item = result[0] if hasattr(result, "__getitem__") else result
    if isinstance(item, np.ndarray):
        item = torch.from_numpy(item.copy())
    if hasattr(item, "dim") and item.dim() == 1:
        item = item.unsqueeze(0)
    return item


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
                if not is_last_unit:
                    pause = 0.18
                elif is_last_sentence and not is_last_paragraph:
                    pause = 0.65
                elif unit.rstrip().endswith((".", "!", "?", "。", "！", "？")):
                    pause = 0.42
                elif unit.rstrip().endswith((",", ";", ":", "，", "；", "：")):
                    pause = 0.18
                else:
                    pause = 0.32
                append_phrase(unit, pause)

    if phrases:
        last_text, _ = phrases[-1]
        phrases[-1] = (last_text, 0.12)
    return phrases


def _insert_natural_pauses(tensor, phrases: list[tuple[str, float]], sample_rate: int, args):
    import torch
    import torch.nn.functional as functional

    if tensor.dim() == 1:
        tensor = tensor.unsqueeze(0)
    if len(phrases) <= 1 or tensor.shape[1] < sample_rate:
        return torch.cat([tensor.cpu(), torch.zeros((tensor.shape[0], int(sample_rate * 0.12)), dtype=tensor.dtype)], dim=1)

    weights = [max(1, len(re.findall(r"\w+", phrase, flags=re.UNICODE))) for phrase, _ in phrases]
    total_weight = max(1, sum(weights))
    energy = tensor.detach().float().abs().mean(dim=0).cpu()
    frame = max(1, int(sample_rate * 0.025))
    stride = max(1, int(sample_rate * 0.005))
    smoothed = functional.avg_pool1d(energy.view(1, 1, -1), kernel_size=frame, stride=stride).flatten()

    cut_points: list[tuple[int, float]] = []
    cumulative = 0
    previous_cut = 0
    search_radius = int(sample_rate * 1.25)
    min_gap = int(sample_rate * 0.35)
    total_samples = int(tensor.shape[1])
    for index, ((_, detected_pause), weight) in enumerate(zip(phrases[:-1], weights[:-1])):
        cumulative += weight
        target = int(total_samples * cumulative / total_weight)
        start = max(previous_cut + min_gap, target - search_radius)
        end = min(total_samples - min_gap, target + search_radius)
        if end <= start:
            continue
        pooled_start = max(0, start // stride)
        pooled_end = min(int(smoothed.numel()), max(pooled_start + 1, end // stride))
        quiet_index = int(torch.argmin(smoothed[pooled_start:pooled_end]).item()) + pooled_start
        cut = max(start, min(end, quiet_index * stride + frame // 2))
        if detected_pause >= 0.6:
            pause_seconds = max(0.0, float(args.paragraph_pause))
        elif detected_pause <= 0.2:
            pause_seconds = max(0.0, float(args.clause_pause))
        else:
            pause_seconds = max(0.0, float(args.sentence_pause))
        cut_points.append((cut, pause_seconds))
        previous_cut = cut

    if not cut_points:
        return torch.cat([tensor.cpu(), torch.zeros((tensor.shape[0], int(sample_rate * 0.12)), dtype=tensor.dtype)], dim=1)

    parts = []
    cursor = 0
    source = tensor.cpu()
    for cut, pause_seconds in cut_points:
        parts.append(source[:, cursor:cut])
        parts.append(torch.zeros((source.shape[0], max(1, int(sample_rate * pause_seconds))), dtype=source.dtype))
        cursor = cut
    parts.append(source[:, cursor:])
    parts.append(torch.zeros((source.shape[0], int(sample_rate * 0.12)), dtype=source.dtype))
    return torch.cat(parts, dim=1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate cloned voice with MagicVoice / OmniVoice")
    parser.add_argument("--text-file", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--steps", type=int, default=16)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="float16")
    parser.add_argument("--instruct", default="")
    parser.add_argument("--sentence-pause", type=float, default=0.42)
    parser.add_argument("--clause-pause", type=float, default=0.18)
    parser.add_argument("--paragraph-pause", type=float, default=0.65)
    args = parser.parse_args()

    text = Path(args.text_file).read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        raise ValueError("Text rỗng.")
    ref = Path(args.ref)
    if not ref.is_file():
        raise FileNotFoundError(f"Không thấy audio mẫu clone: {ref}")

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
    tts_text = re.sub(r"(?<=[.!?。！？])\s+", "\n", text)
    kwargs = {
        "text": tts_text,
        "ref_audio": str(ref),
        "num_step": max(4, int(args.steps)),
        "speed": float(args.speed or 1.0),
        "guidance_scale": 2.0,
    }
    instruct = _normalize_instruct(args.instruct)
    if instruct:
        kwargs["instruct"] = instruct
    try:
        with torch.inference_mode():
            result = model.generate(**kwargs)
    except TypeError as exc:
        if "unexpected keyword" in str(exc).lower() or "got an unexpected" in str(exc).lower():
            kwargs.pop("guidance_scale", None)
            with torch.inference_mode():
                result = model.generate(**kwargs)
        else:
            raise

    tensor = _to_tensor(result)
    if tensor is None:
        raise RuntimeError("MagicVoice không trả về audio tensor.")
    if tensor.dim() == 1:
        tensor = tensor.unsqueeze(0)
    if tensor.shape[0] > 1:
        tensor = tensor.mean(dim=0, keepdim=True)
    tensor = _insert_natural_pauses(tensor, phrases, 24000, args)
    print(f"Inserted natural pauses at {max(0, len(phrases) - 1)} sentence boundaries.")
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
