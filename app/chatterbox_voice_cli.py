from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Visual CapCut voice with Chatterbox TTS.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--voice", default="")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--delivery", default="dramatic")
    parser.add_argument("--max-words", type=int, default=40)
    parser.add_argument("--disable-qa", action="store_true")
    return parser.parse_args()


def delivery_exaggeration(name: str) -> float:
    return {
        "plain": 0.35,
        "natural": 0.50,
        "expressive": 0.70,
        "dramatic": 0.90,
        "heavy_drama": 1.20,
        "storytelling": 0.72,
        "calm": 0.38,
    }.get(str(name or "").lower(), 0.70)


def resolve_voice(root: Path, voice: str, language: str) -> str | None:
    voice_dir = root / "modules" / "voice_samples"
    clean = str(voice or "").strip()
    if clean.lower() in {"", "none", "default"}:
        return None
    direct = voice_dir / f"{clean}.wav"
    if direct.exists():
        return str(direct)
    normalized = clean.replace(" male", "_male").replace(" female", "_female")
    candidates = [voice_dir / f"{normalized}.wav"]
    if language != "en":
        candidates.append(voice_dir / f"{normalized}_{language}.wav")
    for path in candidates:
        if path.exists():
            return str(path)
    raise FileNotFoundError(f"Khong thay voice Chatterbox: {clean}")


def write_outputs(output_path: Path, chunks: list[str], wavs: list, sample_rate: int, metadata: dict) -> None:
    import torch
    import torchaudio

    if not wavs:
        raise RuntimeError("Chatterbox khong tao duoc audio.")
    normalized = []
    segments = []
    cursor = 0.0
    for text, wav in zip(chunks, wavs):
        audio = wav.detach().cpu().float()
        if audio.dim() == 1:
            audio = audio.unsqueeze(0)
        if audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)
        duration = audio.shape[-1] / float(sample_rate)
        normalized.append(audio)
        segments.append(
            {
                "text": text,
                "start": round(cursor, 4),
                "end": round(cursor + duration, 4),
                "duration": round(duration, 4),
            }
        )
        cursor += duration

    output_path.parent.mkdir(parents=True, exist_ok=True)
    full_audio = torch.cat(normalized, dim=-1)
    torchaudio.save(str(output_path), full_audio, sample_rate, encoding="PCM_S", bits_per_sample=16)
    timing_path = output_path.with_suffix(".segments.json")
    timing_path.write_text(
        json.dumps(
            {
                "audio": str(output_path),
                "duration": round(cursor, 4),
                "sampleRate": int(sample_rate),
                "engine": "chatterbox",
                "segments": segments,
                **metadata,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    os.environ["PYTHONUTF8"] = "1"
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from text_to_voice_cli import sanitize_text_for_tts
    from modules.generation_functions import _generate_with_qa, smart_chunk_text
    from modules.model_manager import model_manager

    text = sanitize_text_for_tts(args.input.read_text(encoding="utf-8"))
    chunks = smart_chunk_text(text, max_words=max(12, min(int(args.max_words), 60)))
    if not chunks:
        raise ValueError("Script rong.")

    language = str(args.lang or "en").lower()
    voice_path = resolve_voice(root, args.voice, language)
    exaggeration = delivery_exaggeration(args.delivery)
    cfg_weight = max(0.15, min(0.85, 0.50 + ((float(args.speed) - 1.0) * 0.35)))
    temperature = 0.80

    import modules.generation_functions as generation

    if args.disable_qa:
        generation.WHISPER_VALIDATION = False

    if language == "en":
        model = model_manager.get_tts_model()
        if model is None:
            raise RuntimeError("Khong load duoc Chatterbox TTS model.")

        def generate_chunk(chunk: str):
            return model.generate(
                chunk,
                audio_prompt_path=voice_path,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight,
                min_p=0.05,
                top_p=1.0,
                repetition_penalty=1.2,
            )
    else:
        model = model_manager.get_mtl_model()
        if model is None:
            raise RuntimeError("Khong load duoc Chatterbox Multilingual model.")

        def generate_chunk(chunk: str):
            return model.generate(
                chunk,
                language_id=language,
                audio_prompt_path=voice_path,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfg_weight,
            )

    wavs = []
    qa = []
    for index, chunk in enumerate(chunks, start=1):
        print(f"Chatterbox chunk {index}/{len(chunks)}", flush=True)
        wav, similarity, attempts = _generate_with_qa(
            lambda current=chunk: generate_chunk(current),
            chunk,
            model.sr,
            language=language,
        )
        wavs.append(wav)
        qa.append({"chunk": index, "similarity": similarity, "attempts": attempts})

    output_path = args.out.with_suffix(".wav")
    write_outputs(
        output_path,
        chunks,
        wavs,
        model.sr,
        {
            "lang": language,
            "voice": args.voice,
            "speed": args.speed,
            "delivery": args.delivery,
            "qa": qa,
        },
    )
    print(
        json.dumps(
            {
                "output": str(output_path),
                "timing": str(output_path.with_suffix(".segments.json")),
                "parts": len(chunks),
                "engine": "chatterbox",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
