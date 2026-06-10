# Huong dan chay tool tren may moi

File nay danh cho nguoi moi pull repo ve va can chay duoc tu dau den cuoi: tao script, tao voice Kokoro, chia canh, tim anh, duyet anh va xuat CapCut. Neu nguoi dung khong biet code, chi can doc muc 3.

## 1. Can cai truoc

Bat buoc:

- Git.
- CapCut PC da dang nhap va mo duoc binh thuong.
- Python 3.10 tro len, co Python Launcher `py`. Khuyen nghi Python 3.13. Neu may co `winget`, launcher se thu cai Python tu dong khi chua co.
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

File nay se hien cua so khoi dong va tu lam cac viec sau:

- Tao `settings.json` tu `settings.example.json` neu chua co.
- Tao moi truong backend `.venv` neu thieu.
- Cai thu vien backend bang `requirements.txt` neu thieu.
- Cai Chromium cho Playwright de tim anh Google Images.
- Cai Kokoro local vao `kokoro-tts-local/.venv` neu thieu. Neu nguoi dung mo backend truc tiep va chua co `.venv`, tool se tu cai khi bam `Nghe thu` hoac `Tao giong doc`.
- Mo API local tai `http://127.0.0.1:8765`.
- Mo giao dien web tren trinh duyet.

Lan dau co the lau vi Kokoro va Playwright phai tai dependency/model. Nhung tu lan sau se nhanh hon.

Trong qua trinh chay, neu thieu thu vien, cua so khoi dong se hien thong bao dang cai. Khong tat cua so do cho den khi trinh duyet mo giao dien tool.

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

Thong thuong chi can mo lai:

```powershell
run_visual_capcut.bat
```

Neu van loi, gui file `logs/startup.log` va `logs/api.err.log` cho nguoi phu trach.

### Playwright khong tim anh

Thong thuong launcher tu cai. Neu can cai tay:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

### Kokoro khong tao voice

Neu bao:

```text
Khong thay Python venv cua Kokoro
```

thi thu muc `.venv` chua duoc tao tren may do. Cach dung dung la chay:

```powershell
run_visual_capcut.bat
```

Hoac chay setup tay:

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

- Python/Internet de cai dependency va Kokoro `.venv` lan dau.
- Gemini API key hop le.
- CapCut PC da cai.
- Quyen chay PowerShell script setup Kokoro.

Nhung thu khong can copy tu may hien tai:

- Khong can copy `settings.json`.
- Khong can copy `Projects`.
- Khong can copy `.venv` Kokoro.
- Khong can copy model cache Kokoro. Lan dau tool se tai lai.
