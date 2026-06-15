import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

// App now derives its screen from the URL, so it must render inside a Router.
function renderApp(initialEntries = ['/']) {
  return render(<MemoryRouter initialEntries={initialEntries}><App /></MemoryRouter>)
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
      // Provide a dummy key so the "Thiếu Gemini API key" notice dialog does
      // not open and cover the main UI under an aria-hidden overlay.
      gemini_api_key: 'test-key',
    },
    project: null,
    projects: [],
    series: [],
    active_job: null,
    queued_jobs: [],
    jobs: [],
    ...overrides,
  }
}

function mockFetch(data) {
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

  it('renders the app header "CONTENT AUTOMATION" after state is loaded', async () => {
    mockFetch(makeState())
    renderApp()
    await waitFor(() => {
      // The header now reads "CONTENT AUTOMATION" (with AUTOMATION in emerald span)
      expect(screen.getByText(/CONTENT/)).toBeInTheDocument()
      expect(screen.getByText(/AUTOMATION/)).toBeInTheDocument()
    })
  })

  it('shows empty-state hero section when no series exist', async () => {
    mockFetch(makeState({ project: null, series: [] }))
    renderApp()
    await waitFor(() => {
      // The dashboard shows "AI VIDEO PRODUCTION" kicker when no projects
      expect(screen.getByText('AI VIDEO PRODUCTION')).toBeInTheDocument()
    })
  })

  it('shows series title in the dashboard grid when series exist', async () => {
    const series = [
      {
        path: 'C:/Projects/bong-da',
        title: 'Bóng đá',
        description: 'Series bóng đá',
        is_virtual: false,
        video_count: 2,
        latest_updated_at: 0,
        videos: [],
      },
    ]
    mockFetch(makeState({ series }))
    renderApp()
    await waitFor(() => {
      expect(screen.getByText('Bóng đá')).toBeInTheDocument()
    })
  })

  it('shows "Tạo Dự án mới" button on the dashboard', async () => {
    mockFetch(makeState())
    renderApp()
    await waitFor(() => {
      // Dashboard always shows a "Tạo Dự án mới" button in the hero CTA
      const btn = screen.getAllByRole('button').find(
        (b) => b.textContent.normalize('NFC').includes('Tạo Dự án mới'.normalize('NFC'))
      )
      expect(btn).toBeInTheDocument()
    })
  })

  it('shows process steps section when no projects exist', async () => {
    mockFetch(makeState({ series: [] }))
    renderApp()
    await waitFor(() => {
      // The empty-state dashboard shows 4 process steps like "Nhập nội dung"
      expect(screen.getByText('Nhập nội dung')).toBeInTheDocument()
    })
  })

  it('hides process strip when series already exist', async () => {
    const series = [
      {
        path: 'C:/Projects/khoa-hoc',
        title: 'Khoa học',
        description: '',
        is_virtual: false,
        video_count: 1,
        latest_updated_at: 0,
        videos: [],
      },
    ]
    mockFetch(makeState({ series }))
    renderApp()
    await waitFor(() => {
      // "Nhập nội dung" belongs to the process strip — hidden when projects exist
      expect(screen.queryByText('Nhập nội dung')).not.toBeInTheDocument()
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
