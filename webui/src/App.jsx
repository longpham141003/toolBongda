import {
  Activity,
  AlertTriangle,
  Aperture,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Circle,
  Eye,
  EyeOff,
  FileAudio,
  FileText,
  Film,
  FolderOpen,
  Image,
  KeyRound,
  Layers,
  ListVideo,
  LoaderCircle,
  Lock,
  Mic,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  Save,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  WandSparkles,
  X,
  XCircle,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import {
  Badge,
  Button,
  Card,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Input,
  Select,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "./components/ui"
import { cn, formatTime, mediaUrl } from "./lib/utils"
import {
  SEGMENT_TO_STEP,
  STEP_TO_SEGMENT,
  pathToSeriesSlug,
  pathToVideoSlug,
  seriesSlugToPath,
  videoSlugToPath,
} from "./lib/routing"

const defaultSteps = [
  { enabled: true, name: "Phân tích đề tài", prompt: "Analyze the topic, audience, key facts, named entities, timeline and strongest visual moments." },
  { enabled: true, name: "Lập dàn ý", prompt: "Create a coherent video outline with a strong opening, logical body and concise conclusion." },
  { enabled: true, name: "Viết script final", prompt: "Write the final natural voice-over script. Output narration only, without headings or notes." },
]

const voiceLanguageOptions = [
  { value: "en", label: "American English" },
  { value: "en-gb", label: "British English" },
  { value: "fr", label: "French" },
  { value: "es", label: "Spanish" },
  { value: "hi", label: "Hindi" },
  { value: "it", label: "Italian" },
  { value: "ja", label: "Japanese" },
  { value: "pt", label: "Portuguese" },
  { value: "zh", label: "Chinese" },
]

function normalizeVoiceLanguage(language) {
  return voiceLanguageOptions.some((item) => item.value === language) ? language : "en"
}

const cp1252ReverseMap = {
  "€": 0x80,
  "‚": 0x82,
  "ƒ": 0x83,
  "„": 0x84,
  "…": 0x85,
  "†": 0x86,
  "‡": 0x87,
  "ˆ": 0x88,
  "‰": 0x89,
  "Š": 0x8a,
  "‹": 0x8b,
  "Œ": 0x8c,
  "Ž": 0x8e,
  "‘": 0x91,
  "’": 0x92,
  "“": 0x93,
  "”": 0x94,
  "•": 0x95,
  "–": 0x96,
  "—": 0x97,
  "˜": 0x98,
  "™": 0x99,
  "š": 0x9a,
  "›": 0x9b,
  "œ": 0x9c,
  "ž": 0x9e,
  "Ÿ": 0x9f,
}

function mojibakeScore(value) {
  const text = String(value || "")
  return ["Ã", "Â", "Ä", "Æ", "á»", "áº", "â€", "�", "\u0095", "\u00a3"].reduce((total, marker) => total + text.split(marker).length - 1, 0)
}

function decodeMojibakeOnce(value) {
  const text = String(value || "")
  const bytes = []
  for (const char of text) {
    const code = char.codePointAt(0)
    if (code <= 0xff) {
      bytes.push(code)
    } else if (cp1252ReverseMap[char] !== undefined) {
      bytes.push(cp1252ReverseMap[char])
    } else {
      return text
    }
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes))
  } catch {
    return text
  }
}

function repairMojibakeText(value) {
  let text = String(value || "")
  for (let i = 0; i < 3; i += 1) {
    const score = mojibakeScore(text)
    if (!score) break
    const candidate = decodeMojibakeOnce(text)
    if (candidate === text || mojibakeScore(candidate) >= score) break
    text = candidate
  }
  return text
}

function repairWorkflowPreset(preset) {
  return {
    ...preset,
    name: repairMojibakeText(preset?.name || ""),
    description: repairMojibakeText(preset?.description || ""),
    steps: Array.isArray(preset?.steps)
      ? preset.steps.map((step) => ({
          ...step,
          name: repairMojibakeText(step?.name || ""),
          prompt: repairMojibakeText(step?.prompt || ""),
        }))
      : [],
  }
}

const visualClientId = (() => {
  const prefix = "visual-capcut:"
  if (window.name.startsWith(prefix)) return window.name.slice(prefix.length)
  const created = globalThis.crypto?.randomUUID?.() || `tab-${Date.now()}-${Math.random().toString(16).slice(2)}`
  window.name = `${prefix}${created}`
  return created
})()

function nextScreenForProject(project) {
  const assets = project?.assets || []
  if (project?.has_capcut_export) return "step4"
  // Media already downloaded → go straight to the review screen.
  if (assets.some((item) => item.local_path)) return "step3b"
  // Prompts generated (manifest) but no media yet, or voice ready and no prompts
  // yet → the per-sentence prompt screen is the next stage.
  if (project?.has_scenes || project?.has_voice) return "step2b"
  return project?.script ? "step2" : "step1"
}

/**
 * Parse a pathname into the derived screen description.
 * Returns one of:
 *   { kind: "dashboard" }
 *   { kind: "project", seriesSlug }
 *   { kind: "new-video", seriesSlug }     // /du-an/:slug/tao-video
 *   { kind: "video", videoSlug, step }    // step null = "redirect to next step"
 *   { kind: "unknown" }
 */
function parseRoute(pathname) {
  const parts = String(pathname || "/").split("/").filter(Boolean)
  if (parts.length === 0) return { kind: "dashboard" }
  if (parts[0] === "du-an" && parts[1]) {
    if (parts.length === 2) return { kind: "project", seriesSlug: parts[1] }
    if (parts.length === 3 && parts[2] === "tao-video") return { kind: "new-video", seriesSlug: parts[1] }
    return { kind: "unknown" }
  }
  if (parts[0] === "video" && parts[1]) {
    if (parts.length === 2) return { kind: "video", videoSlug: parts[1], step: null }
    if (parts.length === 3 && parts[2] in SEGMENT_TO_STEP) {
      return { kind: "video", videoSlug: parts[1], step: SEGMENT_TO_STEP[parts[2]] }
    }
    return { kind: "unknown" }
  }
  return { kind: "unknown" }
}

/** Build the URL for a video at a given workflow step. */
function videoStepPath(videoSlug, step) {
  return `/video/${videoSlug}/${STEP_TO_SEGMENT[step] || "noi-dung"}`
}

