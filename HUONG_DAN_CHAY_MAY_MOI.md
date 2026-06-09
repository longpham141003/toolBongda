# Huong dan chay tool tren may moi

File nay danh cho nguoi moi pull repo ve va can chay duoc tu dau den cuoi: tao script, tao voice Kokoro, chia canh, tim anh, duyet anh va xuat CapCut.

## 1. Can cai truoc

Bat buoc:

- Git.
- CapCut PC da dang nhap va mo duoc binh thuong.
- Python 3.13, co Python Launcher `py`.
- Python 3.10 hoac 3.11 khuyen nghi cho Kokoro local. Neu may chi co Python 3.13 va `python` trong PATH van tao venv duoc thi co the chay, nhung 3.10/3.11 on dinh hon cho goi voice.
- Internet cho lan chay dau tien de tai thu vien, Chromium Playwright va model Kokoro.

Khong bat buoc:

- Node.js chi can neu muon sua/build lai giao dien React. Ban pull ve chay tool thi da co san `webui/dist`.

## 2. Pull code

```powershell
git clone https://github.com/longpham141003/toolBongda.git
cd toolBongda
```

Neu da co repo:

```powershell
git pull origin main
```

## 3. Chay lan dau

Chay file:

```powershell
run_visual_capcut.bat
```

File nay se tu lam cac viec sau:

- Tao `settings.json` tu `settings.example.json` neu chua co.
- Cai thu vien backend bang `requirements.txt` neu thieu.
- Cai Chromium cho Playwright de tim anh Google Images.
- Cai Kokoro local vao `kokoro-tts-local/.venv` neu thieu.
- Mo API local tai `http://127.0.0.1:8765`.
- Mo giao dien web tren trinh duyet.

Lan dau co the lau vi Kokoro va Playwright phai tai dependency/model. Nhung tu lan sau se nhanh hon.

## 4. Cau hinh trong tool

Vao nut Cai dat trong giao dien va dien:

- Gemini API key: bat buoc neu muon AI hieu script, chia canh dung, tao keyword va kiem tra anh.
- CapCut path: chi can dien neu tool khong tu mo duoc CapCut.
- Thu muc project: co the de mac dinh.

Mac dinh project se luu ngoai repo tai:

```text
C:\Users\<ten_may>\Videos\VisualCapCutStudio\Projects
```

Khong luu project vao trong repo nua de tranh phinh Git.

## 5. Test nhanh tu A den Z

1. Bam Tao video moi.
2. Dan script ngan vao o Noi dung.
3. Bam Luu noi dung va tiep tuc.
4. Chon giong doc Kokoro.
5. Bam Nghe thu neu muon kiem tra giong.
6. Bam Tao giong doc.
7. Khi tool bao da tao voice xong, bam Tao canh va tim anh.
8. Cho tool chia canh va tai anh.
9. O man Duyet hinh anh:
   - Anh dung thi bam Duyet.
   - Anh sai thi bam Tim lai.
   - Co anh/video san thi bam Tai len.
10. Khi duyet xong, sang Xuat CapCut.
11. Bam Xuat va mo CapCut.

## 6. Neu bi loi

### API khong khoi dong

Chay thu:

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 -m app.web_server
```

### Playwright khong tim anh

Chay:

```powershell
py -3.13 -m playwright install chromium
```

### Kokoro khong tao voice

Chay thu:

```powershell
cd kokoro-tts-local
powershell -ExecutionPolicy Bypass -File setup.ps1
.\.venv\Scripts\python.exe .\tts.py --text "Hello, Kokoro is ready." --out outputs\test.wav
cd ..
```

Neu len file `outputs\test.wav` la Kokoro ok.

### CapCut khong mo project

- Mo CapCut thu cong mot lan.
- Tao san mot project rong trong CapCut neu tool bao thieu draft mau.
- Vao Cai dat cua tool va dien dung duong dan CapCut.

## 7. Nhung file khong duoc commit

Repo da ignore san:

- `settings.json`: chua key rieng cua tung may.
- `Projects/`: project cu neu co trong repo local.
- `.webui_state`: trang thai project dang mo.
- `kokoro-tts-local/.venv/`: moi truong Python local.
- `kokoro-tts-local/.hf_cache/`: model Kokoro tai ve.
- `kokoro-tts-local/outputs/`: file voice test/output tam.
- `chrome_*_profile/`: profile trinh duyet dung de tim anh.

## 8. Xac nhan kha nang chay giong may hien tai

Nguoi trong team pull code ve co the chay giong may hien tai neu may do co du:

- Python/Internet de cai dependency lan dau.
- Gemini API key hop le.
- CapCut PC da cai.
- Quyen chay PowerShell script setup Kokoro.

Nhung thu khong can copy tu may hien tai:

- Khong can copy `settings.json`.
- Khong can copy `Projects`.
- Khong can copy `.venv` Kokoro.
- Khong can copy model cache Kokoro. Lan dau tool se tai lai.
