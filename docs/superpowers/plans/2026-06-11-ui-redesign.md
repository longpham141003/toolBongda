# UI Redesign — Visual CapCut Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Làm lại toàn bộ giao diện Visual CapCut Studio — sidebar navigation, font Be Vietnam Pro, spacing 4px grid, và cải thiện từng màn hình.

**Architecture:** Thay layout margin-based hiện tại bằng sidebar 240px cố định + main content area. Xóa `ProgressRail` và `UserProgressPanel` ngang, chuyển logic vào sidebar. Mỗi màn hình được tái cấu trúc trong cùng file `App.jsx`.

**Tech Stack:** React 18, Tailwind CSS, CSS custom classes, Be Vietnam Pro (Google Fonts), Radix UI (giữ nguyên)

---

## File Map

| File | Thay đổi |
|------|----------|
| `webui/index.html` | Thêm Google Fonts link |
| `webui/src/styles.css` | Viết lại hoàn toàn — layout, typography, sidebar, spacing |
| `webui/src/App.jsx` | Thêm `Sidebar` component, cập nhật `App` render, cập nhật từng màn hình |
| `webui/src/components/ui.jsx` | Không thay đổi (Radix UI components giữ nguyên) |

---

## Task 1: Font Be Vietnam Pro

**Files:**
- Modify: `webui/index.html`
- Modify: `webui/src/styles.css` (chỉ dòng `font-family` trong `:root`)

- [ ] **Step 1: Thêm Google Fonts vào index.html**

Mở `webui/index.html`, thêm 2 thẻ vào trong `<head>` sau `<meta name="theme-color">`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;600;700&display=swap" rel="stylesheet" />
```

- [ ] **Step 2: Cập nhật font-family trong styles.css**

Trong `webui/src/styles.css`, tìm dòng:
```css
font-family: Inter, "Segoe UI", system-ui, sans-serif;
```
Thay thành:
```css
font-family: 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif;
```

- [ ] **Step 3: Chạy app và kiểm tra font**

```bash
cd webui && npm run dev
```

Mở `http://127.0.0.1:5173`. Kiểm tra: chữ "Tạo video hoàn chỉnh chỉ trong 4 bước" phải dùng Be Vietnam Pro (góc tròn nhẹ, dấu tiếng Việt sắc nét hơn Inter).

- [ ] **Step 4: Commit**

```bash
git add webui/index.html webui/src/styles.css
git commit -m "feat: switch font to Be Vietnam Pro for Vietnamese support"
```

---

## Task 2: Typography Token System

**Files:**
- Modify: `webui/src/styles.css`

- [ ] **Step 1: Cập nhật `:root` variables và typography**

Trong `webui/src/styles.css`, tìm khối `:root { ... }` và thay thế toàn bộ nội dung bên trong bằng:

```css
:root {
  color-scheme: dark;
  --background: 240 5% 7%;
  --foreground: 300 7% 89%;
  --card: 240 5% 10%;
  --card-foreground: 0 0% 96%;
  --primary: 263 89% 68%;
  --primary-foreground: 0 0% 100%;
  --muted: 240 5% 14%;
  --muted-foreground: 240 4% 55%;
  --border: 240 4% 16%;
  --input: 240 4% 16%;
  --ring: 263 70% 58%;

  /* Typography */
  --text-xl: 32px;
  --text-lg: 24px;
  --text-md: 18px;
  --text-base: 14px;
  --text-sm: 13px;
  --text-xs: 12px;
  --text-micro: 11px;

  /* Spacing (4px grid) */
  --sp-1: 4px;
  --sp-2: 8px;
  --sp-3: 12px;
  --sp-4: 16px;
  --sp-5: 20px;
  --sp-6: 24px;
  --sp-8: 32px;
  --sp-12: 48px;

  /* Layout */
  --sidebar-width: 240px;
  --topbar-height: 48px;

  font-family: 'Be Vietnam Pro', 'Segoe UI', system-ui, sans-serif;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
  line-height: 1.6;
}
```

- [ ] **Step 2: Cập nhật `.screen-heading` để dùng token mới**

Tìm khối `.screen-heading` trong `styles.css`:
```css
.screen-heading { flex-shrink:0; text-align:center; }
.screen-heading h1 { font-size:36px; line-height:42px; font-weight:800; color:white; }
.screen-heading p { margin-top:4px; color:#cbc3d7; font-size:14px; }
.screen-heading.compact h1 { font-size:30px; }
```
Thay bằng:
```css
.screen-heading { flex-shrink: 0; text-align: center; }
.screen-heading h1 { font-size: var(--text-lg); line-height: 1.3; font-weight: 700; color: white; }
.screen-heading p { margin-top: var(--sp-1); color: #cbc3d7; font-size: var(--text-xs); line-height: 1.6; }
.screen-heading.compact h1 { font-size: var(--text-md); }
```

- [ ] **Step 3: Cập nhật `.hero-title`**

Tìm:
```css
.hero-title {
  font-size: 48px;
  line-height: 56px;
```
Thay `48px` → `var(--text-xl)` và `56px` → `1.25`:
```css
.hero-title {
  font-size: var(--text-xl);
  line-height: 1.25;
```

- [ ] **Step 4: Commit**

```bash
git add webui/src/styles.css
git commit -m "feat: add typography token system with 4px spacing grid"
```

---

## Task 3: CSS — New App Shell Layout

**Files:**
- Modify: `webui/src/styles.css`

Đây là task quan trọng nhất — thay thế layout margin-based bằng sidebar + main content.

- [ ] **Step 1: Thêm app shell CSS**

Thêm vào cuối `webui/src/styles.css` (sau tất cả CSS hiện có):

