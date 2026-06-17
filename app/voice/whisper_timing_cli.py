from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create precise SRT timing with faster-whisper.")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-srt", type=Path, required=True)
    parser.add_argument("--model", default="base")
    parser.add_argument("--language", default="en")
    parser.add_argument("--beam-size", type=int, default=5)
    return parser.parse_args()


def srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def main() -> int:
    args = parse_args()
    os.environ["PYTHONUTF8"] = "1"
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    from faster_whisper import WhisperModel

    print(f"Whisper: loading {args.model} (CPU int8)...", flush=True)
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    raw_segments, info = model.transcribe(
        str(args.audio),
        language=args.language or None,
        beam_size=max(1, int(args.beam_size)),
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=True,
    )

    segments = []
    for raw in raw_segments:
        text = str(raw.text or "").strip()
        if not text:
            continue
        start = max(0.0, float(raw.start or 0.0))
        end = max(start + 0.05, float(raw.end or start))
        words = []
        for word in raw.words or []:
            word_text = str(word.word or "").strip()
            if not word_text:
                continue
            word_start = max(start, float(word.start if word.start is not None else start))
            word_end = max(word_start + 0.01, float(word.end if word.end is not None else word_start))
            words.append(
                {
                    "text": word_text,
                    "start": round(word_start, 4),
                    "end": round(word_end, 4),
                    "probability": round(float(word.probability or 0.0), 4),
                }
            )
        segments.append(
            {
                "text": text,
                "start": round(start, 4),
                "end": round(end, 4),
                "duration": round(end - start, 4),
                "words": words,
            }
        )

    if not segments:
        raise RuntimeError("Whisper did not return any speech segments.")

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_srt.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "audio": str(args.audio),
        "duration": round(max(item["end"] for item in segments), 4),
        "engine": "faster-whisper",
        "model": args.model,
        "language": str(getattr(info, "language", None) or args.language or ""),
        "language_probability": round(float(getattr(info, "language_probability", 0.0) or 0.0), 4),
        "segments": segments,
    }
    args.out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{srt_time(segment['start'])} --> {srt_time(segment['end'])}\n{segment['text']}"
        )
    args.out_srt.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "timing": str(args.out_json),
                "srt": str(args.out_srt),
                "segments": len(segments),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
