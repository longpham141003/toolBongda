# Implementation Plan: Điều hướng theo URL + page riêng (reload không mất chỗ)

> Spec: `docs/superpowers/specs/2026-06-15-url-routing-design.md`

## Context

Hiện điều hướng của `webui/src/App.jsx` nằm hoàn toàn trong React state (`activeScreen` + `activeSeries` + `project`). Reload trang → `activeScreen` về `"dashboard"`, mất chỗ người dùng đang đứng, dù backend vẫn nhớ project hiện tại theo `clientId` (lưu trong `window.name`).

Mục tiêu: mỗi màn là một **page có URL riêng** (dashboard, chi tiết dự án, tạo video, từng bước workflow); **reload giữ đúng chỗ**; back/forward + bookmark hoạt động.

Quyết định đã chốt: `react-router-dom` với **URL là nguồn sự thật** (bỏ state `activeScreen`); `BrowserRouter` + **SPA fallback ở backend**; **slug suy ra từ tên thư mục**; **không** autosave nháp script.

## Architecture Decisions

- **App vẫn là shell giữ toàn bộ state**; chỉ thay khối render điều kiện `activeScreen === ...` (App.jsx ~1037–1090) bằng `<Routes>`, truyền props xuống screen như cũ. Tên props giữ nguyên.
- **Bước hiện tại suy ra từ `useLocation`/`useParams`** (cho Sidebar highlight + `buildUserProgress`/`estimateBasePercent`), không còn từ state.
- **Slug thuần xác định**: tái dùng logic slugify đã có trong `saveCurrentWorkflowAsPreset` (App.jsx ~560). Map `slug→path` dựng bằng `useMemo` từ `series`/`state.projects`; trùng slug thêm hậu tố `-2/-3…`.
- **Bất biến chống huỷ job khi reload**: chỉ gọi `openProject(path)` khi project hiện tại của backend KHÁC video trên URL; nếu đã trùng thì render thẳng (vì `openProject` chạy `bestEffortCancel(true)`).
- **BrowserRouter ở `main.jsx`**; test dùng `MemoryRouter` (`initialEntries`).

## Sơ đồ URL ⇄ màn

```
/                                 → Dashboard
/du-an/:duAnId                    → ProjectDetailScreen
/du-an/:duAnId/tao-video          → ScriptStepScreen (chưa có project)
/video/:videoId                   → redirect tới bước phù hợp (nextScreenForProject)
/video/:videoId/noi-dung          → step1 (script của video đã mở)
/video/:videoId/giong-doc         → step2 VoiceScreen
/video/:videoId/phan-canh         → step3a SceneScreen
/video/:videoId/duyet-anh         → step3b MediaReviewScreen
/video/:videoId/xuat              → step4 ExportScreen
*                                 → redirect "/" + toast
```

## Dependency graph

```
react-router-dom + BrowserRouter (main.jsx)        slug utils (routing.js)
        │                                                  │
        └──────────────┬───────────────────────────────────┘
                       ▼
        App routing shell (<Routes> + layout + navigate helpers)
                       ▼
   route wrappers + chuyển ~25 call-site setActiveScreen → navigate
                       ▼
        reload restoration (skip-openProject invariant)
                       ▼
   backend SPA fallback   +   tests (FE MemoryRouter, BE TestClient)
```

## Task List

### Phase 1: Foundation

#### Task 1: Cài react-router-dom + bọc BrowserRouter — Scope S
**Description:** Thêm dependency và bọc app trong `<BrowserRouter>` ở `main.jsx`. Chưa đổi logic điều hướng — app chạy y như cũ.
**Acceptance criteria:**
- [ ] `react-router-dom` có trong `webui/package.json` và cài được.
- [ ] App vẫn hiển thị bình thường (dashboard).
**Verification:** `npm run build` thành công; test hiện có chạy lại (bọc router nếu cần — xem Task 7).
**Dependencies:** None · **Files:** `webui/package.json`, `webui/src/main.jsx`