/** Build the URL for a series detail page. */
function seriesPath(slug) { return `/du-an/${slug}` }

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", "X-Visual-Client": visualClientId, ...(options.headers || {}) },
    ...options,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`)
  return data
}

async function bestEffortCancel(clearProject = false) {
  try {
    await api(`/api/jobs/cancel${clearProject ? "?clear_project=true" : ""}`, { method: "POST" })
    return true
  } catch {
    return false
  }
}

function statusBadge(status) {
  if (status === "approved") return { label: "Đã duyệt", variant: "success" }
  if (status === "downloaded") return { label: "Đã tải", variant: "default" }
  if (status === "failed") return { label: "Lỗi", variant: "danger" }
  return { label: "Chờ xử lý", variant: "muted" }
}

function ParticleCanvas() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext("2d")
    if (!context) return
    let animationFrame = 0
    let particles = []

    const resize = () => {
      const ratio = window.devicePixelRatio || 1
      canvas.width = Math.floor(window.innerWidth * ratio)
      canvas.height = Math.floor(window.innerHeight * ratio)
      canvas.style.width = `${window.innerWidth}px`
      canvas.style.height = `${window.innerHeight}px`
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      particles = Array.from({ length: 90 }, () => ({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        size: 1 + Math.random() * 2,
        speed: 0.28 + Math.random() * 0.58,
        drift: -0.18 + Math.random() * 0.36,
        opacity: 0.08 + Math.random() * 0.14,
        violet: Math.random() > 0.62,
      }))
    }

    const draw = () => {
      context.clearRect(0, 0, window.innerWidth, window.innerHeight)
      particles.forEach((particle) => {
        particle.y += particle.speed
        particle.x += particle.drift
        if (particle.y > window.innerHeight + 10) {
          particle.y = -10
          particle.x = Math.random() * window.innerWidth
        }
        if (particle.x < -10) particle.x = window.innerWidth + 10
        if (particle.x > window.innerWidth + 10) particle.x = -10

        context.beginPath()
        context.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2)
        context.fillStyle = particle.violet
          ? `rgba(208, 188, 255, ${particle.opacity})`
          : `rgba(255, 255, 255, ${particle.opacity})`
        context.fill()
      })
      animationFrame = requestAnimationFrame(draw)
    }

    resize()
    draw()
    window.addEventListener("resize", resize)
    return () => {
      window.removeEventListener("resize", resize)
      cancelAnimationFrame(animationFrame)
    }
  }, [])

  return <canvas ref={canvasRef} className="particle-canvas" aria-hidden="true" />
}

function App() {
  const [state, setState] = useState(null)
  const [script, setScript] = useState("")
  const [subtitleSegments, setSubtitleSegments] = useState([])
  const [title, setTitle] = useState("")
  const [settings, setSettings] = useState({})
  const [voiceOptions, setVoiceOptions] = useState([{ value: "af_heart", label: "af_heart" }])
  const [workflowInput, setWorkflowInput] = useState("")
  const [projectCategory, setProjectCategory] = useState("")
  const [workflowSteps, setWorkflowSteps] = useState(defaultSteps)
  const [activeJob, setActiveJob] = useState(null)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState("")
  const [toast, setToast] = useState("")
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [apiKeyNoticeDismissed, setApiKeyNoticeDismissed] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [voicePreviewBusy, setVoicePreviewBusy] = useState(false)
  const [voicePreviewUrl, setVoicePreviewUrl] = useState("")
  const [lightboxIndex, setLightboxIndex] = useState(null)
  const [busyAction, setBusyAction] = useState("")
  const [followLogs, setFollowLogs] = useState(true)
  const [editingAssetId, setEditingAssetId] = useState(null)
  const [editingKeywordValue, setEditingKeywordValue] = useState("")
  const [assetFilter, setAssetFilter] = useState("all")
  const [preflight, setPreflight] = useState(null)
  const [preflightBusy, setPreflightBusy] = useState(false)
  const [promptAnalysis, setPromptAnalysis] = useState(null)

  const navigate = useNavigate()
  const location = useLocation()
  const [stateLoaded, setStateLoaded] = useState(false)
  const [activeSeries, setActiveSeries] = useState(null)
  const [series, setSeries] = useState([])
  const [flows, setFlows] = useState([])
  const [flowsOpen, setFlowsOpen] = useState(false)
  const [activeFlowId, setActiveFlowId] = useState(null)
  const logContainerRef = useRef(null)
  const scriptFileInputRef = useRef(null)
  const settingsSnapshot = useRef(null)
  // Latest loadProjectIntoState (declared below) so restoration effects can call
  // it without re-running on every render. Assigned during render (before effects fire), so the effect always reads the latest closure without listing the function as a dependency.
  const loadProjectIntoStateRef = useRef(null)
  // Path currently being opened by the restoration effect — prevents duplicate
  // /api/projects/open calls while one is already in flight for the same target.
  const restoringPathRef = useRef(null)

  // Snapshot the last-persisted settings whenever the dialog opens so that
  // closing via Huỷ / X / Esc / overlay reverts unsaved in-memory edits.
  useEffect(() => {
    if (settingsOpen) settingsSnapshot.current = { settings, workflowSteps, workflowInput }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settingsOpen])

  function handleSettingsOpenChange(next) {
    if (next) return setSettingsOpen(true)
    const snap = settingsSnapshot.current
    if (snap) {
      setSettings(snap.settings)
      setWorkflowSteps(snap.workflowSteps)
      setWorkflowInput(snap.workflowInput)
    }
    setSettingsOpen(false)
  }

  const loadState = useCallback(async (preserveScript = false) => {
    const data = await api("/api/state")
    setState(data)
    setSettings(data.settings || {})
    setSeries(data.series || [])
    if (data.series) {
      setActiveSeries(current => current ? (data.series.find(s => s.path === current.path) || current) : null)
    }
    if (data.flows) {
      setFlows(data.flows)
      setActiveFlowId(current => current || data.flows[0]?.id || null)
    }
    setWorkflowInput(data.settings?.script_workflow_input || "")
    setWorkflowSteps(data.settings?.script_workflow_steps?.length ? data.settings.script_workflow_steps : defaultSteps)
    if (!preserveScript) {
      setScript(data.project?.script || "")
      setTitle(data.project?.name || "")
      setSubtitleSegments(data.project?.subtitle_segments || [])
    }
    setActiveJob(data.active_job || null)
    if (data.active_job) setLogs(data.active_job.logs || [])
    return data
  }, [])

  useEffect(() => {
    loadState().catch((err) => setError(err.message)).finally(() => setStateLoaded(true))
  }, [loadState])

  useEffect(() => {
    api("/api/preflight").then(setPreflight).catch(() => {})
  }, [])

  const project = state?.project
  const assets = useMemo(() => project?.assets || [], [project])
  const liveJobs = state?.jobs || []

  // ---- Derive the active screen from the URL (no React state) ----
  // Declared before the job-polling effect because that effect lists goStep in
  // its dependency array, which React evaluates during render.
  const route = useMemo(() => parseRoute(location.pathname), [location.pathname])
  // Slug for the currently-open video (used to build step nav targets).
  const currentVideoSlug = useMemo(
    () => (project?.path ? pathToVideoSlug(project.path, state?.projects || []) : null),
    [project?.path, state?.projects],
  )
  // Slug for the active series (used to build the breadcrumb back-link target).
  const activeSeriesSlug = useMemo(
    () => (activeSeries?.path != null ? pathToSeriesSlug(activeSeries.path, series) : null),
    [activeSeries?.path, series],
  )
  const activeScreen = useMemo(() => {
    if (route.kind === "dashboard") return "dashboard"
    if (route.kind === "project") return "project"
    if (route.kind === "new-video") return "step1"
    if (route.kind === "video") {
      if (route.step) return route.step
      // Bare /video/:id → fall back to the project-derived step.
      return nextScreenForProject(project)
    }
    return "dashboard"
  }, [route, project])

  // Navigate a step within the currently-open video by step id.
  const goStep = useCallback((step) => {
    if (!currentVideoSlug) {
      if (import.meta.env.DEV) console.warn("goStep called with no current video, step =", step)
      return
    }
    navigate(videoStepPath(currentVideoSlug, step))
  }, [currentVideoSlug, navigate])

  // Redirect a bare /video/:id URL to its resolved step, once the project is open.
  useEffect(() => {
    if (route.kind === "video" && route.step === null && currentVideoSlug) {
      navigate(videoStepPath(currentVideoSlug, nextScreenForProject(project)), { replace: true })
    }
  }, [route, currentVideoSlug, project, navigate])

  // Unknown URLs fall back to the dashboard.
  useEffect(() => {
    if (route.kind === "unknown") navigate("/", { replace: true })
  }, [route.kind, navigate])

  // ---- Deep-link restoration ----------------------------------------------
  // Reloading a deep URL (/video/:slug/... or /du-an/:slug) must restore the
  // right page. All restoration is gated on stateLoaded so it never fires during
  // the initial /api/state load window (when projects/series are still empty).

  // Video routes: ensure the URL's video is the open project, then stay on the
  // requested step. NO-CANCEL INVARIANT: if the backend already has this exact
  // video open (project.path === target) we do NOTHING — calling open would run
  // bestEffortCancel and kill an in-flight job. Only when a DIFFERENT (or no)
  // project is open do we loadProjectIntoState(target) (not openProject — the
  // URL already encodes the desired step, so we must not navigate away from it).
  useEffect(() => {
    if (!stateLoaded || route.kind !== "video") return
    const target = videoSlugToPath(route.videoSlug, state?.projects || [])
    if (target == null) {
      navigate("/", { replace: true })
      setToast("Không tìm thấy video")
      return
    }
    // Same video already open → leave the running job (and current step) alone.
    if (project?.path === target) {
      // Clear in case a render fired after the open settled but before state propagated.
      restoringPathRef.current = null
      return
    }
    // Avoid re-triggering while an open for this same target is already in flight.
    if (restoringPathRef.current === target) return
    restoringPathRef.current = target
    Promise.resolve(loadProjectIntoStateRef.current?.(target, { notify: false }))
      .catch((err) => setError(err?.message || String(err)))
      .finally(() => {
        if (restoringPathRef.current === target) restoringPathRef.current = null
      })
  }, [stateLoaded, route, state?.projects, project?.path, navigate])

  // Series routes (/du-an/:slug and /du-an/:slug/tao-video): restore activeSeries
  // from the slug. The virtual/ungrouped series uses slug "chua-phan-nhom".
  useEffect(() => {
    if (!stateLoaded) return
    if (route.kind !== "project" && route.kind !== "new-video") return
    const foundPath = seriesSlugToPath(route.seriesSlug, series)
    const found = foundPath != null ? series.find((s) => s.path === foundPath) : null
    if (found) {
      if (activeSeries?.path !== found.path) setActiveSeries(found)
      return
    }
    // Pure client-side lookup (no async call), so no error handler is needed here.
    navigate("/", { replace: true })
    setToast("Không tìm thấy dự án")
  }, [stateLoaded, route, series, activeSeries?.path, navigate])

  // Load prompt analysis whenever the user enters the prompt screen.
  useEffect(() => {
    if (activeScreen === "step2b" && project?.path) loadPromptAnalysis().catch(() => {})
  }, [activeScreen, project?.path, loadPromptAnalysis])

  useEffect(() => {
    if (!activeJob || !["queued", "running"].includes(activeJob.status)) return
    const timer = setInterval(async () => {
      try {
        const data = await api(`/api/jobs/${activeJob.id}`)
        const job = data.job
        setActiveJob(job)
        setLogs(job.logs || [])
        if (job.result?.project) {
          setState((current) => ({ ...current, project: job.result.project }))
        }
        if (job.status === "done") {
          clearInterval(timer)
          if (job.name === "AI Workflow" && job.result?.script) setScript(job.result.script)
          await loadState(job.name === "AI Workflow")
          if (job.name === "B1 Kokoro Voice") {
            setToast("Đã tạo voice xong. Sang bước Prompt để tạo prompt cho từng câu trước khi tìm ảnh.")
          } else if (job.name === "AI Workflow") {
            setToast("Đã tạo kịch bản. Hãy kiểm tra và chỉnh sửa nếu cần.")
          } else {
            setToast(`${job.name} đã hoàn thành`)
          }
          if (job.name === "B2 Phan tich canh") goStep("step2b")
          if (job.name === "B2+B3 Chia canh va tim media") goStep("step3b")
          if (job.name === "B3 Tim anh") goStep("step3b")
          if (job.name === "B2 Phan tich nhan vat") loadPromptAnalysis().catch(() => {})
          if (job.name === "B2 Tao prompt") loadState(true).catch(() => {})
          setBusyAction("")
        } else if (job.status === "cancelled") {
          clearInterval(timer)
          setActiveJob(null)
          setBusyAction("")
          await loadState(true)
          setToast(`${job.name} đã dừng`)
        } else if (job.status === "failed") {
          clearInterval(timer)
          setError(job.error || "Tác vụ thất bại")
          setBusyAction("")
        }
      } catch (err) {
        clearInterval(timer)
        const message = String(err?.message || "")
        if (message.includes("Không tìm thấy tác vụ") || message.includes("Khong tim thay tac vu") || message.includes("HTTP 404")) {
          setActiveJob(null)
          setLogs([])
          setBusyAction("")
          loadState(true).catch(() => {})
          return
        }
        setError(message)
        setBusyAction("")
      }
    }, 900)
    return () => clearInterval(timer)
  }, [activeJob?.id, activeJob?.status, loadState, goStep])

  useEffect(() => {
    const container = logContainerRef.current
    if (container && followLogs) container.scrollTop = container.scrollHeight
  }, [logs, followLogs])

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(""), 2800)
    return () => clearTimeout(timer)
  }, [toast])

  const refreshVoices = useCallback(async (language = settings.text_to_voice_language || "en") => {
    try {
      const safeLanguage = normalizeVoiceLanguage(language)
      const data = await api(`/api/voices?language=${encodeURIComponent(safeLanguage)}`)
      const options = data.options?.length ? data.options : [{ value: "af_heart", label: "af_heart" }]
      setVoiceOptions(options)
      if (data.warning) setToast(data.warning)
      if (!options.some((item) => item.value === settings.text_to_voice_voice)) {
        setSettings((current) => ({ ...current, text_to_voice_voice: options[0]?.value || "af_heart" }))
      }
      return options
    } catch (err) {
      setError(err.message)
      return []
    }
  }, [settings.text_to_voice_language, settings.text_to_voice_voice])

  useEffect(() => {
    refreshVoices(settings.text_to_voice_language || "en")
  }, [settings.text_to_voice_language])

  useEffect(() => {
    if (lightboxIndex === null) return
    const onKey = (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        for (let i = lightboxIndex + 1; i < assets.length; i++) {
          if (assets[i].local_path) { setLightboxIndex(i); break }
        }
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        for (let i = lightboxIndex - 1; i >= 0; i--) {
          if (assets[i].local_path) { setLightboxIndex(i); break }
        }
      } else if (e.key === "Escape") {
        setLightboxIndex(null)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [lightboxIndex, assets])
  const assetJobs = useMemo(
    () => new Map(
      liveJobs
        .filter((job) => job.asset_id && ["queued", "running"].includes(job.status))
        .map((job) => [job.asset_id, job]),
    ),
    [liveJobs],
  )
  const isBusy = activeJob && ["queued", "running"].includes(activeJob.status)
  const lightboxAsset = lightboxIndex !== null ? assets[lightboxIndex] ?? null : null
  const scriptSaved = Boolean(project) && script.trim() === String(project?.script || "").trim()
  const completedSteps = useMemo(() => {
    const allDownloaded = assets.length > 0 && assets.every((item) => Boolean(item.local_path))
    const allApproved = assets.length > 0 && assets.every((item) => item.status === "approved")
    return [
      scriptSaved,
      scriptSaved && Boolean(project?.has_voice),
      Boolean(project?.has_scenes) && allDownloaded && allApproved,
      Boolean(project?.has_capcut_export),
    ]
  }, [project, assets, scriptSaved])

  // Per-step status that distinguishes "todo" (never made) from "stale" (made
  // but invalidated by an upstream edit — needs redo). Drives the StepsBar so a
  // script change reopens the later steps for regeneration instead of dead-ending.
  // Values: "done" | "progress" | "stale" | "dirty" | "todo".
  const stepStates = useMemo(() => {
    const allDownloaded = assets.length > 0 && assets.every((item) => Boolean(item.local_path))
    const allApproved = assets.length > 0 && assets.every((item) => item.status === "approved")
    const voiceExists = Boolean(project?.voice_exists)
    const scenesExist = Boolean(project?.scenes_exist)
    const exportExists = Boolean(project?.export_exists)
    const step1 = !project ? "todo" : scriptSaved ? "done" : (script.trim() ? "dirty" : "todo")
    const step2 = project?.has_voice ? "done" : voiceExists ? "stale" : "todo"
    // Prompt stage: "done" once the AI prompts/manifest exist for the current voice.
    const step2b = project?.has_scenes ? "done" : scenesExist ? "stale" : "todo"
    const scenesDone = Boolean(project?.has_scenes) && allDownloaded && allApproved
    const step3a = scenesDone ? "done" : project?.has_scenes ? "progress" : scenesExist ? "stale" : "todo"
    const step4 = project?.has_capcut_export ? "done" : exportExists ? "stale" : "todo"
    return { step1, step2, step2b, step3a, step4 }
  }, [project, assets, script, scriptSaved])

  // True while the Step 1 script box holds unsaved edits.
  const scriptDirty = Boolean(project) && script.trim().length > 0 && !scriptSaved
  // Navigation that warns before abandoning unsaved Step 1 edits.
  const [pendingStep, setPendingStep] = useState(null)
  const guardedGoStep = useCallback((step) => {
    if (activeScreen === "step1" && scriptDirty) { setPendingStep(step); return }
    goStep(step)
  }, [activeScreen, scriptDirty, goStep])

  const userProgress = useMemo(() => {
    return buildUserProgress({
      activeScreen,
      activeJob,
      busyAction,
      logs,
      project,
      assets,
      script,
      completedSteps,
    })
  }, [activeScreen, activeJob, busyAction, logs, project, assets, script, completedSteps])

  const filteredAssets = useMemo(() => {
    const categoryOf = (item) => {
      if (assetJobs.has(item.asset_id)) return "processing"
      if (item.status === "error" || item.status === "failed" || Boolean(item.error)) return "error"
      if (!item.local_path) return "missing"
      if (item.status === "approved") return "approved"
      return "review"
    }
    if (assetFilter !== "all") return assets.filter((item) => categoryOf(item) === assetFilter)
    return assets
  }, [assets, assetFilter, assetJobs])

  async function startJob(path, body, action) {
    setError("")
    const isAssetRetry = action.startsWith("retry-")
    if (!isAssetRetry) setBusyAction(action)
    try {
      const data = await api(path, {
        method: "POST",
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      const latest = await loadState(true)
      if (!latest.active_job) {
        setActiveJob(data.job)
        setLogs(data.job?.logs || [])
      }
      setFollowLogs(true)
      if (isAssetRetry && data.job?.status === "queued") {
        setToast(`${data.job.asset_id} đã vào hàng đợi, vị trí #${data.job.queue_position}`)
      }
    } catch (err) {
      setError(err.message)
      if (!isAssetRetry) setBusyAction("")
    }
  }

  async function bulkRetryAssets(assetIds) {
    if (!assetIds.length) return
    setError("")
    try {
      await Promise.all(assetIds.map(id => api(`/api/assets/${id}/retry`, { method: "POST" })))
      const latest = await loadState(true)
      if (!latest.active_job) setFollowLogs(true)
      setToast(`Đã đưa ${assetIds.length} asset vào hàng đợi`)
    } catch (err) {
      setError(err.message)
    }
  }

  async function saveSettings(close = true) {
    try {
      const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: { ...settings, script_workflow_input: workflowInput, script_workflow_steps: workflowSteps } }) })
      setSettings(data.settings)
      settingsSnapshot.current = { settings: data.settings, workflowSteps, workflowInput }
      if (close) setSettingsOpen(false)
      setToast("Đã lưu cài đặt")
    } catch (err) {
      setError(err.message)
    }
  }

  function workflowPresets() {
    return Array.isArray(settings.workflow_presets) ? settings.workflow_presets.map(repairWorkflowPreset) : []
  }

  async function applyWorkflowPreset(id) {
    const preset = workflowPresets().find((item) => item.id === id)
    if (!preset) return
    const steps = preset.steps?.length ? preset.steps : defaultSteps
    setWorkflowSteps(steps)
    setSettings((current) => ({ ...current, active_workflow_id: id, script_workflow_steps: steps }))
    try {
      const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: { active_workflow_id: id, script_workflow_steps: steps } }) })
      setSettings(data.settings)
      settingsSnapshot.current = { settings: data.settings, workflowSteps: steps, workflowInput }
      setToast(`Đã chọn flow: ${preset.name}`)
    } catch (err) {
      setError(err.message)
    }
  }

  async function uploadTxtFile(file) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith(".txt")) return setError("Chỉ nhận file .txt.")
    const text = await file.text()
    setScript(text)
    setToast("Đã đưa nội dung file TXT vào ô script")
  }

  async function createProject() {
    if (!script.trim()) return setError("Hãy nhập script trước khi tạo project.")
    try {
      const seriesPath = activeSeries?.is_virtual ? "" : (activeSeries?.path || "")
      const data = await api("/api/projects", { method: "POST", body: JSON.stringify({ title, script, category: projectCategory, series_path: seriesPath, flow_id: activeFlowId || "" }) })
      setState((current) => ({ ...current, project: data.project }))
      setTitle(data.project.name)
      setToast("Đã lưu nội dung. Bước tiếp theo: tạo giọng đọc.")
      if (subtitleSegments.length) await persistSubtitle(subtitleSegments)
      const latest = await loadState()
      // The new project now exists in state.projects — navigate to its step2 URL.
      const slug = pathToVideoSlug(data.project.path, latest?.projects || [])
      if (slug) navigate(videoStepPath(slug, "step2"))
    } catch (err) {
      setError(err.message)
    }
  }

  // Persist the Step 1 script without navigating. Returns the updated project
  // (or null on failure) so callers decide where to go next.
  async function persistScript() {
    const data = await api("/api/projects/script", { method: "POST", body: JSON.stringify({ script }) })
    setState((current) => ({ ...current, project: data.project }))
    return data.project
  }

  // Ghi phụ đề canonical (subtitle.json + subtitle.srt). Trả project đã cập nhật.
  async function persistSubtitle(segments) {
    const data = await api("/api/projects/subtitle", { method: "POST", body: JSON.stringify({ segments }) })
    setState((current) => ({ ...current, project: data.project }))
    setSubtitleSegments(data.project.subtitle_segments || [])
    return data.project
  }

  async function saveScriptStep() {
    if (!script.trim()) return setError("Hãy nhập script trước khi lưu B1.")
    if (!project) return createProject()
    try {
      const updated = await persistScript()
      if (subtitleSegments.length) await persistSubtitle(subtitleSegments)
      const wasComplete = project?.voice_exists || project?.scenes_exist || project?.export_exists
      const nowStale = wasComplete && !updated.has_voice
      setToast(nowStale
        ? "Đã lưu kịch bản mới. Hãy tạo lại giọng đọc cho khớp nội dung."
        : "Đã lưu nội dung. Bước tiếp theo: tạo giọng đọc.")
      // Navigate via the currently-open video's slug (robust) and fall back to a
      // freshly-resolved slug so the jump to Giọng đọc never silently no-ops.
      if (currentVideoSlug) {
        goStep("step2")
      } else {
        const slug = pathToVideoSlug(updated.path, state?.projects || [])
        navigate(slug ? videoStepPath(slug, "step2") : "/")
      }
    } catch (err) {
      setError(err.message)
    }
  }

  // Open a project into React/backend state WITHOUT navigating. Returns the
  // opened project object so callers can decide where (if anywhere) to navigate.
  // Switching to a different project here will bestEffortCancel the previous one;
  // callers that must preserve a running job (same-video reload) must avoid
  // calling this when the project is already open.
  async function loadProjectIntoState(path, { notify = true } = {}) {
    await bestEffortCancel(true)
    const data = await api("/api/projects/open", { method: "POST", body: JSON.stringify({ path }) })
    setState((current) => ({ ...current, project: data.project }))
    setActiveJob(null)
    setLogs([])
    setScript(data.project.script)
    setSubtitleSegments(data.project.subtitle_segments || [])
    setTitle(data.project.name)
    setProjectsOpen(false)
    if (notify) setToast("Đã mở video")
    const cat = data.project?.category
    if (cat) {
      const found = series.find(s => s.title === cat && !s.is_virtual)
      if (found) setActiveSeries(found)
      else setActiveSeries({ path: "", title: cat, is_virtual: false, description: "", settings_overrides: {}, video_count: 0, latest_updated_at: 0, videos: [] })
    }
    loadPromptAnalysis().catch(() => {})
    return data.project
  }
  // Keep the ref pointing at the latest closure so restoration effects can call
  // loadProjectIntoState without taking it as a (per-render-unstable) dependency.
  loadProjectIntoStateRef.current = loadProjectIntoState

  async function openProject(path) {
    try {
      const opened = await loadProjectIntoState(path)
      const slug = pathToVideoSlug(opened.path, state?.projects || [])
      navigate(slug ? videoStepPath(slug, nextScreenForProject(opened)) : "/")
    } catch (err) {
      setError(err.message)
    }
  }

  async function goHomeAndStopProject() {
    await bestEffortCancel(true)
    setState((current) => ({ ...(current || {}), project: null, active_job: null, queued_jobs: [], jobs: [] }))
    setActiveJob(null)
    setBusyAction("")
    setLogs([])
    setScript("")
    setTitle("")
    setVoicePreviewUrl("")
    setLightboxIndex(null)
    setActiveSeries(null)
    navigate("/")
    setToast("Đã dừng tác vụ và thoát video hiện tại")
  }

  async function startVideoInSeries(seriesItem) {
    await bestEffortCancel(true)
    setState((current) => ({ ...(current || {}), project: null, active_job: null, queued_jobs: [], jobs: [] }))
    setActiveJob(null)
    setBusyAction("")
    setScript("")
    setTitle("")
    setWorkflowInput("")
    setProjectCategory(seriesItem?.is_virtual ? "" : (seriesItem?.title || ""))
    setLogs([])
    setError("")
    setToast("")
    setVoicePreviewUrl("")
    setLightboxIndex(null)
    setEditingAssetId(null)
    setEditingKeywordValue("")
    setAssetFilter("all")
    setPreflight(null)
    setActiveSeries(seriesItem)
    setActiveFlowId(seriesItem?.default_flow_id || flows[0]?.id || null)
    const slug = pathToSeriesSlug(seriesItem?.path, series)
    navigate(slug ? `/du-an/${slug}/tao-video` : "/")
  }

  async function startNewVideo() {
    if (!activeSeries) return navigate("/")
    await startVideoInSeries(activeSeries)
  }

  async function createSeries(title, description = "", defaultFlowId = "") {
    const data = await api("/api/series", { method: "POST", body: JSON.stringify({ title, description, default_flow_id: defaultFlowId || "" }) })
    await loadState(true)
    return data.series
  }

  async function deleteSeries(path) {
    try {
      await api("/api/series", { method: "DELETE", body: JSON.stringify({ path }) })
      if (activeSeries?.path === path) setActiveSeries(null)
      navigate("/")
      await loadState(true)
    } catch (err) {
      setError(err.message)
    }
  }

  async function updateSeriesInfo(path, title, description, defaultFlowId) {
    const body = { path }
    if (title !== null && title !== undefined) body.title = title
    if (description !== null && description !== undefined) body.description = description
    if (defaultFlowId !== null && defaultFlowId !== undefined) body.default_flow_id = defaultFlowId
    const data = await api("/api/series", { method: "PATCH", body: JSON.stringify(body) })
    setActiveSeries(current => current?.path === path ? data.series : current)
    await loadState(true)
    return data.series
  }

  async function createFlow(name, description, steps) {
    const data = await api("/api/flows", { method: "POST", body: JSON.stringify({ name, description, steps }) })
    setFlows(data.flows)
    return data.flow
  }

  async function updateFlow(id, patch) {
    const data = await api("/api/flows", { method: "PATCH", body: JSON.stringify({ id, ...patch }) })
    setFlows(data.flows)
  }

  async function deleteFlow(id) {
    const data = await api("/api/flows", { method: "DELETE", body: JSON.stringify({ id }) })
    setFlows(data.flows)
    if (activeFlowId === id) setActiveFlowId(data.flows[0]?.id || null)
  }

  async function applyBeginnerVoicePreset() {
    const language = looksLikeEnglish(script) ? "en" : normalizeVoiceLanguage(settings.text_to_voice_language || "en")
    const options = await refreshVoices(language)
    const preferredVoice = options?.find((voice) => /heart|bella|sarah|michael/i.test(voice.value || voice.label)) || options?.[0]
    const nextSettings = {
      ...settings,
      text_to_voice_language: language,
      text_to_voice_voice: preferredVoice?.value || settings.text_to_voice_voice || "af_heart",
      text_to_voice_delivery: "natural",
      text_to_voice_speed: 1,
      voice_clone_enabled: false,
      voice_clone_reference_path: "",
      voice_clone_reference_name: "",
      voice_clone_preview_url: "",
    }
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: nextSettings }) })
    setSettings(data.settings)
    setToast("Đã chọn cấu hình dễ nhất: giọng thường ổn định, tốc độ 1.0.")
  }

  async function renameProject(path, title) {
    if (!title || !title.trim()) return
    try {
      const data = await api("/api/projects/rename", { method: "POST", body: JSON.stringify({ path, title }) })
      if (project?.path === path) {
        setState((current) => ({ ...current, project: data.project }))
        setTitle(data.project.name)
      }
      await loadState(true)
      setToast("Đã đổi tên video")
    } catch (err) {
      setError(err.message)
    }
  }

  async function deleteProject(path, name) {
    try {
      await api("/api/projects/delete", { method: "POST", body: JSON.stringify({ path }) })
      if (project?.path === path) {
        setState((current) => ({ ...(current || {}), project: null }))
        // The open video was deleted — leave the step screens. Go back to its
        // series detail if one is active, otherwise the dashboard.
        navigate(activeSeriesSlug ? seriesPath(activeSeriesSlug) : "/")
      }
      await loadState(true)
      setToast("Đã xóa video")
    } catch (err) {
      setError(err.message)
    }
  }

  async function approveAsset(assetId) {
    try {
      const data = await api(`/api/assets/${assetId}/approve`, { method: "POST" })
      setState((current) => ({ ...current, project: data.project }))
    } catch (err) {
      setError(err.message)
    }
  }

  async function approveAllAssets() {
    try {
      const data = await api("/api/assets/approve-all", { method: "POST" })
      setState((current) => ({ ...current, project: data.project }))
      setToast("Đã duyệt tất cả media đã tải")
    } catch (err) {
      setError(err.message)
    }
  }

  async function saveKeyword(assetId, keyword) {
    try {
      const data = await api(`/api/assets/${assetId}/keyword`, { method: "POST", body: JSON.stringify({ keyword }) })
      setState((current) => ({ ...current, project: data.project }))
      setEditingAssetId(null)
      setToast("Đã cập nhật keyword")
    } catch (err) {
      setError(err.message)
    }
  }

  const loadPromptAnalysis = useCallback(async () => {
    try {
      const data = await api("/api/prompt-analysis")
      setPromptAnalysis(data.analysis && Object.keys(data.analysis).length ? data.analysis : null)
    } catch { /* ignore */ }
  }, [])

  async function savePromptAnalysis(next) {
    const data = await api("/api/prompt-analysis", { method: "POST", body: JSON.stringify({ analysis: next }) })
    setPromptAnalysis(data.analysis)
    return data.analysis
  }

  async function saveAssetPrompt(assetId, prompt) {
    const data = await api(`/api/assets/${assetId}/prompt`, { method: "POST", body: JSON.stringify({ prompt }) })
    setState((current) => ({ ...current, project: data.project }))
  }

  async function uploadAssetMedia(assetId, file) {
    if (!file) return
    setError("")
    try {
      const form = new FormData()
      form.append("file", file)
      const response = await fetch(`/api/assets/${assetId}/upload`, { method: "POST", body: form })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
      setState((current) => ({ ...current, project: data.project }))
      setToast("Đã thay media cho cảnh")
    } catch (err) {
      setError(err.message)
    }
  }

  function chooseAssetMedia(assetId) {
    const input = document.createElement("input")
    input.type = "file"
    input.accept = "image/*,video/*"
    input.onchange = () => uploadAssetMedia(assetId, input.files?.[0])
    input.click()
  }

  async function uploadVoiceCloneReference(file, meta = {}) {
    if (!file) return
    setError("")
    try {
      const form = new FormData()
      form.append("file", file)
      form.append("name", meta.name || "")
      form.append("language", meta.language || "")
      form.append("country", "")
      form.append("set_default", meta.setDefault ? "true" : "false")
      const response = await fetch("/api/voice-clone/reference", { method: "POST", body: form })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`)
      const latest = await loadState(true)
      setSettings(latest.settings || data.settings || {})
      setToast(`Đã lưu giọng clone: ${data.reference_name}`)
      return latest.settings || data.settings || {}
    } catch (err) {
      setError(err.message)
      throw err
    }
  }

  async function selectSavedCloneVoice(profile, makeDefault = false) {
    if (!profile) return
    const profiles = Array.isArray(settings.voice_clone_profiles) ? settings.voice_clone_profiles : []
    const profileLanguage = normalizeVoiceLanguage(profile.language || settings.text_to_voice_language || "vi")
    const payload = {
      text_to_voice_language: profileLanguage,
      voice_clone_enabled: true,
      voice_clone_engine: "magicvoice",
      voice_clone_reference_path: profile.path || "",
      voice_clone_reference_name: profile.name || profile.file_name || "Giọng clone",
      voice_clone_preview_url: profile.preview_url || "",
      voice_clone_profiles: profiles,
      voice_clone_default_id: makeDefault ? profile.id : (settings.voice_clone_default_id || ""),
    }
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: payload }) })
    setSettings(data.settings)
    if (makeDefault) setToast(`Đã đặt mặc định: ${payload.voice_clone_reference_name}`)
  }

  async function deleteVoiceClone(profileId) {
    if (!profileId) return
    try {
      const data = await api(`/api/voice-clone/${profileId}`, { method: "DELETE" })
      const latest = await loadState(true)
      setSettings(latest.settings || data.settings || {})
      setToast("Đã xóa giọng clone")
    } catch (err) {
      setError(err.message)
    }
  }

  async function runPreflight() {
    setPreflightBusy(true)
    try {
      const data = await api("/api/preflight")
      setPreflight(data)
      setToast(data.ok ? "Kiểm tra xong: cấu hình ổn" : "Kiểm tra xong: có mục cần sửa")
    } catch (err) {
      setError(err.message)
    } finally {
      setPreflightBusy(false)
    }
  }

  async function createVoiceWithQuickSettings() {
    setError("")
    try {
      const voiceIsRunning = Boolean(activeJob && ["queued", "running"].includes(activeJob.status) && inferActionFromJob(activeJob) === "voice")
      if (voiceIsRunning) {
        setToast("Đang dừng bản voice cũ để tạo lại bằng giọng mới...")
        await api("/api/jobs/cancel", { method: "POST" })
        const deadline = Date.now() + 45000
        while (Date.now() < deadline) {
          const current = await api(`/api/jobs/${activeJob.id}`).catch(() => ({ job: null }))
          if (!current.job || !["queued", "running"].includes(current.job.status)) break
          await new Promise((resolve) => setTimeout(resolve, 300))
        }
        const latest = await loadState(true)
        if (latest.active_job) throw new Error("Voice cũ vẫn đang dừng. Hãy đợi vài giây rồi bấm Tạo lại.")
        setActiveJob(null)
        setLogs([])
        setBusyAction("")
      } else if (isBusy) {
        throw new Error("Một bước khác đang chạy. Hãy dừng hoặc chờ bước đó hoàn thành trước khi tạo lại voice.")
      }
      setVoicePreviewUrl("")
      const voiceLanguage = normalizeVoiceLanguage(settings.text_to_voice_language || "en")
      const hasCloneReference = Boolean(settings.voice_clone_reference_path)
      const voiceSettings = {
        text_to_voice_language: voiceLanguage,
        text_to_voice_voice: settings.text_to_voice_voice || "af_heart",
        text_to_voice_delivery: settings.text_to_voice_delivery || "natural",
        text_to_voice_speed: Number(settings.text_to_voice_speed || 1),
        voice_clone_enabled: hasCloneReference,
        voice_clone_engine: settings.voice_clone_engine || "magicvoice",
        voice_clone_reference_path: settings.voice_clone_reference_path || "",
        voice_clone_reference_name: settings.voice_clone_reference_name || "",
        voice_clone_preview_url: settings.voice_clone_preview_url || "",
        magicvoice_steps: Math.max(8, Math.min(16, Number(settings.magicvoice_steps || 16))),
        magicvoice_sentence_pause: Number(settings.magicvoice_sentence_pause || 0.28),
        magicvoice_clause_pause: Number(settings.magicvoice_clause_pause || 0.12),
        magicvoice_paragraph_pause: Number(settings.magicvoice_paragraph_pause || 0.43),
        magicvoice_clarity_speed: Number(settings.magicvoice_clarity_speed || 0.96),
      }
      const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: voiceSettings }) })
      setSettings(data.settings)
      await startJob("/api/voice", { script }, "voice")
    } catch (err) {
      setError(err.message)
    }
  }

  async function previewVoiceNow(settingsOverride = null, textOverride = "") {
    try {
      setVoicePreviewBusy(true)
      setVoicePreviewUrl("")
      const sourceSettings = settingsOverride && !settingsOverride?.nativeEvent ? settingsOverride : settings
      if (!textOverride && sourceSettings.voice_clone_enabled && sourceSettings.voice_clone_preview_url) {
        setVoicePreviewUrl(`${sourceSettings.voice_clone_preview_url}${sourceSettings.voice_clone_preview_url.includes("?") ? "&" : "?"}v=${Date.now()}`)
        return { url: sourceSettings.voice_clone_preview_url, cached: true }
      }
      const voiceLanguage = normalizeVoiceLanguage(sourceSettings.text_to_voice_language || "en")
      const safeSettings = {
        ...sourceSettings,
        text_to_voice_language: voiceLanguage,
      }
      const data = await api("/api/voice-preview", {
        method: "POST",
        body: JSON.stringify({
          settings: safeSettings,
          text: textOverride || "",
        }),
      })
      if (data.warning) setToast(data.warning)
      setVoicePreviewUrl(`${data.url}${data.url?.includes("?") ? "&" : "?"}v=${Date.now()}`)
      if (!textOverride && data.url && sourceSettings.voice_clone_enabled && sourceSettings.voice_clone_reference_path) {
        const profiles = Array.isArray(sourceSettings.voice_clone_profiles) ? sourceSettings.voice_clone_profiles : []
        const nextProfiles = profiles.map((item) => item.path === sourceSettings.voice_clone_reference_path ? { ...item, preview_url: data.url } : item)
        const saved = await api("/api/settings", {
          method: "POST",
          body: JSON.stringify({ settings: { ...sourceSettings, voice_clone_profiles: nextProfiles, voice_clone_preview_url: data.url } }),
        })
        setSettings(saved.settings)
      }
      return data
    } catch (err) {
      setError(err.message)
    } finally {
      setVoicePreviewBusy(false)
    }
  }


  const flowSteps = [
    { code: "1", label: "Nội dung", hint: "Nhập chủ đề hoặc kịch bản", icon: FileText },
    { code: "2", label: "Giọng đọc", hint: "Chọn giọng, clone, tạo voice", icon: FileAudio },
    { code: "3", label: "Hình ảnh", hint: "Phân cảnh, tìm và duyệt media", icon: Image },
    { code: "4", label: "Xuất CapCut", hint: "Kiểm tra và mở project", icon: Rocket },
  ]

  const currentStepIndex = activeScreen === "step1" ? 0 : activeScreen === "step2" ? 1 : (activeScreen === "step2b" || activeScreen === "step3a" || activeScreen === "step3b") ? 2 : activeScreen === "step4" ? 3 : 0

  if (!state) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#131315] text-zinc-300">
        <LoaderCircle className="mr-3 h-5 w-5 animate-spin text-violet-300" /> Đang khởi động...
      </div>
    )
  }

  const stepCards = [
    { id: "step1", title: "Nội dung", desc: "Nhập chủ đề hoặc kịch bản", icon: FileText },
    { id: "step2", title: "Giọng đọc", desc: "Chọn giọng phù hợp", icon: FileAudio },
    { id: "step3a", title: "Hình ảnh", desc: "Phân cảnh và duyệt media", icon: Image },
    { id: "step4", title: "Xuất CapCut", desc: "Kiểm tra và mở project", icon: Rocket },
  ]
  const missingAiApiKey = ![settings.kiro_api_key, settings.claude_api_key, settings.gemini_api_key, settings.openai_api_key].some((value) => String(value || "").trim())
  const showApiKeyNotice = missingAiApiKey && !apiKeyNoticeDismissed && !settingsOpen
  const preflightChecks = preflight?.checks || []
  const readyChecks = preflightChecks.filter((item) => item.ok).length
  const allReady = preflightChecks.length > 0 && readyChecks === preflightChecks.length

  return (
    <div className="stitch-app min-h-screen overflow-hidden bg-[#131315] text-[#e5e1e4]">
      <div className="aurora-bg"><div className="aurora-blob-1" /><div className="aurora-blob-2" /></div>
      <ParticleCanvas />
      <header className="stitch-topbar">
        {activeScreen !== "dashboard" && (
          <button className="back-home-button" onClick={goHomeAndStopProject} title="Quay lại trang chủ">
            <ArrowLeft className="h-4 w-4" />
          </button>
        )}
        <button className="flex items-center gap-2 flex-shrink-0" onClick={() => activeScreen !== "dashboard" && goHomeAndStopProject()}>
          <div className="logo-mark"><WandSparkles className="h-4 w-4" /></div>
          <span className="text-[15px] font-bold text-white">CONTENT <span className="text-emerald-300">AUTOMATION</span></span>
        </button>
        {["step1","step2","step3a","step3b","step4"].includes(activeScreen) && (
          <div className="topbar-breadcrumb">
            {activeSeries && <>
              <button className="topbar-breadcrumb-item" onClick={() => activeSeriesSlug && navigate(seriesPath(activeSeriesSlug))}>
                <FolderOpen className="h-3.5 w-3.5 flex-shrink-0" />
                <span>{activeSeries.title}</span>
              </button>
              <ChevronRight className="h-3 w-3 text-zinc-600 flex-shrink-0" />
            </>}
            <button className="topbar-breadcrumb-item" onClick={() => setProjectsOpen(true)}>
              <Film className="h-3.5 w-3.5 flex-shrink-0" />
              <span>{project?.name || "Video mới"}</span>
            </button>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <button className="icon-action" aria-label="Kho Flow" onClick={() => setFlowsOpen(true)} title="Kho Flow"><Layers className="h-4 w-4" /></button>
          <button className="icon-action" aria-label="Trợ giúp" onClick={() => setHelpOpen(true)}><Bot className="h-4 w-4" /></button>
          <button className="icon-action" aria-label="Cài đặt" onClick={() => setSettingsOpen(true)}><Settings className="h-4 w-4" /></button>
          <div className="avatar-dot">L</div>
        </div>
      </header>

      {["step1", "step2", "step2b", "step3a", "step3b", "step4"].includes(activeScreen) && (
        <StepsBar
          activeScreen={activeScreen}
          goStep={guardedGoStep}
          stepStates={stepStates}
          project={project}
        />
      )}

      <Dialog open={Boolean(pendingStep)} onOpenChange={(open) => !open && setPendingStep(null)}>
        <DialogContent className="max-w-md">
          <DialogTitle>Lưu thay đổi kịch bản?</DialogTitle>
          <DialogDescription>Bạn đã sửa kịch bản nhưng chưa lưu. Rời đi mà không lưu sẽ mất các thay đổi này.</DialogDescription>
          <div className="dialog-actions">
            <Button variant="ghost" onClick={() => setPendingStep(null)}>Ở lại Bước 1</Button>
            <Button variant="secondary" onClick={() => { const t = pendingStep; setPendingStep(null); setScript(String(project?.script || "")); goStep(t) }}>Bỏ thay đổi</Button>
            <Button onClick={async () => { const t = pendingStep; setPendingStep(null); try { await persistScript() } catch (e) { setError(e.message); return } goStep(t) }}>Lưu rồi đi</Button>
          </div>
        </DialogContent>
      </Dialog>
      {activeScreen === "dashboard" ? (
        <DashboardScreen
          series={series}
          allReady={allReady}
          runPreflight={runPreflight}
          preflightChecks={preflightChecks}
          onOpenSeries={(s) => {
            setActiveSeries(s)
            const slug = pathToSeriesSlug(s?.path, series)
            navigate(slug ? seriesPath(slug) : "/")
          }}
          onCreateSeries={createSeries}
          flows={flows}
          setError={setError}
        />
      ) : activeScreen === "project" ? (
        <ProjectDetailScreen
          activeSeries={activeSeries}
          allProjects={state?.projects || []}
          onBack={() => navigate("/")}
          onOpenVideo={(path) => openProject(path)}
          onNewVideo={() => startVideoInSeries(activeSeries)}
          onDeleteSeries={deleteSeries}
          onDeleteVideo={deleteProject}
          onUpdateSeries={updateSeriesInfo}
          setError={setError}
          flows={flows}
        />
      ) : (
        <main className="stitch-workspace">
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
            startJob={startJob}
            projectCategory={projectCategory}
            setProjectCategory={setProjectCategory}
            categoryLocked={!!activeSeries && !activeSeries.is_virtual}
            categories={state.categories || []}
            settings={settings}
            flows={flows}
            activeFlowId={activeFlowId}
            setActiveFlowId={setActiveFlowId}
            setFlowsOpen={setFlowsOpen}
            busyAction={busyAction}
            activeJob={activeJob}
            staleWarning={scriptDirty && Boolean(project?.voice_exists || project?.scenes_exist || project?.export_exists)}
            subtitleSegments={subtitleSegments}
            setSubtitleSegments={setSubtitleSegments}
            persistSubtitle={persistSubtitle}
            hasSubtitle={Boolean(project?.has_subtitle)}
          />}
          {activeScreen === "step2" && <VoiceScreen script={script} project={project} settings={settings} setSettings={setSettings} voiceOptions={voiceOptions} refreshVoices={refreshVoices} previewVoiceNow={previewVoiceNow} voicePreviewBusy={voicePreviewBusy} voicePreviewUrl={voicePreviewUrl} createVoiceWithQuickSettings={createVoiceWithQuickSettings} startJob={startJob} applyBeginnerVoicePreset={applyBeginnerVoicePreset} saveCloneVoice={uploadVoiceCloneReference} selectSavedCloneVoice={selectSavedCloneVoice} deleteVoiceClone={deleteVoiceClone} isBusy={isBusy} busyAction={busyAction} activeJob={activeJob} goStep={goStep} userProgress={userProgress} />}
          {activeScreen === "step2b" && <PromptScreen assets={assets} project={project} startJob={startJob} isBusy={isBusy} busyAction={busyAction} goStep={goStep} saveKeyword={saveKeyword} userProgress={userProgress} promptAnalysis={promptAnalysis} savePromptAnalysis={savePromptAnalysis} saveAssetPrompt={saveAssetPrompt} loadPromptAnalysis={loadPromptAnalysis} />}
          {activeScreen === "step3a" && <SceneScreen assets={assets} project={project} startJob={startJob} isBusy={isBusy} busyAction={busyAction} goStep={goStep} />}
          {activeScreen === "step3b" && <MediaReviewScreen assets={assets} filteredAssets={filteredAssets} assetFilter={assetFilter} setAssetFilter={setAssetFilter} project={project} assetJobs={assetJobs} statusBadge={statusBadge} setLightboxIndex={setLightboxIndex} startJob={startJob} approveAsset={approveAsset} approveAllAssets={approveAllAssets} chooseAssetMedia={chooseAssetMedia} bulkRetryAssets={bulkRetryAssets} isBusy={isBusy} goStep={goStep} />}
          {activeScreen === "step4" && <ExportScreen project={project} assets={assets} preflight={preflight} runPreflight={runPreflight} startJob={startJob} title={title} isBusy={isBusy} busyAction={busyAction} goStep={goStep} />}
        </main>
      )}

      <SettingsModal open={settingsOpen} onOpenChange={handleSettingsOpenChange} settings={settings} setSettings={setSettings} saveSettings={saveSettings} runPreflight={runPreflight} preflight={preflight} preflightBusy={preflightBusy} />
      <ProjectsModal open={projectsOpen} onOpenChange={setProjectsOpen} state={state} project={project} openProject={openProject} renameProject={renameProject} deleteProject={deleteProject} />
      <HelpModal open={helpOpen} onOpenChange={setHelpOpen} />
      <FlowsModal open={flowsOpen} onClose={() => setFlowsOpen(false)} flows={flows} onCreate={createFlow} onUpdate={updateFlow} onDelete={deleteFlow} />
      <Lightbox open={lightboxIndex !== null} setLightboxIndex={setLightboxIndex} lightboxIndex={lightboxIndex} assets={assets} project={project} lightboxAsset={lightboxAsset} assetJobs={assetJobs} statusBadge={statusBadge} startJob={startJob} approveAsset={approveAsset} chooseAssetMedia={chooseAssetMedia} editingAssetId={editingAssetId} setEditingAssetId={setEditingAssetId} editingKeywordValue={editingKeywordValue} setEditingKeywordValue={setEditingKeywordValue} saveKeyword={saveKeyword} />
      <Dialog open={showApiKeyNotice} onOpenChange={(open) => !open && setApiKeyNoticeDismissed(true)}>
        <DialogContent className="api-key-dialog max-w-xl">
          <div className="api-key-dialog-glow" />
          <div className="api-key-dialog-head">
            <div className="api-key-dialog-icon"><KeyRound className="h-7 w-7" /></div>
            <div>
              <DialogTitle>Thiếu API key AI</DialogTitle>
              <DialogDescription>
                Tool vẫn mở được, nhưng các phần AI như tạo kịch bản, chia cảnh, tạo keyword và kiểm ảnh sẽ không chạy đúng nếu chưa nhập key.
              </DialogDescription>
            </div>
          </div>
          <div className="api-key-dialog-body">
            <div><CheckCircle2 className="h-4 w-4" />Nhập một lần trong Cài đặt, tool sẽ tự lưu cho các lần sau.</div>
            <div><AlertTriangle className="h-4 w-4" />Nếu bỏ qua, người dùng vẫn có thể dán kịch bản thủ công nhưng trải nghiệm AI sẽ bị thiếu.</div>
          </div>
          <div className="api-key-dialog-actions">
            <Button variant="secondary" onClick={() => setApiKeyNoticeDismissed(true)}>Để sau</Button>
            <Button onClick={() => {
              setApiKeyNoticeDismissed(true)
              setSettingsOpen(true)
              setToast("Vào tab AI, dán Kiro, Claude, Gemini hoặc OpenAI API key rồi bấm Lưu cài đặt.")
            }}>
              <Settings className="mr-2 h-4 w-4" /> Nhập API key ngay
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      {error && <div className="toast-error"><XCircle className="h-4 w-4 shrink-0" /><span>{error}</span><button onClick={() => setError("")}>Đóng</button></div>}
      {toast && <div className="toast-ok"><CheckCircle2 className="h-4 w-4" />{toast}</div>}
    </div>
  )
}

function StepsBar({ activeScreen, goStep, stepStates, project }) {
  const steps = [
    { id: "step1", label: "Nội dung" },
    { id: "step2", label: "Giọng đọc" },
    { id: "step2b", label: "Prompt" },
    { id: "step3a", label: "Hình ảnh" },
    { id: "step4", label: "Xuất CapCut" },
  ]
  // A step with existing data (done / in-progress / stale) is always reachable.
  // A "todo" step only unlocks once the previous step is fully done.
  const hasData = (id) => ["done", "progress", "stale"].includes(stepStates[id])

  const isLocked = (id) => {
    const idx = steps.findIndex(s => s.id === id)
    if (idx === 0) return false
    if (hasData(id)) return false
    const isStep3Active = id === "step3a" && (activeScreen === "step3a" || activeScreen === "step3b")
    if (isStep3Active || activeScreen === id) return false
    return stepStates[steps[idx - 1].id] !== "done"
  }

  const goToStep = (id) => {
    if (isLocked(id)) return
    goStep(id === "step3a" ? (project?.has_scenes ? "step3b" : "step3a") : id)
  }

  return (
    <div className="stitch-steps-bar">
      {steps.map((step, idx) => {
        const state = stepStates[step.id]
        const done = state === "done"
        const stale = state === "stale"
        const active = activeScreen === step.id || (step.id === "step3a" && activeScreen === "step3b")
        const locked = isLocked(step.id)
        return (
          <div key={step.id} className="flex items-center">
            {idx > 0 && <span className="step-tab-sep" />}
            <button
              className={cn("step-tab", active && "active", done && !active && "done", stale && !active && "stale", locked && "locked")}
              disabled={locked}
              title={stale ? "Cần làm lại vì kịch bản đã thay đổi" : undefined}
              onClick={() => goToStep(step.id)}
            >
              <span className="step-tab-num">
                {stale && !active ? <RefreshCw className="h-3 w-3" /> : done && !active ? <Check className="h-3 w-3" /> : idx + 1}
              </span>
              {step.label}
              {stale && !active && <span className="step-tab-redo">Cần làm lại</span>}
            </button>
          </div>
        )
      })}
    </div>
  )
}

function StepPill({ index, label, active, done }) {
  return <div className={cn("step-pill", active && "active", done && "done")}><span>{done ? <Check className="h-4 w-4" /> : index + 1}</span><b>{label}</b></div>
}

function buildUserProgress({ activeScreen, activeJob, busyAction, logs, project, assets, script, completedSteps }) {
  const running = Boolean(activeJob && ["queued", "running"].includes(activeJob.status))
  const failed = activeJob?.status === "failed"
  const cancelled = activeJob?.status === "cancelled"
  const action = busyAction || inferActionFromJob(activeJob)
  const downloaded = assets.filter((item) => item.local_path).length
  const approved = assets.filter((item) => item.status === "approved").length
  const total = assets.length
  const latest = normalizeUserLog(logs?.slice(-1)?.[0])
  const percentFromJob = Number(activeJob?.progress ?? activeJob?.percent ?? activeJob?.progress_percent)

  if (failed) {
    return {
      status: "error",
      running: false,
      percent: Math.max(1, estimateBasePercent(activeScreen, project, assets, script, completedSteps)),
      title: "Tác vụ bị lỗi",
      messages: [activeJob?.error || latest || "Có lỗi xảy ra. Hãy đọc thông báo lỗi phía dưới hoặc bấm chạy lại."],
    }
  }

  if (cancelled) {
    return {
      status: "idle",
      running: false,
      percent: Math.max(1, estimateBasePercent(activeScreen, project, assets, script, completedSteps)),
      title: "Tác vụ đã dừng",
      messages: ["Bạn có thể chỉnh lại nội dung hoặc bấm chạy lại bước hiện tại."],
    }
  }

  if (running) {
    const percent = Number.isFinite(percentFromJob)
      ? percentFromJob
      : estimateRunningPercent(action, logs, assets)
    return {
      status: "running",
      running: true,
      percent,
      title: runningTitle(action, activeJob),
      messages: runningMessages(action, logs, assets, latest),
    }
  }

  if (activeScreen === "step1") {
    const hasScript = Boolean(script?.trim())
    return {
      status: completedSteps[0] ? "done" : "idle",
      running: false,
      percent: completedSteps[0] ? 100 : hasScript ? 65 : 0,
      title: completedSteps[0] ? "Nội dung đã sẵn sàng" : hasScript ? "Đã có nội dung, chờ lưu" : "Bắt đầu bằng nội dung",
      messages: completedSteps[0]
        ? ["Kịch bản đã được lưu vào project.", "Bước tiếp theo: chọn giọng và tạo file đọc."]
        : hasScript
          ? ["Bạn đã nhập script. Bấm Lưu nội dung và tiếp tục để sang bước giọng đọc."]
          : ["Dán script hoặc tải file TXT vào ô bên trái.", "Nếu chưa có script, nhập ý tưởng vào Workflow rồi bấm Chạy workflow."],
    }
  }

  if (activeScreen === "step2") {
    return {
      status: project?.has_voice ? "done" : "idle",
      running: false,
      percent: project?.has_voice ? 100 : completedSteps[0] ? 25 : 0,
      title: project?.has_voice ? "Giọng đọc đã tạo xong" : "Chờ tạo giọng đọc",
      messages: project?.has_voice
        ? ["Giọng đọc và mốc thời gian đã có trong project.", "Bước tiếp theo: tạo cảnh và tìm ảnh/video."]
        : ["Chọn đúng ngôn ngữ và giọng đọc.", "Bấm Nghe thử nếu cần, sau đó bấm Tạo giọng đọc."],
    }
  }

  if (activeScreen === "step2b") {
    return {
      status: project?.has_scenes ? "done" : "idle",
      running: false,
      percent: project?.has_scenes ? 100 : project?.has_voice ? 30 : 0,
      title: project?.has_scenes ? "Đã có prompt cho từng câu" : "Chờ tạo prompt",
      messages: project?.has_scenes
        ? [`Đã tạo prompt cho ${total} câu.`, "Sửa lại nếu cần rồi bấm Tìm ảnh theo prompt."]
        : ["AI sẽ đọc toàn bộ kịch bản và tạo prompt tìm hình cho từng câu theo SRT."],
    }
  }

  if (activeScreen === "step3a") {
    return {
      status: project?.has_scenes ? "done" : "idle",
      running: false,
      percent: project?.has_scenes ? 100 : project?.has_voice ? 35 : 0,
      title: project?.has_scenes ? "Đã chia cảnh" : "Chờ phân cảnh",
      messages: project?.has_scenes
        ? [`Đã tạo ${total} cảnh theo lời đọc.`, "Bước tiếp theo: kiểm tra ảnh/video cho từng cảnh."]
        : ["Tool sẽ nghe lại voice, gom các câu cùng ý thành cảnh, rồi tìm ảnh/video phù hợp."],
    }
  }

  if (activeScreen === "step3b") {
    const mediaPercent = total ? Math.round((downloaded / total) * 75 + (approved / total) * 25) : 0
    return {
      status: total && approved === total ? "done" : "idle",
      running: false,
      percent: mediaPercent,
      title: total && approved === total ? "Media đã duyệt đủ" : "Đang kiểm tra media",
      messages: total
        ? [`Đã tải ${downloaded}/${total} ảnh hoặc video.`, `Đã duyệt ${approved}/${total} cảnh.`, "Cảnh nào chưa hợp thì bấm Tìm lại hoặc Tải lên media từ máy."]
        : ["Chưa có cảnh để duyệt. Hãy quay lại Bước 3A để phân cảnh và tìm media."],
    }
  }

  if (activeScreen === "step4") {
    const ready = Boolean(project?.has_voice && total && downloaded === total && approved === total)
    return {
      status: project?.has_capcut_export ? "done" : "idle",
      running: false,
      percent: project?.has_capcut_export ? 100 : ready ? 85 : 35,
      title: project?.has_capcut_export ? "Đã xuất project CapCut" : ready ? "Sẵn sàng xuất CapCut" : "Cần hoàn thiện dữ liệu",
      messages: project?.has_capcut_export
        ? ["Project CapCut đã được tạo. Bạn có thể mở và kiểm tra timeline."]
        : ready
          ? ["Giọng đọc và ảnh/video đã đủ. Bấm Xuất và mở CapCut để tạo project."]
          : ["Cần đủ giọng đọc, cảnh và ảnh/video đã duyệt trước khi xuất."],
    }
  }

  return {
    status: "idle",
    running: false,
    percent: estimateBasePercent(activeScreen, project, assets, script, completedSteps),
    title: "Sẵn sàng",
    messages: ["Chọn một bước và làm theo hướng dẫn trên màn hình."],
  }
}

function inferActionFromJob(job) {
  const name = String(job?.name || "").toLowerCase()
  if (name.includes("workflow")) return "workflow"
  if (name.includes("voice") || name.includes("magic")) return "voice"
  if (name.includes("analyze") || name.includes("search")) return "analyze-search"
  if (name.includes("export") || name.includes("capcut")) return "export"
  if (job?.asset_id) return "retry-asset"
  return ""
}

function estimateBasePercent(activeScreen, project, assets, script, completedSteps) {
  if (activeScreen === "step1") return completedSteps[0] ? 100 : script?.trim() ? 65 : 0
  if (activeScreen === "step2") return project?.has_voice ? 100 : completedSteps[0] ? 25 : 0
  if (activeScreen === "step2b") return project?.has_scenes ? 100 : project?.has_voice ? 30 : 0
  if (activeScreen === "step3a") return project?.has_scenes ? 100 : project?.has_voice ? 35 : 0
  if (activeScreen === "step3b") {
    const total = assets.length
    if (!total) return 0
    const downloaded = assets.filter((item) => item.local_path).length
    const approved = assets.filter((item) => item.status === "approved").length
    return Math.round((downloaded / total) * 75 + (approved / total) * 25)
  }
  if (activeScreen === "step4") return project?.has_capcut_export ? 100 : project?.has_voice ? 60 : 0
  return 0
}

function estimateRunningPercent(action, logs = [], assets = []) {
  const text = logs.join("\n").toLowerCase()
  if (action === "workflow") {
    if (text.includes("script")) return 85
    if (text.includes("outline") || text.includes("dàn")) return 55
    return 25
  }
  if (action === "voice") {
    if (text.includes("whisper") || text.includes("srt")) return 82
    if (text.includes("chunk") || text.includes("wav")) return 55
    return 20
  }
  if (action === "analyze-search") {
    const total = assets.length
    const downloaded = assets.filter((item) => item.local_path).length
    if (total) return Math.max(35, Math.min(95, Math.round((downloaded / total) * 70 + 25)))
    if (text.includes("keyword")) return 45
    if (text.includes("srt") || text.includes("scene")) return 28
    return 15
  }
  if (action === "analyze") {
    if (text.includes("keyword") || text.includes("prompt") || text.includes("từ khóa")) return 60
    if (text.includes("srt") || text.includes("scene") || text.includes("cảnh")) return 30
    return 18
  }
  if (action === "search") {
    const total = assets.length
    const downloaded = assets.filter((item) => item.local_path).length
    if (total) return Math.max(20, Math.min(95, Math.round((downloaded / total) * 90 + 10)))
    return 25
  }
  if (action === "export") {
    if (text.includes("capcut")) return 88
    if (text.includes("timeline")) return 62
    return 22
  }
  if (action?.startsWith("retry") || action === "retry-asset") return 55
  return 35
}

function runningTitle(action, job) {
  if (action === "workflow") return "Đang tạo kịch bản bằng AI"
  if (action === "voice") return "Đang tạo giọng đọc và timing"
  if (action === "analyze-search") return "Đang phân cảnh và tìm media"
  if (action === "analyze") return "Đang tạo prompt cho từng câu"
  if (action === "search") return "Đang tìm ảnh theo prompt"
  if (action === "export") return "Đang xuất project CapCut"
  if (action?.startsWith("retry") || job?.asset_id) return `Đang tìm lại media${job?.asset_id ? ` cho ${job.asset_id}` : ""}`
  return "Đang xử lý"
}

function runningMessages(action, logs = [], assets = [], latest) {
  const messages = []
  const rawText = (logs || []).join(" ").toLowerCase()
  if (action === "workflow") {
    messages.push("AI đang đọc yêu cầu và viết kịch bản cuối.")
    messages.push("Khi xong, nội dung sẽ tự điền vào ô script.")
  } else if (action === "voice") {
    if (rawText.includes("magicvoice") || rawText.includes("clone")) {
      messages.push("Đang tạo giọng đọc bằng giọng clone đã chọn.")
      messages.push("Tool sẽ lưu file voice và căn thời gian lời đọc sau khi tạo xong.")
    } else {
      messages.push("Đang tạo giọng đọc cho script hiện tại.")
      messages.push("Sau khi xong, tool sẽ căn thời gian lời đọc để chia cảnh.")
    }
  } else if (action === "analyze-search") {
    const total = assets.length
    const downloaded = assets.filter((item) => item.local_path).length
    messages.push(total ? `Đang chuẩn bị media cho các cảnh: ${downloaded}/${total} cảnh đã có media.` : "Đang đọc lời thoại để chia cảnh và tạo từ khóa tìm ảnh.")
    messages.push("Khi đủ dữ liệu, tool sẽ chuyển sang màn duyệt hình ảnh.")
  } else if (action === "analyze") {
    messages.push("AI đang đọc toàn bộ kịch bản và tạo prompt tìm hình cho từng câu.")
    messages.push("Khi xong, bạn có thể xem và chỉnh prompt từng câu trước khi tìm ảnh.")
  } else if (action === "search") {
    const total = assets.length
    const downloaded = assets.filter((item) => item.local_path).length
    messages.push(total ? `Đang tải media theo prompt: ${downloaded}/${total} cảnh đã có.` : "Đang tìm ảnh/video theo prompt của từng câu.")
    messages.push("Khi đủ media, tool sẽ chuyển sang màn duyệt hình ảnh.")
  } else if (action === "export") {
    messages.push("Đang gắn voice và hình ảnh vào timeline CapCut.")
    messages.push("Khi xong, project sẽ mở được trong CapCut.")
  } else if (action?.startsWith("retry")) {
    messages.push("Đang tìm media mới cho cảnh đã chọn.")
  } else {
    messages.push("Tool đang chạy tác vụ hiện tại.")
  }
  return messages.slice(0, 2)
}

function normalizeUserLog(line) {
  if (!line) return ""
  const text = String(line).replace(/\s+/g, " ").trim()
  if (!text) return ""
  if (/error|loi|lỗi|failed/i.test(text)) return "Có lỗi khi xử lý. Mở thông báo để xem hướng khắc phục."
  if (/queue|hàng đợi|dang cho|chờ/i.test(text)) return "Tác vụ đã vào hàng đợi, tool sẽ xử lý lần lượt."
  if (/download|tai|tải/i.test(text)) return "Đang tải media phù hợp cho cảnh."
  if (/keyword/i.test(text)) return "Đang chọn từ khóa phù hợp với nội dung từng cảnh."
  if (/srt|whisper|timing/i.test(text)) return "Đang căn lời đọc khớp với thời gian."
  if (/kokoro|magicvoice|text to voice|tts/i.test(text)) return "Đang tạo giọng đọc từ nội dung video."
  if (/capcut|timeline/i.test(text)) return "Đang sắp xếp giọng đọc và media vào project CapCut."
  if (text.length > 120) return `${text.slice(0, 117)}...`
  return text
}

function FlowCard({ icon: Icon, title, desc, accent = "violet", dashed, onClick, cta = "Chọn" }) {
  return <button onClick={onClick} className={cn("flow-card text-left", dashed && "border-dashed")}>
    <div className={cn("flow-icon", accent)}><Icon className="h-5 w-5" /></div><div><b>{title}</b><p>{desc}</p></div><span className="flow-card-cta">{cta}<ArrowRight className="h-3.5 w-3.5" /></span>
  </button>
}

function ScriptStepScreen({ title, setTitle, script, setScript, scriptFileInputRef, uploadTxtFile, saveScriptStep, isBusy, workflowInput, setWorkflowInput, startJob, projectCategory, setProjectCategory, categoryLocked = false, categories = [], settings, flows = [], activeFlowId, setActiveFlowId, setFlowsOpen, busyAction, activeJob, staleWarning = false, subtitleSegments = [], setSubtitleSegments, persistSubtitle, hasSubtitle = false }) {
  const [contentMode, setContentMode] = useState("existing")
  // Live, estimated SRT preview generated from the script text as it is typed.
  // Real timing is recomputed from the TTS audio in Step 2; this only previews
  // how the script will be segmented into subtitles (MagicVoice-style).
  const [srt, setSrt] = useState({ segments: [], words: 0, sentences: 0, duration: 0 })
  const [srtBusy, setSrtBusy] = useState(false)
  const srtLang = normalizeVoiceLanguage(settings.text_to_voice_language || "vi")
  const srtSpeed = Number(settings.text_to_voice_speed || 1)
  useEffect(() => {
    const text = script.trim()
    if (!text) { setSrt({ segments: [], words: 0, sentences: 0, duration: 0 }); setSrtBusy(false); return }
    let cancelled = false
    setSrtBusy(true)
    const timer = setTimeout(async () => {
      try {
        const res = await fetch("/api/script/srt-preview", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ script: text, language: srtLang, speed: srtSpeed }),
        })
        const data = await res.json()
        if (!cancelled) setSrt({ segments: data.segments || [], words: data.words || 0, sentences: data.sentences || 0, duration: data.duration || 0 })
      } catch {
        /* preview is best-effort; ignore errors */
      } finally {
        if (!cancelled) setSrtBusy(false)
      }
    }, 400)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [script, srtLang, srtSpeed])
  // Khi chưa có phụ đề canonical, preview tự động trở thành bản nháp canonical
  // để người dùng chỉnh; sau khi đã chỉnh/lưu thì canonical là nguồn chính.
  useEffect(() => {
    if (!hasSubtitle && !subtitleSegments.some((s) => s.edited) && srt.segments.length) {
      setSubtitleSegments?.(srt.segments.map((s, i) => ({
        index: i + 1, start: s.start, end: s.end, text: s.text, edited: false,
      })))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srt.segments])
  const activeFlow = flows.find(f => f.id === activeFlowId) || flows[0] || null
  const workflowRunning = isBusy && busyAction === "workflow"
  const workflowPercent = Math.max(0, Math.min(100, Math.round(Number(activeJob?.progress || 0))))
  const runWorkflow = () => startJob("/api/workflow", {
    source_input: workflowInput,
    steps: activeFlow?.steps || [],
    settings: { script_workflow_input: workflowInput },
  }, "workflow")

  const rows = subtitleSegments.length ? subtitleSegments : srt.segments.map((s, i) => ({ index: i + 1, start: s.start, end: s.end, text: s.text, edited: false }))

  const updateRow = (i, patch) => {
    const next = rows.map((row, idx) => idx === i ? { ...row, ...patch, edited: true } : row)
    setSubtitleSegments?.(next)
  }
  const deleteRow = (i) => setSubtitleSegments?.(rows.filter((_, idx) => idx !== i).map((row, idx) => ({ ...row, index: idx + 1 })))
  const addRowBelow = (i) => {
    const prev = rows[i]
    const inserted = { index: i + 2, start: prev?.end ?? 0, end: (prev?.end ?? 0) + 1, text: "", edited: true }
    const next = [...rows.slice(0, i + 1), inserted, ...rows.slice(i + 1)].map((row, idx) => ({ ...row, index: idx + 1 }))
    setSubtitleSegments?.(next)
  }
  // "Tách lại" ghi đè canonical bằng preview hiện tại (mất chỉnh tay).
  const resplitFromScript = () => {
    if (!window.confirm("Tách lại từ kịch bản sẽ ghi đè các chỉnh sửa phụ đề thủ công. Tiếp tục?")) return
    setSubtitleSegments?.(srt.segments.map((s, i) => ({ index: i + 1, start: s.start, end: s.end, text: s.text, edited: false })))
  }

  const categoryHidden = categoryLocked && !projectCategory
  return <div className="step-screen step1-screen">
    <div className="screen-heading"><h1>Bước 1 - Chuẩn bị nội dung</h1><p>Chọn cách bắt đầu phù hợp. Kịch bản cuối luôn có thể chỉnh sửa trước khi tạo giọng đọc.</p></div>
    {staleWarning && (
      <div className="stale-banner">
        <AlertTriangle className="h-4 w-4 flex-shrink-0" />
        <span>Bạn đang sửa kịch bản của video đã có giọng đọc/cảnh. Lưu nội dung mới sẽ cần <b>tạo lại giọng đọc, phân cảnh và xuất CapCut</b> cho khớp.</span>
      </div>
    )}
    <div className="panel">
      <div className={cn("script-project-fields", categoryHidden && "single")}>
        <Field label="Tên video"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Brazil vs Panama" /></Field>
        {!categoryHidden && (
          <Field label="Thư mục / chủ đề lưu video">
            {categoryLocked ? (
              <div className="category-locked-field">
                <Input value={projectCategory} disabled />
                <Lock className="h-3.5 w-3.5 text-zinc-500 flex-shrink-0" />
              </div>
            ) : (
              <>
                <Input list="project-category-list" value={projectCategory} onChange={(e) => setProjectCategory(e.target.value)} placeholder="Ví dụ: Bóng đá, Nấu ăn, Khoa học..." />
                <datalist id="project-category-list">{categories.map((item) => <option key={item} value={item} />)}</datalist>
              </>
            )}
          </Field>
        )}
      </div>

      <div className="script-mode-switch">
        <button className={cn(contentMode === "existing" && "active")} onClick={()=>setContentMode("existing")}><FileText/><span><b>Tôi đã có kịch bản</b><small>Dán nội dung hoặc tải file TXT</small></span></button>
        <button className={cn(contentMode === "idea" && "active")} onClick={()=>setContentMode("idea")}><Sparkles/><span><b>Tạo kịch bản từ ý tưởng</b><small>Nhập tóm tắt, AI chạy theo flow đã cấu hình</small></span></button>
      </div>

      {contentMode === "existing" ? <div className="script-mode-content script-2col">
        <div className="script-col">
          <div className="panel-title"><div><h2>Kịch bản dùng để đọc</h2><p>Dán nguyên văn nội dung bạn muốn xuất hiện trong giọng đọc.</p></div><FileText className="text-violet-300" /></div>
          <Textarea className="script-editor" value={script} onChange={(e) => setScript(e.target.value)} placeholder="Dán kịch bản cuối vào đây..." />
          <div className="script-editor-actions">
            <input ref={scriptFileInputRef} type="file" accept=".txt,text/plain" className="hidden" onChange={(e) => uploadTxtFile(e.target.files?.[0])} />
            <Button variant="secondary" onClick={() => scriptFileInputRef.current?.click()}><Upload className="h-4 w-4" /> Tải file TXT</Button>
            <span>{script.trim() ? script.trim().split(/\s+/).length : 0} từ</span>
          </div>
        </div>
        <div className="srt-col">
          <div className="panel-title"><div><h2>Phụ đề tự động (SRT)</h2><p>Tách câu theo thời gian ngay khi bạn gõ. Timing là ước lượng, sẽ chính xác sau khi tạo giọng đọc.</p></div>{srtBusy ? <LoaderCircle className="h-4 w-4 animate-spin text-emerald-300" /> : <ListVideo className="text-emerald-300" />}</div>
          {srt.segments.length > 0 && (
            <div className="srt-preview-meta"><span>{srt.sentences} câu phụ đề</span><span>~{formatTime(srt.duration)} (ước lượng)</span></div>
          )}
          <div className="srt-preview-list">
            {rows.length === 0
              ? <EmptyState text={script.trim() ? "Đang tạo phụ đề..." : "Nhập kịch bản bên trái để xem phụ đề SRT tự động."} />
              : rows.map((seg, i) => (
                <div className="srt-edit-row" key={i}>
                  <span className="srt-preview-idx">{i + 1}</span>
                  <div className="srt-edit-body">
                    <div className="srt-edit-time">
                      <input type="number" step="0.1" min="0" value={seg.start}
                        onChange={(e) => updateRow(i, { start: Number(e.target.value) })} />
                      <span>→</span>
                      <input type="number" step="0.1" min="0" value={seg.end}
                        onChange={(e) => updateRow(i, { end: Number(e.target.value) })} />
                      <small>{formatTime(seg.start)} → {formatTime(seg.end)}</small>
                    </div>
                    <Textarea className="srt-edit-text" value={seg.text}
                      onChange={(e) => updateRow(i, { text: e.target.value })} />
                  </div>
                  <div className="srt-edit-actions">
                    <button title="Thêm dòng dưới" onClick={() => addRowBelow(i)}><Plus className="h-3.5 w-3.5" /></button>
                    <button title="Xoá dòng" onClick={() => deleteRow(i)}><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
              ))}
          </div>
          {rows.length > 0 && (
            <div className="srt-edit-footer">
              <Button variant="secondary" onClick={resplitFromScript}><RefreshCw className="h-4 w-4" /> Tách lại (ghi đè)</Button>
            </div>
          )}
        </div>
      </div> : <div className="script-mode-content workflow-create">
        <div className="workflow-create-head">
          <div><h2>Tạo kịch bản bằng flow</h2><p>AI sẽ chạy lần lượt các bước trong flow bạn chọn.</p></div>
        </div>
        <div className="workflow-flow-picker">
          <Field label="Flow tạo kịch bản">
            <Select value={activeFlowId || flows[0]?.id || ""} onValueChange={setActiveFlowId} options={flows.map(f => ({ value: f.id, label: f.name }))} />
          </Field>
          <Button variant="secondary" onClick={() => setFlowsOpen(true)}><Layers className="h-4 w-4" /> Quản lý Flow</Button>
        </div>
        {activeFlow && (
          <div className="flow-steps-preview">
            {activeFlow.steps?.filter(s => s.enabled !== false).map((s, i) => (
              <span key={i} className="flow-step-chip">{i + 1}. {s.name}</span>
            ))}
          </div>
        )}
        <Field label="Tóm tắt chủ đề muốn làm">
          <Textarea className="workflow-topic-input" value={workflowInput} onChange={(e) => setWorkflowInput(e.target.value)} placeholder="Ví dụ: Video 2 phút phân tích trận Brazil sáng nay, tập trung vào diễn biến chính, cầu thủ nổi bật và kết quả cuối cùng. Giọng tin tức, dễ hiểu." />
        </Field>
        {workflowRunning && <div className="workflow-live-progress"><div><b>{activeJob?.current_label || "Đang chuẩn bị..."}</b><span>{workflowPercent}%</span></div><i><em style={{width:`${workflowPercent}%`}} /></i></div>}
        <Button className="workflow-generate-button" onClick={runWorkflow} disabled={!workflowInput.trim() || isBusy || !activeFlow}>{workflowRunning ? <LoaderCircle className="h-4 w-4 animate-spin"/> : <Sparkles className="h-4 w-4"/>}{workflowRunning ? "Đang tạo kịch bản..." : "Tạo kịch bản"}</Button>
        {script.trim() && <div className="workflow-result"><div><b>Kịch bản đã tạo</b><span>Có thể chỉnh trực tiếp trước khi tiếp tục.</span></div><Textarea className="script-editor generated" value={script} onChange={(e)=>setScript(e.target.value)} /></div>}
      </div>}
    </div>
    <div className="screen-footer"><span>{script.trim() ? "Nội dung đã có. Bấm nút bên phải để lưu và chọn giọng." : "Hãy nhập nội dung hoặc nhờ AI viết kịch bản trước."}</span><Button onClick={saveScriptStep} disabled={!script.trim() || workflowRunning}>Lưu và chọn giọng đọc <ArrowRight className="h-4 w-4" /></Button></div>
  </div>
}

function ScriptPanel({ title, setTitle, script, setScript, scriptFileInputRef, uploadTxtFile }) {
  return <div className="flex h-full flex-col">
    <div className="panel-title"><div><h2>Kịch bản cuối</h2><p>Nội dung giọng đọc sẽ đọc</p></div><FileText className="text-violet-300" /></div>
    <div className="quick-help"><b>Bắt đầu nhanh</b><span>Dán nguyên văn nội dung muốn đọc. Không cần ghi chú hình ảnh, không cần chia cảnh, tool sẽ tự làm ở bước sau.</span></div>
    <Field label="Tên project"><Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Brazil vs Panama" /></Field>
    <div className="mt-4 flex-1"><Textarea className="h-full min-h-[360px]" value={script} onChange={(e) => setScript(e.target.value)} placeholder="Dán kịch bản cuối vào đây..." /></div>
    <div className="mt-4 flex items-center gap-2">
      <input ref={scriptFileInputRef} type="file" accept=".txt,text/plain" className="hidden" onChange={(e) => uploadTxtFile(e.target.files?.[0])} />
      <Button variant="secondary" onClick={() => scriptFileInputRef.current?.click()}><Upload className="h-4 w-4" /> Tải file TXT</Button>
      <span className="ml-auto text-xs text-slate-500">{script.trim() ? script.trim().split(/\s+/).length : 0} từ</span>
    </div>
  </div>
}

function WorkflowPanel({ workflowInput, setWorkflowInput, workflowSteps, settings, workflowPresets, applyWorkflowPreset, startJob, isBusy, busyAction, setSettingsOpen }) {
  const presets = workflowPresets()
  return <div className="flex h-full flex-col">
    <div className="panel-title"><div><h2>Nhờ AI viết kịch bản</h2><p>Phù hợp khi bạn chỉ có ý tưởng hoặc tài liệu thô</p></div><Sparkles className="text-emerald-300" /></div>
    <div className="quick-help"><b>Nhập đơn giản</b><span>Ví dụ: “Viết video 1 phút về Argentina thắng trận sáng nay, giọng tin tức, dễ hiểu”.</span></div>
    <Field label="Kiểu kịch bản muốn tạo"><Select value={settings.active_workflow_id || presets[0]?.id || ""} onValueChange={applyWorkflowPreset} options={presets.map((x) => ({ value: x.id, label: x.name }))} /></Field>
    <Textarea className="mt-4 min-h-[200px]" value={workflowInput} onChange={(e) => setWorkflowInput(e.target.value)} placeholder="Nhập chủ đề, dữ liệu nguồn, độ dài video và phong cách mong muốn..." />
    <div className="mt-4 space-y-2">{workflowSteps.filter((x) => x.enabled).map((step, index) => <div className="workflow-row" key={index}><span>{index + 1}</span><div><b>{step.name}</b><p>{step.prompt}</p></div></div>)}</div>
    <div className="mt-auto flex justify-between pt-4"><Button variant="ghost" onClick={() => setSettingsOpen(true)}><Settings className="h-4 w-4" /> Sửa mẫu flow</Button><span className="text-xs leading-8 text-slate-500">Xong phần này bấm nút tím ở dưới cùng.</span></div>
  </div>
}

function VoiceScreen({ script, project, settings, setSettings, voiceOptions, refreshVoices, previewVoiceNow, voicePreviewBusy, voicePreviewUrl, createVoiceWithQuickSettings, startJob, applyBeginnerVoicePreset, saveCloneVoice, selectSavedCloneVoice, deleteVoiceClone, isBusy, busyAction, activeJob, goStep, userProgress }) {
  const [cloneName, setCloneName] = useState("")
  const [cloneLanguage, setCloneLanguage] = useState("vi")
  const [pendingCloneFile, setPendingCloneFile] = useState(null)
  const [cloneToDelete, setCloneToDelete] = useState(null)
  const cloneInputRef = useRef(null)
  const voiceLanguage = normalizeVoiceLanguage(settings.text_to_voice_language || "en")
  const cloneProfiles = Array.isArray(settings.voice_clone_profiles) ? settings.voice_clone_profiles : []
  const selectedClone = cloneProfiles.find((item) => item.path === settings.voice_clone_reference_path)
  const selectedCloneId = selectedClone?.id || ""
  const usingClone = Boolean(settings.voice_clone_enabled && selectedClone)
  const [voiceMode, setVoiceMode] = useState(usingClone ? "clone" : "normal")
  useEffect(() => { setVoiceMode(usingClone ? "clone" : "normal") }, [usingClone])
  useEffect(() => {
    if (selectedClone?.language && selectedClone.language !== cloneLanguage) setCloneLanguage(selectedClone.language)
  }, [selectedClone?.language])
  const cloneLanguageOptions = useMemo(() => {
    const values = new Set(["vi"])
    cloneProfiles.forEach((item) => values.add(item.language || "vi"))
    if (cloneLanguage) values.add(cloneLanguage)
    return [...values].map((value) => ({ value, label: value }))
  }, [cloneProfiles, cloneLanguage])
  const filteredCloneProfiles = cloneProfiles.filter((item) => (item.language || "vi") === cloneLanguage)
  const cloneProfileOptions = filteredCloneProfiles.map((item) => ({ value: item.id, label: item.name || item.file_name || "Giọng clone" }))
  const voiceRunning = Boolean(isBusy && (busyAction === "voice" || inferActionFromJob(activeJob) === "voice"))
  const changeVoiceLanguage = (language) => setSettings({
    ...settings,
    text_to_voice_language: language,
  })
  const cloneVoiceNow = async () => {
    if (!pendingCloneFile) return
    const latestSettings = await saveCloneVoice(pendingCloneFile, {
      name: cloneName.trim() || pendingCloneFile.name.replace(/\.[^.]+$/, ""),
      language: cloneLanguage,
      setDefault: true,
    })
    setPendingCloneFile(null)
    setSettings(latestSettings)
    setVoiceMode("clone")
  }
  const chooseNormalMode = () => {
    setVoiceMode("normal")
    setSettings({ ...settings, voice_clone_enabled:false, voice_clone_reference_path:"", voice_clone_reference_name:"", voice_clone_preview_url:"" })
  }
  const chooseCloneMode = async () => {
    setVoiceMode("clone")
    const profile = selectedClone || filteredCloneProfiles[0] || cloneProfiles[0]
    if (profile) {
      setCloneLanguage(profile.language || "vi")
      await selectSavedCloneVoice(profile, false)
    }
  }
  const chooseCloneProfile = async (profile) => {
    if (!profile) return
    setVoiceMode("clone")
    setCloneLanguage(profile.language || "vi")
    await selectSavedCloneVoice(profile, false)
  }
  const changeCloneLanguage = async (language) => {
    setCloneLanguage(language)
    const first = cloneProfiles.find((item) => (item.language || "vi") === language)
    if (first && first.id !== selectedCloneId) await chooseCloneProfile(first)
  }
  const progress = Math.max(0, Math.min(100, Math.round(userProgress?.percent || 0)))
  const progressMessages = userProgress?.messages || []
  const voiceStale = Boolean(project?.voice_exists) && !project?.has_voice
  return <div className="step-screen">
    <div className="screen-heading"><h1>Bước 2 - Chọn giọng đọc cho video</h1><p>Chọn giọng, nghe thử, rồi tạo file đọc để bước sau tự chia cảnh.</p></div>
    {voiceStale && <div className="stale-banner"><AlertTriangle className="h-4 w-4 flex-shrink-0" /><span>Kịch bản đã thay đổi nên giọng đọc cũ không còn khớp. Hãy bấm <b>Tạo giọng đọc</b> để làm lại trước khi sang bước phân cảnh.</span></div>}
    <div className="recommended-action">
      <div><b>Không biết chọn gì?</b><span>Bấm nút này để tool tự chọn ngôn ngữ, chế độ ổn định và tắt kiểm tra chậm cho script dài.</span></div>
      <Button variant="secondary" onClick={applyBeginnerVoicePreset} disabled={isBusy}><WandSparkles className="h-4 w-4" /> Dùng cấu hình dễ nhất</Button>
    </div>
    {isBusy && busyAction === "voice" && <div className="voice-progress-panel">
      <div className="voice-progress-head"><b>{userProgress?.title || "Đang tạo giọng đọc và timing"}</b><span>{progress}%</span></div>
      <i><em style={{width:`${progress}%`}} /></i>
      <div className="voice-progress-log">{progressMessages.map((message, index)=><p key={index}>{message}</p>)}</div>
    </div>}
    <div className="voice-screen-grid">
      <div className="glass-panel screen-panel flex flex-col">
        <div className="voice-choice-buttons">
          <button className={cn(voiceMode==="normal" && "active")} onClick={chooseNormalMode}><FileAudio className="h-4 w-4" /><span>Giọng có sẵn</span></button>
          <button className={cn(voiceMode==="clone" && "active")} onClick={chooseCloneMode}><Mic className="h-4 w-4" /><span>Giọng đã clone</span></button>
        </div>
        {voiceMode === "normal" ? <>
          <div className="panel-title"><h2>Giọng có sẵn</h2><Button variant="ghost" size="sm" onClick={() => refreshVoices(settings.text_to_voice_language || "en")}><RefreshCw className="h-4 w-4" /> Tải lại</Button></div>
          <Field label="Ngôn ngữ đọc"><Select value={voiceLanguage} onValueChange={changeVoiceLanguage} options={voiceLanguageOptions} /></Field>
          <Field label="Chọn giọng">
            <Select
              value={settings.text_to_voice_voice || voiceOptions[0]?.value || "af_heart"}
              onValueChange={(value) => setSettings({...settings, text_to_voice_voice:value, voice_clone_enabled:false, voice_clone_reference_path:"", voice_clone_reference_name:"", voice_clone_preview_url:""})}
              options={voiceOptions.map((voice) => ({ value: voice.value, label: voice.label }))}
            />
          </Field>
          <div className="voice-left-actions">
            <Button variant="secondary" onClick={() => previewVoiceNow()} disabled={voicePreviewBusy}>{voicePreviewBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Nghe thử</Button>
          </div>
        </> : <>
          <div className="panel-title"><div><h2>Giọng đã clone</h2><p>Chọn ngôn ngữ rồi chọn giọng đã lưu.</p></div></div>
          <Field label="Ngôn ngữ clone"><Select value={cloneLanguage} onValueChange={changeCloneLanguage} options={cloneLanguageOptions} /></Field>
          {cloneProfileOptions.length > 0 ? <>
            <Field label="Chọn giọng clone">
              <div className="clone-select-row">
                <Select
                  value={selectedCloneId}
                  onValueChange={(id) => chooseCloneProfile(cloneProfiles.find((item) => item.id === id))}
                  options={cloneProfileOptions}
                  placeholder={cloneProfileOptions.length ? "Chọn giọng clone" : "Không có giọng cho ngôn ngữ này"}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  title="Xóa giọng clone đang chọn"
                  disabled={!selectedClone}
                  onClick={() => selectedClone && setCloneToDelete(selectedClone)}
                ><Trash2 className="h-4 w-4 text-red-400" /></Button>
              </div>
            </Field>
          </> : <div className="clone-empty-hint"><Mic className="h-5 w-5" /><span>Chưa có giọng clone cho ngôn ngữ này. Tạo giọng mới ở bảng bên phải.</span></div>}
          <Dialog open={Boolean(cloneToDelete)} onOpenChange={(open) => !open && setCloneToDelete(null)}>
            <DialogContent className="max-w-md">
              <DialogTitle>Xóa giọng clone?</DialogTitle>
              <DialogDescription>Giọng "{cloneToDelete?.name || cloneToDelete?.file_name}" và file audio mẫu sẽ bị xóa vĩnh viễn. Thao tác này không thể hoàn tác.</DialogDescription>
              <div className="dialog-actions">
                <Button variant="secondary" onClick={() => setCloneToDelete(null)}>Giữ lại</Button>
                <Button variant="danger" onClick={() => { const id = cloneToDelete?.id; setCloneToDelete(null); deleteVoiceClone(id) }}><Trash2 className="h-4 w-4" /> Xóa giọng</Button>
              </div>
            </DialogContent>
          </Dialog>
          <div className="voice-left-actions">
            <Button variant="secondary" onClick={() => previewVoiceNow()} disabled={!selectedClone || voicePreviewBusy}>{voicePreviewBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Nghe thử</Button>
          </div>
        </>}
        {voicePreviewUrl && <audio autoPlay src={voicePreviewUrl} className="hidden" />}
      </div>
      <div className="glass-panel screen-panel flex flex-col">
        {voiceMode === "clone" && <>
          <div className="panel-title"><div><h3>Clone giọng mới</h3><p>Tải audio mẫu, bấm Clone giọng một lần, lần sau chọn lại ở bảng trái.</p></div><Mic className="text-emerald-300" /></div>
          <div className="clone-inline-card">
            <div className="clone-dialog-grid">
              <Field label="Tên giọng"><Input value={cloneName} onChange={(e)=>setCloneName(e.target.value)} placeholder="Ví dụ: BLV Anh Quân" /></Field>
              <Field label="Ngôn ngữ"><Input value={cloneLanguage} onChange={(e)=>setCloneLanguage(e.target.value)} placeholder="vi, en, fr..." /></Field>
            </div>
            <button type="button" className="clone-upload-zone compact" onClick={() => cloneInputRef.current?.click()}>
              <Upload className="h-6 w-6 text-emerald-300" />
              <b>{pendingCloneFile ? pendingCloneFile.name : "Tải audio mẫu clone"}</b>
              <span>WAV/MP3 sạch, một người nói, khoảng 10-30 giây.</span>
            </button>
            <input ref={cloneInputRef} type="file" accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.webm" className="hidden" onChange={(e)=>setPendingCloneFile(e.target.files?.[0] || null)} />
            <Button disabled={!pendingCloneFile || isBusy || voicePreviewBusy} onClick={cloneVoiceNow}>
              {voicePreviewBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Mic className="h-4 w-4" />}
              {voicePreviewBusy ? "Đang clone và tạo nghe thử..." : "Clone giọng"}
            </Button>
          </div>
        </>}
        <div className="panel-title mt-4"><div><h3>Cài đặt giọng đọc</h3><p>Chỉnh tốc độ, mức clone và nghe thử kết quả.</p></div><Settings className="text-emerald-300" /></div>
        <RangeField label="Tốc độ đọc" value={settings.text_to_voice_speed ?? 1} min={.5} max={2} step={.05} onChange={(v)=>setSettings({...settings,text_to_voice_speed:v})} />
        <div className="setting-help">0.9-1.0 là tự nhiên. Tăng lên nếu muốn đọc nhanh, giảm xuống nếu muốn chậm và rõ hơn.</div>
        {voiceMode === "clone" && <><RangeField label="Mức xử lý giọng clone" value={Math.max(8, Math.min(16, settings.magicvoice_steps ?? 16))} min={8} max={16} step={1} onChange={(v)=>setSettings({...settings, magicvoice_steps:v})} />
        <div className="setting-help">8 tạo nhanh hơn, 16 ưu tiên chất lượng. Tool giới hạn tối đa 16 để tránh lỗi và quá tải bộ nhớ.</div></>}
      </div>
    </div>
    <div className="screen-footer"><Button variant="secondary" onClick={()=>goStep("step1")}><ArrowLeft className="h-4 w-4" /> Quay lại Bước 1</Button><span>{voiceRunning ? "Đổi giọng hoặc tốc độ rồi bấm Tạo lại. Tool sẽ dừng bản đang chạy." : project?.voice_path ? "Đã có voice. Sang bước Prompt để tạo prompt cho từng câu." : "Chọn giọng xong hãy bấm Tạo giọng đọc."}</span><div className="voice-footer-actions">
      <Button variant={project?.voice_path || voiceRunning ? "secondary" : "default"} onClick={createVoiceWithQuickSettings} disabled={isBusy && !voiceRunning}>{voiceRunning?<RefreshCw className="h-4 w-4 animate-spin"/>:<Sparkles className="h-4 w-4"/>} {voiceRunning ? "Dừng và tạo lại" : project?.voice_path ? "Tạo lại giọng đọc" : "Tạo giọng đọc"}</Button>
      {project?.voice_path && <Button onClick={()=>goStep("step2b")} disabled={isBusy}><ArrowRight className="h-4 w-4"/> Tạo prompt theo câu</Button>}
    </div></div>
  </div>
}

function RangeField({ label, value, min, max, step, onChange }) {
  return <div className="mb-5"><div className="mb-2 flex justify-between text-xs text-slate-400"><span>{label}</span><b className="text-white">{Number(value).toFixed(2)}</b></div><input className="stitch-range" type="range" min={min} max={max} step={step} value={value} onChange={(e)=>onChange(Number(e.target.value))} /></div>
}

function looksLikeEnglish(text = "") {
  const sample = String(text).slice(0, 1600)
  const tokens = sample.toLowerCase().match(/[a-z']+/g) || []
  if (tokens.length < 8) return false
  const common = new Set(["the","and","with","from","that","their","they","this","when","into","after","match","team","goal","player","control"])
  const hits = tokens.filter((token) => common.has(token)).length
  const asciiRatio = [...sample].filter((ch) => ch.charCodeAt(0) < 128).length / Math.max(1, sample.length)
  return asciiRatio > 0.92 && hits >= 4
}

function PromptScreen({ assets, project, startJob, isBusy, busyAction, goStep, saveKeyword, userProgress, promptAnalysis, savePromptAnalysis, saveAssetPrompt, loadPromptAnalysis }) {
  const generating = busyAction === "analyze" && isBusy
  const searching = busyAction === "search" && isBusy
  const analyzingStory = busyAction === "analyze-story" && isBusy
  const generatingRealPrompts = busyAction === "generate-prompts" && isBusy
  const hasPrompts = Boolean(project?.has_scenes) && assets.length > 0
  const promptsStale = Boolean(project?.has_voice && project?.scenes_exist && !project?.has_scenes)
  const [editingId, setEditingId] = useState(null)
  const [editValue, setEditValue] = useState("")
  const progress = Math.max(0, Math.min(100, Math.round(userProgress?.percent || 0)))
  const runGenerate = () => startJob("/api/analyze", undefined, "analyze")
  const runSearch = () => startJob("/api/search", undefined, "search")
  const startEdit = (item) => { setEditingId(item.asset_id); setEditValue(item.keyword || item.ai_search_keyword || "") }
  const commitEdit = async (item) => {
    const value = editValue.trim()
    setEditingId(null)
    if (value && value !== (item.keyword || "")) await saveKeyword(item.asset_id, value)
  }

  // Character editor helpers
  const chars = promptAnalysis?.characters || []
  const persist = (nextChars) => savePromptAnalysis({ ...(promptAnalysis || {}), characters: nextChars })
  const updateCharacter = (i, patch) => persist(chars.map((c, idx) => idx === i ? { ...c, ...patch } : c))
  const removeCharacter = (i) => persist(chars.filter((_, idx) => idx !== i))
  const addCharacter = () => persist([...chars, { name: "", role: "", description: "" }])

  return <div className="step-screen prompt-screen">
    <div className="screen-heading"><h1>Bước 2.5 - Prompt cho từng câu</h1><p>Mỗi câu thoại (theo SRT của giọng đọc) được AI tạo một prompt/từ khóa tìm hình đồng nhất. Xem và chỉnh trước khi tìm ảnh.</p></div>

    {!project?.has_voice ? (
      <div className="step-guidance">
        <div><b>Cần tạo giọng đọc trước.</b><span>Prompt được sinh theo SRT của giọng đọc. Hãy quay lại Bước 2 và tạo giọng đọc.</span></div>
        <Button variant="secondary" onClick={()=>goStep("step2")}><ArrowLeft className="h-4 w-4" /> Về Bước 2</Button>
      </div>
    ) : (
      <>
        {promptsStale && !generating && <div className="stale-banner"><AlertTriangle className="h-4 w-4 flex-shrink-0" /><span>Giọng đọc đã thay đổi nên prompt cũ không còn khớp. Hãy bấm <b>Tạo lại prompt</b>.</span></div>}

        {/* Character analysis section */}
        <div className="prompt-analysis">
          <div className="panel-title"><div><h2>Phân tích &amp; nhân vật</h2><p>AI dựng bối cảnh và nhân vật từ phụ đề. Sửa cho khớp rồi tạo prompt đời thật.</p></div></div>
          <Button variant="secondary" disabled={isBusy} onClick={() => startJob("/api/analyze-story", undefined, "analyze-story")}>
            {analyzingStory ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />} {analyzingStory ? "Đang phân tích..." : "Phân tích nhân vật"}
          </Button>
          {promptAnalysis && (
            <>
              {promptAnalysis.storyContext && <p className="prompt-story">{promptAnalysis.storyContext}</p>}
              <div className="character-list">
                {chars.map((ch, i) => (
                  <div className="character-row" key={i}>
                    <Input value={ch.name || ""} placeholder="Tên"
                      onChange={(e) => updateCharacter(i, { name: e.target.value })} />
                    <Input value={ch.role || ""} placeholder="Vai trò"
                      onChange={(e) => updateCharacter(i, { role: e.target.value })} />
                    <Textarea value={ch.description || ""} placeholder="Mô tả ngoại hình đời thật"
                      onChange={(e) => updateCharacter(i, { description: e.target.value })} />
                    <button title="Xoá" onClick={() => removeCharacter(i)}><Trash2 className="h-4 w-4" /></button>
                  </div>
                ))}
                <Button variant="ghost" onClick={addCharacter}><Plus className="h-4 w-4" /> Thêm nhân vật</Button>
              </div>
              <Button disabled={isBusy} onClick={() => startJob("/api/generate-prompts", undefined, "generate-prompts")}>
                {generatingRealPrompts ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} {generatingRealPrompts ? "Đang tạo prompt..." : "Tạo prompt cho từng câu"}
              </Button>
            </>
          )}
        </div>

        {/* Existing analyze/generate scene-keyword flow */}
        <div className={cn("step-guidance", hasPrompts && "ready")}>
          <div>
            <b>{generating ? "Đang tạo prompt cho từng câu..." : hasPrompts ? `${assets.length} câu đã có prompt` : "Chưa có prompt."}</b>
            <span>{generating ? "AI đang đọc toàn bộ kịch bản và tạo prompt nhất quán cho từng câu." : hasPrompts ? "Bấm vào prompt để sửa. Xong thì bấm Tìm ảnh." : "Bấm Tạo prompt để AI sinh prompt cho từng câu theo SRT."}</span>
          </div>
          <Button variant={hasPrompts ? "secondary" : "default"} onClick={runGenerate} disabled={isBusy}>{generating ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} {hasPrompts ? "Tạo lại prompt" : "Tạo prompt"}</Button>
        </div>

        {(generating || generatingRealPrompts || analyzingStory) && <div className="voice-progress-panel"><div className="voice-progress-head"><b>{userProgress?.title || "Đang xử lý"}</b><span>{progress}%</span></div><i><em style={{width:`${progress}%`}} /></i></div>}

        <div className="prompt-list">
          {assets.length === 0
            ? <EmptyState text={generating ? "Đang tạo prompt..." : "Chưa có prompt. Bấm Tạo prompt ở trên."} />
            : assets.map((item, i) => (
              <div className="prompt-row" key={item.asset_id}>
                <span className="prompt-row-idx">{i + 1}</span>
                <div className="prompt-row-time">{formatTime(item.start)} → {formatTime(item.end)}</div>
                <div className="prompt-row-body">
                  <p className="prompt-row-sentence">{item.sentence_text}</p>
                  {editingId === item.asset_id ? (
                    <Input
                      autoFocus
                      value={editValue}
                      onChange={(e)=>setEditValue(e.target.value)}
                      onBlur={()=>commitEdit(item)}
                      onKeyDown={(e)=>{ if (e.key==="Enter") commitEdit(item); if (e.key==="Escape") setEditingId(null) }}
                      className="prompt-row-input"
                    />
                  ) : (
                    <button className="prompt-row-keyword" onClick={()=>startEdit(item)} title="Bấm để sửa keyword">
                      <Sparkles className="h-3 w-3 text-emerald-300 flex-shrink-0" />
                      <span>{item.keyword || item.ai_search_keyword || "— chưa có keyword —"}</span>
                      <Pencil className="h-3 w-3 text-zinc-500 flex-shrink-0 prompt-row-pencil" />
                    </button>
                  )}
                  <Textarea
                    key={`${item.asset_id}:${item.prompt || ""}`}
                    className="asset-prompt"
                    defaultValue={item.prompt || ""}
                    placeholder="Prompt ảnh đời thật cho câu này..."
                    onBlur={(e) => saveAssetPrompt && saveAssetPrompt(item.asset_id, e.target.value)}
                  />
                </div>
              </div>
            ))}
        </div>
      </>
    )}

    <div className="screen-footer">
      <Button variant="secondary" onClick={()=>goStep("step2")}><ArrowLeft className="h-4 w-4"/> Quay lại Giọng đọc</Button>
      <span>{searching ? "Đang tìm ảnh theo prompt..." : hasPrompts ? "Prompt sẵn sàng. Bấm Tìm ảnh để tải media theo prompt." : "Tạo prompt trước khi tìm ảnh."}</span>
      <Button disabled={!hasPrompts || isBusy} onClick={runSearch}>{searching ? <LoaderCircle className="h-4 w-4 animate-spin"/> : <Image className="h-4 w-4"/>} Tìm ảnh theo prompt <ArrowRight className="h-4 w-4"/></Button>
    </div>
  </div>
}

function SceneScreen({ assets, project, startJob, isBusy, busyAction, goStep }) {
  const loading = busyAction === "analyze-search" && isBusy
  const scenesStale = Boolean(project?.has_voice && project?.scenes_exist && !project?.has_scenes)
  const runAnalyze = () => startJob("/api/analyze-search", undefined, "analyze-search")
  return <div className="step-screen">
    <div className="screen-heading"><h1>Bước 3A - Chuẩn bị cảnh</h1><p>Tool tự đọc mốc thời gian, gom câu cùng ý và chuẩn bị ảnh/video cho từng cảnh.</p></div>
    {scenesStale && !loading && <div className="stale-banner"><AlertTriangle className="h-4 w-4 flex-shrink-0" /><span>Giọng đọc đã được tạo lại nên phân cảnh cũ không còn khớp. Hãy bấm <b>Tạo lại phân cảnh</b> để cập nhật cảnh và ảnh theo nội dung mới.</span></div>}
    <div className={cn("step-guidance", project?.has_voice && "ready")}>
      <div>
        <b>{project?.has_voice ? "Tool đang chuẩn bị dữ liệu cho bước duyệt ảnh." : "Cần tạo giọng đọc trước."}</b>
        <span>{loading ? "Đang chia nội dung thành cảnh và tìm media phù hợp. Xong bước này tool sẽ chuyển sang màn duyệt ảnh." : project?.has_voice ? "Nếu đã có dữ liệu, bạn có thể xem lại từng cảnh ở bên dưới hoặc sang bước duyệt ảnh." : "Quay lại Bước 2, bấm tạo giọng đọc. Tool cần voice để biết mỗi câu nằm ở giây nào."}</span>
      </div>
      {!project?.has_voice
        ? <Button variant="secondary" onClick={()=>goStep("step2")}><ArrowLeft className="h-4 w-4" /> Về Bước 2</Button>
        : <Button variant={scenesStale ? "default" : "secondary"} onClick={runAnalyze} disabled={isBusy}>{loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} {assets.length ? "Tạo lại phân cảnh" : "Tạo phân cảnh"}</Button>}
    </div>
    <div className="scene-layout">
      <div className="glass-panel screen-panel"><div className="panel-title"><div><h2>Lời đọc theo thời gian</h2><p>{project?.has_voice ? "Mỗi dòng là một đoạn voice đã được căn mốc" : "Chưa tạo giọng đọc"}</p></div><FileText className="text-violet-300" /></div><div className="srt-preview">{assets.length ? assets.map((a,i)=><div key={a.asset_id}><span>{i+1}</span><b>{formatTime(a.start)} → {formatTime(a.end)}</b><p>{a.sentence_text}</p></div>) : <EmptyState text={loading ? "Đang căn thời gian và gom câu thành cảnh..." : "Chưa có dữ liệu. Hãy hoàn thành Bước 2."} />}</div></div>
      <div className="glass-panel screen-panel"><div className="panel-title"><div><h2>Cảnh video</h2><p>Mỗi cảnh sẽ có ảnh/video riêng ở bước sau</p></div><Aperture className="text-emerald-300" /></div><div className="scene-list">{assets.length ? assets.map((a,i)=><div className="scene-row" key={a.asset_id}><span>{String(i+1).padStart(2,"0")}</span><div><b>{formatTime(a.start)} - {formatTime(a.end)} · {Number(a.duration||0).toFixed(1)}s</b><p>{a.sentence_text}</p><small>{a.scene_break_reason || "Chuyển chủ thể, sự kiện hoặc ý chính"}</small></div></div>) : <EmptyState text={loading ? "Đang tạo phân cảnh và tìm ảnh/video..." : "Chưa có cảnh."} />}</div></div>
    </div>
    <div className="screen-footer"><Button variant="secondary" onClick={()=>goStep("step2")}><ArrowLeft className="h-4 w-4"/> Quay lại</Button><span>{loading ? "Đang xử lý, vui lòng chờ..." : assets.length ? `${assets.length} cảnh đã sẵn sàng` : "Chưa có dữ liệu cảnh"}</span><Button variant="secondary" disabled={!assets.length} onClick={()=>goStep("step3b")}>Xem ảnh từng cảnh <ArrowRight className="h-4 w-4"/></Button></div>
  </div>
}

function MediaReviewScreen({ assets, filteredAssets, assetFilter, setAssetFilter, project, assetJobs, statusBadge, setLightboxIndex, startJob, approveAsset, approveAllAssets, chooseAssetMedia, bulkRetryAssets, goStep }) {
  const pageSize = 15
  const [page, setPage] = useState(1)
  const headerRef = useRef(null)
  const categoryOf = (asset) => {
    if (assetJobs.has(asset.asset_id)) return "processing"
    if (asset.status === "error" || asset.status === "failed" || Boolean(asset.error)) return "error"
    if (!asset.local_path) return "missing"
    if (asset.status === "approved") return "approved"
    return "review"
  }
  const counts = assets.reduce((result, asset) => {
    result[categoryOf(asset)] += 1
    return result
  }, { processing:0, review:0, approved:0, error:0, missing:0 })
  counts.all = assets.length
  const retryableAssets = assets.filter(asset => ["error", "missing"].includes(categoryOf(asset)))
  const approvalPercent = assets.length ? Math.round((counts.approved / assets.length) * 100) : 0
  const changeFilter = (value) => {
    setAssetFilter(value)
    setPage(1)
    requestAnimationFrame(() => headerRef.current?.scrollIntoView({ block:"start", behavior:"smooth" }))
  }
  const pageCount = Math.max(1, Math.ceil(filteredAssets.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const visibleAssets = filteredAssets.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  useEffect(() => {
    if (page > pageCount) setPage(pageCount)
  }, [page, pageCount])
  const filterOptions = [
    ["all","Tất cả"],
    ["review","Cần duyệt"],
    ["approved","Đã duyệt"],
    ["processing","Đang xử lý"],
    ["error","Lỗi"],
    ["missing","Thiếu media"],
  ]
  return <div className="step-screen media-screen">
    <div className="media-review-header" ref={headerRef}>
      <div>
        <h1>Duyệt hình ảnh <span>({assets.length} cảnh)</span></h1>
        <p>Kiểm tra nhanh từng cảnh. Bấm vào thẻ để xem đầy đủ nội dung và nguồn ảnh.</p>
      </div>
      <div className="media-review-progress">
        <b>{approvalPercent}%</b>
        <span>đã duyệt</span>
        <i><em style={{width:`${approvalPercent}%`}} /></i>
      </div>
    </div>
    <div className="media-task-strip">
      <div><CheckCircle2 className="h-4 w-4" /><b>{counts.approved}</b><span>đã duyệt</span></div>
      <div><Image className="h-4 w-4" /><b>{counts.review}</b><span>cần xem</span></div>
      <div><LoaderCircle className="h-4 w-4" /><b>{counts.processing}</b><span>đang xử lý</span></div>
      <div><AlertTriangle className="h-4 w-4" /><b>{counts.error + counts.missing}</b><span>cần xử lý</span></div>
    </div>
    <div className="media-filter-row">
      <div className="media-filter-control">
        <span>Hiển thị</span>
        <Select
          value={assetFilter}
          onValueChange={changeFilter}
          options={filterOptions.map(([value,label])=>({value,label:`${label} (${counts[value]})`}))}
        />
      </div>
      <div className="media-filter-actions">
        <small>{filteredAssets.length} cảnh · trang {currentPage}/{pageCount}</small>
        <Button size="sm" variant="secondary" disabled={!retryableAssets.length} onClick={()=>bulkRetryAssets(retryableAssets.map(a=>a.asset_id))}><RefreshCw className="h-4 w-4" /> Tìm lại ảnh lỗi</Button>
        <Button size="sm" variant="secondary" disabled={!assets.some(a=>a.local_path && a.status !== "approved")} onClick={approveAllAssets}><Check className="h-4 w-4" /> Duyệt tất cả</Button>
      </div>
    </div>
    <div className="media-grid">{visibleAssets.length ? visibleAssets.map((asset)=>{
      const idx=assets.findIndex(a=>a.asset_id===asset.asset_id), job=assetJobs.get(asset.asset_id), badge=statusBadge(asset.status), version=asset.media_version||asset.sha256||asset.search_attempt
      return <article className="media-card" key={asset.asset_id}>
          <button className={cn("media-image", !asset.local_path && "empty")} onClick={()=>setLightboxIndex(idx)}>
            {asset.local_path?<img src={mediaUrl(asset.local_path,version)} alt={`Cảnh ${idx+1}`}/>:<Image className="h-10 w-10 text-slate-700"/>}
            <span className="scene-number">Cảnh {idx+1}</span><Badge variant={badge.variant}>{badge.label}</Badge>
            <time>{formatTime(asset.start)} - {formatTime(asset.end)}</time>
          {job&&<div className="media-busy"><LoaderCircle className="h-7 w-7 animate-spin"/>{job.status==="queued"?`Đang chờ #${job.queue_position}`:"Đang tìm ảnh mới..."}</div>}
        </button>
          <div className="media-card-body">
            <button className="media-card-title" onClick={()=>setLightboxIndex(idx)}><b>{asset.main_subject || asset.asset_id}</b><span>{Number(asset.duration||0).toFixed(1)}s</span></button>
            <button className="media-card-script" onClick={()=>setLightboxIndex(idx)}>{asset.sentence_text || asset.visual_context || "Bấm để xem chi tiết cảnh."}</button>
            <div className="media-actions">
            <Button size="sm" variant="secondary" disabled={!!job} onClick={()=>startJob(`/api/assets/${asset.asset_id}/retry`,undefined,`retry-${asset.asset_id}`)}><RefreshCw className="h-3.5 w-3.5"/> Tìm lại</Button>
            <Button size="sm" variant="ghost" onClick={()=>chooseAssetMedia(asset.asset_id)}><Upload className="h-3.5 w-3.5"/> Tải lên</Button>
            <Button size="sm" variant={asset.status==="approved"?"success":"ghost"} disabled={!asset.local_path} onClick={()=>approveAsset(asset.asset_id)}><Check className="h-3.5 w-3.5"/> {asset.status==="approved"?"Đã duyệt":"Duyệt"}</Button>
          </div>
          <div className={cn("media-card-status", job ? "processing" : categoryOf(asset))}>
            {job ? "Đang xử lý cảnh này." : categoryOf(asset)==="error" ? (asset.error || "Tìm media bị lỗi.") : categoryOf(asset)==="missing" ? "Cảnh chưa có media." : categoryOf(asset)==="approved" ? "Media đã được duyệt." : "Media đang chờ bạn duyệt."}
          </div>
        </div>
      </article>}) : <div className="media-empty"><EmptyState text={assets.length ? "Không có cảnh nào theo bộ lọc này." : "Chưa có cảnh. Hãy quay lại Bước 2 và bấm Tạo cảnh và tìm ảnh."} />{!assets.length && <Button variant="secondary" onClick={()=>goStep("step2")}>Về Bước 2</Button>}</div>}</div>
    {pageCount > 1 && <nav className="media-pagination" aria-label="Phân trang cảnh">
      <Button size="sm" variant="secondary" disabled={currentPage===1} onClick={()=>{setPage(value=>Math.max(1,value-1));headerRef.current?.scrollIntoView({block:"start"})}}><ArrowLeft className="h-4 w-4"/> Trang trước</Button>
      <div>{Array.from({length:pageCount},(_,index)=>index+1).map(number=><button key={number} className={number===currentPage?"active":""} onClick={()=>{setPage(number);headerRef.current?.scrollIntoView({block:"start"})}}>{number}</button>)}</div>
      <Button size="sm" variant="secondary" disabled={currentPage===pageCount} onClick={()=>{setPage(value=>Math.min(pageCount,value+1));headerRef.current?.scrollIntoView({block:"start"})}}>Trang sau <ArrowRight className="h-4 w-4"/></Button>
    </nav>}
    <div className="screen-footer"><Button variant="secondary" onClick={()=>goStep("step2b")}><ArrowLeft className="h-4 w-4"/> Prompt</Button><span>{project?.approved_count||0}/{assets.length} cảnh đã duyệt</span><Button disabled={!assets.length} onClick={()=>goStep("step4")}>Tiếp tục kiểm tra <ArrowRight className="h-4 w-4"/></Button></div>
  </div>
}