```css
/* ═══════════════════════════════════════
   APP SHELL — Sidebar Layout
   ═══════════════════════════════════════ */

.app-shell {
  position: relative;
  isolation: isolate;
  min-height: 100vh;
  background: #131315;
  color: #e5e1e4;
}

/* TOPBAR */
.app-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  height: var(--topbar-height);
  align-items: center;
  gap: var(--sp-3);
  border-bottom: 1px solid rgba(255,255,255,0.1);
  background: rgba(19,19,21,0.85);
  padding: 0 var(--sp-6);
  backdrop-filter: blur(24px);
}

.app-topbar-logo {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}

.app-topbar-logo .logo-mark {
  width: 32px;
  height: 32px;
  border-radius: 10px;
}

.app-topbar-logo .logo-name {
  font-size: 15px;
  font-weight: 700;
  color: white;
  white-space: nowrap;
}

.app-topbar-logo .logo-name span {
  color: #4edea3;
}

.app-topbar-project {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-left: var(--sp-4);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 10px;
  background: rgba(255,255,255,0.04);
  padding: 6px var(--sp-3);
  color: #d0bcff;
  font-size: var(--text-xs);
  font-weight: 600;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: background 0.2s;
}

.app-topbar-project:hover {
  background: rgba(255,255,255,0.08);
}

.app-topbar-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

/* SIDEBAR */
.app-sidebar {
  position: fixed;
  top: var(--topbar-height);
  left: 0;
  width: var(--sidebar-width);
  height: calc(100vh - var(--topbar-height));
  z-index: 90;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255,255,255,0.08);
  background: rgba(17,17,20,0.92);
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--sp-4) 0 var(--sp-4);
  backdrop-filter: blur(20px);
}

.sidebar-section {
  padding: 0 var(--sp-4);
  margin-bottom: var(--sp-4);
}

.sidebar-label {
  display: block;
  margin-bottom: var(--sp-2);
  color: #64748b;
  font-size: var(--text-micro);
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.sidebar-project-name {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  background: rgba(255,255,255,0.04);
  padding: var(--sp-2) var(--sp-3);
  color: #e5e1e4;
  font-size: var(--text-sm);
  font-weight: 600;
  text-align: left;
  overflow: hidden;
  transition: background 0.2s;
}

.sidebar-project-name:hover {
  background: rgba(255,255,255,0.08);
}

.sidebar-project-name span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.sidebar-project-status {
  margin-top: var(--sp-1);
  color: #94a3b8;
  font-size: var(--text-micro);
  padding-left: var(--sp-1);
}

.sidebar-divider {
  margin: var(--sp-3) var(--sp-4);
  border: none;
  border-top: 1px solid rgba(255,255,255,0.07);
}

/* Sidebar step nav */
.sidebar-steps {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--sp-3);
}

.sidebar-step {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  width: 100%;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: var(--sp-2) var(--sp-3);
  color: #94a3b8;
  font-size: var(--text-sm);
  text-align: left;
  transition: background 0.2s, border-color 0.2s, color 0.2s;
  cursor: pointer;
}

.sidebar-step:hover:not(.locked) {
  background: rgba(255,255,255,0.05);
  color: #e5e1e4;
}

.sidebar-step.active {
  background: rgba(160,120,255,0.12);
  border-color: rgba(208,188,255,0.28);
  color: #d0bcff;
}

.sidebar-step.done {
  color: #4edea3;
}

.sidebar-step.locked {
  opacity: 0.4;
  cursor: not-allowed;
}

.sidebar-step-num {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.06);
  font-size: var(--text-xs);
  font-weight: 700;
}

.sidebar-step.active .sidebar-step-num {
  background: linear-gradient(135deg, rgba(160,120,255,0.9), rgba(208,188,255,0.8));
  border-color: rgba(208,188,255,0.5);
  color: #23005c;
  box-shadow: 0 0 16px rgba(160,120,255,0.5);
}

.sidebar-step.done .sidebar-step-num {
  background: #4edea3;
  border-color: rgba(78,222,163,0.4);
  color: #002113;
}

.sidebar-step-text b {
  display: block;
  font-size: var(--text-sm);
  font-weight: 600;
}

.sidebar-step-text small {
  display: block;
  font-size: var(--text-micro);
  color: #64748b;
  margin-top: 1px;
}

.sidebar-step.active .sidebar-step-text small {
  color: #a78bfa;
}

.sidebar-step.done .sidebar-step-text small {
  color: #6ee7b7;
}

/* Sidebar job progress */
.sidebar-job {
  margin: var(--sp-2) var(--sp-4);
  padding: var(--sp-3);
  border: 1px solid rgba(208,188,255,0.2);
  border-radius: 12px;
  background: rgba(160,120,255,0.08);
}

.sidebar-job-title {
  color: white;
  font-size: var(--text-xs);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.sidebar-job-bar {
  position: relative;
  height: 6px;
  border-radius: 999px;
  background: rgba(255,255,255,0.1);
  overflow: hidden;
  margin-bottom: var(--sp-2);
}

.sidebar-job-bar-fill {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 999px;
  background: linear-gradient(90deg, #8b5cf6, #d0bcff, #4edea3);
  box-shadow: 0 0 12px rgba(160,120,255,0.4);
  transition: width 0.45s ease;
}

.sidebar-job-bar-fill::after {
  content: "";
  position: absolute;
  inset: 0;
  width: 40%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent);
  animation: progress-indeterminate 1.8s linear infinite;
}

.sidebar-job-log {
  color: #94a3b8;
  font-size: var(--text-micro);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Sidebar bottom actions */
.sidebar-bottom {
  margin-top: auto;
  padding: 0 var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-bottom-btn {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  border-radius: 10px;
  padding: var(--sp-2) var(--sp-3);
  color: #64748b;
  font-size: var(--text-xs);
  font-weight: 500;
  text-align: left;
  transition: background 0.2s, color 0.2s;
}

.sidebar-bottom-btn:hover {
  background: rgba(255,255,255,0.05);
  color: #94a3b8;
}

/* MAIN CONTENT */
.app-main {
  margin-left: var(--sidebar-width);
  margin-top: var(--topbar-height);
  min-height: calc(100vh - var(--topbar-height));
  padding: var(--sp-6);
  overflow-x: hidden;
}
```

- [ ] **Step 2: Cập nhật `.stitch-workspace` và `.stitch-home` để tương thích**

Tìm trong `styles.css`:
```css
.stitch-home {
  display: flex;
  width: calc(100% - (var(--app-side-margin) * 2));
```
Thay thành:
```css
.stitch-home {
  display: flex;
  width: 100%;
```

