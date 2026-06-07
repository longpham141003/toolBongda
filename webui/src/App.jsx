import {
  Activity,
  Aperture,
  ArrowDown,
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
  WandSparkles,
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
  { enabled: true, name: "Phan tich de tai", prompt: "Analyze the topic, audience, key facts, named entities, timeline and strongest visual moments." },
  { enabled: true, name: "Lap dan y", prompt: "Create a coherent video outline with a strong opening, logical body and concise conclusion." },
  { enabled: true, name: "Viet script final", prompt: "Write the final natural voice-over script. Output narration only, without headings or notes." },
]

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || data.error || `HTTP ${response.status}`)
  return data
}

function statusBadge(status) {
  if (status === "approved") return { label: "Da duyet", variant: "success" }
  if (status === "downloaded") return { label: "Da tai", variant: "default" }
  if (status === "failed") return { label: "Loi", variant: "danger" }
  return { label: "Cho xu ly", variant: "muted" }
}

function App() {
  const [state, setState] = useState(null)
  const [script, setScript] = useState("")
  const [title, setTitle] = useState("")
  const [settings, setSettings] = useState({})
  const [workflowInput, setWorkflowInput] = useState("")
  const [workflowSteps, setWorkflowSteps] = useState(defaultSteps)
  const [activeJob, setActiveJob] = useState(null)
  const [logs, setLogs] = useState([])
  const [error, setError] = useState("")
  const [toast, setToast] = useState("")
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [projectsOpen, setProjectsOpen] = useState(false)
  const [lightbox, setLightbox] = useState(null)
  const [busyAction, setBusyAction] = useState("")
  const [followLogs, setFollowLogs] = useState(true)
  const logContainerRef = useRef(null)

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
          setToast(`${job.name} da hoan thanh`)
          setBusyAction("")
        } else if (job.status === "failed") {
          clearInterval(timer)
          setError(job.error || "Tac vu that bai")
          setBusyAction("")
        }
      } catch (err) {
        clearInterval(timer)
        setError(err.message)
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

  const project = state?.project
  const assets = project?.assets || []
  const liveJobs = state?.jobs || []
  const assetJobs = useMemo(
    () => new Map(
      liveJobs
        .filter((job) => job.asset_id && ["queued", "running"].includes(job.status))
        .map((job) => [job.asset_id, job]),
    ),
    [liveJobs],
  )
  const isBusy = activeJob && ["queued", "running"].includes(activeJob.status)
  const lightboxAsset = lightbox
    ? assets.find((asset) => asset.asset_id === lightbox.asset_id) || lightbox
    : null
  const scriptSaved = Boolean(project) && script.trim() === String(project?.script || "").trim()
  const completedSteps = useMemo(() => {
    return [
      scriptSaved,
      scriptSaved && Boolean(project?.has_voice),
      Boolean(project?.has_scenes),
      Boolean(project?.has_scenes) && assets.length > 0 && assets.every((item) => Boolean(item.local_path)),
      Boolean(project?.has_capcut_export),
    ]
  }, [project, assets, scriptSaved])

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
        setToast(`${data.job.asset_id} da vao hang doi so ${data.job.queue_position}`)
      }
    } catch (err) {
      setError(err.message)
      if (!isAssetRetry) setBusyAction("")
    }
  }

  async function saveSettings(close = true) {
    try {
      const data = await api("/api/settings", { method: "POST", body: JSON.stringify({ settings: { ...settings, script_workflow_input: workflowInput, script_workflow_steps: workflowSteps } }) })
      setSettings(data.settings)
      if (close) setSettingsOpen(false)
      setToast("Da luu cai dat")
    } catch (err) {
      setError(err.message)
    }
  }

  async function createProject() {
    if (!script.trim()) return setError("Hay nhap script truoc khi tao project.")
    try {
      const data = await api("/api/projects", { method: "POST", body: JSON.stringify({ title, script }) })
      setState((current) => ({ ...current, project: data.project }))
      setTitle(data.project.name)
      setToast("Da tao project")
      await loadState()
    } catch (err) {
      setError(err.message)
    }
  }

  async function saveScriptStep() {
    if (!script.trim()) return setError("Hay nhap script truoc khi luu B0.")
    if (!project) return createProject()
    try {
      const data = await api("/api/projects/script", { method: "POST", body: JSON.stringify({ script }) })
      setState((current) => ({ ...current, project: data.project }))
      setToast("B0 da luu script")
    } catch (err) {
      setError(err.message)
    }
  }

  async function openProject(path) {
    try {
      const data = await api("/api/projects/open", { method: "POST", body: JSON.stringify({ path }) })
      setState((current) => ({ ...current, project: data.project }))
      setScript(data.project.script)
      setTitle(data.project.name)
      setProjectsOpen(false)
      setToast("Da mo project")
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
    { code: "B0", label: "Script", hint: "Nhap va luu noi dung", icon: FileText },
    { code: "B1", label: "Magic Voice", hint: "Tao voice + timing", icon: FileAudio },
    { code: "B2", label: "Phan canh", hint: "Whisper + Gemini", icon: Aperture },
    { code: "B3", label: "Tai anh", hint: "SportsDB + Google", icon: Image },
    { code: "B4", label: "CapCut", hint: "Xuat project", icon: Film },
  ]

  if (!state) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-zinc-300">
        <LoaderCircle className="mr-3 h-5 w-5 animate-spin text-violet-400" /> Dang khoi dong Visual Studio...
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="fixed inset-0 -z-10 overflow-hidden">
        <div className="absolute -left-48 -top-48 h-[520px] w-[520px] rounded-full bg-violet-700/10 blur-[120px]" />
        <div className="absolute -right-48 top-1/3 h-[500px] w-[500px] rounded-full bg-cyan-600/[0.07] blur-[120px]" />
      </div>

      <header className="sticky top-0 z-30 border-b border-white/[0.07] bg-zinc-950/75 backdrop-blur-2xl">
        <div className="mx-auto flex h-16 max-w-[1800px] items-center gap-4 px-5 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-600 shadow-glow">
              <WandSparkles className="h-5 w-5 text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-tight">Visual CapCut Studio</div>
              <div className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">AI Production Workspace</div>
            </div>
          </div>
          <div className="mx-2 hidden h-7 w-px bg-white/10 md:block" />
          <button onClick={() => setProjectsOpen(true)} className="hidden min-w-0 items-center gap-2 rounded-xl px-3 py-2 text-left transition hover:bg-white/5 md:flex">
            <FolderOpen className="h-4 w-4 shrink-0 text-zinc-500" />
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-zinc-300">{project?.name || "Chua co project"}</div>
              <div className="truncate text-[10px] text-zinc-600">{project?.path || "Bam de mo project gan day"}</div>
            </div>
            <ChevronRight className="h-4 w-4 text-zinc-600" />
          </button>
          <div className="ml-auto flex items-center gap-2">
            {isBusy ? <Badge variant="warning"><LoaderCircle className="mr-1 h-3 w-3 animate-spin" /> {activeJob.name}</Badge> : <Badge variant="success"><span className="mr-1 h-1.5 w-1.5 rounded-full bg-emerald-400" /> San sang</Badge>}
            <Button variant="ghost" size="icon" onClick={() => setSettingsOpen(true)} title="Cai dat"><Settings className="h-4 w-4" /></Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1800px] px-5 py-6 lg:px-8">
        <section className="mb-6 grid grid-cols-5 gap-2">
          {flowSteps.map((step, index) => {
            const Icon = step.icon
            const done = completedSteps[index]
            const active = index === completedSteps.findIndex((value) => !value)
            return (
              <div key={step.label} className={cn("relative rounded-2xl border p-3 transition", done ? "border-emerald-400/20 bg-emerald-400/[0.06]" : active ? "border-violet-400/30 bg-violet-500/[0.08] shadow-glow" : "border-white/[0.07] bg-white/[0.025]")}>
                <div className="flex items-center gap-3">
                  <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-xl", done ? "bg-emerald-400/15 text-emerald-300" : active ? "bg-violet-500 text-white" : "bg-white/5 text-zinc-600")}>
                    {done ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
                  </div>
                  <div className="hidden min-w-0 sm:block">
                    <div className={cn("truncate text-xs font-medium", done ? "text-emerald-200" : active ? "text-white" : "text-zinc-500")}>{step.code} · {step.label}</div>
                    <div className="mt-0.5 truncate text-[10px] text-zinc-600">{step.hint}</div>
                  </div>
                </div>
              </div>
            )
          })}
        </section>

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_390px]">
          <div className="min-w-0 space-y-6">
            <Card className="overflow-hidden">
              <div className="flex flex-wrap items-center gap-3 border-b border-white/[0.07] px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold">B0 · Tao noi dung</h2>
                  <p className="mt-0.5 text-xs text-zinc-500">Dan script co san hoac dung workflow AI cua ban.</p>
                </div>
                <div className="ml-auto flex items-center gap-2">
                  <Input className="w-56" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ten project" />
                  <Button variant="secondary" onClick={() => setProjectsOpen(true)}><FolderOpen className="h-4 w-4" /> Mo cu</Button>
                  <Button onClick={createProject} disabled={!script.trim() || isBusy}><Plus className="h-4 w-4" /> Tao project</Button>
                </div>
              </div>
              <div className="p-5">
                <Tabs defaultValue="script">
                  <TabsList>
                    <TabsTrigger value="script"><FileText className="mr-2 h-4 w-4" /> Script final</TabsTrigger>
                    <TabsTrigger value="workflow"><Bot className="mr-2 h-4 w-4" /> AI Workflow</TabsTrigger>
                  </TabsList>
                  <TabsContent value="script">
                    <div className="mb-2 flex items-center justify-between text-xs text-zinc-500">
                      <span>Noi dung nay se duoc dung truc tiep cho B1 Magic Voice.</span>
                      <span>{script.trim() ? script.trim().split(/\s+/).length : 0} tu</span>
                    </div>
                    <Textarea className="min-h-[280px] text-[14px]" value={script} onChange={(e) => setScript(e.target.value)} placeholder="Dan script final vao day..." />
                  </TabsContent>
                  <TabsContent value="workflow">
                    <Textarea className="min-h-28" value={workflowInput} onChange={(e) => setWorkflowInput(e.target.value)} placeholder="Nhap chu de, thong tin nguon, yeu cau do dai, phong cach..." />
                    <div className="mt-4 space-y-3">
                      {workflowSteps.map((step, index) => (
                        <div key={index} className={cn("group rounded-2xl border p-4 transition", step.enabled ? "border-white/10 bg-white/[0.025]" : "border-white/[0.05] bg-black/10 opacity-55")}>
                          <div className="flex items-center gap-3">
                            <button onClick={() => updateStep(index, { enabled: !step.enabled })} className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border", step.enabled ? "border-violet-400/30 bg-violet-500/15 text-violet-300" : "border-white/10 text-zinc-600")}>
                              {step.enabled ? <Check className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}
                            </button>
                            <span className="text-xs font-semibold text-zinc-600">{String(index + 1).padStart(2, "0")}</span>
                            <Input value={step.name} onChange={(e) => updateStep(index, { name: e.target.value })} className="h-9 max-w-xs font-medium" />
                            <div className="ml-auto flex opacity-40 transition group-hover:opacity-100">
                              <Button variant="ghost" size="icon" onClick={() => moveStep(index, -1)} disabled={index === 0}><ArrowUp className="h-4 w-4" /></Button>
                              <Button variant="ghost" size="icon" onClick={() => moveStep(index, 1)} disabled={index === workflowSteps.length - 1}><ArrowDown className="h-4 w-4" /></Button>
                              <Button variant="ghost" size="icon" onClick={() => setWorkflowSteps((items) => items.filter((_, i) => i !== index))}><Trash2 className="h-4 w-4" /></Button>
                            </div>
                          </div>
                          <Textarea className="mt-3 min-h-20 bg-black/15 text-xs" value={step.prompt} onChange={(e) => updateStep(index, { prompt: e.target.value })} placeholder="Yeu cau AI xu ly o buoc nay..." />
                        </div>
                      ))}
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <Button variant="secondary" onClick={() => setWorkflowSteps((items) => [...items, { enabled: true, name: `Buoc ${items.length + 1}`, prompt: "" }])}><Plus className="h-4 w-4" /> Them buoc</Button>
                      <Button variant="ghost" onClick={() => setWorkflowSteps(defaultSteps)}><RefreshCw className="h-4 w-4" /> Khoi phuc mau</Button>
                      <Button className="ml-auto" disabled={!workflowInput.trim() || !workflowSteps.some((step) => step.enabled) || isBusy} onClick={() => startJob("/api/workflow", { source_input: workflowInput, steps: workflowSteps, settings: { ...settings, script_workflow_input: workflowInput, script_workflow_steps: workflowSteps } }, "workflow")}>
                        {busyAction === "workflow" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Chay workflow
                      </Button>
                    </div>
                  </TabsContent>
                </Tabs>
              </div>
            </Card>

            <Card>
              <div className="flex flex-wrap items-center gap-4 px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold">Dieu khien B0-B4</h2>
                  <p className="mt-0.5 text-xs text-zinc-500">5 buoc thong nhat voi thanh tien trinh phia tren.</p>
                </div>
                <div className="ml-auto flex flex-wrap gap-2">
                  <Button variant={scriptSaved ? "success" : "secondary"} disabled={!script.trim() || isBusy} onClick={saveScriptStep}>
                    <FileText className="h-4 w-4" /> B0 {project ? "Luu script" : "Tao project"}
                  </Button>
                  <Button variant={project?.has_voice ? "success" : "secondary"} disabled={!project || isBusy} onClick={() => startJob("/api/voice", { script }, "voice")}>
                    {busyAction === "voice" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FileAudio className="h-4 w-4" />} B1 Magic Voice
                  </Button>
                  <Button variant={assets.length ? "success" : "secondary"} disabled={!project?.has_voice || isBusy} onClick={() => startJob("/api/analyze", undefined, "analyze")}>
                    {busyAction === "analyze" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Aperture className="h-4 w-4" />} B2 Phan canh
                  </Button>
                  <Button variant={project?.downloaded_count === assets.length && assets.length ? "success" : "secondary"} disabled={!assets.length || isBusy} onClick={() => startJob("/api/search", undefined, "search")}>
                    {busyAction === "search" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />} B3 Tim anh
                  </Button>
                  <Button disabled={!assets.length || project?.downloaded_count !== assets.length || isBusy} onClick={() => startJob("/api/export", { title }, "export")} title={assets.length && project?.downloaded_count !== assets.length ? "Can tai du anh cho tat ca scene truoc khi xuat" : "Xuat project CapCut"}>
                    {busyAction === "export" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Rocket className="h-4 w-4" />} B4 Xuat CapCut
                  </Button>
                </div>
              </div>
            </Card>

            <Card className="overflow-hidden">
              <div className="flex items-center border-b border-white/[0.07] px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold">Canh & tai nguyen</h2>
                  <p className="mt-0.5 text-xs text-zinc-500">{assets.length ? `${assets.length} canh · ${project.downloaded_count} anh · ${project.approved_count} da duyet` : "Chay B2 de tao danh sach canh."}</p>
                </div>
                {project && <Button className="ml-auto" variant="ghost" size="sm" onClick={() => api("/api/project/open-folder", { method: "POST" })}><ExternalLink className="h-3.5 w-3.5" /> Mo thu muc</Button>}
              </div>
              {!assets.length ? (
                <div className="flex min-h-64 flex-col items-center justify-center px-6 text-center">
                  <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-dashed border-white/15 bg-white/[0.025]"><Image className="h-6 w-6 text-zinc-600" /></div>
                  <h3 className="text-sm font-medium text-zinc-300">Chua co canh nao</h3>
                  <p className="mt-1 max-w-sm text-xs leading-5 text-zinc-600">Sau khi co voice, B2 se dung Whisper va Gemini de chia canh, tao keyword va timing.</p>
                </div>
              ) : (
                <div className="grid gap-4 p-5 md:grid-cols-2 2xl:grid-cols-3">
                  {assets.map((asset) => {
                    const badge = statusBadge(asset.status)
                    const assetJob = assetJobs.get(asset.asset_id)
                    const isProcessingAsset = assetJob?.status === "running"
                    const isQueuedAsset = assetJob?.status === "queued"
                    const imageVersion = asset.media_version || asset.sha256 || asset.search_attempt
                    return (
                      <article key={asset.asset_id} className={cn("group overflow-hidden rounded-2xl border bg-black/20 transition hover:-translate-y-0.5 hover:shadow-xl", isProcessingAsset ? "border-violet-400/50 shadow-glow" : "border-white/[0.08] hover:border-white/15")}>
                        <button className="relative block aspect-video w-full overflow-hidden bg-zinc-900" onClick={() => asset.local_path && setLightbox(asset)}>
                          {asset.local_path ? <img key={`${asset.asset_id}-${imageVersion}`} src={mediaUrl(asset.local_path, imageVersion)} className="h-full w-full object-cover transition duration-500 group-hover:scale-[1.03]" /> : <div className="flex h-full items-center justify-center"><Image className="h-8 w-8 text-zinc-700" /></div>}
                          <div className="absolute left-3 top-3"><Badge variant={badge.variant}>{badge.label}</Badge></div>
                          <div className="absolute bottom-3 right-3 rounded-lg bg-black/70 px-2 py-1 text-[10px] text-white backdrop-blur">{formatTime(asset.start)} - {formatTime(asset.end)}</div>
                          {isProcessingAsset && (
                            <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/65 backdrop-blur-[2px]">
                              <LoaderCircle className="h-7 w-7 animate-spin text-violet-300" />
                              <span className="mt-2 text-xs font-medium text-white">Dang lay anh goc tu Google</span>
                            </div>
                          )}
                          {isQueuedAsset && (
                            <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/60 backdrop-blur-[2px]">
                              <Clock3 className="h-7 w-7 text-amber-300" />
                              <span className="mt-2 text-xs font-medium text-white">Dang cho trong hang doi</span>
                              <span className="mt-1 text-[10px] text-zinc-400">Vi tri {assetJob.queue_position}</span>
                            </div>
                          )}
                        </button>
                        <div className="p-4">
                          <div className="flex items-start gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="text-xs font-semibold text-zinc-300">{asset.asset_id}</div>
                              <p className="mt-1 line-clamp-3 text-xs leading-5 text-zinc-500">{asset.sentence_text}</p>
                            </div>
                            <Badge variant="muted">{Number(asset.duration || 0).toFixed(1)}s</Badge>
                          </div>
                          <div className="mt-3 rounded-xl border border-white/[0.06] bg-black/20 p-3">
                            <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-600"><KeyRound className="h-3 w-3" /> Keyword</div>
                            <p className="text-xs leading-5 text-zinc-400">{asset.keyword || "Chua co keyword"}</p>
                          </div>
                          <div className="mt-3 flex gap-2">
                            <Button className="flex-1" variant="secondary" size="sm" disabled={Boolean(assetJob)} onClick={() => startJob(`/api/assets/${asset.asset_id}/retry`, undefined, `retry-${asset.asset_id}`)}>
                              {isQueuedAsset ? <Clock3 className="h-3.5 w-3.5" /> : <RefreshCw className={cn("h-3.5 w-3.5", isProcessingAsset && "animate-spin")} />}
                              {isProcessingAsset ? "Dang tim" : isQueuedAsset ? `Cho #${assetJob.queue_position}` : "Tim lai"}
                            </Button>
                            <Button className="flex-1" variant={asset.status === "approved" ? "success" : "ghost"} size="sm" onClick={() => approveAsset(asset.asset_id)}>
                              <CheckCircle2 className="h-3.5 w-3.5" /> {asset.status === "approved" ? "Da duyet" : "Duyet"}
                            </Button>
                          </div>
                        </div>
                      </article>
                    )
                  })}
                </div>
              )}
            </Card>
          </div>

          <aside className="space-y-6 xl:sticky xl:top-22 xl:self-start">
            <Card className="overflow-hidden">
              <div className="border-b border-white/[0.07] px-5 py-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold">Project overview</h2>
                  <Activity className="h-4 w-4 text-zinc-600" />
                </div>
              </div>
              <div className="grid grid-cols-3 divide-x divide-white/[0.07]">
                <Metric value={project?.has_voice ? "Ready" : "—"} label="Voice" accent={project?.has_voice} />
                <Metric value={project?.asset_count || 0} label="Canh" />
                <Metric value={project?.approved_count || 0} label="Da duyet" accent={project?.approved_count > 0} />
              </div>
              <div className="border-t border-white/[0.07] p-5">
                <div className="mb-2 flex justify-between text-[11px] text-zinc-500"><span>Tien do asset</span><span>{assets.length ? Math.round((project.downloaded_count / assets.length) * 100) : 0}%</span></div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500 transition-all" style={{ width: `${assets.length ? (project.downloaded_count / assets.length) * 100 : 0}%` }} /></div>
              </div>
            </Card>

            <Card className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold">Activity</h2>
                  <p className="mt-0.5 text-[11px] text-zinc-600">Log tac vu dang chay</p>
                </div>
                {isBusy && <LoaderCircle className="h-4 w-4 animate-spin text-violet-400" />}
              </div>
              {activeJob && (
                <div className="border-b border-white/[0.07] px-5 py-3">
                  <div className="flex items-center justify-between gap-3 text-xs">
                    <div className="min-w-0">
                      <div className="truncate font-medium text-zinc-300">{activeJob.name}</div>
                      <div className="mt-0.5 truncate text-[10px] text-zinc-600">{activeJob.current_label || (isBusy ? "Dang xu ly..." : "Da hoan thanh")}</div>
                    </div>
                    <span className="shrink-0 text-zinc-500">
                      {activeJob.determinate
                        ? `${activeJob.completed_units || 0}/${activeJob.total_units || 0} · ${activeJob.progress || 0}%`
                        : isBusy ? "Dang xu ly" : "Hoan thanh"}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
                    {activeJob.determinate ? (
                      <div className="h-full rounded-full bg-violet-500 transition-all duration-500" style={{ width: `${activeJob.progress || 0}%` }} />
                    ) : (
                      <div className={cn("h-full w-1/3 rounded-full bg-gradient-to-r from-violet-600 via-fuchsia-400 to-violet-600", isBusy && "animate-progress-indeterminate")} />
                    )}
                  </div>
                </div>
              )}
              <div
                ref={logContainerRef}
                onScroll={(event) => {
                  const element = event.currentTarget
                  const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 36
                  setFollowLogs(nearBottom)
                }}
                className="activity-log relative h-[360px] overflow-y-auto overscroll-contain bg-black/20 p-4 font-mono text-[11px] leading-5"
              >
                {!logs.length ? <div className="flex h-full items-center justify-center text-zinc-700">Log se hien tai day</div> : logs.map((line, index) => <div key={index} className={cn("border-l pl-3", line.startsWith("LOI") ? "border-rose-500 text-rose-300" : "border-white/10 text-zinc-500")}><span className="mr-2 text-zinc-700">{String(index + 1).padStart(2, "0")}</span>{line}</div>)}
              </div>
              {!followLogs && logs.length > 0 && (
                <div className="border-t border-white/[0.07] p-2">
                  <Button
                    className="w-full"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setFollowLogs(true)
                      const container = logContainerRef.current
                      if (container) container.scrollTop = container.scrollHeight
                    }}
                  >
                    <ArrowDown className="h-3.5 w-3.5" /> Ve log moi nhat
                  </Button>
                </div>
              )}
            </Card>
          </aside>
        </div>
      </main>

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-w-4xl">
          <DialogTitle>Cai dat he thong</DialogTitle>
          <DialogDescription>API, voice, phan canh va chat luong anh. Thay doi duoc luu cho ca giao dien cu.</DialogDescription>
          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <SettingSection title="AI & Keyword" icon={Bot}>
              <Field label="Nha cung cap">
                <Select value={settings.keyword_ai_provider || "auto"} onValueChange={(value) => setSettings({ ...settings, keyword_ai_provider: value })} options={[{ value: "auto", label: "Tu dong" }, { value: "gemini", label: "Gemini" }, { value: "openai", label: "OpenAI" }]} />
              </Field>
              <Field label="Gemini API key"><Input type="password" value={settings.gemini_api_key || ""} onChange={(e) => setSettings({ ...settings, gemini_api_key: e.target.value })} /></Field>
              <Field label="Gemini model"><Input value={settings.gemini_keyword_model || ""} onChange={(e) => setSettings({ ...settings, gemini_keyword_model: e.target.value })} /></Field>
              <Field label="OpenAI API key"><Input type="password" value={settings.openai_api_key || ""} onChange={(e) => setSettings({ ...settings, openai_api_key: e.target.value })} /></Field>
            </SettingSection>
            <SettingSection title="Magic Voice" icon={FileAudio}>
              <Field label="Ngon ngu">
                <Select value={settings.text_to_voice_language || "en"} onValueChange={(value) => setSettings({ ...settings, text_to_voice_language: value })} options={[{ value: "en", label: "English" }, { value: "vi", label: "Vietnamese" }]} />
              </Field>
              <Field label="Voice"><Input value={settings.text_to_voice_voice || ""} onChange={(e) => setSettings({ ...settings, text_to_voice_voice: e.target.value })} /></Field>
              <Field label="Kieu doc">
                <Select value={settings.text_to_voice_delivery || "dramatic"} onValueChange={(value) => setSettings({ ...settings, text_to_voice_delivery: value })} options={[{ value: "dramatic", label: "Dien cam" }, { value: "news", label: "Tin tuc" }, { value: "neutral", label: "Tu nhien" }]} />
              </Field>
              <Field label={`Toc do ${Number(settings.text_to_voice_speed || 1).toFixed(2)}x`}><input type="range" min="0.7" max="1.3" step="0.05" value={settings.text_to_voice_speed || 1} onChange={(e) => setSettings({ ...settings, text_to_voice_speed: Number(e.target.value) })} className="w-full accent-violet-500" /></Field>
            </SettingSection>
            <SettingSection title="Timing & Scene" icon={Aperture}>
              <Switch checked={Boolean(settings.whisper_timing_enabled)} onCheckedChange={(value) => setSettings({ ...settings, whisper_timing_enabled: value })} label="Can timestamp bang Whisper" />
              <Switch checked={Boolean(settings.scene_ai_enabled)} onCheckedChange={(value) => setSettings({ ...settings, scene_ai_enabled: value })} label="Gemini gom canh theo ngu canh" />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Canh toi thieu (s)"><Input type="number" value={settings.scene_min_seconds || 3} onChange={(e) => setSettings({ ...settings, scene_min_seconds: Number(e.target.value) })} /></Field>
                <Field label="Canh muc tieu (s)"><Input type="number" value={settings.scene_target_max_seconds || 10} onChange={(e) => setSettings({ ...settings, scene_target_max_seconds: Number(e.target.value) })} /></Field>
              </div>
            </SettingSection>
            <SettingSection title="Image quality" icon={Image}>
              <Switch checked={Boolean(settings.image_enhance_enabled)} onCheckedChange={(value) => setSettings({ ...settings, image_enhance_enabled: value })} label="Lam net anh sau khi tai" />
              <div className="grid grid-cols-2 gap-3">
                <Field label="Min width"><Input type="number" value={settings.image_min_width || 600} onChange={(e) => setSettings({ ...settings, image_min_width: Number(e.target.value) })} /></Field>
                <Field label="Min height"><Input type="number" value={settings.image_min_height || 330} onChange={(e) => setSettings({ ...settings, image_min_height: Number(e.target.value) })} /></Field>
                <Field label="Output width"><Input type="number" value={settings.image_target_width || 1920} onChange={(e) => setSettings({ ...settings, image_target_width: Number(e.target.value) })} /></Field>
                <Field label="Output height"><Input type="number" value={settings.image_target_height || 1080} onChange={(e) => setSettings({ ...settings, image_target_height: Number(e.target.value) })} /></Field>
              </div>
            </SettingSection>
          </div>
          <div className="mt-6 flex justify-end gap-2"><Button variant="ghost" onClick={() => setSettingsOpen(false)}>Huy</Button><Button onClick={() => saveSettings(true)}>Luu cai dat</Button></div>
        </DialogContent>
      </Dialog>

      <Dialog open={projectsOpen} onOpenChange={setProjectsOpen}>
        <DialogContent className="max-w-2xl">
          <DialogTitle>Project gan day</DialogTitle>
          <DialogDescription>Chon project de tiep tuc tu trang thai truoc.</DialogDescription>
          <div className="mt-5 max-h-[60vh] space-y-2 overflow-auto">
            {state.projects?.map((item) => (
              <button key={item.path} onClick={() => openProject(item.path)} className={cn("flex w-full items-center gap-3 rounded-xl border p-3 text-left transition hover:border-violet-400/30 hover:bg-violet-500/[0.06]", project?.path === item.path ? "border-violet-400/30 bg-violet-500/[0.06]" : "border-white/[0.07] bg-white/[0.02]")}>
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/5"><FolderOpen className="h-4 w-4 text-zinc-500" /></div>
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-zinc-300">{item.name}</div><div className="mt-0.5 truncate text-[11px] text-zinc-600">{item.path}</div></div>
                {project?.path === item.path && <Badge>Dang mo</Badge>}
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(lightboxAsset)} onOpenChange={(open) => !open && setLightbox(null)}>
        <DialogContent className="max-w-6xl border-0 bg-black/95 p-3">
          {lightboxAsset && <><img key={`${lightboxAsset.asset_id}-${lightboxAsset.media_version || lightboxAsset.sha256 || lightboxAsset.search_attempt}`} src={mediaUrl(lightboxAsset.local_path, lightboxAsset.media_version || lightboxAsset.sha256 || lightboxAsset.search_attempt)} className="max-h-[82vh] w-full rounded-xl object-contain" /><div className="px-2 pb-1 pt-3"><div className="text-sm font-medium">{lightboxAsset.asset_id}</div><p className="mt-1 text-xs text-zinc-500">{lightboxAsset.keyword}</p></div></>}
        </DialogContent>
      </Dialog>

      {error && <div className="fixed bottom-5 left-1/2 z-[80] flex max-w-xl -translate-x-1/2 items-center gap-3 rounded-xl border border-rose-400/20 bg-rose-950/95 px-4 py-3 text-sm text-rose-200 shadow-2xl"><XCircle className="h-4 w-4 shrink-0" /><span>{error}</span><button onClick={() => setError("")} className="ml-2 text-rose-400 hover:text-white">×</button></div>}
      {toast && <div className="fixed bottom-5 left-1/2 z-[80] flex -translate-x-1/2 items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-950/95 px-4 py-3 text-sm text-emerald-200 shadow-2xl"><CheckCircle2 className="h-4 w-4" />{toast}</div>}
    </div>
  )
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