function ExportScreen({ project, assets, preflight, runPreflight, startJob, title, isBusy, busyAction, goStep }) {
  const ready=project?.has_voice&&assets.length&&assets.every(a=>a.local_path)&&assets.every(a=>a.status==="approved")
  return <div className="step-screen">
    <div className="screen-heading"><h1>Bước 4 - Kiểm tra và xuất CapCut</h1><p>Kiểm tra đủ giọng đọc, cảnh và ảnh đã duyệt trước khi tạo project.</p></div>
    <div className="export-layout">
      <div className="glass-panel screen-panel"><div className="panel-title"><h2>Tình trạng project</h2><Activity className="text-violet-300"/></div><CheckRow ok={!!project} label="Đã có project và kịch bản"/><CheckRow ok={!!project?.has_voice} label="Đã có giọng đọc"/><CheckRow ok={!!project?.has_scenes} label="Đã chia cảnh"/><CheckRow ok={assets.length>0&&assets.every(a=>a.local_path)} label="Mỗi cảnh đã có ảnh/video"/><CheckRow ok={assets.length>0&&assets.every(a=>a.status==="approved")} label="Tất cả ảnh/video đã duyệt"/><Button className="mt-5" variant="secondary" onClick={runPreflight}><CheckCircle2 className="h-4 w-4"/> Kiểm tra cấu hình hệ thống</Button></div>
      <div className="glass-panel screen-panel export-hero"><div className="rocket-orb"><Rocket className="h-20 w-20"/></div><h2>{ready ? "Sẵn sàng tạo project CapCut" : "Còn mục cần hoàn thành"}</h2><p>Ảnh/video được gắn theo mốc thời gian, giọng đọc nằm đúng timeline và flow giữ nguyên theo script.</p><div className="timeline-preview" aria-hidden="true">{assets.slice(0, 8).map((asset, index)=><span key={asset.asset_id || index} style={{"--clip": `${Math.max(34, Math.min(90, Number(asset.duration || 5) * 7))}px`}} />)}<i /></div><Button size="lg" className="export-button" disabled={!ready||isBusy} onClick={()=>startJob("/api/export",{title},"export")}>{busyAction==="export"?<LoaderCircle className="h-5 w-5 animate-spin"/>:<Rocket className="h-5 w-5"/>} Xuất và mở CapCut</Button></div>
    </div>
    {preflight&&<div className="glass-panel mt-4 p-4"><div className="grid grid-cols-3 gap-3">{preflight.checks.map(c=><CheckRow key={c.id} ok={c.ok} label={c.label}/>)}</div></div>}
    <div className="screen-footer"><Button variant="secondary" onClick={()=>goStep("step3b")}><ArrowLeft className="h-4 w-4"/> Quay lại duyệt ảnh</Button><span>{ready?"Project đã đủ dữ liệu để xuất":"Còn mục chưa hoàn thành"}</span></div>
  </div>
}

