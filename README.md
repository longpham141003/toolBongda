# Tool Visual CapCut

Tool tao video tu script, tao voice bang Kokoro local, tu chia SRT thanh canh, tim media va xuat project CapCut.

## Chay nhanh cho nguoi khong biet code

Double click file:

```text
run_visual_capcut.bat
```

Lan dau mo tool, cua so khoi dong se tu kiem tra va cai cac thanh phan con thieu:

- Python backend environment `.venv`
- thu vien backend
- Chromium Playwright de tim anh
- Kokoro local voice environment
- MagicVoice/OmniVoice clone environment, chi cai khi nguoi dung bat clone giong va tai audio mau
- file cau hinh rieng `settings.json`

Nguoi dung chi can cho den khi trinh duyet tu mo giao dien `Visual CapCut Studio`.

Huong dan chi tiet cho may moi pull repo: xem `HUONG_DAN_CHAY_MAY_MOI.md`.

Tool se mo giao dien web tai:

```text
http://127.0.0.1:8765
```

Lan dau chay co the mat 5-15 phut tuy toc do mang/may. Tu lan sau se nhanh hon.

## Cai dat cho may moi

1. Cai Python 3.10 tro len. Khuyen nghi Python 3.12 vi Kokoro hien chua ho tro Python 3.13 on dinh. Neu may co `winget`, launcher se thu cai Python tu dong khi chua co.
2. Cai CapCut PC va mo/dang nhap duoc binh thuong.
3. Clone/pull repo.
4. Double click `run_visual_capcut.bat`.

Ghi chu:

- Repo co kem `kokoro-tts-local/` va danh sach voice Kokoro.
- Repo co kem `magic_voice/` de clone giong tu audio mau, ho tro tieng Viet. Lan dau dung clone se cai Python 3.11, Torch, OmniVoice va model nen co the lau hon Kokoro preset.
- Khong commit `.venv`, model cache, browser profile va project output.
- Lan dau tao voice co the lau vi may phai cai Kokoro, load/tai model.

## Cau hinh

Launcher se tu tao `settings.json` neu chua co. `settings.json` bi ignore, khong day len Git.

Quan trong:

- `text_to_voice_root` mac dinh tro toi `kokoro-tts-local`.
- `text_to_voice_python` co the de trong; tool tu dung `kokoro-tts-local/.venv`.
- `projects_dir` mac dinh la `%USERPROFILE%\Videos\VisualCapCutStudio\Projects`, nam ngoai repo de khong lam phinh Git.
- Gemini API key dung cho tao keyword va kiem tra anh.
- CapCut path co the chinh trong Settings cua tool.

## Pipeline

1. Nhap script hoac tao script bang workflow AI.
2. Tao voice bang Kokoro preset hoac MagicVoice clone neu bat clone giong, sinh WAV + timing + SRT.
3. Whisper/Gemini gom SRT thanh canh.
4. Tao keyword va tim anh/video cho tung canh.
5. Duyet/tim lai/tai media local cho tung canh.
6. Xuat draft CapCut va mo CapCut.

## Khong day len Git

- `settings.json`
- `Projects/` cu trong repo, neu con du lieu local
- `%USERPROFILE%\Videos\VisualCapCutStudio\Projects` tren may tung nguoi
- `.webui_state`
- `kokoro-tts-local/.venv/`
- `kokoro-tts-local/.hf_cache/`
- `kokoro-tts-local/outputs/`
- cache/model sinh ra boi MagicVoice/OmniVoice
- `magic_voice/clone_refs/` neu chua muon day voice mau rieng tu len repo
- `.hf-cache/`
- `chrome_*_profile/`
- log/cache/temp/output sinh ra khi chay tool
