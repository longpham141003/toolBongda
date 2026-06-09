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
  ChevronRight,
  Circle,
  Clock3,
  ExternalLink,
  FileAudio,
  FileText,
  Film,
  FolderOpen,
  Image,
  KeyRound,
  LoaderCircle,
  Mic,
  MoreHorizontal,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  Search,
  Settings,
  Sparkles,
  Trash2,
  Upload,
  WandSparkles,
  X,
  XCircle,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
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

const deliveryOptions = [
  { value: "plain", label: "Mặc định" },
  { value: "natural", label: "Tự nhiên" },
  { value: "expressive", label: "Nhấn nhá" },
  { value: "dramatic", label: "Diễn cảm" },
  { value: "heavy_drama", label: "Kịch tính mạnh" },
  { value: "storytelling", label: "Kể chuyện" },
  { value: "calm", label: "Điềm tĩnh" },
]

function normalizeVoiceLanguage(language) {
  return voiceLanguageOptions.some((item) => item.value === language) ? language : "en"
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
  if (assets.length) return assets.some((item) => item.local_path) ? "step3b" : "step3a"
  if (project?.has_scenes) return "step3a"
  if (project?.has_voice) return "step2"
  return project?.script ? "step2" : "step1"
}

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
  const [title, setTitle] = useState("")
  const [settings, setSettings] = useState({})
  const [voiceOptions, setVoiceOptions] = useState([{ value: "af_heart", label: "af_heart" }])
  const [workflowInput, setWorkflowInput] = useState("")
  const [workflowSteps, setWorkflowSteps] = useState(defaultSteps)
  const [activeJob, setActiveJob] = useState(null)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState("")
  const [toast, setToast] = useState("")
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [voicePreviewBusy, setVoicePreviewBusy] = useState(false)
  const [voicePreviewUrl, setVoicePreviewUrl] = useState("")
  const [lightboxIndex, setLightboxIndex] = useState(null)
  const [busyAction, setBusyAction] = useState("")
  const [followLogs, setFollowLogs] = useState(true)
  const [editingAssetId, setEditingAssetId] = useState(null)
  const [editingKeywordValue, setEditingKeywordValue] = useState("")
  const [assetFilter, setAssetFilter] = useState("all")
  const [presetName, setPresetName] = useState("")
  const [preflight, setPreflight] = useState(null)
  const [scriptMode, setScriptMode] = useState("paste")

  const [activeScreen, setActiveScreen] = useState("home")
  const logContainerRef = useRef(null)
  const scriptFileInputRef = useRef(null)

  const loadState = useCallback(async (preserveScript = false) => {
    const data = await api("/api/state")
    setState(data)
    setSettings(data.settings || {})
    setWorkflowInput(data.settings?.script_workflow_input || "")
    setWorkflowSteps(data.settings?.script_workflow_steps?.length ? data.settings.script_workflow_steps : defaultSteps)
    if (!preserveScript) {
      setScript(data.project?.script || "")
      setTitle(data.project?.name || "")
    }
    setActiveJob(data.active_job || null)
    if (data.active_job) setLogs(data.active_job.logs || [])
    return data
  }, [])

  useEffect(() => {
    loadState().catch((err) => setError(err.message))
  }, [loadState])

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
            setToast("Đã tạo voice xong. Hãy bấm Tạo cảnh và tìm ảnh để tool tự chia cảnh và tải media.")
          } else {
            setToast(`${job.name} đã hoàn thành`)
          }
          if (job.name === "B2 Phan tich canh") setActiveScreen("step3a")
          if (job.name === "B2+B3 Chia canh va tim media") setActiveScreen("step3b")
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
  }, [activeJob?.id, activeJob?.status, loadState])

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

  const project = state?.project
  const assets = useMemo(() => project?.assets || [], [project])
  const liveJobs = state?.jobs || []

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
      if (close) setSettingsOpen(false)
      setToast("Đã lưu cài đặt")
    } catch (err) {
      setError(err.message)
    }
  }

  function workflowPresets() {
    return Array.isArray(settings.workflow_presets) ? settings.workflow_presets : []
  }

  async function saveCurrentWorkflowAsPreset() {
    const name = presetName.trim()
    if (!name) return setError("Hãy nhập tên flow trước khi lưu.")
    const id = name.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || `flow-${Date.now()}`
    const next = [
      ...workflowPresets().filter((item) => item.id !== id),
      { id, name, description: "Flow do người dùng tạo", steps: workflowSteps },
    ]
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: { ...settings, active_workflow_id: id, workflow_presets: next, script_workflow_steps: workflowSteps } }) })
    setSettings(data.settings)
    setPresetName("")
    setToast("Đã lưu flow")
  }

  function applyWorkflowPreset(id) {
    const preset = workflowPresets().find((item) => item.id === id)
    if (!preset) return
    setWorkflowSteps(preset.steps?.length ? preset.steps : defaultSteps)
    setSettings((current) => ({ ...current, active_workflow_id: id, script_workflow_steps: preset.steps || defaultSteps }))
    setToast(`Đã chọn flow: ${preset.name}`)
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
      const data = await api("/api/projects", { method: "POST", body: JSON.stringify({ title, script }) })
      setState((current) => ({ ...current, project: data.project }))
      setTitle(data.project.name)
      setToast("Đã lưu nội dung. Bước tiếp theo: tạo giọng đọc.")
      await loadState()
      setActiveScreen("step2")
    } catch (err) {
      setError(err.message)
    }
  }

  async function saveScriptStep() {
    if (!script.trim()) return setError("Hãy nhập script trước khi lưu B1.")
    if (!project) return createProject()
    try {
      const data = await api("/api/projects/script", { method: "POST", body: JSON.stringify({ script }) })
      setState((current) => ({ ...current, project: data.project }))
      setToast("Đã lưu nội dung. Bước tiếp theo: tạo giọng đọc.")
      setActiveScreen("step2")
    } catch (err) {
      setError(err.message)
    }
  }

  async function openProject(path) {
    try {
      await bestEffortCancel(false)
      const data = await api("/api/projects/open", { method: "POST", body: JSON.stringify({ path }) })
      setState((current) => ({ ...current, project: data.project }))
      setActiveJob(null)
      setLogs([])
      setScript(data.project.script)
      setTitle(data.project.name)
      setProjectsOpen(false)
      setToast("Đã mở project")
      setActiveScreen(nextScreenForProject(data.project))
    } catch (err) {
      setError(err.message)
    }
  }

  async function goHomeAndStopProject() {
    await bestEffortCancel(true)
    setState((current) => ({ ...(current || {}), project: null, active_job: null, queued_jobs: [] }))
    setActiveJob(null)
    setLogs([])
    setScript("")
    setTitle("")
    setLightboxIndex(null)
    setActiveScreen("home")
    setToast("Đã dừng tác vụ và thoát project hiện tại")
  }

  async function startNewVideo() {
    await bestEffortCancel(true)
    setState((current) => ({ ...(current || {}), project: null }))
    setScript("")
    setTitle("")
    setWorkflowInput("")
    setLogs([])
    setError("")
    setToast("")
    setLightboxIndex(null)
    setEditingAssetId(null)
    setEditingKeywordValue("")
    setAssetFilter("all")
    setPreflight(null)
    setScriptMode("paste")
    setActiveScreen("step1")
  }

  async function applyBeginnerVoicePreset() {
    const language = looksLikeEnglish(script) ? "en" : normalizeVoiceLanguage(settings.text_to_voice_language || "en")
    const options = await refreshVoices(language)
    const preferredVoice = options?.find((voice) => /heart|bella|sarah|michael/i.test(voice.value || voice.label)) || options?.[0]
    setSettings((current) => ({
      ...current,
      text_to_voice_language: language,
      text_to_voice_voice: preferredVoice?.value || current.text_to_voice_voice || "af_heart",
      text_to_voice_delivery: "natural",
      text_to_voice_speed: 1,
    }))
    setToast("Đã chọn cấu hình giọng dễ dùng. Có thể bấm Nghe thử hoặc Tạo giọng đọc.")
  }

  async function approveAsset(assetId) {
    try {
      const data = await api(`/api/assets/${assetId}/approve`, { method: "POST" })
      setState((current) => ({ ...current, project: data.project }))
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

  async function runPreflight() {
    try {
      const data = await api("/api/preflight")
      setPreflight(data)
      setToast(data.ok ? "Kiểm tra xong: cấu hình ổn" : "Kiểm tra xong: có mục cần sửa")
    } catch (err) {
      setError(err.message)
    }
  }

  async function createVoiceWithQuickSettings() {
    setError("")
    try {
      const voiceLanguage = normalizeVoiceLanguage(settings.text_to_voice_language || "en")
      const voiceSettings = {
        text_to_voice_language: voiceLanguage,
        text_to_voice_voice: settings.text_to_voice_voice || "af_heart",
        text_to_voice_delivery: settings.text_to_voice_delivery || "natural",
        text_to_voice_speed: Number(settings.text_to_voice_speed || 1),
      }
      const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: voiceSettings }) })
      setSettings(data.settings)
      await startJob("/api/voice", { script }, "voice")
    } catch (err) {
      setError(err.message)
    }
  }

  async function previewVoiceNow() {
    try {
      setVoicePreviewBusy(true)
      setVoicePreviewUrl("")
      const voiceLanguage = normalizeVoiceLanguage(settings.text_to_voice_language || "en")
      const safeSettings = {
        ...settings,
        text_to_voice_language: voiceLanguage,
      }
      const data = await api("/api/voice-preview", {
        method: "POST",
        body: JSON.stringify({
          settings: safeSettings,
          text: "",
        }),
      })
      if (data.warning) setToast(data.warning)
      setVoicePreviewUrl(`${data.url}${data.url?.includes("?") ? "&" : "?"}v=${Date.now()}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setVoicePreviewBusy(false)
    }
  }

  function updateStep(index, patch) {
    setWorkflowSteps((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  }

  function moveStep(index, direction) {
    const target = index + direction
    if (target < 0 || target >= workflowSteps.length) return
    setWorkflowSteps((items) => {
      const next = [...items]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  const flowSteps = [
    { code: "1", label: "Nội dung", hint: "Nhập chủ đề hoặc kịch bản", icon: FileText },
    { code: "2", label: "Giọng đọc", hint: "Chọn giọng, clone, tạo voice", icon: FileAudio },
    { code: "3", label: "Hình ảnh", hint: "Phân cảnh, tìm và duyệt media", icon: Image },
    { code: "4", label: "Xuất CapCut", hint: "Kiểm tra và mở project", icon: Rocket },
  ]

  const currentStepIndex = activeScreen === "step1" ? 0 : activeScreen === "step2" ? 1 : activeScreen === "step3a" || activeScreen === "step3b" ? 2 : activeScreen === "step4" ? 3 : 0

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

  return (
    <div className="stitch-app min-h-screen overflow-hidden bg-[#131315] text-[#e5e1e4]">
      <div className="aurora-bg"><div className="aurora-blob-1" /><div className="aurora-blob-2" /></div>
      <ParticleCanvas />
      <header className="stitch-topbar">
        {activeScreen !== "home" && (
          <button className="back-home-button" onClick={goHomeAndStopProject} title="Quay lại trang chủ và dừng project hiện tại">
            <ArrowLeft className="h-5 w-5" />
          </button>
        )}
        <button className="flex items-center gap-3" onClick={() => activeScreen === "home" ? undefined : goHomeAndStopProject()}>
          <div className="logo-mark"><WandSparkles className="h-5 w-5" /></div>
          <div className="text-left">
            <div className="text-[22px] font-bold tracking-tight text-white">Visual CapCut <span className="text-emerald-300">Studio</span></div>
            <div className="text-[10px] uppercase tracking-[0.24em] text-slate-500">AI video production</div>
          </div>
        </button>
        <button onClick={() => setProjectsOpen(true)} className="project-pill">
          <FolderOpen className="h-4 w-4" />
          <span className="max-w-[300px] truncate">{project?.name || "Dự án của tôi"}</span>
          <ChevronRight className="h-4 w-4 opacity-50" />
        </button>
        <div className="ml-auto flex items-center gap-3">
          <button className="top-action">Trợ giúp</button>
          <button className="icon-action" onClick={() => setSettingsOpen(true)}><Settings className="h-5 w-5" /></button>
          <div className="avatar-dot">L</div>
        </div>
      </header>

      {activeScreen === "home" ? (
        <main className="stitch-home">
          <section className="grid h-[220px] grid-cols-12 items-center gap-8 fade-in-up">
            <div className="col-span-7 flex flex-col gap-4">
              <h1 className="hero-title">Tạo video hoàn chỉnh chỉ trong 4 bước</h1>
              <p className="max-w-lg text-base leading-7 text-slate-400">Không cần biết AI hay kỹ thuật. Chỉ cần làm lần lượt từ trái sang phải.</p>
            </div>
            <div className="glass-panel col-span-5 flex h-full items-center justify-center overflow-hidden p-4">
              <div className="hero-visual">
                <div className="hero-orb hero-orb-violet" /><div className="hero-orb hero-orb-emerald" />
                <Film className="relative z-10 h-24 w-24 text-violet-200/80" />
                <Sparkles className="absolute right-16 top-12 h-8 w-8 text-emerald-200" />
              </div>
            </div>
          </section>

          <section className="glass-panel progress-rail fade-in-up delay-100">
            <div className="rail-line"><div className="rail-flow" /></div>
            {stepCards.map((step, index) => <StepPill key={step.id} index={index} active={index === 0} done={false} label={step.title} />)}
          </section>

          <section className="grid h-[200px] grid-cols-12 gap-6 fade-in-up delay-200">
            <button onClick={startNewVideo} className="glass-card-primary col-span-7 flex flex-col justify-between p-8 text-left">
              <div className="relative z-10 flex justify-between">
                <div><h2 className="text-[32px] font-semibold text-white">Tạo video mới</h2><p className="mt-2 text-sm text-slate-400">Bắt đầu luồng sáng tạo từ đầu</p></div>
                <div className="big-icon"><Plus className="h-7 w-7" /></div>
              </div>
              <span className="btn-primary w-fit">Bắt đầu ngay <ArrowRight className="h-4 w-4" /></span>
            </button>
            <button onClick={() => setProjectsOpen(true)} className="glass-card-secondary col-span-5 flex flex-col justify-between p-8 text-left">
              <div className="relative z-10 flex justify-between">
                <div><h2 className="text-[32px] font-semibold text-white">Mở project gần đây</h2><p className="mt-2 text-sm text-slate-400">Tiếp tục công việc đang dang dở</p></div>
                <div className="big-icon emerald"><FolderOpen className="h-7 w-7" /></div>
              </div>
              <span className="btn-secondary w-fit">Tiếp tục</span>
            </button>
          </section>

          <section className="flex flex-1 flex-col gap-4 fade-in-up delay-300">
            <h3 className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">Mẫu Flow Phổ Biến</h3>
            <div className="grid flex-1 grid-cols-4 gap-4">
              <FlowCard icon={Circle} title="Tin tức bóng đá" desc="Cập nhật nhanh trận đấu" />
              <FlowCard icon={Rocket} title="Khoa học & vũ trụ" desc="Kiến thức khám phá" accent="emerald" />
              <FlowCard icon={FileText} title="Kể chuyện" desc="Truyện cổ tích, tóm tắt" accent="blue" />
              <FlowCard icon={Settings} title="Tạo flow riêng" desc="Tuỳ chỉnh mọi bước" dashed onClick={() => setSettingsOpen(true)} />
            </div>
          </section>
          <footer className="home-footer"><span>Dễ sử dụng</span><span>Ảnh được AI kiểm tra</span><span>Project mở trực tiếp trong CapCut</span></footer>
        </main>
      ) : (
        <main className="stitch-workspace">
          <ProgressRail steps={stepCards} current={currentStepIndex} done={completedSteps} setActiveScreen={setActiveScreen} />
          <UserProgressPanel progress={userProgress} />
          {activeScreen === "step1" && <ScriptStepScreen
            mode={scriptMode}
            setMode={setScriptMode}
            title={title}
            setTitle={setTitle}
            script={script}
            setScript={setScript}
            scriptFileInputRef={scriptFileInputRef}
            uploadTxtFile={uploadTxtFile}
            createProject={createProject}
            saveScriptStep={saveScriptStep}
            workflowInput={workflowInput}
            setWorkflowInput={setWorkflowInput}
            workflowSteps={workflowSteps}
            settings={settings}
            workflowPresets={workflowPresets}
            applyWorkflowPreset={applyWorkflowPreset}
            startJob={startJob}
            isBusy={isBusy}
            busyAction={busyAction}
            setSettingsOpen={setSettingsOpen}
          />}
          {activeScreen === "step2" && <VoiceScreen script={script} project={project} settings={settings} setSettings={setSettings} voiceOptions={voiceOptions} refreshVoices={refreshVoices} previewVoiceNow={previewVoiceNow} voicePreviewBusy={voicePreviewBusy} voicePreviewUrl={voicePreviewUrl} createVoiceWithQuickSettings={createVoiceWithQuickSettings} startJob={startJob} applyBeginnerVoicePreset={applyBeginnerVoicePreset} isBusy={isBusy} busyAction={busyAction} setActiveScreen={setActiveScreen} />}
          {activeScreen === "step3a" && <SceneScreen assets={assets} project={project} startJob={startJob} isBusy={isBusy} busyAction={busyAction} setActiveScreen={setActiveScreen} />}
          {activeScreen === "step3b" && <MediaReviewScreen assets={assets} filteredAssets={filteredAssets} assetFilter={assetFilter} setAssetFilter={setAssetFilter} project={project} assetJobs={assetJobs} statusBadge={statusBadge} setLightboxIndex={setLightboxIndex} startJob={startJob} approveAsset={approveAsset} chooseAssetMedia={chooseAssetMedia} bulkRetryAssets={bulkRetryAssets} isBusy={isBusy} setActiveScreen={setActiveScreen} />}
          {activeScreen === "step4" && <ExportScreen project={project} assets={assets} preflight={preflight} runPreflight={runPreflight} startJob={startJob} title={title} isBusy={isBusy} busyAction={busyAction} setActiveScreen={setActiveScreen} />}
        </main>
      )}

      <SettingsModal open={settingsOpen} onOpenChange={setSettingsOpen} settings={settings} setSettings={setSettings} workflowSteps={workflowSteps} setWorkflowSteps={setWorkflowSteps} workflowPresets={workflowPresets} applyWorkflowPreset={applyWorkflowPreset} updateStep={updateStep} presetName={presetName} setPresetName={setPresetName} saveCurrentWorkflowAsPreset={saveCurrentWorkflowAsPreset} saveSettings={saveSettings} runPreflight={runPreflight} preflight={preflight} />
      <ProjectsModal open={projectsOpen} onOpenChange={setProjectsOpen} state={state} project={project} openProject={openProject} />
      <Lightbox open={lightboxIndex !== null} setLightboxIndex={setLightboxIndex} lightboxIndex={lightboxIndex} assets={assets} lightboxAsset={lightboxAsset} assetJobs={assetJobs} statusBadge={statusBadge} startJob={startJob} approveAsset={approveAsset} chooseAssetMedia={chooseAssetMedia} editingAssetId={editingAssetId} setEditingAssetId={setEditingAssetId} editingKeywordValue={editingKeywordValue} setEditingKeywordValue={setEditingKeywordValue} saveKeyword={saveKeyword} />
      {error && <div className="toast-error"><XCircle className="h-4 w-4 shrink-0" /><span>{error}</span><button onClick={() => setError("")}>Đóng</button></div>}
      {toast && <div className="toast-ok"><CheckCircle2 className="h-4 w-4" />{toast}</div>}
    </div>
  )
}

function StepPill({ index, label, active, done }) {
  return <div className={cn("step-pill", active && "active", done && "done")}><span>{done ? <Check className="h-4 w-4" /> : index + 1}</span><b>{label}</b></div>
}

function ProgressRail({ steps, current, done, setActiveScreen }) {
  return <div className="workspace-progress">
    <div className="workspace-rail-line"><div className="workspace-rail-flow" /></div>
    {steps.map((step, index) => {
      const locked = index > 0 && !done[index - 1] && index !== current
      return <button key={step.id} disabled={locked} title={locked ? "Hãy hoàn thành bước trước trước." : ""} onClick={() => !locked && setActiveScreen(step.id)} className={cn("workspace-step", index === current && "active", done[index] && "done", locked && "locked")}>
      <span>{done[index] ? <Check className="h-4 w-4" /> : index + 1}</span>
      <div><b>{step.title}</b><small>{index === current ? "Đang thực hiện" : done[index] ? "Hoàn thành" : locked ? "Chưa mở" : "Sẵn sàng"}</small></div>
    </button>
    })}
  </div>
}

function UserProgressPanel({ progress }) {
  const percent = Math.max(0, Math.min(100, Math.round(progress.percent || 0)))
  return <section className={cn("user-progress-panel", progress.running && "running", progress.status === "done" && "done", progress.status === "error" && "error")}>
    <div className="user-progress-main">
      <div className="user-progress-icon">{progress.running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : progress.status === "done" ? <CheckCircle2 className="h-4 w-4" /> : progress.status === "error" ? <XCircle className="h-4 w-4" /> : <Activity className="h-4 w-4" />}</div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <h3>{progress.title}</h3>
          <b>{percent}%</b>
        </div>
        <div className="user-progress-track"><i style={{ width: `${percent}%` }} /></div>
      </div>
    </div>
    <div className="user-progress-log">
      {progress.messages.map((message, index) => <span key={`${message}-${index}`}>{message}</span>)}
    </div>
  </section>
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
  if (action === "export") return "Đang xuất project CapCut"
  if (action?.startsWith("retry") || job?.asset_id) return `Đang tìm lại media${job?.asset_id ? ` cho ${job.asset_id}` : ""}`
  return "Đang xử lý"
}

function runningMessages(action, logs = [], assets = [], latest) {
  const messages = []
  if (action === "workflow") {
    messages.push("AI đang đọc yêu cầu và tạo kịch bản cuối.")
    messages.push("Bạn có thể đợi ở màn này, xong tool sẽ tự điền script.")
  } else if (action === "voice") {
    messages.push("Kokoro đang tạo file WAV từ script.")
    messages.push("Sau đó Whisper sẽ căn timing và tạo SRT để chia cảnh.")
  } else if (action === "analyze-search") {
    const total = assets.length
    const downloaded = assets.filter((item) => item.local_path).length
    messages.push(total ? `Đã tải được ${downloaded}/${total} media.` : "Gemini đang đọc SRT để gom cảnh và tạo keyword.")
    messages.push("Tool sẽ tự tải ảnh/video phù hợp cho từng cảnh.")
  } else if (action === "export") {
    messages.push("Tool đang gắn voice và media vào timeline CapCut.")
    messages.push("Khi xong, project sẽ sẵn sàng mở trong CapCut.")
  } else if (action?.startsWith("retry")) {
    messages.push("Ảnh cũ đã bị bỏ qua, tool đang tìm phương án mới.")
  } else {
    messages.push("Tool đang chạy tác vụ hiện tại.")
  }
  if (latest) messages.push(latest)
  return messages.slice(0, 3)
}

function normalizeUserLog(line) {
  if (!line) return ""
  const text = String(line).replace(/\s+/g, " ").trim()
  if (!text) return ""
  if (/error|loi|lỗi|failed/i.test(text)) return text
  if (/queue|hàng đợi|dang cho|chờ/i.test(text)) return "Tác vụ đã vào hàng đợi, tool sẽ xử lý lần lượt."
  if (/download|tai|tải/i.test(text)) return "Đang tải media phù hợp cho cảnh."
  if (/keyword/i.test(text)) return "Đang tạo keyword tìm ảnh/video."
  if (/srt|whisper/i.test(text)) return "Đang căn timing và tạo SRT."
  if (/capcut|timeline/i.test(text)) return "Đang dựng timeline CapCut."
  if (text.length > 120) return `${text.slice(0, 117)}...`
  return text
}

function FlowCard({ icon: Icon, title, desc, accent = "violet", dashed, onClick }) {
  return <button onClick={onClick} className={cn("flow-card text-left", dashed && "border-dashed")}>
    <div className={cn("flow-icon", accent)}><Icon className="h-5 w-5" /></div><div><b>{title}</b><p>{desc}</p></div>
  </button>
}

function StepContentScreen({ title, subtitle, left, right, footerLeft, footerAction }) {
  return <div className="step-screen">
    <div className="screen-heading"><h1>{title}</h1><p>{subtitle}</p></div>
    <div className="screen-columns"><div className="glass-panel screen-panel">{left}</div><div className="glass-panel screen-panel">{right}</div></div>
    <div className="screen-footer"><span>{footerLeft}</span>{footerAction}</div>
  </div>
}

function ScriptStepScreen({ mode, setMode, title, setTitle, script, setScript, scriptFileInputRef, uploadTxtFile, createProject, saveScriptStep, workflowInput, setWorkflowInput, workflowSteps, settings, workflowPresets, applyWorkflowPreset, startJob, isBusy, busyAction, setSettingsOpen }) {
  const isPaste = mode === "paste"
  return <div className="step-screen beginner-step">
    <div className="screen-heading">
      <h1>Bước 1 - Chuẩn bị nội dung</h1>
      <p>Chọn đúng trường hợp của bạn. Tool sẽ dẫn tiếp từng bước, không cần hiểu kỹ thuật.</p>
    </div>
    <div className="beginner-choice-grid">
      <button className={cn("beginner-choice", isPaste && "active")} onClick={() => setMode("paste")}>
        <FileText className="h-6 w-6" />
        <div><b>Tôi đã có kịch bản</b><span>Dán nội dung hoặc tải file TXT, sau đó bấm lưu.</span></div>
        <CheckCircle2 className="choice-check h-5 w-5" />
      </button>
      <button className={cn("beginner-choice", !isPaste && "active")} onClick={() => setMode("workflow")}>
        <Sparkles className="h-6 w-6" />
        <div><b>Tôi chưa có kịch bản</b><span>Nhập ý tưởng, AI sẽ viết thành kịch bản cuối.</span></div>
        <CheckCircle2 className="choice-check h-5 w-5" />
      </button>
    </div>
    <div className="glass-panel screen-panel beginner-main-panel">
      {isPaste
        ? <ScriptPanel title={title} setTitle={setTitle} script={script} setScript={setScript} scriptFileInputRef={scriptFileInputRef} uploadTxtFile={uploadTxtFile} createProject={createProject} saveScriptStep={saveScriptStep} isBusy={isBusy} />
        : <WorkflowPanel workflowInput={workflowInput} setWorkflowInput={setWorkflowInput} workflowSteps={workflowSteps} settings={settings} workflowPresets={workflowPresets} applyWorkflowPreset={applyWorkflowPreset} startJob={startJob} isBusy={isBusy} busyAction={busyAction} setSettingsOpen={setSettingsOpen} />}
    </div>
    <div className="screen-footer">
      <span>{isPaste ? "Việc cần làm: dán kịch bản → bấm Lưu nội dung." : "Việc cần làm: nhập ý tưởng → bấm Chạy AI viết kịch bản."}</span>
      {isPaste
        ? <Button onClick={saveScriptStep} disabled={!script.trim() || isBusy}>Lưu nội dung và sang Bước 2 <ArrowRight className="h-4 w-4" /></Button>
        : <Button disabled={!workflowInput.trim() || isBusy} onClick={() => startJob("/api/workflow", { source_input: workflowInput, steps: workflowSteps, settings }, "workflow")}>{busyAction === "workflow" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Chạy AI viết kịch bản</Button>}
    </div>
  </div>
}

function ScriptPanel({ title, setTitle, script, setScript, scriptFileInputRef, uploadTxtFile }) {
  return <div className="flex h-full flex-col">
    <div className="panel-title"><div><h2>Kịch bản cuối</h2><p>Nội dung Kokoro sẽ đọc</p></div><FileText className="text-violet-300" /></div>
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

function VoiceScreen({ script, project, settings, setSettings, voiceOptions, refreshVoices, previewVoiceNow, voicePreviewBusy, voicePreviewUrl, createVoiceWithQuickSettings, startJob, applyBeginnerVoicePreset, isBusy, busyAction, setActiveScreen }) {
  const languageMismatch = looksLikeEnglish(script) && (settings.text_to_voice_language || "en") !== "en"
  const voiceLanguage = normalizeVoiceLanguage(settings.text_to_voice_language || "en")
  const changeVoiceLanguage = (language) => setSettings({
    ...settings,
    text_to_voice_language: language,
  })
  return <div className="step-screen">
    <div className="screen-heading"><h1>Bước 2 - Chọn giọng đọc cho video</h1><p>Chọn giọng, nghe thử, rồi tạo file đọc để bước sau tự chia cảnh.</p></div>
    <div className="recommended-action">
      <div><b>Không biết chọn gì?</b><span>Bấm nút này để tool tự chọn ngôn ngữ, chế độ ổn định và tắt kiểm tra chậm cho script dài.</span></div>
      <Button variant="secondary" onClick={applyBeginnerVoicePreset} disabled={isBusy}><WandSparkles className="h-4 w-4" /> Dùng cấu hình dễ nhất</Button>
    </div>
    {languageMismatch && <div className="ux-warning"><AlertTriangle className="h-4 w-4" /><span>Script có vẻ là tiếng Anh nhưng ngôn ngữ giọng đang không phải English. Giọng có thể phát âm sai.</span><button onClick={() => setSettings({...settings, text_to_voice_language:"en", text_to_voice_voice:"af_heart"})}>Đổi sang English</button></div>}
    <div className="voice-layout">
      <div className="glass-panel screen-panel flex flex-col">
        <div className="panel-title"><h2>Chọn giọng đọc</h2><Button variant="ghost" size="sm" onClick={() => refreshVoices(settings.text_to_voice_language || "en")}><RefreshCw className="h-4 w-4" /> Tải lại</Button></div>
        <Field label="Ngôn ngữ đọc"><Select value={voiceLanguage} onValueChange={changeVoiceLanguage} options={voiceLanguageOptions} /></Field>
        <div className="voice-auto-mode"><Sparkles className="h-4 w-4" /><span>Đang dùng Kokoro local: tạo giọng nhanh, ổn định và không cần API.</span></div>
        <div className="voice-language-note">Kokoro hiện chưa hỗ trợ tiếng Việt. Chỉ các ngôn ngữ thực sự dùng được mới xuất hiện trong danh sách.</div>
        <div className="voice-list">{voiceOptions.map((voice) => <button key={voice.value} onClick={() => setSettings({...settings,text_to_voice_voice:voice.value})} className={cn("voice-row", settings.text_to_voice_voice === voice.value && "active")}><div className="voice-avatar"><Mic className="h-5 w-5" /></div><div><b>{voice.label}</b><small>Giọng đã sẵn sàng</small></div><Play className="ml-auto h-4 w-4" /></button>)}</div>
        <div className="audio-preview"><div className="flex justify-between text-xs"><span>Nghe thử 5-10 giây</span><Button size="sm" variant="ghost" onClick={previewVoiceNow}>{voicePreviewBusy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Nghe thử</Button></div>{voicePreviewUrl && <audio controls autoPlay src={voicePreviewUrl} className="mt-2 w-full" />}</div>
      </div>
      <div className="flex min-h-0 flex-col gap-4">
        <div className="glass-panel screen-panel flex-1">
          <div className="panel-title"><div><h3>Điều chỉnh cách đọc</h3><p>Các tùy chọn Kokoro có tác dụng trực tiếp lên audio.</p></div><Settings className="text-emerald-300" /></div>
          <Field label="Phong cách đọc"><Select value={settings.text_to_voice_delivery || "natural"} onValueChange={(v)=>setSettings({...settings,text_to_voice_delivery:v})} options={deliveryOptions} /></Field>
          <div className="mt-5"><RangeField label="Tốc độ đọc" value={settings.text_to_voice_speed ?? 1} min={.5} max={2} step={.05} onChange={(v)=>setSettings({...settings,text_to_voice_speed:v})} /></div>
          <div className="voice-language-note">Chỉ những tùy chọn Kokoro thực sự hỗ trợ mới được hiển thị tại đây.</div>
        </div>
      </div>
    </div>
    <div className="screen-footer"><Button variant="secondary" onClick={()=>setActiveScreen("step1")}><ArrowLeft className="h-4 w-4" /> Quay lại Bước 1</Button><div className="footer-chips"><span>Xuất WAV</span><span>Tạo mốc thời gian</span><span>{project?.has_voice ? "Sẵn sàng tạo cảnh" : "Tạo voice trước"}</span></div>{project?.has_voice
      ? <Button onClick={()=>{setActiveScreen("step3a");startJob("/api/analyze-search",undefined,"analyze-search")}} disabled={isBusy}>{busyAction==="analyze-search"?<LoaderCircle className="h-4 w-4 animate-spin"/>:<Sparkles className="h-4 w-4"/>} Tạo cảnh và tìm ảnh</Button>
      : <Button onClick={createVoiceWithQuickSettings} disabled={isBusy}>{busyAction==="voice"?<LoaderCircle className="h-4 w-4 animate-spin"/>:<Sparkles className="h-4 w-4"/>} Tạo giọng đọc</Button>}</div>
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

function SceneScreen({ assets, project, startJob, isBusy, busyAction, setActiveScreen }) {
  const loading = busyAction === "analyze-search" && isBusy
  return <div className="step-screen">
    <div className="screen-heading"><h1>Bước 3A - Tạo cảnh tự động</h1><p>Tool nghe lại voice, chia nội dung thành từng cảnh và chuẩn bị từ khóa tìm ảnh.</p></div>
    <div className={cn("step-guidance", project?.has_voice && "ready")}>
      <div>
        <b>{project?.has_voice ? "Đã có giọng đọc. Có thể tạo cảnh." : "Chưa có giọng đọc."}</b>
        <span>{loading ? "Đang đọc SRT, hiểu toàn bộ script, chia cảnh và tìm media. Khi đủ dữ liệu tool sẽ tự chuyển sang màn duyệt ảnh." : project?.has_voice ? "Cảnh và media sẽ được tạo từ nút ở Bước 2. Màn này dùng để xem lại kết quả phân cảnh." : "Hãy quay lại Bước 2 để tạo giọng đọc trước. Bước này cần file voice để biết thời gian từng cảnh."}</span>
      </div>
      {!project?.has_voice && <Button variant="secondary" onClick={()=>setActiveScreen("step2")}><ArrowLeft className="h-4 w-4" /> Về Bước 2</Button>}
    </div>
    <div className="scene-layout">
      <div className="glass-panel screen-panel"><div className="panel-title"><div><h2>Lời đọc đã căn thời gian</h2><p>{project?.has_voice ? "Đã có giọng đọc và mốc thời gian" : "Chưa tạo giọng đọc"}</p></div><FileText className="text-violet-300" /></div><div className="srt-preview">{assets.length ? assets.map((a,i)=><div key={a.asset_id}><span>{i+1}</span><b>{formatTime(a.start)} → {formatTime(a.end)}</b><p>{a.sentence_text}</p></div>) : <EmptyState text={loading ? "Đang căn thời gian và gom câu thành cảnh..." : "Chưa có dữ liệu. Hãy hoàn thành Bước 2."} />}</div></div>
      <div className="glass-panel screen-panel"><div className="panel-title"><div><h2>Các cảnh đã chia</h2><p>Không cắt giữa một ý đang nói</p></div><Aperture className="text-emerald-300" /></div><div className="scene-list">{assets.length ? assets.map((a,i)=><div className="scene-row" key={a.asset_id}><span>{String(i+1).padStart(2,"0")}</span><div><b>{formatTime(a.start)} - {formatTime(a.end)} · {Number(a.duration||0).toFixed(1)}s</b><p>{a.sentence_text}</p><small>{a.scene_break_reason || "Chuyển ý hoặc chủ thể"}</small></div></div>) : <EmptyState text={loading ? "Đang tạo phân cảnh và tìm ảnh/video..." : "Chưa có cảnh."} />}</div></div>
    </div>
    <div className="screen-footer"><Button variant="secondary" onClick={()=>setActiveScreen("step2")}><ArrowLeft className="h-4 w-4"/> Quay lại</Button><span>{loading ? "Đang xử lý, vui lòng chờ..." : assets.length ? `${assets.length} cảnh đã sẵn sàng` : "Chưa có dữ liệu cảnh"}</span><Button variant="secondary" disabled={!assets.length} onClick={()=>setActiveScreen("step3b")}>Xem ảnh từng cảnh <ArrowRight className="h-4 w-4"/></Button></div>
  </div>
}

function MediaReviewScreen({ assets, filteredAssets, assetFilter, setAssetFilter, project, assetJobs, statusBadge, setLightboxIndex, startJob, approveAsset, chooseAssetMedia, bulkRetryAssets, setActiveScreen }) {
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
    </div>
    <div className="media-filter-row">
      <div>
        <span>Hiển thị</span>
        <Select value={assetFilter} onValueChange={changeFilter} options={filterOptions.map(([value,label])=>({value,label:`${label} (${counts[value]})`}))}/>
      </div>
      <div className="media-filter-actions">
        <small>{filteredAssets.length} cảnh · trang {currentPage}/{pageCount}</small>
        <Button size="sm" variant="secondary" disabled={!retryableAssets.length} onClick={()=>bulkRetryAssets(retryableAssets.map(a=>a.asset_id))}><RefreshCw className="h-4 w-4" /> Tìm lại ảnh lỗi</Button>
        <Button size="sm" variant="secondary" disabled={!assets.some(a=>a.local_path && a.status !== "approved")} onClick={()=>assets.filter(a=>a.local_path && a.status !== "approved").forEach(a=>approveAsset(a.asset_id))}><Check className="h-4 w-4" /> Duyệt ảnh đã tải</Button>
      </div>
    </div>
    <div className="media-grid">{visibleAssets.length ? visibleAssets.map((asset)=>{
      const idx=assets.findIndex(a=>a.asset_id===asset.asset_id), job=assetJobs.get(asset.asset_id), badge=statusBadge(asset.status), version=asset.media_version||asset.sha256||asset.search_attempt
      return <article className="media-card" key={asset.asset_id}>
        <button className="media-image" onClick={()=>setLightboxIndex(idx)}>
          {asset.local_path?<img src={mediaUrl(asset.local_path,version)} alt={`Cảnh ${idx+1}`}/>:<Image className="h-10 w-10 text-slate-700"/>}
          <span className="scene-number">Cảnh {idx+1}</span><Badge variant={badge.variant}>{badge.label}</Badge>
          <time>{formatTime(asset.start)} - {formatTime(asset.end)}</time>
          {job&&<div className="media-busy"><LoaderCircle className="h-7 w-7 animate-spin"/>{job.status==="queued"?`Đang chờ #${job.queue_position}`:"Đang tìm ảnh mới..."}</div>}
        </button>
        <div className="media-card-body">
          <button className="media-card-title" onClick={()=>setLightboxIndex(idx)}><b>{asset.main_subject || asset.asset_id}</b><span>{Number(asset.duration||0).toFixed(1)}s</span></button>
          <div className="media-actions">
            <Button size="sm" variant="secondary" disabled={!!job} onClick={()=>startJob(`/api/assets/${asset.asset_id}/retry`,undefined,`retry-${asset.asset_id}`)}><RefreshCw className="h-3.5 w-3.5"/> Tìm lại</Button>
            <Button size="sm" variant="ghost" onClick={()=>chooseAssetMedia(asset.asset_id)}><Upload className="h-3.5 w-3.5"/> Tải lên</Button>
            <Button size="sm" variant={asset.status==="approved"?"success":"ghost"} disabled={!asset.local_path} onClick={()=>approveAsset(asset.asset_id)}><Check className="h-3.5 w-3.5"/> {asset.status==="approved"?"Đã duyệt":"Duyệt"}</Button>
          </div>
          <div className={cn("media-card-status", job ? "processing" : categoryOf(asset))}>
            {job ? "Đang xử lý cảnh này." : categoryOf(asset)==="error" ? (asset.error || "Tìm media bị lỗi.") : categoryOf(asset)==="missing" ? "Cảnh chưa có media." : categoryOf(asset)==="approved" ? "Media đã được duyệt." : "Media đang chờ bạn duyệt."}
          </div>
        </div>
      </article>}) : <div className="media-empty"><EmptyState text={assets.length ? "Không có cảnh nào theo bộ lọc này." : "Chưa có cảnh. Hãy bấm Tạo cảnh và tìm ảnh ở Bước 3A."} />{!assets.length && <Button variant="secondary" onClick={()=>setActiveScreen("step3a")}>Về Bước 3A</Button>}</div>}</div>
    {pageCount > 1 && <nav className="media-pagination" aria-label="Phân trang cảnh">
      <Button size="sm" variant="secondary" disabled={currentPage===1} onClick={()=>{setPage(value=>Math.max(1,value-1));headerRef.current?.scrollIntoView({block:"start"})}}><ArrowLeft className="h-4 w-4"/> Trang trước</Button>
      <div>{Array.from({length:pageCount},(_,index)=>index+1).map(number=><button key={number} className={number===currentPage?"active":""} onClick={()=>{setPage(number);headerRef.current?.scrollIntoView({block:"start"})}}>{number}</button>)}</div>
      <Button size="sm" variant="secondary" disabled={currentPage===pageCount} onClick={()=>{setPage(value=>Math.min(pageCount,value+1));headerRef.current?.scrollIntoView({block:"start"})}}>Trang sau <ArrowRight className="h-4 w-4"/></Button>
    </nav>}
    <div className="screen-footer"><Button variant="secondary" onClick={()=>setActiveScreen("step3a")}><ArrowLeft className="h-4 w-4"/> Phân cảnh</Button><span>{project?.approved_count||0}/{assets.length} cảnh đã duyệt</span><Button disabled={!assets.length} onClick={()=>setActiveScreen("step4")}>Tiếp tục kiểm tra <ArrowRight className="h-4 w-4"/></Button></div>
  </div>
}