function CheckRow({ ok, label }) { return <div className={cn("check-row",ok?"ok":"bad")}>{ok?<CheckCircle2/>:<XCircle/>}<span>{label}</span></div> }
function EmptyState({ text }) { return <div className="empty-state"><Image className="h-10 w-10"/><p>{text}</p></div> }

function SettingsModal({ open, onOpenChange, settings, setSettings, saveSettings, runPreflight, preflight, preflightBusy }) {
  const [showKey, setShowKey] = useState(false)
  // Keep the previous value when the field is blank or not a finite number,
  // so clearing the box never stores 0/NaN. Backend clamps the final range.
  const setNum = (key, raw, fallback) => { const n = Number(raw); setSettings({ ...settings, [key]: raw === "" || !Number.isFinite(n) ? fallback : n }) }
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="settings-dialog max-w-6xl"><DialogTitle>Cài đặt</DialogTitle><DialogDescription>Chỉnh những thứ hay dùng. Các thông số kỹ thuật nằm trong tab Nâng cao.</DialogDescription>
    <Tabs defaultValue="basic" className="mt-5"><TabsList className="grid w-full grid-cols-4"><TabsTrigger value="basic">Cơ bản</TabsTrigger><TabsTrigger value="ai">AI</TabsTrigger><TabsTrigger value="advanced">Nâng cao</TabsTrigger><TabsTrigger value="validate">Kiểm tra</TabsTrigger></TabsList>
      <TabsContent value="basic"><div className="settings-grid">
        <SettingSection title="Giọng đọc mặc định" icon={FileAudio}>
          <Field label="Ngôn ngữ hay dùng"><Select value={normalizeVoiceLanguage(settings.text_to_voice_language||"en")} onValueChange={v=>setSettings({...settings,text_to_voice_language:v})} options={voiceLanguageOptions}/></Field>
          <div className="setting-note">Nếu không chắc, giữ nguyên. Người dùng vẫn có thể chọn giọng cụ thể ở Bước 2.</div>
        </SettingSection>
        <SettingSection title="Ảnh và video" icon={Image}>
          <Switch checked={settings.image_ai_validation_enabled!==false} onCheckedChange={v=>setSettings({...settings,image_ai_validation_enabled:v})} label="AI kiểm tra ảnh có đúng nội dung"/>
          <Switch checked={settings.image_enhance_enabled!==false} onCheckedChange={v=>setSettings({...settings,image_enhance_enabled:v})} label="Làm nét ảnh sau khi tải"/>
          <div className="setting-note">Khuyến nghị: bật cả hai mục trên để ảnh ít sai hơn và đủ nét khi xuất CapCut.</div>
        </SettingSection>
      </div></TabsContent>
      <TabsContent value="ai">
        <SettingSection title="AI dùng để hiểu nội dung và kiểm ảnh" icon={Bot}>
          <Field label="Nhà cung cấp">
            <Select
              value={settings.keyword_ai_provider||"auto"}
              onValueChange={v=>setSettings({...settings,keyword_ai_provider:v})}
              options={[
                {value:"auto",label:"Tự động"},
                {value:"kiro",label:"Kiro / Claude proxy"},
                {value:"claude",label:"Claude"},
                {value:"gemini",label:"Gemini"},
                {value:"openai",label:"OpenAI"},
              ]}
            />
          </Field>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Kiro API key">
              <div className="relative"><Input type={showKey?"text":"password"} className="pr-11" value={settings.kiro_api_key||""} onChange={e=>setSettings({...settings,kiro_api_key:e.target.value})}/><button type="button" onClick={()=>setShowKey(v=>!v)} aria-label={showKey?"Ẩn key":"Hiện key"} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-zinc-500 hover:bg-white/10 hover:text-white">{showKey?<EyeOff className="h-4 w-4"/>:<Eye className="h-4 w-4"/>}</button></div>
            </Field>
            <Field label="Model Kiro">
              <Input value={settings.kiro_keyword_model||"kr/claude-opus-4.8"} onChange={e=>setSettings({...settings,kiro_keyword_model:e.target.value})}/>
            </Field>
            <Field label="Kiro endpoint">
              <Input value={settings.kiro_api_base||"https://xapi.labpinky.com/v1"} onChange={e=>setSettings({...settings,kiro_api_base:e.target.value})}/>
            </Field>
            <Field label="Claude API key">
              <div className="relative"><Input type={showKey?"text":"password"} className="pr-11" value={settings.claude_api_key||""} onChange={e=>setSettings({...settings,claude_api_key:e.target.value})}/><button type="button" onClick={()=>setShowKey(v=>!v)} aria-label={showKey?"Ẩn key":"Hiện key"} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-zinc-500 hover:bg-white/10 hover:text-white">{showKey?<EyeOff className="h-4 w-4"/>:<Eye className="h-4 w-4"/>}</button></div>
            </Field>
            <Field label="Model Claude">
              <Input value={settings.claude_keyword_model||"claude-sonnet-4-20250514"} onChange={e=>setSettings({...settings,claude_keyword_model:e.target.value})}/>
            </Field>
            <Field label="Gemini API key">
              <div className="relative"><Input type={showKey?"text":"password"} className="pr-11" value={settings.gemini_api_key||""} onChange={e=>setSettings({...settings,gemini_api_key:e.target.value})}/><button type="button" onClick={()=>setShowKey(v=>!v)} aria-label={showKey?"Ẩn key":"Hiện key"} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-zinc-500 hover:bg-white/10 hover:text-white">{showKey?<EyeOff className="h-4 w-4"/>:<Eye className="h-4 w-4"/>}</button></div>
            </Field>
            <Field label="Model Gemini">
              <Input value={settings.gemini_keyword_model||"gemini-2.5-flash"} onChange={e=>setSettings({...settings,gemini_keyword_model:e.target.value})}/>
            </Field>
          </div>
          <div className="setting-note">Khuyên dùng: Kiro/Claude cho hiểu ngữ cảnh và tạo keyword, Gemini cho kiểm ảnh. Với key Kiro hiện tại, base URL là https://xapi.labpinky.com/v1 và model có dạng kr/claude-... Nếu để Tự động, tool sẽ ưu tiên Kiro khi có key, rồi OpenAI, Claude, Gemini.</div>
        </SettingSection>
      </TabsContent>
      <TabsContent value="advanced"><div className="settings-grid">
        <SettingSection title="Clone giọng (MagicVoice)" icon={Mic}>
          <Field label="Thiết bị xử lý"><Select value={settings.magicvoice_device||"auto"} onValueChange={v=>setSettings({...settings,magicvoice_device:v})} options={[{value:"auto",label:"Tự động (ưu tiên CUDA)"},{value:"cuda",label:"CUDA (GPU)"},{value:"cpu",label:"CPU"}]}/></Field>
          <div className="setting-note">Chọn CPU nếu gặp lỗi CUDA hoặc cuDNN. CPU chậm hơn nhưng ổn định hơn.</div>
        </SettingSection>
        <SettingSection title="Cảnh và chất lượng hình ảnh" icon={Aperture}><Switch checked={!!settings.whisper_timing_enabled} onCheckedChange={v=>setSettings({...settings,whisper_timing_enabled:v})} label="Căn lời đọc chính xác theo thời gian"/><Switch checked={!!settings.scene_ai_enabled} onCheckedChange={v=>setSettings({...settings,scene_ai_enabled:v})} label="Tự gom các câu cùng ý thành một cảnh"/><div className="grid grid-cols-2 gap-4"><Field label="Cảnh ngắn nhất gợi ý (giây)"><Input type="number" min={1} step={1} value={settings.scene_min_seconds??4} onChange={e=>setNum("scene_min_seconds",e.target.value,4)}/></Field><Field label="Cảnh dài nhất gợi ý (giây)"><Input type="number" min={1} step={1} value={settings.scene_target_max_seconds??25} onChange={e=>setNum("scene_target_max_seconds",e.target.value,25)}/></Field><Field label="Chiều rộng video"><Input type="number" min={16} step={2} value={settings.image_target_width??1920} onChange={e=>setNum("image_target_width",e.target.value,1920)}/></Field><Field label="Chiều cao video"><Input type="number" min={16} step={2} value={settings.image_target_height??1080} onChange={e=>setNum("image_target_height",e.target.value,1080)}/></Field></div><div className="setting-note">AI vẫn ưu tiên chia theo ý/cảnh visual. Thời lượng chỉ là gợi ý mềm để tránh cảnh quá vụn hoặc quá dài.</div></SettingSection>
      </div></TabsContent>
      <TabsContent value="validate"><SettingSection title="Kiểm tra cấu hình máy" icon={CheckCircle2}><Button onClick={runPreflight} disabled={preflightBusy}>{preflightBusy?<LoaderCircle className="h-4 w-4 animate-spin"/>:<RefreshCw className="h-4 w-4"/>}{preflightBusy?"Đang kiểm tra...":"Chạy kiểm tra"}</Button><div className="grid grid-cols-2 gap-3">{(preflight?.checks||[]).map(x=><CheckRow key={x.id} ok={x.ok} label={x.label}/>)}</div></SettingSection></TabsContent>
    </Tabs><div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={()=>onOpenChange(false)}>Hủy</Button><Button onClick={()=>saveSettings(true)}>Lưu cài đặt</Button></div></DialogContent></Dialog>
}

