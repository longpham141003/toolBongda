/**
 * Routing.test.jsx
 *
 * Integration tests for URL-based routing in App.jsx.
 * These tests verify that:
 *   1. "/" → DashboardScreen renders
 *   2. "/du-an/:slug" → ProjectDetailScreen shows the series title
 *   3. Reload no-cancel invariant: video already open → no POST /api/projects/open
 *   4. Reload, switch project: different video in state → POST /api/projects/open is called
 *   5. Unknown video slug → navigates back to "/"
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App'
import { pathToSeriesSlug, pathToVideoSlug } from './lib/routing'

// ---------------------------------------------------------------------------
// Constants for test fixtures
// ---------------------------------------------------------------------------
const SERIES = [
  {
    path: 'C:/Projects/bong-da',
    title: 'Bóng đá',
    description: 'Series bóng đá',
    is_virtual: false,
    video_count: 1,
    latest_updated_at: 0,
    videos: [],
  },
]

const VIDEO_A = {
  path: 'C:/Projects/bong-da/tran-dau-lon',
  name: 'Trận đấu lớn',
  category: 'Bóng đá',
  script: 'Script A',
  has_voice: true,
  has_scenes: false,
  has_capcut_export: false,
  assets: [],
  updated_at: 0,
}

const VIDEO_B = {
  path: 'C:/Projects/bong-da/tran-chung-ket',
  name: 'Trận chung kết',
  category: 'Bóng đá',
  script: 'Script B',
  has_voice: false,
  has_scenes: false,
  has_capcut_export: false,
  assets: [],
  updated_at: 0,
}

// ---------------------------------------------------------------------------
// Slug helpers
// ---------------------------------------------------------------------------
// Compute slugs using the same logic as the app so tests stay in sync.
const seriesSlug = pathToSeriesSlug(SERIES[0].path, SERIES)           // "bong-da"
const videoASlug = pathToVideoSlug(VIDEO_A.path, [VIDEO_A, VIDEO_B])  // "tran-dau-lon"
const videoBSlug = pathToVideoSlug(VIDEO_B.path, [VIDEO_A, VIDEO_B])  // "tran-chung-ket"

// ---------------------------------------------------------------------------
// Fetch router factory
// ---------------------------------------------------------------------------
/**
 * Creates a mock fetch that routes by URL/method.
 * - GET /api/state → returns stateData
 * - GET /api/preflight → returns { ok: true, checks: [] }
 * - GET /api/voices?... → returns { options: [{ value: 'af_heart', label: 'af_heart' }] }
 * - POST /api/projects/open → records the call in openCalls and returns project
 * - Everything else → { ok: true }
 */
function makeRoutedFetch(stateData, openCalls = []) {
  return vi.fn(async (url, options = {}) => {
    if (url === '/api/state') {
      return { ok: true, json: async () => stateData }
    }
    if (url === '/api/preflight') {
      return { ok: true, json: async () => ({ ok: true, checks: [] }) }
    }
    if (typeof url === 'string' && url.startsWith('/api/voices')) {
      return { ok: true, json: async () => ({ options: [{ value: 'af_heart', label: 'af_heart' }] }) }
    }
    if (url === '/api/projects/open' && options?.method === 'POST') {
      const body = JSON.parse(options.body)
      openCalls.push(body)
      // Return a minimal project to satisfy setState in loadProjectIntoState
      const target = stateData.projects?.find(p => p.path === body.path) || VIDEO_A
      return { ok: true, json: async () => ({ project: target }) }
    }
    if (url === '/api/jobs/cancel' || (typeof url === 'string' && url.startsWith('/api/jobs/cancel'))) {
      return { ok: true, json: async () => ({}) }
    }
    return { ok: true, json: async () => ({}) }
  })
}

