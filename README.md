# Tool Visual CapCut

Tool doc lap theo pipeline:

1. Dan `script_final`.
2. Tao voice bang Chatterbox TTS, ho tro voice sample/clone, chia chunk va Whisper QA.
3. Doc timing that tu `voice.segments.json`, noi cac segment bi cat, tu chia canh theo noi dung/chuyen y.
4. Tao keyword cho tung canh. Neu co Gemini API key hoac OpenAI API key, tool se hieu noi dung canh va toi uu keyword + fallback keyword truoc khi tim anh.
5. Tim va tai anh theo 2 tang: TheSportsDB truoc, sau do Google Images bang Playwright. Preview, duyet va tim lai tung asset.
6. Xuat draft CapCut gom voice va asset dung timing.

Chay `run_visual_capcut.bat`.

Khong can Google API key hoac Search Engine ID.

Sao chep `settings.example.json` thanh `settings.json`, sau do dien duong dan
local va API key cua rieng ban. `settings.json` khong duoc commit len Git.

Dependency:

```powershell
py -3.13 -m pip install playwright requests pillow imagehash
py -3.13 -m playwright install chromium
```

Du lieu nam trong `Projects/<project>/`, gom `script_final`, voice, timing, `asset_manifest.json`, asset tai ve va ban draft CapCut portable.
# Visual CapCut Studio

## Chay giao dien moi

Chay `run_visual_capcut.bat`. Tool se mo giao dien React tai
`http://127.0.0.1:8765`.

## Quay lai giao dien cu

Chay `run_visual_capcut_legacy.bat`. Toan bo giao dien PyQt cu va pipeline
Python van duoc giu nguyen.
