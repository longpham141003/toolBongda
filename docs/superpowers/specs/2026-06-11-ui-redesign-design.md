# UI Redesign — Visual CapCut Studio

**Ngày:** 2026-06-11  
**Phạm vi:** Làm lại toàn bộ giao diện — layout, font, spacing, navigation, từng màn hình  
**Mục tiêu:** Thân thiện hơn với người Việt, tận dụng tối đa diện tích màn hình, bố cục rõ ràng hơn

---

## 1. Cấu trúc tổng thể (Layout)

### Hiện tại
- Topbar cố định 64px chiều cao
- Margin hai bên: `clamp(48px, 15.625vw, 200px)` — lãng phí tới 400px ngang trên màn 1920px
- Progress rail ngang + UserProgressPanel chiếm ~130px chiều dọc trên mọi màn workspace
- Home screen có layout riêng biệt khác hoàn toàn với workspace

### Thiết kế mới

```
┌─────────────────────────────────────────────────────┐
│  TOPBAR (48px) — logo | tên project | settings+user │
├──────────────┬──────────────────────────────────────┤
│   SIDEBAR    │         MAIN CONTENT                 │
│   (240px)    │         padding: 24px                │
│   fixed      │         overflow-y: auto             │
└──────────────┴──────────────────────────────────────┘
```

- Topbar giảm từ 64px → 48px, chỉ giữ logo + tên project pill + icon settings + avatar
- Sidebar 240px cố định bên trái, thay thế toàn bộ margin lãng phí
- Main content: `calc(100vw - 240px)`, padding `24px`, scroll độc lập
- Xóa biến `--app-side-margin` khỏi CSS
- `stitch-home` và `stitch-workspace` gộp thành một layout duy nhất

---

## 2. Font & Typography

### Font
**Be Vietnam Pro** (Google Fonts) — thiết kế bởi người Việt, hỗ trợ đầy đủ ký tự có dấu, kern pair chuẩn.

```css
@import url('https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;600;700&display=swap');
font-family: 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif;
```

Chỉ load 3 weight: 400 (body), 600 (heading-md, label), 700 (heading-lg, heading-xl).

### Hệ thống cỡ chữ

| Token | Size | Weight | Line-height | Dùng ở đâu |
|-------|------|--------|-------------|------------|
| `text-xl` | 32px | 700 | 1.25 | Tiêu đề trang chủ |
| `text-lg` | 24px | 700 | 1.3 | Tiêu đề màn hình bước |
| `text-md` | 18px | 600 | 1.4 | Tiêu đề panel |
| `text-base` | 14px | 400 | 1.6 | Nội dung thông thường |
| `text-sm` | 13px | 400 | 1.6 | Text trong card, row |
| `text-xs` | 12px | 500 | 1.5 | Hint, caption, label phụ |
| `text-micro` | 11px | 600 | 1.4 | Section label UPPERCASE |

**Line-height tiếng Việt:** `1.6` cho body text (thay vì 1.4 hiện tại) — tiếng Việt có dấu trên và dưới cần thêm không gian dọc.

### Xóa cỡ chữ lẻ
Bỏ hoàn toàn: 10px, 22px, 28px, 36px, 48px hiện đang dùng rải rác trong code.

---

## 3. Spacing — 4px Grid

Toàn bộ margin, padding, gap chuẩn hóa về bội số 4:

**Thang spacing:** `4 · 8 · 12 · 16 · 20 · 24 · 32 · 48px`

Xóa các giá trị lẻ đang dùng trong CSS: 7px, 9px, 11px, 13px, 14px, 22px, 26px, 34px.

---

## 4. Sidebar Navigation

### Cấu trúc sidebar (240px, fixed, height: calc(100vh - 48px), top: 48px)

```
┌────────────────────────┐
│  DỰ ÁN                 │  ← text-micro uppercase
│  [📁 Brazil vs Panama] │  ← bấm → mở ProjectsModal
│  Bước 2 · Đang làm    │  ← trạng thái nhỏ text-xs
├────────────────────────┤
│  CÁC BƯỚC             │  ← text-micro uppercase
│                        │
│  ✓  1  Nội dung        │  ← done: emerald
│  ▶  2  Giọng đọc       │  ← active: violet bg nhạt
│  ○  3  Hình ảnh        │  ← locked: opacity 50%
│  ○  4  Xuất CapCut     │
├────────────────────────┤
│  (job running only)    │
│  [████░░░░] 45%        │  ← progress bar
│  Đang tạo giọng đọc   │  ← tên job, text-xs
│  · log gần nhất...    │  ← 1 dòng log, text-xs
├────────────────────────┤
│  ⚙ Cài đặt            │  ← bottom, luôn hiện
│  ? Trợ giúp           │
└────────────────────────┘
```

### Logic navigation
- Step locked nếu `done[index - 1] === false && index !== current` (giữ nguyên logic hiện tại)
- Job progress section chỉ render khi `activeJob && ["queued","running"].includes(activeJob.status)` — ẩn hoàn toàn khi không có job
- Bấm tên project → mở `ProjectsModal`
- Settings + Help → góc dưới sidebar, không còn trong topbar

### Thay thế components
- `ProgressRail` (ngang) → xóa, logic chuyển vào sidebar
- `UserProgressPanel` (ngang) → xóa, logic chuyển vào sidebar job section

