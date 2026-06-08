"""
Speech generation, conversion, and utility functions for Chatterbox TTS Enhanced
"""
import os
import random
import numpy as np
import torch
import time
import re
from .config import DEVICE, LANGUAGE_CONFIG, SUPPORTED_LANGUAGES
from .model_manager import model_manager
from .voice_manager import resolve_voice_path


# ---------------------------------------------------------------
# Stop flag: cho phép người dùng bấm nút DỪNG giữa chừng.
# Tool sẽ dừng sau khi đọc xong đoạn hiện tại, lưu phần đã tạo
# vào outputs (kèm SRT) để nghe thử.
# ---------------------------------------------------------------
_stop_requested = False


def request_stop():
    """Called by the Stop button. Sets flag checked between chunks."""
    global _stop_requested
    _stop_requested = True
    return "⏸ Đã nhận lệnh DỪNG. Tool sẽ tạm dừng sau khi đọc xong đoạn hiện tại và lưu phần đã tạo để anh nghe thử.\nSau đó bấm ▶ TIẾP TỤC để chạy nốt, hoặc TẠO AUDIO để làm lại từ đầu."


def _clear_stop():
    global _stop_requested
    _stop_requested = False


def set_seed(seed: int):
    """Set random seed for reproducibility."""
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)


def estimate_generation_time(text_length):
    """Estimate generation time based on text length."""
    return (text_length / 50) * 2 + 1


