# Tool Visual CapCut

Tool tao video tu script, tao voice bang Kokoro local, tu chia SRT thanh canh, tim media va xuat project CapCut.

## Chay nhanh

```powershell
run_visual_capcut.bat
```

Huong dan chi tiet cho may moi pull repo: xem `HUONG_DAN_CHAY_MAY_MOI.md`.

Tool se mo giao dien web tai:

```text
http://127.0.0.1:8765
```

Lan dau chay, file `.bat` se tu tao `settings.json`, cai dependency backend neu thieu va cai moi truong Kokoro local trong `kokoro-tts-local/.venv`. Neu mo backend truc tiep ma chua co `.venv`, tool cung se tu cai khi bam nghe thu hoac tao voice.

## Cai dat cho may moi

1. Cai Python 3.10 tro len. Khuyen nghi Python 3.13. Node.js chi can neu muon sua/build lai UI.
2. Cai dependency backend:

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 -m playwright install chromium
```

3. Cai dependency frontend neu can build lai UI:

```powershell
cd webui
npm install
npm run build
cd ..
```

4. Neu muon cai Kokoro thu cong:

```powershell
cd kokoro-tts-local
powershell -ExecutionPolicy Bypass -File setup.ps1
cd ..
```

Ghi chu:

- Repo co kem `kokoro-tts-local/` va danh sach voice Kokoro.
- Khong commit `.venv`, model cache, browser profile va project output.
- Lan dau tao voice co the lau vi may phai cai Kokoro, load/tai model.

## Cau hinh

Sao chep:

```powershell
copy settings.example.json settings.json
```

Sau do dien API key va duong dan rieng cua may. `settings.json` bi ignore, khong day len Git.

Quan trong:

- `text_to_voice_root` mac dinh tro toi `kokoro-tts-local`.
- `text_to_voice_python` co the de trong; tool tu dung `kokoro-tts-local/.venv`.
- `projects_dir` mac dinh la `%USERPROFILE%\Videos\VisualCapCutStudio\Projects`, nam ngoai repo de khong lam phinh Git.
- Gemini API key dung cho tao keyword va kiem tra anh.
- CapCut path co the chinh trong Settings cua tool.

## Pipeline

1. Nhap script hoac tao script bang workflow AI.
2. Tao voice bang Kokoro, sinh WAV + timing + SRT.
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
- `.hf-cache/`
- `chrome_*_profile/`
- log/cache/temp/output sinh ra khi chay tool
