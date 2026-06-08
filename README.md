# Tool Visual CapCut

Tool tao video tu script, tao voice bang Magic Voice/Chatterbox, tu chia SRT thanh canh, tim media va xuat project CapCut.

## Chay nhanh

```powershell
run_visual_capcut.bat
```

Tool se mo giao dien web tai:

```text
http://127.0.0.1:8765
```

## Cai dat cho may moi

1. Cai Python 3.13 va Node.js.
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

4. Cai moi truong Magic Voice de tao voice:

```powershell
py -3.10 -m venv chatterbox-venv
chatterbox-venv\Scripts\python.exe -m pip install -r magic_voice\requirements.txt
```

Ghi chu:

- Repo co kem `magic_voice/` source va cac voice sample trong `magic_voice/modules/voice_samples/`.
- Khong commit `chatterbox-venv/`, model cache, browser profile, project output.
- Lan dau tao voice co the lau vi may phai load/tai model.

## Cau hinh

Sao chep:

```powershell
copy settings.example.json settings.json
```

Sau do dien API key va duong dan rieng cua may. `settings.json` bi ignore, khong day len Git.

Quan trong:

- `text_to_voice_root` mac dinh tro toi `magic_voice`.
- `text_to_voice_python` co the de trong neu da tao `chatterbox-venv` trong thu muc tool.
- Gemini API key dung cho tao keyword va kiem tra anh.
- CapCut path co the chinh trong Settings cua tool.

## Pipeline

1. Nhap script hoac tao script bang workflow AI.
2. Tao voice bang Magic Voice, sinh WAV + timing + SRT.
3. Whisper/Gemini gom SRT thanh canh.
4. Tao keyword va tim anh/video cho tung canh.
5. Duyet/tim lai/tai media local cho tung canh.
6. Xuat draft CapCut va mo CapCut.

## Khong day len Git

- `settings.json`
- `Projects/`
- `.webui_state`
- `chatterbox-venv/`
- `.hf-cache/`
- `chrome_*_profile/`
- log/cache/temp/output sinh ra khi chay tool