function ProjectsModal({ open, onOpenChange, state, project, openProject, renameProject, deleteProject }) {
  const [editingProject, setEditingProject] = useState(null)
  const [deletingProject, setDeletingProject] = useState(null)
  const [editingName, setEditingName] = useState("")
  const beginRename = (item) => {
    setEditingProject(item)
    setEditingName(item.name || "")
  }
  const confirmRename = async () => {
    if (!editingProject || !editingName.trim()) return
    await renameProject(editingProject.path, editingName.trim())
    setEditingProject(null)
  }
  const confirmDelete = async () => {
    if (!deletingProject) return
    await deleteProject(deletingProject.path, deletingProject.name)
    setDeletingProject(null)
  }
  return <>
    <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-w-3xl"><DialogTitle>Project gần đây</DialogTitle><DialogDescription>Chọn project muốn làm tiếp, đổi tên hoặc xóa project không cần nữa.</DialogDescription><div className="project-list">{state.projects?.map(item=>{
    const isOpen = project?.path===item.path
    return <div className={cn("project-row managed", isOpen && "active")} key={item.path}>
      <button onClick={()=>openProject(item.path)}><FolderOpen/><div><b>{item.name}</b><small>{item.category ? `${item.category} · ` : ""}{formatProjectDate(item.updated_at)} · {shortPath(item.path)}</small></div>{isOpen&&<Badge>Đang mở</Badge>}</button>
      <div className="project-row-actions">
        <Button size="sm" variant="ghost" onClick={()=>beginRename(item)}><Pencil className="h-3.5 w-3.5"/> Đổi tên</Button>
        <Button size="sm" variant="ghost" onClick={()=>setDeletingProject(item)}><Trash2 className="h-3.5 w-3.5"/> Xóa</Button>
      </div>
    </div>
  })}</div></DialogContent></Dialog>
    <Dialog open={!!editingProject} onOpenChange={(value)=>!value&&setEditingProject(null)}>
      <DialogContent className="max-w-md">
        <DialogTitle>Đổi tên project</DialogTitle>
        <DialogDescription>Tên mới sẽ được dùng ở trang chủ và danh sách project.</DialogDescription>
        <Field label="Tên project"><Input autoFocus value={editingName} onChange={(event)=>setEditingName(event.target.value)} onKeyDown={(event)=>event.key==="Enter"&&confirmRename()} maxLength={120} /></Field>
        <div className="dialog-actions"><Button variant="secondary" onClick={()=>setEditingProject(null)}>Hủy</Button><Button disabled={!editingName.trim()} onClick={confirmRename}>Lưu tên mới</Button></div>
      </DialogContent>
    </Dialog>
    <Dialog open={!!deletingProject} onOpenChange={(value)=>!value&&setDeletingProject(null)}>
      <DialogContent className="max-w-md">
        <DialogTitle>Xóa project này?</DialogTitle>
        <DialogDescription>Project “{deletingProject?.name}” và dữ liệu bên trong sẽ bị xóa. Thao tác này không thể hoàn tác.</DialogDescription>
        <div className="dialog-actions"><Button variant="secondary" onClick={()=>setDeletingProject(null)}>Giữ lại</Button><Button variant="danger" onClick={confirmDelete}><Trash2 className="h-4 w-4"/> Xóa project</Button></div>
      </DialogContent>
    </Dialog>
  </>
}