function baseState(overrides = {}) {
  return {
    settings: {
      projects_dir: 'C:/Projects',
      script_workflow_steps: [],
      script_workflow_input: '',
      // Provide API key so the "missing key" dialog doesn't cover the UI
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

function renderAt(url, fetchMock) {
  global.fetch = fetchMock
  return render(
    <MemoryRouter initialEntries={[url]}>
      <App />
    </MemoryRouter>
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('Routing', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  // -------------------------------------------------------------------------
  // Test 1: "/" → Dashboard renders
  // -------------------------------------------------------------------------
  it('renders DashboardScreen at "/"', async () => {
    const state = baseState({ series: [] })
    renderAt('/', makeRoutedFetch(state))

    await waitFor(() => {
      // The empty-state dashboard always shows this kicker
      expect(screen.getByText('AI VIDEO PRODUCTION')).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Test 2: "/du-an/:slug" → ProjectDetailScreen shows the series title
  // -------------------------------------------------------------------------
  it('renders ProjectDetailScreen with series title at "/du-an/:slug"', async () => {
    const state = baseState({ series: SERIES, projects: [VIDEO_A] })
    // seriesSlug = "bong-da" (computed above)
    renderAt(`/du-an/${seriesSlug}`, makeRoutedFetch(state))

    await waitFor(() => {
      // ProjectDetailScreen renders <h1>{activeSeries.title}</h1>
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Bóng đá')
    })
  })

  // -------------------------------------------------------------------------
  // Test 3: No-cancel invariant
  // When the mocked state already has the target video open (project.path === target),
  // the restoration effect must NOT call POST /api/projects/open.
  // -------------------------------------------------------------------------
  it('does NOT call POST /api/projects/open when the target video is already open', async () => {
    // State has VIDEO_A open as the current project
    const state = baseState({
      project: VIDEO_A,
      projects: [VIDEO_A, VIDEO_B],
      series: SERIES,
    })
    const openCalls = []
    renderAt(`/video/${videoASlug}/giong-doc`, makeRoutedFetch(state, openCalls))

    await waitFor(() => {
      // VoiceScreen heading confirms we are on step 2
      expect(screen.getByText(/Bước 2/)).toBeInTheDocument()
    })

    // Allow extra async ticks to ensure no open call fires late
    await new Promise(r => setTimeout(r, 200))
    expect(openCalls).toHaveLength(0)
  })

  // -------------------------------------------------------------------------
  // Test 4: Reload, switch project
  // When state has a DIFFERENT project open (or none), the restoration effect
  // must call POST /api/projects/open with the resolved path,
  // and the URL must stay on "giong-doc" (not redirect to another step).
  // -------------------------------------------------------------------------
  it('calls POST /api/projects/open when reloading a video URL with a different project open', async () => {
    // State has VIDEO_B open, but URL is for VIDEO_A
    const state = baseState({
      project: VIDEO_B,
      projects: [VIDEO_A, VIDEO_B],
      series: SERIES,
    })
    const openCalls = []
    renderAt(`/video/${videoASlug}/giong-doc`, makeRoutedFetch(state, openCalls))

    await waitFor(() => {
      expect(openCalls.length).toBeGreaterThan(0)
    }, { timeout: 3000 })

    // The open call must target VIDEO_A's path
    expect(openCalls[0].path).toBe(VIDEO_A.path)

    // URL stays on "giong-doc" — VoiceScreen content should appear
    await waitFor(() => {
      expect(screen.getByText(/Bước 2/)).toBeInTheDocument()
    })
  })

  // -------------------------------------------------------------------------
  // Test 5: Unknown video slug → navigates to "/"
  // -------------------------------------------------------------------------
  it('navigates to "/" when the video slug is not found in state.projects', async () => {
    // No projects in state → slug can't be resolved
    const state = baseState({ projects: [], series: [] })
    renderAt('/video/does-not-exist/giong-doc', makeRoutedFetch(state))

    await waitFor(() => {
      // After the redirect, we land on the dashboard
      expect(screen.getByText('AI VIDEO PRODUCTION')).toBeInTheDocument()
    })
  })
})
