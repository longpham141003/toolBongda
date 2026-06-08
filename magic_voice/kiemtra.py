# -*- coding: utf-8 -*-
"""Kiem tra loi Chatterbox Tool - chay boi 3_KIEM_TRA_LOI.bat"""
import sys, os, traceback

print("=" * 60)
print("KIEM TRA HE THONG CHATTERBOX TOOL")
print("=" * 60)
print("Python:", sys.version)
print("Thu muc:", os.getcwd())
print()

mods = [
    ("numpy", "numpy"), ("torch", "torch"), ("torchaudio", "torchaudio"),
    ("gradio", "gradio"), ("transformers", "transformers"), ("diffusers", "diffusers"),
    ("librosa", "librosa"), ("safetensors", "safetensors"), ("s3tokenizer", "s3tokenizer"),
    ("perth (resemble-perth)", "perth"), ("conformer", "conformer"),
    ("pykakasi", "pykakasi"), ("pyloudnorm", "pyloudnorm"), ("omegaconf", "omegaconf"),
    ("faster_whisper", "faster_whisper"),
]
fails = []
for label, mod in mods:
    try:
        m = __import__(mod)
        ver = getattr(m, "__version__", "?")
        print(f"  OK   {label} ({ver})")
    except Exception as e:
        print(f"  LOI  {label}: {type(e).__name__}: {e}")
        fails.append(label)

print()
try:
    import torch
    print("GPU CUDA:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("GPU:", torch.cuda.get_device_name(0))
except Exception:
    pass

print()
print("-" * 60)
print("Thu nap ung dung (khong khoi dong server)...")
print("-" * 60)
try:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    sys.path.insert(0, os.path.join(here, "src"))
    import app  # builds UI without launching
    print()
    print(">>> KET LUAN: UNG DUNG NAP THANH CONG. Loi co the nam o buoc khoi dong server/trinh duyet.")
    print(">>> Thu mo trinh duyet va vao dia chi: http://127.0.0.1:7860 khi dang chay 2_CHAY_TOOL.bat")
except Exception:
    print()
    print(">>> KET LUAN: UNG DUNG BI LOI KHI NAP. Chi tiet:")
    traceback.print_exc()
    if fails:
        print()
        print(">>> Cac thu vien bi thieu/loi:", ", ".join(fails))
        print(">>> Cach sua: chay lai 1_CAI_DAT.bat")
print()
print("=" * 60)
print("HET. Toan bo noi dung tren da luu vao file loi_log.txt")
print("=" * 60)