Tìm:
```css
.stitch-workspace {
  position: relative;
  z-index: 10;
  display: flex;
  width: calc(100% - (var(--app-side-margin) * 2));
  height: calc(100vh - 64px);
```
Thay thành:
```css
.stitch-workspace {
  position: relative;
  z-index: 10;
  display: flex;
  width: 100%;
  height: calc(100vh - var(--topbar-height));
```

- [ ] **Step 3: Cập nhật `.stitch-topbar` thành chiều cao mới**

Tìm:
```css
.stitch-topbar {
  position: fixed;
  top: 0;
  left: var(--app-side-margin);
  right: var(--app-side-margin);
  z-index: 100;
  display: flex;
  height: 64px;
```
Thay thành:
```css
.stitch-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  height: var(--topbar-height);
```

- [ ] **Step 4: Cập nhật margin-top của home/workspace**

Tìm và thay trong `.stitch-home`:
```css
  margin: 64px auto 0;
```
→
```css
  margin: var(--topbar-height) 0 0;
  padding: var(--sp-6) var(--sp-6) 84px;
```

Tìm và thay trong `.stitch-workspace`:
```css
  margin: 64px auto 0;
```
→
```css
  margin: var(--topbar-height) 0 0;
  padding: var(--sp-3) var(--sp-6) var(--sp-4);
```

- [ ] **Step 5: Commit**

```bash
git add webui/src/styles.css
git commit -m "feat: add sidebar layout CSS and app shell structure"
```

---

## Task 4: CSS — Panel & Card Simplification

**Files:**
- Modify: `webui/src/styles.css`

- [ ] **Step 1: Thêm class `.panel` và `.card` mới**

Thêm vào cuối `styles.css`:

```css
/* ═══════════════════════════════════════
   SIMPLIFIED PANEL & CARD COMPONENTS
   ═══════════════════════════════════════ */

.panel {
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255,255,255,0.065), rgba(255,255,255,0.028));
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 16px 60px rgba(0,0,0,0.2);
  backdrop-filter: blur(24px);
  padding: var(--sp-5);
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}

.panel-header h2,
.panel-header h3 {
  color: white;
  font-size: var(--text-md);
  font-weight: 700;
}

.panel-header p {
  margin-top: var(--sp-1);
  color: #94a3b8;
  font-size: var(--text-xs);
  line-height: 1.5;
}

/* Toast position fix */
.toast-error,
.toast-ok {
  top: auto;
  bottom: var(--sp-6);
  right: var(--sp-6);
}
```

- [ ] **Step 2: Commit**

```bash
git add webui/src/styles.css
git commit -m "feat: add simplified panel/card CSS and fix toast position"
```

---

## Task 5: App.jsx — Sidebar Component

**Files:**
- Modify: `webui/src/App.jsx`

- [ ] **Step 1: Thêm component `Sidebar` vào App.jsx**

Trong `webui/src/App.jsx`, tìm function `StepPill` (dòng ~879). Thêm component `Sidebar` ngay TRƯỚC function `StepPill`:

```jsx
function Sidebar({ activeScreen, setActiveScreen, completedSteps, project, activeJob, userProgress, setSettingsOpen, setProjectsOpen }) {
  // step3a = phân cảnh, step3b = duyệt ảnh — cả hai đều thuộc "Bước 3" trong sidebar
  const steps = [
    { id: "step1", label: "Nội dung", hint: "Kịch bản và AI viết" },
    { id: "step2", label: "Giọng đọc", hint: "Chọn giọng, clone voice" },
    { id: "step3a", label: "Hình ảnh", hint: "Phân cảnh và duyệt media" },
    { id: "step4", label: "Xuất CapCut", hint: "Kiểm tra và xuất" },
  ]
  const doneMap = { step1: completedSteps[0], step2: completedSteps[1], step3a: completedSteps[2], step4: completedSteps[3] }
  const isRunning = activeJob && ["queued", "running"].includes(activeJob.status)
  const percent = Math.max(0, Math.min(100, Math.round(userProgress?.percent || 0)))
  const latestLog = userProgress?.messages?.[userProgress.messages.length - 1] || ""

  const stepLabel = (id) => {
    if (doneMap[id]) return "Hoàn thành"
    if (activeScreen === id) return "Đang thực hiện"
    const idx = steps.findIndex(s => s.id === id)
    const prevId = idx > 0 ? steps[idx - 1].id : null
    if (prevId && !doneMap[prevId] && activeScreen !== id) return "Chưa mở"
    return "Sẵn sàng"
  }

  const isLocked = (id) => {
    const idx = steps.findIndex(s => s.id === id)
    if (idx === 0) return false
    const prevId = steps[idx - 1].id
    // step3b cũng tính là "đang ở bước 3"
    const isStep3 = id === "step3a" && (activeScreen === "step3a" || activeScreen === "step3b")
    return !doneMap[prevId] && !isStep3 && activeScreen !== id
  }

  // Điều hướng bước 3: sang step3b nếu đã có scenes, ngược lại step3a
  const navigateToStep = (id) => {
    if (id === "step3a") {
      setActiveScreen(project?.has_scenes ? "step3b" : "step3a")
    } else {
      setActiveScreen(id)
    }
  }

  return (
    <aside className="app-sidebar">
      <div className="sidebar-section">
        <span className="sidebar-label">Dự án</span>
        <button className="sidebar-project-name" onClick={() => setProjectsOpen(true)}>
          <FolderOpen className="h-4 w-4 flex-shrink-0 text-violet-400" />
          <span>{project?.name || "Chưa có project"}</span>
        </button>
        {project && (
          <div className="sidebar-project-status">
            {completedSteps.filter(Boolean).length} / 4 bước hoàn thành
          </div>
        )}
      </div>

      <hr className="sidebar-divider" />

      <div className="sidebar-section">
        <span className="sidebar-label">Các bước</span>
      </div>
      <nav className="sidebar-steps">
        {steps.map((step, idx) => {
          const done = doneMap[step.id]
          const active = activeScreen === step.id
          const locked = isLocked(step.id)
          return (
            <button
              key={step.id}
              className={cn("sidebar-step", active && "active", done && !active && "done", locked && "locked")}
              disabled={locked}
              onClick={() => !locked && navigateToStep(step.id)}
            >
              <span className="sidebar-step-num">
                {done && !active ? <Check className="h-3 w-3" /> : idx + 1}
              </span>
              <span className="sidebar-step-text">
                <b>{step.label}</b>
                <small>{stepLabel(step.id)}</small>
              </span>
            </button>
          )
        })}
      </nav>

      {isRunning && (
        <>
          <hr className="sidebar-divider" />
          <div className="sidebar-job">
            <div className="sidebar-job-title">{userProgress?.title || "Đang xử lý..."}</div>
            <div className="sidebar-job-bar">
              <div className="sidebar-job-bar-fill" style={{ width: `${percent}%` }} />
            </div>
            <div className="sidebar-job-log">{latestLog || "Đang xử lý..."}</div>
          </div>
        </>
      )}

      <div className="sidebar-bottom">
        <button className="sidebar-bottom-btn" onClick={() => setSettingsOpen(true)}>
          <Settings className="h-4 w-4" /> Cài đặt
        </button>
        <button className="sidebar-bottom-btn">
          <Bot className="h-4 w-4" /> Trợ giúp
        </button>
      </div>
    </aside>
  )
}
```