function ExportScreen({ project, assets, preflight, runPreflight, startJob, title, isBusy, busyAction, setActiveScreen }) {
  const ready=project?.has_voice&&assets.length&&assets.every(a=>a.local_path)&&assets.every(a=>a.status==="approved")
  return <div className="step-screen">
    <div className="screen-heading"><h1>Bước 4 - Kiểm tra và xuất CapCut</h1><p>Kiểm tra đủ giọng đọc, cảnh và ảnh đã duyệt trước khi tạo project.</p></div>
    <div className="export-layout">
      <div className="glass-panel screen-panel"><div className="panel-title"><h2>Tình trạng project</h2><Activity className="text-violet-300"/></div><CheckRow ok={!!project} label="Đã có project và kịch bản"/><CheckRow ok={!!project?.has_voice} label="Đã có giọng đọc"/><CheckRow ok={!!project?.has_scenes} label="Đã chia cảnh"/><CheckRow ok={assets.length>0&&assets.every(a=>a.local_path)} label="Mỗi cảnh đã có ảnh/video"/><CheckRow ok={assets.length>0&&assets.every(a=>a.status==="approved")} label="Tất cả ảnh/video đã duyệt"/><Button className="mt-5" variant="secondary" onClick={runPreflight}><CheckCircle2 className="h-4 w-4"/> Kiểm tra cấu hình hệ thống</Button></div>
      <div className="glass-panel screen-panel export-hero"><div className="rocket-orb"><Rocket className="h-20 w-20"/></div><h2>{ready ? "Sẵn sàng tạo project CapCut" : "Còn mục cần hoàn thành"}</h2><p>Ảnh/video được gắn theo mốc thời gian, giọng đọc nằm đúng timeline và flow giữ nguyên theo script.</p><div className="timeline-preview" aria-hidden="true">{assets.slice(0, 8).map((asset, index)=><span key={asset.asset_id || index} style={{"--clip": `${Math.max(34, Math.min(90, Number(asset.duration || 5) * 7))}px`}} />)}<i /></div><Button size="lg" className="export-button" disabled={!ready||isBusy} onClick={()=>startJob("/api/export",{title},"export")}>{busyAction==="export"?<LoaderCircle className="h-5 w-5 animate-spin"/>:<Rocket className="h-5 w-5"/>} Xuất và mở CapCut</Button></div>
    </div>
    {preflight&&<div className="glass-panel mt-4 p-4"><div className="grid grid-cols-3 gap-3">{preflight.checks.map(c=><CheckRow key={c.id} ok={c.ok} label={c.label}/>)}</div></div>}
    <div className="screen-footer"><Button variant="secondary" onClick={()=>setActiveScreen("step3b")}><ArrowLeft className="h-4 w-4"/> Quay lại duyệt ảnh</Button><span>{ready?"Project đã đủ dữ liệu để xuất":"Còn mục chưa hoàn thành"}</span></div>
  </div>
}