---

## 5. Trang chủ (Home Screen)

### Hiện tại
Hero 220px cố định + progress rail + 2 card lớn + 4 flow card + particle canvas + animation phức tạp.

### Mới
```
  Xin chào,
  Tạo video AI trong 4 bước đơn giản.

  [+ Tạo video mới]     [📁 Mở project gần đây]

  ── Flow phổ biến ──
  [Tin tức]  [Khoa học]  [Kể chuyện]  [Tùy chỉnh]
```

- Bỏ hero visual animation, hero-orb, particle canvas ở trang chủ (giữ aurora background)
- 2 nút CTA lớn thay thế 2 glass-card-primary/secondary với animation phức tạp
- 4 flow card giữ nguyên nhưng layout đơn giản hơn
- Sidebar hiển thị bình thường ở trang chủ (không có project active thì hiện "Chưa có project")

---

## 6. Bước 1 — Nội dung

### Thay đổi
- Bỏ layout 2 cột 50/50. Toàn bộ main area dành cho kịch bản
- Panel "Cách dùng nhanh" (text tĩnh) → xóa
- AI Workflow thu gọn thành 1 dòng: `[Input ý tưởng] [Chạy AI ▶]` phía dưới textarea
- Textarea `min-h-[400px]` thay vì `min-h-[360px]`

```
┌─ Kịch bản cuối ─────────────────────────────────┐
│  Tên project [_______________________________]  │
│                                                 │
│  [Textarea — chiếm phần lớn chiều cao]          │
│                                                 │
│  [↑ Tải TXT]                         123 từ    │
│                                                 │
│  ── Hoặc nhờ AI viết ──────────────────────     │
│  Chủ đề/ý tưởng [__________________] [Chạy ▶]  │
└─────────────────────────────────────────────────┘
```

---

## 7. Bước 2 — Giọng đọc

### Thay đổi
- Bỏ layout `7fr 5fr`. Dùng `1fr 1fr`
- Clone voice tách ra Dialog riêng — bấm "+ Thêm clone mới" để mở
- Cột trái: chọn ngôn ngữ + giọng + danh sách clone profiles
- Cột phải: slider tốc độ + slider mức clone + nghe thử

```
┌─ Chọn giọng ──────────┐  ┌─ Cài đặt & Nghe thử ──┐
│ Ngôn ngữ [select]     │  │ Tốc độ [====●===] 1.0  │
│ Giọng    [select]     │  │ Mức clone [==●=====] 16 │
│                       │  │                        │
│ ─ Giọng clone ──      │  │ [▶ Nghe thử]           │
│ [profile 1] ✓         │  │ [──────audio──────]    │
│ [profile 2]           │  │                        │
│ [+ Thêm clone mới]    │  │                        │
└───────────────────────┘  └────────────────────────┘
```

### Dialog "Thêm clone mới"
- Tên giọng + Ngôn ngữ + Upload audio + nút Clone
- Tách hoàn toàn khỏi màn hình chính

---

## 8. Bước 3B — Duyệt hình ảnh

### Thay đổi
- Grid từ **5 cột → 4 cột** (card lớn hơn, ảnh rõ hơn)
- Filter pills từ `<Select>` dropdown → **tab ngang** (5 tabs: Tất cả · Cần duyệt · Đã duyệt · Lỗi · Thiếu)
- Thêm count badge trên mỗi tab

```
[Tất cả 20] [Cần duyệt 8] [Đã duyệt 10] [Lỗi 1] [Thiếu 1]
```

---

## 9. Bước 4 — Xuất CapCut

Giữ nguyên layout 2 cột (checklist + export hero). Chỉ cải thiện spacing và typography theo hệ thống mới.

---

## 10. Component System

### Cards / Panels
Giảm từ 5 loại xuống 2:
- `.panel` — container chính (border nhạt, backdrop-blur, padding 20px)
- `.card` — item trong danh sách (media card, project row, voice row)

Xóa: `glass-panel`, `glass-card`, `glass-card-primary`, `glass-card-secondary`, `flow-card` → thay bằng `.panel` và `.card` với modifier classes.

### Toast position
Dời từ `top: 82px, right: 22px` → `bottom: 24px, right: 24px` (convention chuẩn, không che nội dung đang thao tác).

### Scrollbar
Sidebar và main content scroll độc lập.

---

## 11. Những gì KHÔNG thay đổi

- Toàn bộ logic React, state management, API calls
- Màu sắc chủ đạo: violet (#8b5cf6), emerald (#10b981), dark bg (#131315)
- Aurora background animation
- Particle canvas (giữ nhưng bỏ ở trang chủ)
- Dialog/Modal system (Radix UI)
- Tất cả text tiếng Việt hiện có
- Logic lock/unlock steps
- Lightbox (Bước 3B detail view)

---

## 12. Files thay đổi

| File | Loại thay đổi |
|------|---------------|
| `webui/src/styles.css` | Viết lại phần lớn — layout, spacing, typography |
| `webui/src/App.jsx` | Tái cấu trúc layout, thêm Sidebar component, cập nhật từng màn hình |
| `webui/src/components/ui.jsx` | Cập nhật font, spacing trong Button/Card/Input |
| `webui/index.html` | Thêm Google Fonts import (Be Vietnam Pro) |
