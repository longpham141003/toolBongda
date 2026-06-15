# Spec: Điều hướng theo URL + page riêng (reload không mất chỗ)

- **Ngày:** 2026-06-15
- **Trạng thái:** Đã duyệt thiết kế, chờ review spec
- **Phạm vi:** `webui/` (frontend) + một thay đổi nhỏ ở `app/web_server.py` (SPA fallback)

## 1. Mục tiêu

1. Mỗi màn là một **page có URL riêng**: dashboard, chi tiết dự án, tạo video, và từng bước của workflow.
2. **Reload trang giữ đúng chỗ đang đứng** — kể cả khi đang ở giữa workflow (giọng đọc / phân cảnh / duyệt ảnh / xuất).
3. Nút back/forward của trình duyệt và bookmark hoạt động đúng.

Không nằm trong phạm vi (YAGNI): autosave nháp script ở trang tạo video; chia nhỏ `App.jsx` thành nhiều file; đổi cách backend định danh project (vẫn dùng đường dẫn thư mục).

## 2. Quyết định đã chốt

| Vấn đề | Quyết định |
|---|---|
| Cơ chế routing | `react-router-dom`, **URL là nguồn sự thật** (bỏ state `activeScreen`) |
| Loại router | `BrowserRouter` (URL sạch) + **SPA fallback ở backend** |
| Định danh trên URL | **Slug suy ra từ tên thư mục**, giải nghĩa lại bằng danh sách đã tải; trùng thì thêm hậu tố `-2`, `-3`… |
| Autosave nháp script | Không (có thể thêm sau) |

## 3. Kiến trúc

### 3.1 Mô hình hiện tại (để tham chiếu)
- Toàn bộ điều hướng nằm trong state của component `App` (`webui/src/App.jsx`, ~2280 dòng): `activeScreen` ∈ {`dashboard`, `project`, `step1`, `step2`, `step3a`, `step3b`, `step4`}, cộng `activeSeries` và `project`.
- Reload → `activeScreen` về `"dashboard"`, `activeSeries` về `null`. Backend vẫn nhớ **project hiện tại** theo `clientId` (lưu trong `window.name`, sống sót qua reload) và trả về trong `GET /api/state`.
- Các screen đã tồn tại: `DashboardScreen`, `ProjectDetailScreen`, `ScriptStepScreen` (step1), `VoiceScreen` (step2), `SceneScreen` (step3a), `MediaReviewScreen` (step3b), `ExportScreen` (step4).

### 3.2 Mô hình mới
- `App` **vẫn là shell giữ toàn bộ state** (script, settings, jobs, project, assets…). Chỉ thay khối render điều kiện theo `activeScreen` bằng `<Routes>`, và truyền props xuống các screen như cũ → ít xáo trộn nhất.
- Layout chung (header + sidebar + modals) bọc `<Outlet/>`.
- Bước hiện tại (cho Sidebar highlight và thanh tiến độ) **suy ra từ `useLocation`/`useParams`**, không còn từ state.
- Mỗi route có một wrapper mỏng đọc param → render screen tương ứng với props từ `App`.

## 4. Sơ đồ URL

| Route | Màn | Ghi chú |
|---|---|---|
| `/` | Dashboard | Danh sách dự án |
| `/du-an/:duAnId` | Chi tiết dự án (`ProjectDetailScreen`) | |
| `/du-an/:duAnId/tao-video` | Tạo video (`ScriptStepScreen`, chưa có project) | `projectCategory` = tên series |
| `/video/:videoId` | (redirect) | Chuyển tới bước phù hợp qua `nextScreenForProject` |
| `/video/:videoId/noi-dung` | step1 — nội dung/script của video đã mở | |
| `/video/:videoId/giong-doc` | step2 — `VoiceScreen` | |
| `/video/:videoId/phan-canh` | step3a — `SceneScreen` | |
| `/video/:videoId/duyet-anh` | step3b — `MediaReviewScreen` | |
| `/video/:videoId/xuat` | step4 — `ExportScreen` | |
| `*` (không khớp) | redirect `/` + toast | |

Bảng ánh xạ bước nội bộ ⇄ segment URL:

```
step1  ⇄ noi-dung      (chỉ với video đã mở; còn tạo mới là /du-an/:id/tao-video)
step2  ⇄ giong-doc
step3a ⇄ phan-canh
step3b ⇄ duyet-anh
step4  ⇄ xuat
```

## 5. Slug và giải nghĩa slug

- Hàm `slugify(name)`: lowercase → `normalize("NFD")` bỏ dấu → thay ký tự không phải `a-z0-9` bằng `-` → bỏ `-` thừa. (Tái dùng đúng logic đã có trong `saveCurrentWorkflowAsPreset`.)
- Xây map ổn định từ danh sách đã tải:
  - `seriesSlugToPath`: từ `series` (loại `is_virtual`). Series ảo "Chưa phân nhóm" dùng slug cố định `chua-phan-nhom`.
  - `videoSlugToPath`: từ `state.projects`.
- **Xử lý trùng slug:** duyệt theo thứ tự danh sách; slug trùng được thêm hậu tố `-2`, `-3`… Việc tạo slug và map phải **thuần xác định** (cùng dữ liệu → cùng slug) để URL ổn định giữa các lần tải.
- Hàm ngược: `pathToSeriesSlug(path)`, `pathToVideoSlug(path)` để dựng URL khi điều hướng.
- Map được tính bằng `useMemo` từ `series`/`state.projects`; sẵn sàng ngay sau `loadState` đầu tiên.

## 6. Khôi phục khi reload (cốt lõi)

Luồng khi tải app ở một URL bất kỳ:

1. `App` mount → màn loading cho tới khi `loadState()` đầu tiên xong (đã có sẵn). `loadState` trả `series`, `state.projects`, và `project` hiện tại (backend nhớ theo clientId).
2. Sau khi có dữ liệu, router khớp route:
   - **`/video/:videoId/<step>`:** giải `videoId` → `path` qua `videoSlugToPath`.
     - Nếu **project hiện tại của backend đã trùng `path`** (`data.project` slug === `videoId`): **render thẳng**, KHÔNG gọi `openProject` (vì `openProject` chạy `bestEffortCancel(true)` sẽ huỷ job đang chạy).
     - Nếu khác: gọi `openProject(path)` để backend mở đúng project, rồi render.
     - `videoId` không giải được (đã xoá) → `navigate("/")` + toast "Không tìm thấy video".
   - **`/du-an/:duAnId`:** lấy series từ `series`. Không có → `navigate("/")` + toast.
   - **`/du-an/:duAnId/tao-video`:** lấy series từ param làm `activeSeries`/`projectCategory`; hiện `ScriptStepScreen` rỗng.
3. Không ép buộc theo trạng thái: nếu URL trỏ tới bước `xuat` mà video chưa đủ dữ liệu, vẫn render (các screen đã có empty-state). Không tự đẩy người dùng sang bước khác — để "giữ đúng chỗ".

**Chống huỷ job khi reload:** so sánh slug của `data.project` với `videoId` trước khi quyết định gọi `openProject`. Đây là bất biến quan trọng nhất của tính năng.

## 7. Thay đổi điều hướng (call-site)

- Bỏ `const [activeScreen, setActiveScreen] = useState(...)`.
- Thêm `const navigate = useNavigate()` và helper điều hướng, ví dụ:
  - `goDashboard()` → `navigate("/")`
  - `goSeries(series)` → `navigate(/du-an/${pathToSeriesSlug(series.path)})`
  - `goVideoStep(stepSegment)` → `navigate(/video/${currentVideoSlug}/${stepSegment})`
- Thay toàn bộ `setActiveScreen("...")` (~25 chỗ, gồm trong `Sidebar`, `VoiceScreen`, `SceneScreen`, `MediaReviewScreen`, `ExportScreen`, `openProject`, `goHomeAndStopProject`, `startVideoInSeries`, các effect ở dòng ~372–373, ~415–417, ~757) bằng lời gọi `navigate` tương ứng.
- Effect tự chuyển bước khi job xong (vd `B2 Phan tich canh` → step3a) đổi thành `navigate` tới segment tương ứng.
- `Sidebar`/`buildUserProgress`/`estimateBasePercent` nhận "bước hiện tại" suy ra từ location thay vì nhận `activeScreen` từ state.

## 8. Thay đổi backend (SPA fallback)

`app/web_server.py` hiện mount `StaticFiles(directory=WEB_DIST, html=True)` ở `/`, nên reload deep-link (vd `/du-an/bong-da`) trả 404.

Thay bằng:
- Giữ phục vụ file tĩnh thật (assets) như cũ.
- Thêm catch-all GET cuối cùng cho path **không thuộc `/api`, không thuộc `/media`, và không phải file tồn tại trong `WEB_DIST`** → trả `FileResponse(WEB_DIST / "index.html")`.
- Không ảnh hưởng các endpoint API (đăng ký trước catch-all).

## 9. Edge cases

- **Reload ở trang tạo video khi đã gõ dở script:** mất nội dung (chỉ ở memory, chưa lưu backend). Chấp nhận — ngoài phạm vi.
- **Trùng slug:** hậu tố xác định `-2/-3…`.
- **Project/series đã bị xoá** mà URL còn trỏ tới: redirect `/` + toast.
- **Tên tiếng Việt có dấu / ký tự lạ:** `slugify` bỏ dấu; nếu slug rỗng dùng `video`/`du-an` + hậu tố.
- **2 tab:** clientId khác nhau theo tab (`window.name`); backend nhớ project riêng từng client; URL điều khiển độc lập.
- **Đổi tên dự án/video:** slug đổi theo tên mới sau `loadState`; URL cũ sẽ không giải được → redirect `/`. Chấp nhận.

## 10. Kiểm thử

**Frontend (vitest + `MemoryRouter` với `initialEntries`):**
- Render `/` → ra `DashboardScreen`.
- Render `/du-an/:id` (state mock có series) → ra `ProjectDetailScreen` đúng dự án.
- **Mô phỏng reload giữa workflow:** render `/video/:id/giong-doc` với state mock mà `data.project` đã là video đó → hiển thị `VoiceScreen`, **không** gọi `POST /api/projects/open`.
- Render `/video/:id/giong-doc` khi `data.project` khác → có gọi `POST /api/projects/open`.
- Slug không tồn tại → điều hướng về `/`.
- Giữ các test SettingsModal hiện có chạy được (bọc trong router nếu cần).

**Backend (pytest, `TestClient`):**
- `GET /du-an/bat-ky` → 200, trả nội dung `index.html`.
- `GET /api/state` vẫn hoạt động (không bị catch-all nuốt).
- `GET /api/media?path=...` không hợp lệ vẫn trả lỗi như cũ.

## 11. Rủi ro & giảm thiểu

- **Refactor đụng nhiều chỗ (`setActiveScreen`):** làm tăng dần, chạy build + test sau mỗi nhóm thay đổi; giữ tên props của screen không đổi.
- **Vô tình huỷ job khi reload:** test riêng bất biến "đã trùng project thì không `openProject`".
- **404 deep-link:** test backend catch-all; xác nhận thứ tự đăng ký route (API trước, catch-all sau).