function CheckRow({ ok, label }) { return <div className={cn("check-row",ok?"ok":"bad")}>{ok?<CheckCircle2/>:<XCircle/>}<span>{label}</span></div> }
function EmptyState({ text }) { return <div className="empty-state"><Image className="h-10 w-10"/><p>{text}</p></div> }

function SettingsModal({ open, onOpenChange, settings, setSettings, workflowSteps, setWorkflowSteps, workflowPresets, applyWorkflowPreset, updateStep, presetName, setPresetName, saveCurrentWorkflowAsPreset, saveSettings, runPreflight, preflight }) {
  const presets=workflowPresets()
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="settings-dialog max-w-6xl"><DialogTitle>Cài đặt</DialogTitle><DialogDescription>Chỉnh những thứ hay dùng. Các thông số kỹ thuật nằm trong tab Nâng cao.</DialogDescription>
    <Tabs defaultValue="basic" className="mt-5"><TabsList className="grid w-full grid-cols-5"><TabsTrigger value="basic">Cơ bản</TabsTrigger><TabsTrigger value="flow">Flow</TabsTrigger><TabsTrigger value="ai">AI</TabsTrigger><TabsTrigger value="advanced">Nâng cao</TabsTrigger><TabsTrigger value="validate">Kiểm tra</TabsTrigger></TabsList>
      <TabsContent value="basic"><div className="settings-grid">
        <SettingSection title="Giọng đọc mặc định" icon={FileAudio}>
          <Field label="Ngôn ngữ hay dùng"><Select value={normalizeVoiceLanguage(settings.text_to_voice_language||"en")} onValueChange={v=>setSettings({...settings,text_to_voice_language:v})} options={voiceLanguageOptions}/></Field>
          <Field label="Phong cách đọc"><Select value={settings.text_to_voice_delivery||"natural"} onValueChange={v=>setSettings({...settings,text_to_voice_delivery:v})} options={deliveryOptions}/></Field>
          <div className="setting-note">Tool dùng Kokoro local và không cần API voice.</div>
        </SettingSection>
        <SettingSection title="Ảnh và video" icon={Image}>
          <Switch checked={settings.image_ai_validation_enabled!==false} onCheckedChange={v=>setSettings({...settings,image_ai_validation_enabled:v})} label="AI kiểm tra ảnh có đúng nội dung"/>
          <Switch checked={!!settings.image_enhance_enabled} onCheckedChange={v=>setSettings({...settings,image_enhance_enabled:v})} label="Làm nét ảnh sau khi tải"/>
          <div className="setting-note">Khuyến nghị: bật cả hai mục trên để ảnh ít sai hơn và đủ nét khi xuất CapCut.</div>
        </SettingSection>
      </div></TabsContent>
      <TabsContent value="flow"><SettingSection title="Flow tạo kịch bản" icon={Bot}><Field label="Flow đang dùng"><Select value={settings.active_workflow_id||presets[0]?.id||""} onValueChange={applyWorkflowPreset} options={presets.map(x=>({value:x.id,label:x.name}))}/></Field>{workflowSteps.map((step,i)=><div className="workflow-edit" key={i}><Switch checked={step.enabled} onCheckedChange={v=>updateStep(i,{enabled:v})}/><Input value={step.name} onChange={e=>updateStep(i,{name:e.target.value})}/><Textarea value={step.prompt} onChange={e=>updateStep(i,{prompt:e.target.value})}/></div>)}<Button variant="secondary" onClick={()=>setWorkflowSteps(x=>[...x,{enabled:true,name:`Bước ${x.length+1}`,prompt:""}])}><Plus className="h-4 w-4"/> Thêm bước</Button><div className="flex gap-2"><Input value={presetName} onChange={e=>setPresetName(e.target.value)} placeholder="Tên flow mới"/><Button onClick={saveCurrentWorkflowAsPreset}>Lưu flow</Button></div></SettingSection></TabsContent>
      <TabsContent value="ai"><SettingSection title="AI dùng để hiểu nội dung và kiểm ảnh" icon={Bot}><Field label="Nhà cung cấp"><Select value={settings.keyword_ai_provider||"auto"} onValueChange={v=>setSettings({...settings,keyword_ai_provider:v})} options={[{value:"auto",label:"Tự động"},{value:"gemini",label:"Gemini"},{value:"openai",label:"OpenAI"}]}/></Field><Field label="Gemini API key"><Input type="password" value={settings.gemini_api_key||""} onChange={e=>setSettings({...settings,gemini_api_key:e.target.value})}/></Field><div className="setting-note">Nếu không biết chọn gì, để Tự động và chỉ nhập Gemini API key.</div></SettingSection></TabsContent>
      <TabsContent value="advanced"><div className="settings-grid">
        <SettingSection title="Kokoro nâng cao" icon={FileAudio}><RangeField label="Tốc độ đọc" value={settings.text_to_voice_speed??1} min={.5} max={2} step={.05} onChange={v=>setSettings({...settings,text_to_voice_speed:v})}/><Field label="Số ký tự tối đa mỗi phần"><Input type="number" value={settings.text_to_voice_max_chars||10000} onChange={e=>setSettings({...settings,text_to_voice_max_chars:Number(e.target.value)})}/></Field><div className="setting-note">Giữ 10.000 nếu không có nhu cầu đặc biệt. Script dài sẽ tự được chia và ghép lại.</div></SettingSection>
        <SettingSection title="Cảnh và chất lượng ảnh" icon={Aperture}><Switch checked={!!settings.whisper_timing_enabled} onCheckedChange={v=>setSettings({...settings,whisper_timing_enabled:v})} label="Căn thời gian bằng Whisper"/><Switch checked={!!settings.scene_ai_enabled} onCheckedChange={v=>setSettings({...settings,scene_ai_enabled:v})} label="AI gom câu thành cảnh"/><div className="grid grid-cols-2 gap-4"><Field label="Cảnh tối thiểu"><Input type="number" value={settings.scene_min_seconds||3} onChange={e=>setSettings({...settings,scene_min_seconds:Number(e.target.value)})}/></Field><Field label="Cảnh mục tiêu"><Input type="number" value={settings.scene_target_max_seconds||10} onChange={e=>setSettings({...settings,scene_target_max_seconds:Number(e.target.value)})}/></Field><Field label="Output width"><Input type="number" value={settings.image_target_width||1920} onChange={e=>setSettings({...settings,image_target_width:Number(e.target.value)})}/></Field><Field label="Output height"><Input type="number" value={settings.image_target_height||1080} onChange={e=>setSettings({...settings,image_target_height:Number(e.target.value)})}/></Field></div></SettingSection>
      </div></TabsContent>
      <TabsContent value="validate"><SettingSection title="Kiểm tra cấu hình máy" icon={CheckCircle2}><Button onClick={runPreflight}>Chạy kiểm tra</Button><div className="grid grid-cols-2 gap-3">{(preflight?.checks||[]).map(x=><CheckRow key={x.id} ok={x.ok} label={x.label}/>)}</div></SettingSection></TabsContent>
    </Tabs><div className="mt-5 flex justify-end gap-2"><Button variant="ghost" onClick={()=>onOpenChange(false)}>Huỷ</Button><Button onClick={()=>saveSettings(true)}>Lưu cài đặt</Button></div></DialogContent></Dialog>
}

function ProjectsModal({ open, onOpenChange, state, project, openProject }) {
  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-w-3xl"><DialogTitle>Project gần đây</DialogTitle><DialogDescription>Chọn project muốn làm tiếp. Đường dẫn chi tiết được rút gọn để dễ nhìn.</DialogDescription><div className="project-list">{state.projects?.map(item=>{
    const isOpen = project?.path===item.path
    return <button className={cn("project-row", isOpen && "active")} onClick={()=>openProject(item.path)} key={item.path}><FolderOpen/><div><b>{item.name}</b><small>{formatProjectDate(item.updated_at)} · {shortPath(item.path)}</small></div>{isOpen&&<Badge>Đang mở</Badge>}</button>
  })}</div></DialogContent></Dialog>
}
function Lightbox({ open, setLightboxIndex, lightboxIndex, assets, lightboxAsset, assetJobs, statusBadge, startJob, approveAsset, chooseAssetMedia, editingAssetId, setEditingAssetId, editingKeywordValue, setEditingKeywordValue, saveKeyword }) {
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
  return <label className="block"><span className="mb-1.5 block text-[11px] font-medium text-zinc-500">{label}</span>{children}</label>
}

export default App
