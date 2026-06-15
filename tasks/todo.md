# TODO: Điều hướng theo URL + page riêng

Plan: `tasks/plan.md` · Spec: `docs/superpowers/specs/2026-06-15-url-routing-design.md`

## Phase 1 — Foundation
- [ ] **Task 1** Cài `react-router-dom` + bọc `<BrowserRouter>` ở `main.jsx` (app chạy như cũ). [S]
- [ ] **Task 2** `lib/routing.js`: slugify + map slug↔path + ánh xạ bước⇄segment, có test round-trip & trùng slug. [S]
- [ ] **Checkpoint:** build xanh, test xanh, app như cũ.

## Phase 2 — Routing shell + chuyển call-site
- [ ] **Task 3** `<Routes>` + layout; route `/` (Dashboard) & `/du-an/:duAnId` (chi tiết); chuyển onOpenSeries / onBack / goHome. [M] (dep: 1,2)
- [ ] **Task 4a** Route wrappers + `/du-an/:duAnId/tao-video`. [phần của L] (dep: 3)
- [ ] **Task 4b** Route `/video/:videoId/*` + redirect; chuyển nốt mọi `setActiveScreen`; Sidebar/progress đọc bước từ location. [phần của L] (dep: 4a)
- [ ] **Checkpoint:** mọi màn truy cập bằng URL; `grep` sạch `setActiveScreen`; build xanh; đi hết một video bằng URL.

## Phase 3 — Khôi phục khi reload
- [ ] **Task 5** Effect khôi phục: giải slug→path; **trùng project thì KHÔNG openProject** (chống huỷ job); slug sai → `/` + toast. [M] (dep: 4)
- [ ] **Checkpoint:** reload mọi page giữ đúng chỗ; reload khi đang chạy job không huỷ job.

## Phase 4 — Backend fallback + kiểm thử
- [ ] **Task 6** SPA fallback trong `app/web_server.py` + test catch-all (API/media không bị nuốt). [S] (song song)
- [ ] **Task 7** Test routing FE (`MemoryRouter`) + bọc router cho `SettingsModal.test.jsx`; chạy đủ FE + BE + build. [M] (dep: 5,6)
- [ ] **Checkpoint cuối:** tất cả acceptance criteria đạt; build + toàn bộ test xanh; sẵn sàng review.