function DashboardScreen({ series, allReady, runPreflight, preflightChecks, onOpenSeries, onCreateSeries, setError, flows = [] }) {
  const [createOpen, setCreateOpen] = useState(false)
  const hasAny = series.length > 0
  const totalVideos = series.reduce((acc, s) => acc + (s.video_count || 0), 0)
  const realSeries = series.filter(s => !s.is_virtual)

  return (
    <main className="dashboard-home fade-in-up">

      {/* Hero banner — always visible, adapts based on whether projects exist */}
      <section className="dashboard-hero">
        <div className="dashboard-hero-content">
          <span className="home-kicker">AI VIDEO PRODUCTION</span>
          <h1 className="dashboard-hero-title">
            {hasAny ? "Dự án của bạn" : "Tạo video bằng AI\nchưa bao giờ dễ hơn"}
          </h1>
          <p className="dashboard-hero-sub">
            {hasAny
              ? `${realSeries.length} dự án · ${totalVideos} video. Chọn một Dự án để tiếp tục hoặc tạo mới.`
              : "Nhập kịch bản, chọn giọng đọc, tool tự chia cảnh, tìm ảnh và xuất thẳng vào CapCut."}
          </p>
          <div className="dashboard-hero-cta">
            <Button size="lg" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" /> Tạo Dự án mới
            </Button>
            {!allReady && (
              <button className="dashboard-setup-btn" onClick={runPreflight}>
                <RefreshCw className="h-3.5 w-3.5" />
                Kiểm tra cấu hình ({preflightChecks.filter(c => c.ok).length}/{preflightChecks.length})
              </button>
            )}
          </div>
        </div>
        <div className="dashboard-hero-readiness">
          <div className={cn("ready-orb", allReady && "ok")}>
            <CheckCircle2 className="h-7 w-7" />
          </div>
          <b>{allReady ? "Sẵn sàng tạo video" : "Cần thiết lập lần đầu"}</b>
          <p>{allReady ? "Mọi thứ đã được chuẩn bị. Bắt đầu bằng cách tạo Dự án." : "Bấm Kiểm tra cấu hình để tool hướng dẫn từng bước."}</p>
          {!allReady && <Button variant="secondary" size="sm" onClick={runPreflight}><RefreshCw className="h-4 w-4" /> Kiểm tra và hướng dẫn</Button>}
        </div>
      </section>

      {/* Process strip — only when no projects yet */}
      {!hasAny && (
        <section className="home-process-strip fade-in-up delay-100">
          {[
            ["1", "Nhập nội dung", "Dán script hoặc tải TXT, hoặc dùng AI viết kịch bản"],
            ["2", "Chọn giọng", "Giọng có sẵn hoặc clone giọng của bạn"],
            ["3", "Duyệt media", "Tìm lại, tải lên, duyệt từng cảnh"],
            ["4", "Xuất CapCut", "Mở project để chỉnh sửa và xuất video"],
          ].map(([num, title, desc]) => (
            <div key={num}>
              <span>{num}</span>
              <b>{title}</b>
              <small>{desc}</small>
            </div>
          ))}
        </section>
      )}

      {/* Series grid — only when projects exist */}
      {hasAny && (
        <div className="series-grid">
          {series.map(s => (
            <div
              key={s.path || "virtual"}
              className={cn("series-card glass-card", s.is_virtual && "virtual")}
              onClick={() => onOpenSeries(s)}
              role="button"
              tabIndex={0}
              onKeyDown={e => e.key === "Enter" && onOpenSeries(s)}
            >
              <div className="series-card-icon">
                {s.is_virtual ? <Film className="h-5 w-5" /> : <FolderOpen className="h-5 w-5" />}
              </div>
              <div className="series-card-body">
                <b className="series-card-title">{s.title}</b>
                {s.description && <p className="series-card-desc">{s.description}</p>}
                <div className="series-card-meta">
                  <span className="series-card-count">{s.video_count} video</span>
                  {s.latest_updated_at > 0 && <span className="series-card-date">{formatProjectDate(s.latest_updated_at)}</span>}
                </div>
              </div>
              <div className="series-card-arrow"><ChevronRight className="h-4 w-4 text-zinc-500" /></div>
            </div>
          ))}
        </div>
      )}

      <CreateSeriesDialog open={createOpen} onOpenChange={setCreateOpen} onCreateSeries={onCreateSeries} flows={flows} setError={setError} onSuccess={onOpenSeries} />
    </main>
  )
}