def format_time(seconds):
    """Format seconds into readable time string."""
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    minutes = int(seconds // 60)
    seconds = seconds % 60
    return f"{minutes} minute{'s' if minutes != 1 else ''} {seconds:.1f} seconds"


def smart_chunk_text(text, max_words=40):
    """
    Intelligently chunk text based on sentence boundaries and word count.
    Accumulates sentences to maximize chunk size up to max_words.
    Supports all languages including CJK (Chinese, Japanese, Korean).
    """
    # Detect if text contains CJK characters (Chinese, Japanese, Korean)
    def has_cjk(text):
        return bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', text))
    
    is_cjk = has_cjk(text)
    
    # Enhanced sentence pattern supporting multiple languages
    # Includes: . ! ? (Western), 。！？ (CJK), । (Hindi), ؟ (Arabic)
    sentence_pattern = r'(?<=[.!?。！？।؟])\s*|\n+'
    sentences = re.split(sentence_pattern, text)
    
    chunks = []
    current_chunk = []
    current_count = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        
        # Count words (space-separated) or characters (CJK)
        if is_cjk:
            sentence_count = len(re.sub(r'\s+', '', sentence))
        else:
            sentence_count = len(sentence.split())
        
        # Check if adding this sentence exceeds the limit
        if current_count + sentence_count > max_words:
            # If current chunk is not empty, save it
            if current_chunk:
                chunks.append(' '.join(current_chunk) if not is_cjk else ''.join(current_chunk))
                current_chunk = []
                current_count = 0
            
            # If the single sentence itself is longer than max_words, we must split it
            if sentence_count > max_words:
                # Split at commas/semicolons: , ; (Western), ，、； (CJK), ، (Arabic)
                sub_parts = re.split(r'[,;،、；،]\s*', sentence)
                for part in sub_parts:
                    part = part.strip()
                    if not part:
                        continue
                    
                    if is_cjk:
                        part_count = len(re.sub(r'\s+', '', part))
                    else:
                        part_count = len(part.split())
                    
                    if current_count + part_count > max_words and current_chunk:
                        chunks.append(' '.join(current_chunk) if not is_cjk else ''.join(current_chunk))
                        current_chunk = [part]
                        current_count = part_count
                    else:
                        current_chunk.append(part)
                        current_count += part_count
            else:
                # Sentence fits in a new chunk
                current_chunk.append(sentence)
                current_count += sentence_count
        else:
            # Sentence fits in current chunk
            current_chunk.append(sentence)
            current_count += sentence_count
    
    # Add remaining chunk
    if current_chunk:
        chunks.append(' '.join(current_chunk) if not is_cjk else ''.join(current_chunk))
    
    return chunks if chunks else [text]



SRT_MAX_CUE_CHARS = 40  # nguyên tắc: mỗi cue phụ đề không quá 40 ký tự


def _split_cue_text(txt, max_chars=SRT_MAX_CUE_CHARS):
    """Split text into subtitle cues of at most max_chars, breaking on word boundaries."""
    words = txt.split()
    cues = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip()
        if current and len(candidate) > max_chars:
            cues.append(current)
            current = w
        else:
            current = candidate
    if current:
        cues.append(current)
    return cues if cues else [txt.strip()]


def save_outputs_with_srt(text_chunks, generated_wavs, sr, mode="tts", validation_log=None):
    """Save final audio, each chunk wav, and an auto-generated SRT subtitle file.
    SRT cues are split to max SRT_MAX_CUE_CHARS chars each; timing within a chunk
    is distributed proportionally to cue text length."""
    try:
        import torchaudio
        from datetime import datetime

        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_dir = os.path.join(project_root, "outputs", f"{stamp}_{mode}")
        os.makedirs(out_dir, exist_ok=True)

        def fmt(ms):
            h, ms = divmod(int(ms), 3600000)
            m, ms = divmod(ms, 60000)
            s, ms = divmod(ms, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        srt_lines = []
        cursor_ms = 0
        cleaned = []
        cue_index = 1
        for i, (txt, wav) in enumerate(zip(text_chunks, generated_wavs)):
            wav_cpu = wav.detach().cpu()
            if wav_cpu.dim() == 1:
                wav_cpu = wav_cpu.unsqueeze(0)
            torchaudio.save(os.path.join(out_dir, f"chunk_{i+1:04d}.wav"), wav_cpu, sr)
            dur_ms = wav_cpu.shape[-1] / sr * 1000

            # Split chunk text into short cues (max 40 chars) and spread the
            # chunk's real audio duration across them by character share.
            cues = _split_cue_text(txt)
            total_chars = sum(len(c) for c in cues)
            cue_start = cursor_ms
            for j, cue_text in enumerate(cues):
                if j == len(cues) - 1:
                    cue_end = cursor_ms + dur_ms  # last cue ends exactly at chunk end
                else:
                    share = (len(cue_text) / total_chars) if total_chars else (1.0 / len(cues))
                    cue_end = cue_start + dur_ms * share
                srt_lines.append(str(cue_index))
                srt_lines.append(f"{fmt(cue_start)} --> {fmt(cue_end)}")
                srt_lines.append(cue_text)
                srt_lines.append("")
                cue_index += 1
                cue_start = cue_end

            cursor_ms += dur_ms
            cleaned.append(wav_cpu)

        full_wav = torch.cat(cleaned, dim=-1) if len(cleaned) > 1 else cleaned[0]
        torchaudio.save(os.path.join(out_dir, "full_audio.wav"), full_wav, sr)
        with open(os.path.join(out_dir, "subtitles.srt"), "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))
        with open(os.path.join(out_dir, "script.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(text_chunks))
        if validation_log:
            with open(os.path.join(out_dir, "qa_report.txt"), "w", encoding="utf-8") as f:
                f.write("QA report - Whisper validation per chunk\n")
                f.write("chunk\tsimilarity\tattempts\tstatus\n")
                for idx, sim, tries in validation_log:
                    status = "OK" if sim >= WHISPER_SIM_THRESHOLD else "CHECK MANUALLY"
                    f.write(f"chunk_{idx:04d}\t{sim:.2f}\t{tries}\t{status}\n")
        print(f"💾 Outputs saved to: {out_dir}")
        return out_dir
    except Exception as e:
        print(f"⚠️ Could not save outputs/SRT: {e}")
        return None



# ---------------------------------------------------------------
# Auto QA: Whisper validation of each generated chunk
# Transcribes every chunk, compares with the intended text, and
# automatically regenerates failing chunks (up to WHISPER_MAX_RETRIES).
# Gracefully disabled if faster-whisper is not installed.
# ---------------------------------------------------------------
WHISPER_VALIDATION = True
WHISPER_SIM_THRESHOLD = 0.80
WHISPER_MAX_RETRIES = 2
_whisper_model = None


def _get_whisper():
    """Lazy-load the Whisper model once (CPU int8, no VRAM contention)."""
    global _whisper_model
    if _whisper_model is None:
        if not WHISPER_VALIDATION:
            _whisper_model = False
            return _whisper_model
        try:
            from faster_whisper import WhisperModel
            print("📥 Loading Whisper QA model (first time only, ~145MB download)...")
            _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            print("✅ Whisper auto-QA enabled: each chunk will be checked and bad chunks regenerated")
        except Exception as e:
            print(f"⚠️ Whisper auto-QA unavailable (continuing without it): {e}")
            _whisper_model = False
    return _whisper_model


def _normalize_for_compare(t):
    t = t.lower()
    t = re.sub(r"\[(?:clear throat|sigh|shush|cough|groan|sniff|gasp|chuckle|laugh)\]", " ", t)
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _chunk_similarity(chunk_text, wav, sr, language="en"):
    """Return similarity 0..1 between intended text and Whisper transcript, or None if QA unavailable."""
    wm = _get_whisper()
    if not wm:
        return None
    try:
        import torchaudio.functional as AF
        from difflib import SequenceMatcher
        audio = wav.detach().cpu().float()
        if audio.dim() > 1:
            audio = audio.mean(dim=0)
        if sr != 16000:
            audio = AF.resample(audio, sr, 16000)
        segments, _ = wm.transcribe(audio.numpy(), language=language, beam_size=1)
        transcript = " ".join(s.text for s in segments)
        a = _normalize_for_compare(chunk_text)
        b = _normalize_for_compare(transcript)
        if not a:
            return 1.0
        return SequenceMatcher(None, a, b).ratio()
    except Exception as e:
        print(f"⚠️ Whisper check failed on a chunk (skipping QA for it): {e}")
        return None


def _generate_with_qa(gen_fn, chunk_text, sr, language="en"):
    """Generate a chunk, validate with Whisper, retry on failure. Returns (best_wav, best_sim, attempts)."""
    best_wav, best_sim = None, -1.0
    attempts_done = 0
    for attempt in range(WHISPER_MAX_RETRIES + 1):
        wav = gen_fn()
        attempts_done = attempt + 1
        sim = _chunk_similarity(chunk_text, wav, sr, language=language)
        if sim is None:
            return wav, None, attempts_done
        if sim > best_sim:
            best_wav, best_sim = wav, sim
        if sim >= WHISPER_SIM_THRESHOLD:
            break
        print(f"🔁 QA failed (similarity {sim:.2f} < {WHISPER_SIM_THRESHOLD}), regenerating chunk (attempt {attempt + 1}/{WHISPER_MAX_RETRIES})...")
    return best_wav, best_sim, attempts_done


def generate_speech(text, voice_name, exaggeration, temperature, seed_num, cfgw, min_p, top_p, repetition_penalty):
    """Generate speech with progress tracking and validation."""
    try:
        _clear_stop()
        start_time = time.time()
        
        # Input validations
        if not text or not text.strip():
            yield 0, None, "❌ Lỗi: Chưa nhập văn bản."
            return
        
        if len(text) > 250:
            print(f"ℹ️ Text length: {len(text)} chars - Using smart chunking")
        
        if not voice_name or voice_name == "None":
            audio_prompt_path = None
            yield 10, None, "⚠️ Chưa chọn giọng - dùng giọng mặc định..."
        else:
            audio_prompt_path = resolve_voice_path(voice_name, "en")
            if not audio_prompt_path:
                yield 0, None, f"❌ Error: Voice '{voice_name}' not found."
                return
            yield 10, None, f"Đang nạp giọng: {voice_name}..."
        
        # Load model via manager (handles unloading others)
        yield 20, None, "Đang nạp model AI (lần đầu sẽ tải ~2GB, vui lòng chờ)..."
        model = model_manager.get_tts_model()
        if model is None:
             yield 0, None, "❌ Error: Failed to load TTS model."
             return
        
        # Set seed if specified
        if seed_num != 0:
            set_seed(int(seed_num))
            yield 30, None, f"Seed set to {seed_num}"
        
        # Chunk text
        text_chunks = smart_chunk_text(text)
        total_chunks = len(text_chunks)
        generated_wavs = []
        validation_log = []
        failed_chunks = []
        
        # Estimate time
        estimated_time = estimate_generation_time(len(text))
        yield 40, None, f"Đang tạo audio (tiếng Anh)...\nSố đoạn: {total_chunks}\nThời gian dự kiến: {format_time(estimated_time)}\n💡 Có thể bấm ⏸ DỪNG bất cứ lúc nào để nghe thử phần đã tạo, rồi ▶ TIẾP TỤC chạy nốt."

        def _gen_chunk(c):
            return model.generate(
                c,
                audio_prompt_path=audio_prompt_path,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfgw,
                min_p=min_p,
                top_p=top_p,
                repetition_penalty=repetition_penalty,
            )

        # Generate audio for each chunk
        for i, chunk in enumerate(text_chunks):
            if _stop_requested:
                break
            progress = 40 + int((i / total_chunks) * 50)
            yield progress, None, f"Đang đọc đoạn {i+1}/{total_chunks}..."
            
            chunk_wav, sim, tries = _generate_with_qa(lambda: _gen_chunk(chunk), chunk, model.sr, language="en")
            if sim is not None:
                validation_log.append((i + 1, sim, tries))
                if sim < WHISPER_SIM_THRESHOLD:
                    failed_chunks.append(i + 1)
            generated_wavs.append(chunk_wav)
        
        yield from _finalize_generation(
            text_chunks, generated_wavs, validation_log, failed_chunks,
            model.sr, mode="tts", start_time=start_time,
            gen_chunk=_gen_chunk, language="en",
            extra_lines=[f"Độ dài văn bản: {len(text)} ký tự"]
        )

    except Exception as e:
        error_status = f"❌ Error generating speech: {str(e)}"
        yield 0, None, error_status


def generate_multilingual_speech(text, voice_name, language_code, exaggeration, temperature, seed_num, cfgw):
    """Generate multilingual speech with progress tracking."""
    try:
        _clear_stop()
        start_time = time.time()
        
        # Input validations
        if not text or not text.strip():
            yield 0, None, "❌ Lỗi: Chưa nhập văn bản."
            return
        
        if len(text) > 250:
            print(f"ℹ️ Text length: {len(text)} chars - Using smart chunking")
        
        if not language_code:
            yield 0, None, "❌ Error: Please select a language for multilingual TTS."
            return
        
        # Resolve voice path based on language
        if not voice_name or voice_name == "None":
            audio_prompt_path = LANGUAGE_CONFIG.get(language_code, {}).get("audio")
            yield 10, None, f"⚠️ Using default voice for {SUPPORTED_LANGUAGES.get(language_code, language_code)}..."
        else:
            audio_prompt_path = resolve_voice_path(voice_name, language_code)
            if not audio_prompt_path:
                yield 0, None, f"❌ Error: Voice '{voice_name}' not found for {SUPPORTED_LANGUAGES.get(language_code)}."
                return
            yield 10, None, f"Đang nạp giọng: {voice_name}..."
        
        # Load model via manager (handles unloading others)
        yield 20, None, "Đang nạp model Đa ngôn ngữ (lần đầu sẽ tải, vui lòng chờ)..."
        model = model_manager.get_mtl_model()
        if model is None:
             yield 0, None, "❌ Error: Failed to load Multilingual model."
             return
        
        # Set seed if specified
        if seed_num != 0:
            set_seed(int(seed_num))
            yield 30, None, f"Seed set to {seed_num}"
        
        # Chunk text
        text_chunks = smart_chunk_text(text)
        total_chunks = len(text_chunks)
        generated_wavs = []
        validation_log = []
        failed_chunks = []
        
        # Estimate time
        estimated_time = estimate_generation_time(len(text))
        lang_name = SUPPORTED_LANGUAGES.get(language_code, language_code)
        yield 40, None, f"Generating speech in {lang_name}...\nChunks: {total_chunks}\nEstimated time: {format_time(estimated_time)}\n💡 Có thể bấm ⏸ DỪNG bất cứ lúc nào để nghe thử phần đã tạo, rồi ▶ TIẾP TỤC chạy nốt."

        def _gen_chunk(c):
            return model.generate(
                c,
                language_id=language_code,
                audio_prompt_path=audio_prompt_path,
                exaggeration=exaggeration,
                temperature=temperature,
                cfg_weight=cfgw,
            )

        # Generate audio for each chunk
        for i, chunk in enumerate(text_chunks):
            if _stop_requested:
                break
            progress = 40 + int((i / total_chunks) * 50)
            yield progress, None, f"Đang đọc đoạn {i+1}/{total_chunks}..."
            
            chunk_wav, sim, tries = _generate_with_qa(lambda: _gen_chunk(chunk), chunk, model.sr, language=language_code)
            if sim is not None:
                validation_log.append((i + 1, sim, tries))
                if sim < WHISPER_SIM_THRESHOLD:
                    failed_chunks.append(i + 1)
            generated_wavs.append(chunk_wav)
            
        yield from _finalize_generation(
            text_chunks, generated_wavs, validation_log, failed_chunks,
            model.sr, mode="multilingual", start_time=start_time,
            gen_chunk=_gen_chunk, language=language_code,
            extra_lines=[f"Ngôn ngữ: {lang_name}", f"Độ dài văn bản: {len(text)} ký tự"]
        )

    except Exception as e:
        error_status = f"❌ Error generating speech: {str(e)}"
        yield 0, None, error_status


def convert_voice(input_audio, target_voice_name):
    """Convert voice with progress tracking."""
    try:
        start_time = time.time()
        
        # Input validations
        if not input_audio:
            yield 0, None, "❌ Error: No input audio provided."
            return
        
        yield 20, None, "Loading input audio..."
        
        # Remove gender symbols if present
        clean_name = target_voice_name.replace(" ♂️", "").replace(" ♀️", "")
        
        if not clean_name or clean_name == "None":
            target_voice_path = None
            yield 40, None, "⚠️ No target voice selected - using default..."
        else:
            # Try to find the voice with different gender suffix combinations
            from .voice_manager import VOICES
            possible_names = [
                clean_name,
                f"{clean_name}_male",
                f"{clean_name}_female"
            ]
            
            target_voice_path = None
            for name in possible_names:
                if name in VOICES["samples"]:
                    target_voice_path = VOICES["samples"][name]
                    break
            
            if not target_voice_path:
                yield 0, None, f"❌ Error: Target voice '{target_voice_name}' not found."
                return
            yield 40, None, f"Using target voice: {target_voice_name}..."
        
        # Load model via manager (handles unloading others)
        yield 60, None, "Đang nạp model đổi giọng..."
        model = model_manager.get_vc_model()
        if model is None:
             yield 0, None, "❌ Error: Failed to load VC model."
             return
        
        yield 70, None, "Converting voice..."
        
        # Convert voice
        wav = model.generate(input_audio, target_voice_path=target_voice_path)
        
        yield 95, None, "Đang hoàn thiện audio..."
        
        # Calculate actual time taken
        total_time = time.time() - start_time
        final_status = f"✅ Conversion complete!\nTime taken: {format_time(total_time)}"
        
        yield 100, (model.sr, wav.squeeze(0).numpy()), final_status
        
    except Exception as e:
        error_status = f"❌ Error converting voice: {str(e)}"
        yield 0, None, error_status


def generate_turbo_speech(text, voice_name):
    """Generate speech using Turbo model with progress tracking and paralinguistic tag support."""
    try:
        _clear_stop()
        start_time = time.time()
        
        # Input validations
        if not text or not text.strip():
            yield 0, None, "❌ Lỗi: Chưa nhập văn bản."
            return
        
        if len(text) > 250:
            print(f"ℹ️ Text length: {len(text)} chars - Using smart chunking")
        
        if not voice_name or voice_name == "None":
            yield 0, None, "❌ Lỗi: Turbo bắt buộc phải chọn giọng. Hãy chọn giọng trong ô bên."
            return
        else:
            audio_prompt_path = resolve_voice_path(voice_name, "en")
            if not audio_prompt_path:
                yield 0, None, f"❌ Error: Voice '{voice_name}' not found."
                return
            yield 10, None, f"Đang nạp giọng: {voice_name}..."
        
        # Load model via manager (handles unloading others)
        yield 20, None, "Đang nạp model Turbo (lần đầu sẽ tải, vui lòng chờ)..."
        model = model_manager.get_turbo_model()
        if model is None:
             yield 0, None, "❌ Error: Failed to load Turbo model."
             return
        
        # Chunk text
        text_chunks = smart_chunk_text(text)
        total_chunks = len(text_chunks)
        generated_wavs = []
        validation_log = []
        failed_chunks = []
        
        # Estimate time (Turbo is faster, so reduce estimate)
        estimated_time = estimate_generation_time(len(text)) * 0.3  # Turbo is ~3x faster
        yield 40, None, f"Generating speech with Turbo (English)...\nChunks: {total_chunks}\nEstimated time: {format_time(estimated_time)}\n💡 Tip: Use tags like [chuckle], [laugh], [sigh] for realism!\n💡 Có thể bấm ⏸ DỪNG bất cứ lúc nào để nghe thử phần đã tạo, rồi ▶ TIẾP TỤC chạy nốt."

        def _gen_chunk(c):
            return model.generate(
                c,
                audio_prompt_path=audio_prompt_path
            )

        # Generate audio for each chunk
        for i, chunk in enumerate(text_chunks):
            if _stop_requested:
                break
            progress = 40 + int((i / total_chunks) * 50)
            yield progress, None, f"Đang đọc đoạn {i+1}/{total_chunks}..."
            
            chunk_wav, sim, tries = _generate_with_qa(lambda: _gen_chunk(chunk), chunk, model.sr, language="en")
            if sim is not None:
                validation_log.append((i + 1, sim, tries))
                if sim < WHISPER_SIM_THRESHOLD:
                    failed_chunks.append(i + 1)
            generated_wavs.append(chunk_wav)
        
        yield from _finalize_generation(
            text_chunks, generated_wavs, validation_log, failed_chunks,
            model.sr, mode="turbo", start_time=start_time,
            gen_chunk=_gen_chunk, language="en",
            extra_lines=[f"Độ dài văn bản: {len(text)} ký tự", "⚡ Tạo bằng Turbo"]
        )

    except Exception as e:
        error_status = f"❌ Error generating speech: {str(e)}"
        yield 0, None, error_status


# ---------------------------------------------------------------
# Pause / Resume: shared ending for all generation functions.
# If the user pressed Stop mid-run, the session (remaining chunks +
# generation settings) is kept in memory so ▶ TIẾP TỤC can continue
# from where it stopped. Partial audio is saved for preview.
# ---------------------------------------------------------------
_paused_session = None


def _finalize_generation(text_chunks, generated_wavs, validation_log, failed_chunks,
                         sr, mode, start_time, gen_chunk, language, extra_lines=None):
    """Either pause (save session + partial preview) or do the final save."""
    global _paused_session
    stopped = _stop_requested
    _clear_stop()
    total_chunks = len(text_chunks)

    # --- Paused mid-run: keep session for resume, save partial preview ---
    if stopped and len(generated_wavs) < total_chunks:
        if not generated_wavs:
            _paused_session = None
            yield 0, None, "⏹ Đã dừng trước khi tạo được đoạn nào. Bấm TẠO AUDIO để chạy lại."
            return

        _paused_session = {
            "mode": mode,
            "chunks": text_chunks,
            "wavs": list(generated_wavs),
            "vlog": list(validation_log),
            "failed": list(failed_chunks),
            "gen_chunk": gen_chunk,
            "sr": sr,
            "language": language,
            "extra_lines": list(extra_lines) if extra_lines else [],
        }

        done_chunks = text_chunks[:len(generated_wavs)]
        out_dir = save_outputs_with_srt(done_chunks, generated_wavs, sr,
                                        mode=f"{mode}_nghe_thu", validation_log=validation_log)
        partial_wav = torch.cat(generated_wavs, dim=-1) if len(generated_wavs) > 1 else generated_wavs[0]
        progress = 40 + int((len(generated_wavs) / total_chunks) * 50)
        status = (
            f"⏸ ĐÃ TẠM DỪNG sau {len(generated_wavs)}/{total_chunks} đoạn.\n"
            f"Nghe thử bên dưới.\n"
            f"▶ Bấm TIẾP TỤC để chạy nốt phần còn lại (đừng chạy tab khác trước khi tiếp tục).\n"
            f"🎙️ Hoặc bấm TẠO AUDIO để làm lại từ đầu."
        )
        if out_dir:
            status += f"\n💾 Bản nghe thử đã lưu vào:\n{out_dir}"
        yield progress, (sr, partial_wav.squeeze(0).numpy()), status
        return

    # --- Normal finish ---
    if not generated_wavs:
        yield 0, None, "❌ Error: No audio generated."
        return

    _paused_session = None
    yield 90, None, "Đang ghép audio + tạo SRT..."

    full_wav = torch.cat(generated_wavs, dim=-1) if len(generated_wavs) > 1 else generated_wavs[0]
    total_time = time.time() - start_time
    final_status = f"✅ HOÀN TẤT!\nThời gian: {format_time(total_time)}\nSố đoạn: {total_chunks}"
    for line in (extra_lines or []):
        final_status += f"\n{line}"

    out_dir = save_outputs_with_srt(text_chunks, generated_wavs, sr, mode=mode, validation_log=validation_log)
    if failed_chunks:
        final_status += f"\n⚠️ KIỂM TRA: {len(failed_chunks)} đoạn có thể vẫn lỗi sau khi đọc lại: {failed_chunks}\nAnh nghe lại các file chunk số này (xem qa_report.txt)."
    elif validation_log:
        final_status += f"\n✅ KIỂM TRA: toàn bộ {len(validation_log)} đoạn đều đạt chuẩn."
    if out_dir:
        final_status += f"\n💾 Audio + phụ đề SRT đã lưu vào:\n{out_dir}"

    yield 100, (sr, full_wav.squeeze(0).numpy()), final_status


def resume_generation(mode):
    """Continue a paused generation session from where it stopped."""
    global _paused_session
    try:
        if _paused_session is None or _paused_session["mode"] != mode:
            yield 0, None, "❌ Không có phiên nào đang tạm dừng ở tab này. Bấm TẠO AUDIO để chạy mới."
            return

        sess = _paused_session
        _paused_session = None
        _clear_stop()
        start_time = time.time()

        text_chunks = sess["chunks"]
        generated_wavs = sess["wavs"]
        validation_log = sess["vlog"]
        failed_chunks = sess["failed"]
        gen_chunk = sess["gen_chunk"]
        sr = sess["sr"]
        language = sess["language"]
        total_chunks = len(text_chunks)

        for i in range(len(generated_wavs), total_chunks):
            if _stop_requested:
                break
            chunk = text_chunks[i]
            progress = 40 + int((i / total_chunks) * 50)
            yield progress, None, f"▶ Tiếp tục: đang đọc đoạn {i+1}/{total_chunks}..."

            chunk_wav, sim, tries = _generate_with_qa(lambda: gen_chunk(chunk), chunk, sr, language=language)
            if sim is not None:
                validation_log.append((i + 1, sim, tries))
                if sim < WHISPER_SIM_THRESHOLD:
                    failed_chunks.append(i + 1)
            generated_wavs.append(chunk_wav)

        yield from _finalize_generation(
            text_chunks, generated_wavs, validation_log, failed_chunks,
            sr, mode=mode, start_time=start_time,
            gen_chunk=gen_chunk, language=language,
            extra_lines=sess["extra_lines"]
        )

    except Exception as e:
        yield 0, None, f"❌ Lỗi khi tiếp tục: {str(e)}\nCó thể model đã bị thay (do chạy tab khác giữa chừng). Bấm TẠO AUDIO để chạy lại từ đầu."


def resume_speech():
    """Resume button for the English TTS tab."""
    yield from resume_generation("tts")


def resume_multilingual_speech():
    """Resume button for the Multilingual tab."""
    yield from resume_generation("multilingual")


def resume_turbo_speech():
    """Resume button for the Turbo tab."""
    yield from resume_generation("turbo")