- [ ] **Step 2: Cập nhật hàm `App` — thay layout render chính**

Trong `App.jsx`, tìm đoạn render return chính (bắt đầu dòng ~743):
```jsx
  return (
    <div className="stitch-app min-h-screen overflow-hidden bg-[#131315] text-[#e5e1e4]">
      <div className="aurora-bg"><div className="aurora-blob-1" /><div className="aurora-blob-2" /></div>
      <ParticleCanvas />
      <header className="stitch-topbar">
```

Thay toàn bộ block `<header className="stitch-topbar">...</header>` (kết thúc trước `{activeScreen === "home" ?`) bằng:

```jsx
  return (
    <div className="stitch-app min-h-screen overflow-hidden bg-[#131315] text-[#e5e1e4]">
      <div className="aurora-bg"><div className="aurora-blob-1" /><div className="aurora-blob-2" /></div>
      <ParticleCanvas />

      <header className="stitch-topbar">
        {activeScreen !== "home" && (
          <button className="back-home-button" onClick={goHomeAndStopProject} title="Quay lại trang chủ">
            <ArrowLeft className="h-4 w-4" />
          </button>
        )}
        <button className="flex items-center gap-2" onClick={() => activeScreen !== "home" && goHomeAndStopProject()}>
          <div className="logo-mark"><WandSparkles className="h-4 w-4" /></div>
          <span className="text-[15px] font-bold text-white">Visual CapCut <span className="text-emerald-300">Studio</span></span>
        </button>
        <div className="ml-auto flex items-center gap-2">
          <button className="icon-action" onClick={() => setSettingsOpen(true)}><Settings className="h-4 w-4" /></button>
          <div className="avatar-dot">L</div>
        </div>
      </header>

      {activeScreen !== "home" && (
        <Sidebar
          activeScreen={activeScreen}
          setActiveScreen={setActiveScreen}
          completedSteps={completedSteps}
          project={project}
          activeJob={activeJob}
          userProgress={userProgress}
          setSettingsOpen={setSettingsOpen}
          setProjectsOpen={setProjectsOpen}
        />
      )}
```

- [ ] **Step 3: Bọc workspace content vào div có margin-left**

Tìm đoạn:
```jsx
      {activeScreen === "home" ? (
        <main className="stitch-home">
```

Thay thành:
```jsx
      {activeScreen === "home" ? (
        <main className="stitch-home">
```
*(giữ nguyên, không thay)*

Tìm đoạn `<main className="stitch-workspace">` và các dòng bên trong cho đến `</main>`. Thay:
```jsx
        <main className="stitch-workspace">
          <ProgressRail steps={stepCards} current={currentStepIndex} done={completedSteps} setActiveScreen={setActiveScreen} />
          <UserProgressPanel progress={userProgress} />
```
Bằng:
```jsx
        <main className="stitch-workspace" style={{ marginLeft: "var(--sidebar-width)" }}>
```
(Xóa 2 dòng `<ProgressRail .../>` và `<UserProgressPanel .../>`)

- [ ] **Step 4: Chạy app kiểm tra sidebar xuất hiện**

```bash
cd webui && npm run dev
```

Mở app ở một bước bất kỳ (vd: bấm "Tạo video mới"). Kiểm tra: sidebar 240px hiện bên trái với 4 bước, bước active được highlight tím.

- [ ] **Step 5: Commit**

```bash
git add webui/src/App.jsx
git commit -m "feat: add Sidebar component and wire into App layout"
```

---

## Task 6: App.jsx — Home Screen Simplification

**Files:**
- Modify: `webui/src/App.jsx`
- Modify: `webui/src/styles.css`

- [ ] **Step 1: Thêm CSS cho home screen mới**

Thêm vào cuối `webui/src/styles.css`:

```css
/* ═══════════════════════════════════════
   HOME SCREEN (simplified)
   ═══════════════════════════════════════ */

.home-welcome {
  max-width: 560px;
}

.home-welcome h1 {
  font-size: var(--text-xl);
  font-weight: 700;
  color: white;
  line-height: 1.25;
  letter-spacing: -0.02em;
  background: linear-gradient(90deg, #d0bcff, #8b5cf6, #4edea3);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.home-welcome p {
  margin-top: var(--sp-2);
  color: #94a3b8;
  font-size: var(--text-base);
  line-height: 1.6;
}

.home-cta-row {
  display: flex;
  gap: var(--sp-3);
  margin-top: var(--sp-6);
  flex-wrap: wrap;
}

.home-flow-section {
  margin-top: var(--sp-8);
}

.home-flow-section h3 {
  font-size: var(--text-micro);
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #64748b;
  margin-bottom: var(--sp-3);
}

.home-flow-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-3);
}
```

- [ ] **Step 2: Thay thế home screen JSX**

Trong `App.jsx`, tìm đoạn `{activeScreen === "home" ? (` và thay toàn bộ khối `<main className="stitch-home">...</main>` bằng:

```jsx
      {activeScreen === "home" ? (
        <main className="stitch-home" style={{ paddingTop: "var(--sp-8)" }}>
          <div className="home-welcome fade-in-up">
            <h1>Tạo video AI<br />trong 4 bước đơn giản</h1>
            <p>Không cần biết AI hay kỹ thuật. Nhập kịch bản, chọn giọng, duyệt ảnh, xuất CapCut.</p>
            <div className="home-cta-row">
              <Button onClick={startNewVideo} size="lg">
                <Plus className="h-4 w-4" /> Tạo video mới
              </Button>
              <Button variant="secondary" size="lg" onClick={() => setProjectsOpen(true)}>
                <FolderOpen className="h-4 w-4" /> Mở project gần đây
              </Button>
            </div>
          </div>

          <div className="home-flow-section fade-in-up delay-100">
            <h3>Flow phổ biến</h3>
            <div className="home-flow-grid">
              <FlowCard icon={Circle} title="Tin tức bóng đá" desc="Cập nhật nhanh trận đấu" />
              <FlowCard icon={Rocket} title="Khoa học & vũ trụ" desc="Kiến thức khám phá" accent="emerald" />
              <FlowCard icon={FileText} title="Kể chuyện" desc="Truyện, tóm tắt sách" accent="blue" />
              <FlowCard icon={Settings} title="Tạo flow riêng" desc="Tuỳ chỉnh mọi bước" dashed onClick={() => setSettingsOpen(true)} />
            </div>
          </div>
        </main>
```

- [ ] **Step 3: Kiểm tra trang chủ**

Chạy app, vào trang chủ. Kiểm tra: tiêu đề gradient đẹp, 2 nút CTA rõ, 4 flow card hiện bên dưới. Không còn hero animation phức tạp hay progress rail.

- [ ] **Step 4: Commit**

```bash
git add webui/src/App.jsx webui/src/styles.css
git commit -m "feat: simplify home screen to welcome + CTA + flow cards"
```

---

## Task 7: App.jsx — Step 1 Single Column Layout

**Files:**
- Modify: `webui/src/App.jsx`

- [ ] **Step 1: Thay thế `ScriptStepScreen`**

Trong `App.jsx`, tìm function `ScriptStepScreen` (dòng ~1151) và thay toàn bộ:

```jsx
function ScriptStepScreen({ title, setTitle, script, setScript, scriptFileInputRef, uploadTxtFile, saveScriptStep, isBusy, workflowInput, setWorkflowInput, workflowSteps, settings, workflowPresets, applyWorkflowPreset, startJob, busyAction, setSettingsOpen }) {
  return (
    <div className="step-screen">
      <div className="screen-heading">
        <h1>Bước 1 — Chuẩn bị nội dung</h1>
        <p>Dán kịch bản cuối hoặc nhờ AI viết. Đây là nội dung giọng đọc sẽ đọc ở bước sau.</p>
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Kịch bản cuối</h2>
            <p>Dán nguyên văn nội dung muốn đọc — không cần ghi chú hình ảnh hay chia cảnh</p>
          </div>
          <FileText className="text-violet-300 flex-shrink-0" />
        </div>

        <Field label="Tên project">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Brazil vs Panama" />
        </Field>

        <div className="mt-4">
          <Textarea
            className="min-h-[400px]"
            value={script}
            onChange={(e) => setScript(e.target.value)}
            placeholder="Dán kịch bản cuối vào đây..."
          />
        </div>

        <div className="mt-3 flex items-center gap-2">
          <input ref={scriptFileInputRef} type="file" accept=".txt,text/plain" className="hidden" onChange={(e) => uploadTxtFile(e.target.files?.[0])} />
          <Button variant="secondary" size="sm" onClick={() => scriptFileInputRef.current?.click()}>
            <Upload className="h-4 w-4" /> Tải file TXT
          </Button>
          <span className="ml-auto text-xs text-slate-500">{script.trim() ? script.trim().split(/\s+/).length : 0} từ</span>
        </div>

        <div className="mt-5 border-t border-white/8 pt-4">
          <div className="flex items-center gap-3">
            <Sparkles className="h-4 w-4 text-emerald-300 flex-shrink-0" />
            <span className="text-xs text-slate-400 font-medium">Hoặc nhờ AI viết kịch bản</span>
          </div>
          <div className="mt-3 flex gap-2">
            <Input
              value={workflowInput}
              onChange={(e) => setWorkflowInput(e.target.value)}
              placeholder="Nhập chủ đề, ý tưởng, độ dài video..."
              className="flex-1"
            />
            <Button
              variant="secondary"
              disabled={!workflowInput.trim() || isBusy}
              onClick={() => startJob("/api/workflow", { input: workflowInput, steps: workflowSteps }, "workflow")}
            >
              {busyAction === "workflow" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              Chạy AI
            </Button>
          </div>
        </div>
      </div>

      <div className="screen-footer">
        <span className="text-xs text-slate-500">Dán kịch bản final, sau đó bấm lưu để sang bước 2.</span>
        <Button onClick={saveScriptStep} disabled={!script.trim() || isBusy}>
          Lưu nội dung và sang Bước 2 <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Cập nhật call-site trong `App` render**

Tìm dòng:
```jsx
          {activeScreen === "step1" && <ScriptStepScreen
            title={title}
            setTitle={setTitle}
            script={script}
            setScript={setScript}
            scriptFileInputRef={scriptFileInputRef}
            uploadTxtFile={uploadTxtFile}
            saveScriptStep={saveScriptStep}
            isBusy={isBusy}
          />}
```
Thay bằng:
```jsx
          {activeScreen === "step1" && <ScriptStepScreen
            title={title}
            setTitle={setTitle}
            script={script}
            setScript={setScript}
            scriptFileInputRef={scriptFileInputRef}
            uploadTxtFile={uploadTxtFile}
            saveScriptStep={saveScriptStep}
            isBusy={isBusy}
            workflowInput={workflowInput}
            setWorkflowInput={setWorkflowInput}
            workflowSteps={workflowSteps}
            settings={settings}
            workflowPresets={workflowPresets}
            applyWorkflowPreset={applyWorkflowPreset}
            startJob={startJob}
            busyAction={busyAction}
            setSettingsOpen={setSettingsOpen}
          />}