function CreateSeriesDialog({ open, onOpenChange, onCreateSeries, flows = [], setError, onSuccess }) {
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const [flowId, setFlowId] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const reset = () => { setTitle(""); setDescription(""); setFlowId(""); setErr(""); setBusy(false) }
  useEffect(() => { if (!open) reset() }, [open])
  // Default the flow to the first available one when the dialog opens.
  useEffect(() => { if (open && flows.length > 0) setFlowId(current => current || flows[0].id) }, [open, flows])
  const submit = async () => {
    if (!title.trim()) return setErr("Hãy nhập tên Dự án.")
    setBusy(true)
    setErr("")
    try {
      const created = await onCreateSeries(title.trim(), description.trim(), flowId)
      onOpenChange(false)
      if (onSuccess && created) onSuccess(created)
    } catch (e) {
      setErr(e.message || "Tạo thất bại.")
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogTitle>Tạo Dự án mới</DialogTitle>
        <DialogDescription>Dự án là nhóm chứa nhiều video cùng chủ đề.</DialogDescription>
        <Field label="Tên Dự án">
          <Input autoFocus value={title} onChange={e => setTitle(e.target.value)} onKeyDown={e => e.key === "Enter" && submit()} placeholder="Ví dụ: Bóng đá, Khoa học vũ trụ..." maxLength={80} />
        </Field>
        <Field label="Mô tả (tuỳ chọn)">
          <Input value={description} onChange={e => setDescription(e.target.value)} placeholder="Ví dụ: Series bình luận các trận đấu lớn" maxLength={200} />
        </Field>
        {flows.length > 0 && (
          <Field label="Flow mặc định cho Dự án">
            <Select
              value={flowId || "__none__"}
              onValueChange={v => setFlowId(v === "__none__" ? "" : v)}
              options={[{ value: "__none__", label: "— Không gắn flow —" }, ...flows.map(f => ({ value: f.id, label: f.name }))]}
            />
          </Field>
        )}
        {flows.length > 0 && <p className="text-xs text-zinc-500">Video mới trong Dự án sẽ dùng flow này; bạn vẫn có thể đổi flow ở từng video.</p>}
        {err && <p className="text-sm text-red-400">{err}</p>}
        <div className="dialog-actions">
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Hủy</Button>
          <Button onClick={submit} disabled={!title.trim() || busy}>{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null} Tạo Dự án</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ProjectDetailScreen({ activeSeries, allProjects, onBack, onOpenVideo, onNewVideo, onDeleteSeries, onDeleteVideo, onUpdateSeries, setError, flows = [] }) {
  const [editTitle, setEditTitle] = useState(activeSeries?.title || "")
  const [editDesc, setEditDesc] = useState(activeSeries?.description || "")
  const [editMode, setEditMode] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [videoToDelete, setVideoToDelete] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setEditTitle(activeSeries?.title || "")
    setEditDesc(activeSeries?.description || "")
    setEditMode(false)
  }, [activeSeries?.path])
  if (!activeSeries) return null
  const videos = allProjects.filter(p => p.category === activeSeries.title || (activeSeries.is_virtual && !p.category))
  const saveEdit = async () => {
    if (!editTitle.trim()) return
    setBusy(true)
    try {
      await onUpdateSeries(activeSeries.path, editTitle.trim(), editDesc.trim())
      setEditMode(false)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return (
    <main className="project-detail fade-in-up">
      <div className="project-detail-header">
        <button className="project-detail-back" onClick={onBack}><ArrowLeft className="h-4 w-4" /> Tất cả Dự án</button>
        {editMode ? (
          <div className="project-detail-edit-row">
            <Input autoFocus value={editTitle} onChange={e => setEditTitle(e.target.value)} className="text-lg font-bold" maxLength={80} onKeyDown={e => e.key === "Enter" && saveEdit()} />
            <Input value={editDesc} onChange={e => setEditDesc(e.target.value)} placeholder="Mô tả..." maxLength={200} />
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setEditMode(false)}>Hủy</Button>
              <Button onClick={saveEdit} disabled={busy || !editTitle.trim()}>{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null} Lưu</Button>
            </div>
          </div>
        ) : (
          <div className="project-detail-title-row">
            <div>
              <h1 className="project-detail-title">{activeSeries.title}</h1>
              {activeSeries.description && <p className="project-detail-desc">{activeSeries.description}</p>}
            </div>
            {!activeSeries.is_virtual && (
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => setEditMode(true)}><Pencil className="h-4 w-4" /> Sửa</Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}><Trash2 className="h-4 w-4 text-red-400" /></Button>
              </div>
            )}
          </div>
        )}
        <div className="project-detail-stats">
          <span>{videos.length} video</span>
          {activeSeries.is_virtual && <Badge>Chưa phân nhóm</Badge>}
        </div>
      </div>

      {!activeSeries.is_virtual && flows.length > 0 && (
        <div className="project-detail-flow-row">
          <Field label="Flow mặc định cho Dự án">
            <Select
              value={activeSeries.default_flow_id || "__none__"}
              onValueChange={id => onUpdateSeries(activeSeries.path, null, null, id === "__none__" ? null : id)}
              options={[{ value: "__none__", label: "— Không gắn flow —" }, ...flows.map(f => ({ value: f.id, label: f.name }))]}
            />
          </Field>
        </div>
      )}

      <div className="project-detail-actions">
        <Button onClick={onNewVideo}><Plus className="h-4 w-4" /> Tạo video mới</Button>
      </div>

      {videos.length === 0 ? (
        <div className="project-detail-empty">
          <Film className="h-10 w-10 text-zinc-600" />
          <p>Dự án này chưa có video nào.</p>
          <Button onClick={onNewVideo}><Plus className="h-4 w-4" /> Tạo video đầu tiên</Button>
        </div>
      ) : (
        <div className="video-grid">
          {videos.map(v => (
            <div key={v.path} className="video-card glass-card" onClick={() => onOpenVideo(v.path)} role="button" tabIndex={0} onKeyDown={e => e.key === "Enter" && onOpenVideo(v.path)}>
              <div className="video-card-title"><Film className="h-4 w-4 text-violet-400 flex-shrink-0" /><b className="truncate">{v.name}</b></div>
              <div className="video-card-status-dots">
                <span className={cn("status-dot", v.has_voice !== false && "done")} title="Giọng đọc" />
                <span className={cn("status-dot", v.has_scenes !== false && "done")} title="Phân cảnh" />
                <span className={cn("status-dot", v.has_capcut_export !== false && "done")} title="Xuất CapCut" />
              </div>
              <div className="video-card-date">{formatProjectDate(v.updated_at)}</div>
              <button
                className="video-card-delete"
                title="Xóa video"
                onClick={(e) => { e.stopPropagation(); setVideoToDelete(v) }}
              ><Trash2 className="h-4 w-4" /></button>
              <ChevronRight className="h-4 w-4 text-zinc-600 flex-shrink-0" />
            </div>
          ))}
        </div>
      )}

      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent className="max-w-md">
          <DialogTitle>Xóa Dự án này?</DialogTitle>
          <DialogDescription>Toàn bộ video và dữ liệu trong "{activeSeries.title}" sẽ bị xóa vĩnh viễn. Thao tác này không thể hoàn tác.</DialogDescription>
          <div className="dialog-actions">
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>Giữ lại</Button>
            <Button variant="danger" onClick={() => { setConfirmDelete(false); onDeleteSeries(activeSeries.path) }}><Trash2 className="h-4 w-4" /> Xóa Dự án</Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(videoToDelete)} onOpenChange={(open) => !open && setVideoToDelete(null)}>
        <DialogContent className="max-w-md">
          <DialogTitle>Xóa video này?</DialogTitle>
          <DialogDescription>Toàn bộ kịch bản, giọng đọc, media và dữ liệu của "{videoToDelete?.name}" sẽ bị xóa vĩnh viễn. Thao tác này không thể hoàn tác.</DialogDescription>
          <div className="dialog-actions">
            <Button variant="secondary" onClick={() => setVideoToDelete(null)}>Giữ lại</Button>
            <Button variant="danger" onClick={() => { const target = videoToDelete; setVideoToDelete(null); onDeleteVideo(target.path, target.name) }}><Trash2 className="h-4 w-4" /> Xóa video</Button>
          </div>
        </DialogContent>
      </Dialog>
    </main>
  )
}