#### Task 2: Tiện ích slug + map slug↔path (có test) — Scope S
**Description:** `webui/src/lib/routing.js`: `slugify(name)`, `buildSeriesSlugMap`, `buildVideoSlugMap`, `seriesSlugToPath`, `videoSlugToPath`, `pathToSeriesSlug`, `pathToVideoSlug`, bảng ánh xạ bước ⇄ segment. Trùng slug → hậu tố xác định; series ảo → `chua-phan-nhom`.
**Acceptance criteria:**
- [ ] Slug bỏ dấu tiếng Việt, chỉ còn `a-z0-9-`.
- [ ] Hai mục cùng tên → slug khác nhau, ổn định theo thứ tự.
- [ ] Round-trip `path → slug → path` đúng trên dữ liệu mẫu.
**Verification:** `npx vitest run src/lib/routing.test.js` xanh.
**Dependencies:** None · **Files:** `webui/src/lib/routing.js`, `webui/src/lib/routing.test.js`

### Checkpoint: Foundation
- [ ] Build xanh, test xanh, app chạy như cũ.

### Phase 2: Routing shell + chuyển call-site

#### Task 3: Dựng `<Routes>` + layout + route dashboard/chi-tiết-dự-án — Scope M
**Description:** Bỏ `activeScreen` state; thêm `useNavigate`/`useLocation`; layout (header + sidebar + modals) bọc `<Outlet/>`/quanh `<Routes>`. Thay render `dashboard`/`project` bằng route `/` và `/du-an/:duAnId`. Chuyển call-site: `onOpenSeries`, `ProjectDetailScreen.onBack`, `goHomeAndStopProject`, nút "Quay lại trang chủ".
**Acceptance criteria:**
- [ ] `/` hiện Dashboard; click dự án → URL `/du-an/:id` + đúng dự án.
- [ ] Reload tại `/du-an/:id` (mock) → đúng dự án.
- [ ] Back/forward đi đúng giữa 2 màn.
**Verification:** `npm run build` xanh; kiểm tay dashboard↔chi tiết.
**Dependencies:** 1, 2 · **Files:** `webui/src/App.jsx`, `lib/routing.js`

#### Task 4: Route tạo-video + bước workflow; chuyển nốt call-site — Scope L (chia 4a/4b)
**Description:** Route `/du-an/:duAnId/tao-video` (ScriptStepScreen chưa có project), `/video/:videoId/{noi-dung|giong-doc|phan-canh|duyet-anh|xuat}`, `/video/:videoId` redirect qua `nextScreenForProject`. Chuyển toàn bộ `setActiveScreen` còn lại sang `navigate`: `Sidebar`, footer Voice/Scene/MediaReview/Export, effect job-xong (~372–373), effect "không series → dashboard" (~415–417), nhánh `"home"` lạ (~757), `openProject`, `startVideoInSeries`, `startNewVideo`. Sidebar + progress nhận bước từ location.
- **4a:** route wrappers + tạo-video.
- **4b:** workflow steps + sidebar/progress.
**Acceptance criteria:**
- [ ] "Tạo video mới" → `/du-an/:id/tao-video`, hiện ScriptStepScreen.
- [ ] Mở video có sẵn → đi qua các bước, URL đổi đúng; Sidebar highlight đúng.
- [ ] Không còn `activeScreen`/`setActiveScreen` trong App.jsx (trừ qua location).
**Verification:** `npm run build` xanh; đi hết workflow; `grep` sạch `setActiveScreen`.
**Dependencies:** 3 · **Files:** `webui/src/App.jsx`, `lib/routing.js`

### Checkpoint: Core navigation
- [ ] Mọi màn truy cập bằng URL; build xanh; đi hết một video bằng URL OK.

### Phase 3: Khôi phục khi reload