```

- [ ] **Step 3: Kiểm tra Bước 1**

Chạy app → Tạo video mới → Bước 1. Kiểm tra: một panel đơn chiều rộng, textarea lớn, dòng AI workflow nhỏ ở dưới.

- [ ] **Step 4: Commit**

```bash
git add webui/src/App.jsx
git commit -m "feat: step 1 single-column layout with inline AI workflow"
```

---

## Task 8: App.jsx — Step 2 Voice Screen Refactor

**Files:**
- Modify: `webui/src/App.jsx`
- Modify: `webui/src/styles.css`

- [ ] **Step 1: Thêm CSS cho CloneVoiceDialog**

Thêm vào cuối `webui/src/styles.css`:

```css
/* ═══════════════════════════════════════
   CLONE VOICE DIALOG
   ═══════════════════════════════════════ */

.clone-dialog-grid {
  display: grid;
  grid-template-columns: 1.4fr 0.7fr;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}

.clone-upload-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  min-height: 120px;
  border: 2px dashed rgba(255,255,255,0.15);
  border-radius: 16px;
  background: rgba(19,19,21,0.5);
  color: #94a3b8;
  text-align: center;
  cursor: pointer;
  padding: var(--sp-5);
  transition: border-color 0.2s, background 0.2s;
}

.clone-upload-zone:hover {
  border-color: rgba(78,222,163,0.4);
  background: rgba(78,222,163,0.04);
}

.clone-upload-zone b {
  color: #e5e1e4;
  font-size: var(--text-sm);
}

.clone-upload-zone span {
  font-size: var(--text-xs);
  line-height: 1.5;
}