function HelpModal({ open, onOpenChange }) {
  const steps = [
    ["1", "Nhập nội dung", "Dán kịch bản hoặc tải file TXT, sau đó lưu để sang bước chọn giọng."],
    ["2", "Tạo giọng đọc", "Chọn giọng có sẵn hoặc giọng đã clone, nghe thử rồi bấm Tạo giọng đọc."],
    ["3", "Duyệt hình ảnh", "Cảnh chưa phù hợp có thể Tìm lại hoặc Tải lên media từ máy."],
    ["4", "Xuất CapCut", "Duyệt đủ các cảnh, kiểm tra cấu hình rồi bấm Xuất và mở CapCut."],
  ]
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="max-w-2xl">
      <DialogTitle>Cách tạo một video</DialogTitle>
      <DialogDescription>Làm lần lượt bốn bước dưới đây. Tool sẽ báo rõ khi bước hiện tại hoàn thành.</DialogDescription>
      <div className="help-step-list">
        {steps.map(([number, title, description]) => <div key={number}><span>{number}</span><div><b>{title}</b><p>{description}</p></div></div>)}
      </div>
      <div className="setting-note">Khi gặp lỗi, đọc thông báo ở góc phải. Nếu một ảnh chưa đúng, chỉ cần bấm Tìm lại tại cảnh đó.</div>
      <div className="dialog-actions"><Button onClick={()=>onOpenChange(false)}>Đã hiểu</Button></div>
    </DialogContent>
  </Dialog>
}

function SceneAudioClip({ src, start, end }) {
  const audioRef = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const duration = Math.max(0.1, Number(end || 0) - Number(start || 0))
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.pause()
    setPlaying(false)
    setPosition(0)
  }, [src, start, end])
  const toggle = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (!audio.paused) {
      audio.pause()
      setPlaying(false)
      return
    }
    if (audio.currentTime < Number(start || 0) || audio.currentTime >= Number(end || 0)) {
      audio.currentTime = Number(start || 0)
    }
    try {
      await audio.play()
      setPlaying(true)
    } catch {
      setPlaying(false)
    }
  }
  const update = () => {
    const audio = audioRef.current
    if (!audio) return
    const elapsed = Math.max(0, audio.currentTime - Number(start || 0))
    setPosition(Math.min(duration, elapsed))
    if (audio.currentTime >= Number(end || 0)) {
      audio.pause()
      audio.currentTime = Number(start || 0)
      setPlaying(false)
      setPosition(0)
    }
  }
  if (!src) return null
  return <div className="scene-audio-clip">
    <audio ref={audioRef} src={src} preload="metadata" onTimeUpdate={update} onPause={()=>setPlaying(false)} />
    <Button size="sm" variant="secondary" onClick={toggle}>{playing?<Pause/>:<Play/>}{playing?"Dừng":"Nghe đoạn voice"}</Button>
    <div><i><em style={{width:`${Math.min(100,(position/duration)*100)}%`}} /></i><span>{formatTime(position)} / {formatTime(duration)}</span></div>
  </div>
}

function Lightbox({ open, setLightboxIndex, lightboxIndex, assets, project, lightboxAsset, assetJobs, statusBadge, startJob, approveAsset, chooseAssetMedia, editingAssetId, setEditingAssetId, editingKeywordValue, setEditingKeywordValue, saveKeyword }) {
  if (!lightboxAsset) return null
  const job = assetJobs.get(lightboxAsset.asset_id)
  const badge = statusBadge(lightboxAsset.status)
  const version = lightboxAsset.media_version || lightboxAsset.sha256 || lightboxAsset.search_attempt
  const isVideo = /\.(mp4|webm|mov|mkv)$/i.test(lightboxAsset.local_path || "")
  const sceneNumber = lightboxIndex + 1
  const source = lightboxAsset.source_page || lightboxAsset.source_url || "Media tải từ máy hoặc nguồn tìm kiếm tự động"
  return <Dialog open={open} onOpenChange={value=>!value&&setLightboxIndex(null)}>
    <DialogContent className="preview-dialog scene-detail-dialog max-w-6xl p-0">
      <div className="scene-detail-title"><Film/><div><DialogTitle>Cảnh {sceneNumber}: {lightboxAsset.main_subject || lightboxAsset.asset_id}</DialogTitle><DialogDescription>{formatTime(lightboxAsset.start)} - {formatTime(lightboxAsset.end)} · {Number(lightboxAsset.duration||0).toFixed(1)} giây</DialogDescription></div></div>
      <div className="scene-detail-content">
        <div className="scene-detail-preview">
          <div className="scene-preview-frame">
            {lightboxAsset.local_path ? (isVideo
              ? <video controls src={mediaUrl(lightboxAsset.local_path,version)} />
              : <img src={mediaUrl(lightboxAsset.local_path,version)} alt={`Cảnh ${sceneNumber}`} />)
              : <div className="scene-preview-empty"><Image/><b>Chưa có ảnh hoặc video</b><span>Bấm Tìm lại hoặc Tải lên để bổ sung media cho cảnh này.</span></div>}
            {job&&<div className="media-busy"><LoaderCircle className="h-8 w-8 animate-spin"/>{job.status==="queued"?`Đang chờ #${job.queue_position}`:"Đang tìm media phù hợp..."}</div>}
          </div>
          <div className="scene-preview-timeline"><span>{formatTime(lightboxAsset.start)}</span><i/><span>{formatTime(lightboxAsset.end)}</span></div>
          <SceneAudioClip src={mediaUrl(project?.voice_path)} start={lightboxAsset.start} end={lightboxAsset.end} />
          <div className="scene-dialog-script"><span>Lời đọc trong cảnh</span><p>{lightboxAsset.sentence_text || "Chưa có nội dung lời đọc."}</p></div>
        </div>
        <aside className="scene-detail-sidebar">
          <section><label>Từ khóa tìm ảnh</label>
            {editingAssetId===lightboxAsset.asset_id
              ? <div className="scene-keyword-edit"><Input autoFocus value={editingKeywordValue} onChange={e=>setEditingKeywordValue(e.target.value)} onKeyDown={e=>e.key==="Enter"&&saveKeyword(lightboxAsset.asset_id,editingKeywordValue)}/><Button size="sm" onClick={()=>saveKeyword(lightboxAsset.asset_id,editingKeywordValue)}>Lưu</Button></div>
              : <button className="scene-keyword" onClick={()=>{setEditingAssetId(lightboxAsset.asset_id);setEditingKeywordValue(lightboxAsset.keyword||"")}}><span>{lightboxAsset.keyword || "Chưa có từ khóa"}</span><Pencil/></button>}
          </section>
          <section><label>Ngữ cảnh AI đã hiểu</label><p>{[lightboxAsset.main_subject, lightboxAsset.action_context, lightboxAsset.visual_intent].filter(Boolean).join(" · ") || lightboxAsset.scene_break_reason || "Chưa có phân tích ngữ cảnh."}</p></section>
          <section><label>Nguồn</label><p className="scene-source">{source}</p></section>
          <section><label>Trạng thái</label><Badge variant={badge.variant}>{badge.label}</Badge></section>
          {lightboxAsset.error&&<div className="scene-detail-error"><AlertTriangle/><span>{lightboxAsset.error}</span></div>}
          <div className="scene-detail-actions">
            <Button variant="secondary" disabled={!!job} onClick={()=>startJob(`/api/assets/${lightboxAsset.asset_id}/retry`,undefined,`retry-${lightboxAsset.asset_id}`)}><RefreshCw/> Tìm lại ảnh</Button>
            <Button variant="secondary" onClick={()=>chooseAssetMedia(lightboxAsset.asset_id)}><Upload/> Tải media thay thế</Button>
            <Button variant={lightboxAsset.status==="approved"?"success":"default"} disabled={!lightboxAsset.local_path} onClick={()=>approveAsset(lightboxAsset.asset_id)}><Check/> {lightboxAsset.status==="approved"?"Đã duyệt cảnh này":"Duyệt cảnh này"}</Button>
          </div>
        </aside>
      </div>
      <div className="scene-detail-footer">
        <Button variant="secondary" disabled={lightboxIndex<=0} onClick={()=>setLightboxIndex(index=>Math.max(0,index-1))}><ArrowLeft/> Cảnh trước</Button>
        <span>{sceneNumber} / {assets.length}</span>
        <Button variant="secondary" disabled={lightboxIndex>=assets.length-1} onClick={()=>setLightboxIndex(index=>Math.min(assets.length-1,index+1))}>Cảnh sau <ArrowRight/></Button>
      </div>
    </DialogContent>
  </Dialog>
}

function formatProjectDate(value) {
  const raw = Number(value || 0)
  if (!raw) return "Chưa rõ thời gian"
  try {
    return new Date(raw * 1000).toLocaleString("vi-VN", { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" })
  } catch {
    return "Chưa rõ thời gian"
  }
}

function shortPath(path = "") {
  const parts = String(path).split(/[\\/]+/).filter(Boolean)
  if (parts.length <= 3) return String(path)
  return `...\\${parts.slice(-3).join("\\")}`
}

function Metric({ value, label, accent }) {
  return <div className="px-3 py-4 text-center"><div className={cn("text-lg font-semibold", accent ? "text-emerald-300" : "text-zinc-200")}>{value}</div><div className="mt-1 text-[10px] uppercase tracking-wider text-zinc-600">{label}</div></div>
}

function SettingSection({ title, icon: Icon, children }) {
  return <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-4"><div className="mb-4 flex items-center gap-2 text-sm font-medium"><Icon className="h-4 w-4 text-violet-400" />{title}</div><div className="space-y-4">{children}</div></div>
}

function Field({ label, children }) {
  return <label className="block min-w-0"><span className="mb-1.5 block text-[12px] font-medium text-zinc-500">{label}</span>{children}</label>
}

function FlowsModal({ open, onClose, flows, onCreate, onUpdate, onDelete }) {
  const [selectedId, setSelectedId] = useState(null)
  const [selectedStepIdx, setSelectedStepIdx] = useState(0)
  const [isNew, setIsNew] = useState(false)
  const [editName, setEditName] = useState("")
  const [editDesc, setEditDesc] = useState("")
  const [editSteps, setEditSteps] = useState([])
  const [busy, setBusy] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)

  const selectedFlow = flows.find(f => f.id === selectedId) || null

  useEffect(() => {
    if (open && !selectedId && !isNew && flows.length > 0) {
      selectFlow(flows[0].id)
    }
  }, [open, flows])

  function selectFlow(id) {
    const flow = flows.find(f => f.id === id)
    if (!flow) return
    setSelectedId(id)
    setIsNew(false)
    setEditName(flow.name)
    setEditDesc(flow.description || "")
    setEditSteps(flow.steps ? [...flow.steps] : [])
    setSelectedStepIdx(0)
  }

  function startNew() {
    setSelectedId(null)
    setIsNew(true)
    setEditName("")
    setEditDesc("")
    setEditSteps([...defaultSteps])
    setSelectedStepIdx(0)
  }

  async function save() {
    if (!editName.trim()) return
    setBusy(true)
    try {
      if (isNew) {
        const flow = await onCreate(editName.trim(), editDesc.trim(), editSteps)
        setSelectedId(flow.id)
        setIsNew(false)
      } else {
        await onUpdate(selectedId, { name: editName.trim(), description: editDesc.trim(), steps: editSteps })
      }
    } finally {
      setBusy(false)
    }
  }

  async function remove(id) {
    setBusy(true)
    try {
      await onDelete(id)
      setConfirmDeleteId(null)
      const next = flows.find(f => f.id !== id)
      if (next) selectFlow(next.id)
      else { setSelectedId(null); setIsNew(false) }
    } finally {
      setBusy(false)
    }
  }

  const updateStep = (idx, patch) => setEditSteps(steps => steps.map((s, i) => i === idx ? { ...s, ...patch } : s))
  const addStep = () => {
    const newIdx = editSteps.length
    setEditSteps(steps => [...steps, { name: "Bước mới", prompt: "", enabled: true }])
    setSelectedStepIdx(newIdx)
  }
  const removeStep = (idx) => {
    setEditSteps(steps => steps.filter((_, i) => i !== idx))
    setSelectedStepIdx(prev => Math.max(0, Math.min(prev, editSteps.length - 2)))
  }
  const moveStep = (idx, dir) => {
    const target = idx + dir
    if (target < 0 || target >= editSteps.length) return
    setEditSteps(steps => { const next = [...steps]; ;[next[idx], next[target]] = [next[target], next[idx]]; return next })
    setSelectedStepIdx(target)
  }

  const currentStep = editSteps[selectedStepIdx] ?? null
  const hasEditor = selectedFlow || isNew

  if (!open) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box flows-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div className="flex items-center gap-2"><Layers className="h-4 w-4 text-violet-400" /><h2>Kho Flow</h2></div>
          <button className="modal-close" onClick={onClose}><X className="h-4 w-4" /></button>
        </div>
        <div className="flows-modal-layout">

          {/* Pane 1: Flow library list */}
          <div className="flows-list">
            <div className="flows-list-header">Thư viện flow</div>
            {flows.map(flow => (
              <button key={flow.id} className={cn("flow-list-item", selectedId === flow.id && !isNew && "active")} onClick={() => selectFlow(flow.id)}>
                <span className="flow-list-name">{flow.name}</span>
                <span className="flow-list-meta">{flow.steps?.filter(s => s.enabled !== false).length || 0} bước</span>
              </button>
            ))}
            <button className="flow-list-add" onClick={startNew}><Plus className="h-3.5 w-3.5" /> Tạo flow mới</button>
          </div>

          {/* Pane 2: Steps of selected flow */}
          {hasEditor && (
            <div className="flows-steps-pane">
              <div className="flow-meta-compact">
                <input
                  className="flow-meta-name-input"
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  placeholder="Tên flow..."
                  maxLength={80}
                />
                <input
                  className="flow-meta-desc-input"
                  value={editDesc}
                  onChange={e => setEditDesc(e.target.value)}
                  placeholder="Mô tả ngắn về flow này..."
                  maxLength={260}
                />
              </div>
              <div className="flows-steps-pane-header">
                <span className="flows-list-header" style={{padding:0}}>Các bước</span>
                <button className="flow-add-step-btn" onClick={addStep}><Plus className="h-3.5 w-3.5" /> Thêm</button>
              </div>
              <div className="flow-steps-compact-list">
                {editSteps.length === 0 && (
                  <div className="flow-steps-empty">Chưa có bước nào</div>
                )}
                {editSteps.map((step, idx) => (
                  <button
                    key={idx}
                    className={cn("flow-step-compact-item", idx === selectedStepIdx && "active", step.enabled === false && "off")}
                    onClick={() => setSelectedStepIdx(idx)}
                  >
                    <span className="flow-step-compact-num">{idx + 1}</span>
                    <span className="flow-step-compact-name">{step.name || "Bước mới"}</span>
                    {step.enabled === false && <span className="flow-step-compact-off">Tắt</span>}
                  </button>
                ))}
              </div>
              <div className="flow-editor-actions">
                {!isNew && selectedFlow && (
                  confirmDeleteId === selectedId ? (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-red-400">Xóa flow?</span>
                      <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>Hủy</Button>
                      <Button size="sm" onClick={() => remove(selectedId)} disabled={busy}>Xóa</Button>
                    </div>
                  ) : (
                    <button className="flow-delete-btn" onClick={() => setConfirmDeleteId(selectedId)} disabled={busy}><Trash2 className="h-3.5 w-3.5" /></button>
                  )
                )}
                <Button onClick={save} disabled={busy || !editName.trim()}>
                  {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {isNew ? "Tạo flow" : "Lưu"}
                </Button>
              </div>
            </div>
          )}

          {/* Pane 3: Selected step editor */}
          <div className="flow-step-editor-pane">
            {hasEditor && currentStep ? (
              <>
                <div className="flow-step-editor-header">
                  <span className="flows-list-header" style={{padding:0}}>Bước {selectedStepIdx + 1}</span>
                  <div className="flow-step-editor-controls">
                    <label className="flow-step-enable-toggle" title="Bật/tắt bước">
                      <input type="checkbox" checked={currentStep.enabled !== false} onChange={e => updateStep(selectedStepIdx, { enabled: e.target.checked })} />
                      <span>{currentStep.enabled !== false ? "Bật" : "Tắt"}</span>
                    </label>
                    <button onClick={() => moveStep(selectedStepIdx, -1)} disabled={selectedStepIdx === 0} className="flow-step-ctrl-btn" title="Lên"><ChevronUp className="h-3.5 w-3.5" /></button>
                    <button onClick={() => moveStep(selectedStepIdx, 1)} disabled={selectedStepIdx === editSteps.length - 1} className="flow-step-ctrl-btn" title="Xuống"><ChevronDown className="h-3.5 w-3.5" /></button>
                    <button onClick={() => removeStep(selectedStepIdx)} className="flow-step-ctrl-btn danger" title="Xóa bước"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                </div>
                <div className="flow-step-editor-body">
                  <label className="flow-step-field-label">Tên bước</label>
                  <Input
                    value={currentStep.name || ""}
                    onChange={e => updateStep(selectedStepIdx, { name: e.target.value })}
                    placeholder="Tên bước..."
                    className="mb-3"
                  />
                  <label className="flow-step-field-label">Prompt AI</label>
                  <Textarea
                    value={currentStep.prompt || ""}
                    onChange={e => updateStep(selectedStepIdx, { prompt: e.target.value })}
                    placeholder="Nhập prompt cho AI ở bước này..."
                    className="flow-step-prompt-full"
                  />
                </div>
              </>
            ) : hasEditor ? (
              <div className="flow-editor-empty">
                <p>Chọn một bước từ danh sách<br />hoặc bấm "Thêm" để tạo bước mới</p>
              </div>
            ) : (
              <div className="flow-editor-empty">
                <Layers className="h-10 w-10 text-zinc-700" />
                <p>Chọn một flow để chỉnh sửa<br />hoặc tạo flow mới</p>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  )
}

export default App
