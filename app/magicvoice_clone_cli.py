from __future__ import annotations

import argparse
import os
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

    kwargs = {
        "text": text,
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