/* Voice screen 2-col */
.voice-screen-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
}
```

- [ ] **Step 2: Thêm `CloneVoiceDialog` component**

Trong `App.jsx`, thêm component sau function `RangeField`:

```jsx
function CloneVoiceDialog({ open, onOpenChange, onClone, isBusy, voicePreviewBusy }) {
  const [cloneName, setCloneName] = useState("")
  const [cloneLanguage, setCloneLanguage] = useState("vi")
  const [pendingFile, setPendingFile] = useState(null)
  const inputRef = useRef(null)

  const handleClone = () => {
    if (!pendingFile) return
    onClone(pendingFile, { name: cloneName, language: cloneLanguage, setDefault: true })
    setPendingFile(null)
    setCloneName("")
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogTitle>Thêm giọng clone mới</DialogTitle>
        <DialogDescription>Tải audio mẫu, đặt tên rồi bấm Clone để lưu vào danh sách.</DialogDescription>
        <div className="mt-4 clone-dialog-grid">
          <Field label="Tên giọng">
            <Input value={cloneName} onChange={(e) => setCloneName(e.target.value)} placeholder="Ví dụ: AnhQuan, GiongKeChuyen..." />
          </Field>
          <Field label="Ngôn ngữ">
            <Input value={cloneLanguage} onChange={(e) => setCloneLanguage(e.target.value)} placeholder="vi, en, fr..." />
          </Field>
        </div>
        <button type="button" className="clone-upload-zone" onClick={() => inputRef.current?.click()}>
          <Upload className="h-7 w-7 text-emerald-300" />
          <b>{pendingFile ? `Đã chọn: ${pendingFile.name}` : "Tải audio mẫu clone"}</b>
          <span>File WAV/MP3 sạch, chỉ một người nói, khoảng 10–30 giây.</span>
        </button>
        <input ref={inputRef} type="file" accept="audio/*,.wav,.mp3,.m4a,.flac" className="hidden" onChange={(e) => setPendingFile(e.target.files?.[0] || null)} />
        <div className="voice-language-note mt-3">
          Lần đầu clone có thể lâu vì tool tự cài thư viện cần thiết.
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Huỷ</Button>
          <Button disabled={!pendingFile || isBusy || voicePreviewBusy} onClick={handleClone}>
            {voicePreviewBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
            {voicePreviewBusy ? "Đang clone..." : "Clone voice"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
```

- [ ] **Step 3: Cập nhật `VoiceScreen` sang layout 2 cột**

Tìm function `VoiceScreen` trong `App.jsx` và thay toàn bộ phần return (từ `return <div className="step-screen">`) bằng:

```jsx
  const [cloneDialogOpen, setCloneDialogOpen] = useState(false)

  const handleCloneVoice = async (file, meta) => {
    await saveCloneVoice(file, meta)
    setCloneDialogOpen(false)
  }

  return (
    <div className="step-screen">
      <div className="screen-heading">
        <h1>Bước 2 — Chọn giọng đọc</h1>
        <p>Chọn giọng, nghe thử, rồi tạo file đọc để bước sau tự chia cảnh.</p>
      </div>

      <div className="recommended-action">
        <div>
          <b>Không biết chọn gì?</b>
          <span>Bấm để tool tự chọn ngôn ngữ và cấu hình ổn định.</span>
        </div>
        <Button variant="secondary" onClick={applyBeginnerVoicePreset} disabled={isBusy}>
          <WandSparkles className="h-4 w-4" /> Dùng cấu hình dễ nhất
        </Button>
      </div>

      {languageMismatch && (
        <div className="ux-warning">
          <AlertTriangle className="h-4 w-4" />
          <span>Script có vẻ là tiếng Anh nhưng ngôn ngữ giọng đang không phải English.</span>
          <button onClick={() => setSettings({ ...settings, text_to_voice_language: "en", text_to_voice_voice: "af_heart" })}>Đổi sang English</button>
        </div>
      )}

      <div className="voice-screen-grid">
        {/* Cột trái: chọn giọng */}
        <div className="panel flex flex-col gap-4">
          <div className="panel-header">
            <div><h2>Chọn giọng</h2><p>Ngôn ngữ và giọng đọc</p></div>
            <Button variant="ghost" size="sm" onClick={() => refreshVoices(settings.text_to_voice_language || "en")}>
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>

          <Field label="Ngôn ngữ đọc">
            <Select value={voiceLanguage} onValueChange={changeVoiceLanguage} options={voiceLanguageOptions} />
          </Field>

          <Field label="Giọng thường">
            <Select
              value={settings.text_to_voice_voice || voiceOptions[0]?.value || "af_heart"}
              onValueChange={(value) => setSettings({ ...settings, text_to_voice_voice: value, voice_clone_enabled: false })}
              options={voiceOptions.map((v) => ({ value: v.value, label: v.label }))}
            />
          </Field>

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-zinc-500">Giọng clone đã lưu</span>
              <Button variant="ghost" size="sm" onClick={() => setCloneDialogOpen(true)}>
                <Plus className="h-3.5 w-3.5" /> Thêm mới
              </Button>
            </div>
            {cloneProfiles.length > 0 ? (
              <div className="saved-voice-list">
                {cloneProfiles.map((item) => {
                  const active = item.id === selectedCloneId
                  return (
                    <button key={item.id} className={cn("saved-voice-row", active && "active")} onClick={() => selectSavedCloneVoice(item, false)}>
                      <span><b>{item.name}</b><small>{item.language || "voice clone"}</small></span>
                      {active && <Check className="h-4 w-4" />}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="text-xs text-slate-500 py-2">Chưa có giọng clone. Bấm "Thêm mới" để tạo.</div>
            )}
            {selectedClone && (
              <Button variant="secondary" size="sm" className="mt-2 w-full" onClick={() => setSettings({ ...settings, voice_clone_enabled: false, voice_clone_reference_path: "", voice_clone_reference_name: "" })}>
                Dùng giọng thường
              </Button>
            )}
          </div>
        </div>

        {/* Cột phải: cài đặt + nghe thử */}
        <div className="flex flex-col gap-4">
          <div className="panel flex-1">
            <div className="panel-header">
              <div><h2>Cài đặt</h2><p>Tốc độ và chất lượng clone</p></div>
              <Settings className="text-emerald-300 flex-shrink-0" />
            </div>
            <RangeField label="Tốc độ đọc" value={settings.text_to_voice_speed ?? 1} min={0.5} max={2} step={0.05} onChange={(v) => setSettings({ ...settings, text_to_voice_speed: v })} />
            <div className="setting-help">0.9–1.0 là tự nhiên. Tăng để đọc nhanh hơn.</div>
            <RangeField label="Mức xử lý giọng clone" value={settings.magicvoice_steps ?? 16} min={8} max={32} step={1} onChange={(v) => setSettings({ ...settings, magicvoice_steps: v })} />
            <div className="setting-help">16 là cân bằng. Số cao hơn giống mẫu hơn nhưng lâu hơn.</div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div><h2>Nghe thử</h2></div>
              <Button size="sm" variant="ghost" onClick={() => previewVoiceNow()}>
                {voicePreviewBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Nghe thử
              </Button>
            </div>
            {voicePreviewUrl
              ? <audio controls autoPlay src={voicePreviewUrl} className="w-full mt-2" />
              : <div className="text-xs text-slate-500">Bấm "Nghe thử" để nghe giọng hiện tại.</div>
            }
          </div>
        </div>
      </div>

      <div className="screen-footer">
        <Button variant="secondary" onClick={() => setActiveScreen("step1")}><ArrowLeft className="h-4 w-4" /> Bước 1</Button>
        <div className="footer-chips">
          <span>Xuất WAV</span>
          <span>Tạo mốc thời gian</span>
          <span>{project?.voice_path ? "Sẵn sàng tạo cảnh" : "Tạo voice trước"}</span>
        </div>
        {project?.voice_path
          ? <Button onClick={() => { setActiveScreen("step3a"); startJob("/api/analyze-search", undefined, "analyze-search") }} disabled={isBusy}>
              {busyAction === "analyze-search" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Tạo cảnh và tìm ảnh
            </Button>
          : <Button onClick={createVoiceWithQuickSettings} disabled={isBusy}>
              {busyAction === "voice" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Tạo giọng đọc
            </Button>
        }
      </div>

      <CloneVoiceDialog
        open={cloneDialogOpen}
        onOpenChange={setCloneDialogOpen}
        onClone={handleCloneVoice}
        isBusy={isBusy}
        voicePreviewBusy={voicePreviewBusy}
      />
    </div>
  )
```

Lưu ý: bỏ `const [cloneName, setCloneName] = useState("")`, `const [cloneLanguage, setCloneLanguage] = useState("vi")`, `const [pendingCloneFile, setPendingCloneFile] = useState(null)`, `const cloneInputRef = useRef(null)`, và function `cloneVoiceNow` ra khỏi `VoiceScreen` (chúng đã chuyển vào `CloneVoiceDialog`). Thêm `const [cloneDialogOpen, setCloneDialogOpen] = useState(false)` thay thế.

- [ ] **Step 4: Kiểm tra Bước 2**

Chạy app → Bước 2. Kiểm tra: layout 2 cột cân đối, nút "Thêm mới" mở dialog riêng.

- [ ] **Step 5: Commit**

```bash
git add webui/src/App.jsx webui/src/styles.css
git commit -m "feat: step 2 two-column layout with CloneVoiceDialog"
```

---

## Task 9: App.jsx — Step 3B Media Grid 4 Columns + Tab Filter

**Files:**
- Modify: `webui/src/App.jsx`
- Modify: `webui/src/styles.css`

- [ ] **Step 1: Cập nhật `.media-grid` thành 4 cột**

Trong `webui/src/styles.css`, tìm:
```css
.media-grid {
  display:grid;
  grid-template-columns:repeat(5,minmax(0,1fr));
```
Thay thành:
```css
.media-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
```

- [ ] **Step 2: Thêm CSS cho tab filter**

Thêm vào cuối `styles.css`:

```css
/* ═══════════════════════════════════════
   MEDIA FILTER TABS
   ═══════════════════════════════════════ */

.media-filter-tabs {
  display: flex;
  gap: var(--sp-1);
  flex-wrap: wrap;
  padding: 4px;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  background: rgba(0,0,0,0.18);
}

.media-filter-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  border-radius: 10px;
  padding: 6px 12px;
  color: #64748b;
  font-size: var(--text-xs);
  font-weight: 600;
  transition: background 0.2s, color 0.2s;
  white-space: nowrap;
}

.media-filter-tab:hover {
  background: rgba(255,255,255,0.06);
  color: #94a3b8;
}

.media-filter-tab.active {
  background: rgba(160,120,255,0.18);
  color: white;
  border: 1px solid rgba(208,188,255,0.3);
}

.media-filter-tab .tab-count {
  background: rgba(255,255,255,0.1);
  border-radius: 999px;
  padding: 1px 6px;
  font-size: 10px;
  color: #d0bcff;
}

.media-filter-tab.active .tab-count {
  background: rgba(208,188,255,0.2);
}
```

- [ ] **Step 3: Cập nhật `MediaReviewScreen` — thay dropdown filter bằng tabs**

Trong `App.jsx`, trong function `MediaReviewScreen`, tìm đoạn:
```jsx
    <div className="media-filter-row">
      <div>
        <span>Hiển thị</span>
        <Select value={assetFilter} onValueChange={changeFilter} options={filterOptions.map(([value,label])=>({value,label:`${label} (${counts[value]})`}))}/>
      </div>
      <div className="media-filter-actions">
```

Thay bằng:

```jsx
    <div className="flex items-center justify-between gap-4 flex-wrap">
      <div className="media-filter-tabs">
        {filterOptions.map(([value, label]) => (
          <button
            key={value}
            className={cn("media-filter-tab", assetFilter === value && "active")}
            onClick={() => changeFilter(value)}
          >
            {label}
            <span className="tab-count">{counts[value]}</span>
          </button>
        ))}
      </div>
      <div className="media-filter-actions">
```

- [ ] **Step 4: Kiểm tra Bước 3B**

Chạy app với project có assets → Bước 3B. Kiểm tra: grid 4 cột, filter là tab pill ngang thay vì dropdown.

- [ ] **Step 5: Commit**

```bash
git add webui/src/App.jsx webui/src/styles.css
git commit -m "feat: step 3B 4-column grid and tab filter pills"
```

---

## Task 10: CSS Cleanup — Remove Dead Code

**Files:**
- Modify: `webui/src/styles.css`

- [ ] **Step 1: Xóa `.workspace-progress`, `.workspace-rail-*`, `.workspace-step*`**

Trong `styles.css`, xóa toàn bộ các khối CSS sau (chúng đã bị thay bởi sidebar):
- `.workspace-progress { ... }`
- `.workspace-rail-line { ... }`
- `.workspace-rail-flow { ... }`
- `.workspace-step { ... }`
- `.workspace-step:hover { ... }`
- `.workspace-step span { ... }`
- `.workspace-step b { ... }`
- `.workspace-step small { ... }`
- `.workspace-step.active { ... }`
- `.workspace-step.active span { ... }`
- `.workspace-step.done { ... }`
- `.workspace-step.done span { ... }`
- `.workspace-step.locked { ... }`
- `.workspace-step.locked:hover { ... }`
- `.user-progress-panel { ... }` và tất cả sub-classes của nó

- [ ] **Step 2: Xóa `.project-pill` và `.top-action` (đã chuyển vào sidebar/topbar mới)**

Tìm và xóa:
- `.project-pill { ... }`
- `.top-action { ... }` và `.top-action:hover { ... }`

- [ ] **Step 3: Kiểm tra không có lỗi CSS**

```bash
cd webui && npm run build 2>&1 | head -30
```

Kết quả mong đợi: build thành công, không có warning về class không tồn tại.

- [ ] **Step 4: Commit**

```bash
git add webui/src/styles.css
git commit -m "chore: remove obsolete CSS classes replaced by sidebar"
```

---

## Task 11: Visual Polish Pass

**Files:**
- Modify: `webui/src/styles.css`

- [ ] **Step 1: Cập nhật spacing cho `.screen-footer`**

Tìm:
```css
.screen-footer { display:flex; flex-shrink:0; align-items:center; justify-content:space-between; gap:12px; border-radius:18px; background:rgba(19,19,21,.78); padding:10px 4px; color:#94a3b8; }
```
Thay bằng:
```css
.screen-footer {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  border-radius: 16px;
  background: rgba(19,19,21,0.78);
  padding: var(--sp-3) var(--sp-4);
  color: #94a3b8;
  font-size: var(--text-xs);
}
```

- [ ] **Step 2: Cập nhật `.panel-title` thành `.panel-header` (CSS alias)**

Tìm:
```css
.panel-title { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:16px; }
.panel-title h2, .panel-title h3 { color:white; font-size:20px; font-weight:800; }
.panel-title p { color:#94a3b8; font-size:12px; }
```
Thay bằng:
```css
.panel-title,
.panel-header-legacy {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}
.panel-title h2, .panel-title h3 {
  color: white;
  font-size: var(--text-md);
  font-weight: 700;
}
.panel-title p {
  color: #94a3b8;
  font-size: var(--text-xs);
  margin-top: var(--sp-1);
  line-height: 1.5;
}
```

- [ ] **Step 3: Kiểm tra toàn bộ app**

Chạy app, đi qua tất cả 4 bước. Kiểm tra:
- Font Be Vietnam Pro áp dụng khắp nơi
- Sidebar hiện đúng bước active
- Spacing nhất quán
- Toast xuất hiện dưới màn hình (bottom-right)

- [ ] **Step 4: Commit**

```bash
git add webui/src/styles.css
git commit -m "feat: visual polish pass - spacing, footer, panel-title"
```

---

---

## Ghi chú: Màn hình không cần task riêng

**Bước 3A (SceneScreen):** Không thay đổi JSX. Các CSS changes trong Task 3, 4, 11 (`.panel`, spacing, typography) tự động áp dụng vì `SceneScreen` dùng `.glass-panel` → alias sang `.panel`. Sidebar hiển thị step 3 active khi `activeScreen === "step3a"` hoặc `"step3b"`.

**Bước 4 (ExportScreen):** Không thay đổi JSX. Layout 2 cột giữ nguyên. Typography và spacing được phủ bởi Task 2 và Task 11. Test bằng cách navigate đến Bước 4 sau khi các task hoàn thành.

---

## Tóm tắt thứ tự thực hiện

1. Task 1 — Font (nhanh, ~5 phút)
2. Task 2 — Typography tokens
3. Task 3 — Layout CSS (sidebar shell)
4. Task 4 — Panel/card + toast
5. Task 5 — Sidebar component JSX *(task phức tạp nhất)*
6. Task 6 — Home screen
7. Task 7 — Bước 1
8. Task 8 — Bước 2
9. Task 9 — Bước 3B
10. Task 10 — CSS cleanup
11. Task 11 — Polish pass