#### Task 5: Logic khôi phục + bất biến chống huỷ job — Scope M
**Description:** Khi mount/route khớp `/video/:videoId/...`: chờ `loadState` đầu xong, giải `videoId→path`. `data.project` đã trùng → render thẳng (KHÔNG `openProject`). Khác → `openProject(path)` rồi render. Slug không giải được → `navigate("/")` + toast. `/du-an/:id` và `.../tao-video`: lấy series từ danh sách; thiếu → `/`.
**Acceptance criteria:**
- [ ] Reload `/video/:id/giong-doc` khi backend mở đúng video → VoiceScreen, KHÔNG gọi `POST /api/projects/open`.
- [ ] Reload khi backend mở video khác → có gọi `POST /api/projects/open` đúng path.
- [ ] Slug/video đã xoá → về `/` + toast.
**Verification:** Test FE mô phỏng reload (Task 7) xanh; kiểm tay: chạy job rồi reload → job không bị huỷ.
**Dependencies:** 4 · **Files:** `webui/src/App.jsx`, `lib/routing.js`

### Checkpoint: Reload an toàn
- [ ] Reload ở mọi page giữ đúng chỗ; reload khi đang chạy job không huỷ job.

### Phase 4: Backend fallback + kiểm thử

#### Task 6: SPA fallback ở backend — Scope S (song song được)
**Description:** Sửa `app/web_server.py`: GET không thuộc `/api`, `/media`, không phải file tĩnh trong `WEB_DIST` → trả `FileResponse(WEB_DIST/"index.html")`. Vẫn phục vụ assets; API trước catch-all.
**Acceptance criteria:**
- [ ] `GET /du-an/bat-ky` → 200, nội dung `index.html`.
- [ ] `GET /api/state`, `GET /api/media?...` như cũ.
**Verification:** `pytest tests/test_web_server.py` xanh (thêm test catch-all).
**Dependencies:** None · **Files:** `app/web_server.py`, `tests/test_web_server.py`

#### Task 7: Test routing FE + sửa test cũ; chạy toàn bộ — Scope M
**Description:** Test (vitest + `MemoryRouter`): `/`→Dashboard; `/du-an/:id`→chi tiết; reload `/video/:id/giong-doc` (trùng project)→VoiceScreen & không gọi open; (khác project)→có gọi open; slug sai→`/`. Bọc router cho `SettingsModal.test.jsx`. Chạy đủ FE + BE + build.
**Acceptance criteria:**
- [ ] Test routing mới xanh; `SettingsModal.test.jsx` xanh trở lại.
- [ ] Toàn bộ FE + BE xanh; `npm run build` xanh.
**Verification:** `npx vitest run` và `pytest tests/test_web_server.py`.
**Dependencies:** 5, 6 · **Files:** `webui/src/Routing.test.jsx` (mới), `webui/src/SettingsModal.test.jsx`

### Checkpoint: Hoàn tất
- [ ] Tất cả acceptance criteria đạt; build + toàn bộ test xanh; sẵn sàng review.

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| Refactor đụng ~25 call-site `setActiveScreen` | Med | Làm tăng dần (4a/4b), build sau mỗi nhóm, `grep` xác nhận hết |
| Vô tình huỷ job đang chạy khi reload | High | Test riêng bất biến "đã trùng project thì không openProject" (Task 5/7) |
| 404 deep-link do thứ tự route backend | Med | Catch-all đăng ký sau API; test backend (Task 6) |
| Test render `<App/>` vỡ vì thiếu Router | Low | Bọc `MemoryRouter` (Task 7) |

## Verification (end-to-end)
1. `cd webui && npm run build` — xanh.
2. `npx vitest run` (FE) và `python -m pytest tests/test_web_server.py` (BE) — xanh.
3. Chạy app, kiểm tay: mở dự án → `/du-an/...`; tạo video → `/du-an/.../tao-video`; đi từng bước → URL đổi; **reload ở mỗi bước giữ đúng màn**; chạy job rồi reload → job không bị huỷ; URL slug sai → về trang chủ.
