import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

// App now derives its screen from the URL, so it must render inside a Router.
function renderApp() {
  return render(<MemoryRouter><App /></MemoryRouter>)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function makeState(overrides = {}) {
  return {
    settings: {
      projects_dir: 'C:/Projects',
      script_workflow_steps: [],
      script_workflow_input: '',
    },
    project: null,
    projects: [],
    active_job: null,
    queued_jobs: [],
    jobs: [],
    ...overrides,
  }
}

function mockFetchOnce(data) {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => data,
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('App', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows loading spinner before state is fetched', () => {
    // fetch that never resolves so the component stays in loading state
    global.fetch = vi.fn().mockReturnValue(new Promise(() => {}))
    renderApp()
    expect(screen.getByText(/Đang khởi động/)).toBeInTheDocument()
  })

  it('renders the app header after state is loaded', async () => {
    mockFetchOnce(makeState())
    renderApp()
    await waitFor(() => {
      expect(screen.getByText('Visual CapCut Studio')).toBeInTheDocument()
    })
  })

  it('shows "Chưa có project" when no project is loaded', async () => {
    mockFetchOnce(makeState({ project: null }))
    renderApp()
    await waitFor(() => {
      expect(screen.getByText('Chưa có project')).toBeInTheDocument()
    })
  })

  it('shows the project name in the header when a project is loaded', async () => {
    const project = {
      name: 'My Test Project',
      path: 'C:/Projects/my-test-project',
      script: 'Hello world script.',
      has_voice: false,
      has_scenes: false,
      has_capcut_export: false,
      assets: [],
    }
    mockFetchOnce(makeState({ project }))
    renderApp()
    await waitFor(() => {
      expect(screen.getByText('My Test Project')).toBeInTheDocument()
    })
  })

  it('shows "Sẵn sàng" badge when no active job is running', async () => {
    mockFetchOnce(makeState())
    renderApp()
    await waitFor(() => {
      expect(screen.getByText('Sẵn sàng')).toBeInTheDocument()
    })
  })

  it('shows the workflow section after state is loaded', async () => {
    mockFetchOnce(makeState())
    renderApp()
    await waitFor(() => {
      // The B0 script section heading should be visible
      expect(screen.getByText('B0 · Tạo nội dung')).toBeInTheDocument()
    })
  })

  it('shows flow step labels once loaded', async () => {
    mockFetchOnce(makeState())
    renderApp()
    await waitFor(() => {
      // The step label in the flow-step header has the exact text "B1 · Magic Voice"
      expect(screen.getByText('B1 · Magic Voice')).toBeInTheDocument()
      expect(screen.getByText('B2 · Phân cảnh')).toBeInTheDocument()
    })
  })

  it('renders "Tạo project" button when no project is loaded', async () => {
    mockFetchOnce(makeState({ project: null }))
    renderApp()
    await waitFor(() => {
      // Multiple "Tạo project" buttons exist (header area + workflow tabs).
      // We just need at least one to be present.
      const buttons = screen.getAllByRole('button', { name: /Tạo project/ })
      expect(buttons.length).toBeGreaterThan(0)
    })
  })

  it('fetches /api/state on mount', async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makeState(),
    })
    global.fetch = fetch
    renderApp()
    await waitFor(() => {
      expect(fetch).toHaveBeenCalled()
      const firstCall = fetch.mock.calls[0]
      expect(firstCall[0]).toBe('/api/state')
    })
  })
})
