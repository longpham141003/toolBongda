import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
// Vietnamese text can be stored in different Unicode normalization forms (NFC
// vs NFD), so all text matching here is normalization-insensitive.
const nfc = (s) => (s || '').normalize('NFC')
const exactName = (label) => ({ name: (n) => nfc(n) === nfc(label) })
const partialName = (frag) => ({ name: (n) => nfc(n).includes(nfc(frag)) })

function makeState(settingsOverrides = {}) {
  return {
    settings: {
      projects_dir: 'C:/Projects',
      script_workflow_steps: [],
      script_workflow_input: '',
      image_ai_validation_enabled: true,
      ...settingsOverrides,
    },
    project: null,
    projects: [],
    series: [],
    active_job: null,
    queued_jobs: [],
    jobs: [],
  }
}

// Routes fetch by URL so /api/state and POST /api/settings behave realistically.
// Captures every settings POST body so tests can assert what would be persisted.
function routedFetch(state, savedBodies) {
  return vi.fn(async (url, options = {}) => {
    if (url === '/api/settings' && options.method === 'POST') {
      const body = JSON.parse(options.body)
      savedBodies.push(body.settings)
      return { ok: true, json: async () => ({ settings: body.settings }) }
    }
    if (url === '/api/state') {
      return { ok: true, json: async () => state }
    }
    return { ok: true, json: async () => ({}) }
  })
}

async function openSettings(user, container) {
  // The header gear button is the only ".icon-action" on the dashboard.
  await user.click(container.querySelector('.icon-action'))
  await screen.findByRole('button', exactName('Lưu cài đặt'))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('SettingsModal', () => {
  afterEach(() => vi.restoreAllMocks())

  it('saves a toggled value when "Lưu cài đặt" is pressed', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const saved = []
    global.fetch = routedFetch(makeState(), saved)
    const { container } = render(<App />)
    await waitFor(() => expect(container.querySelector('.icon-action')).toBeTruthy())

    await openSettings(user, container)
    // Toggle "AI kiểm tra ảnh có đúng nội dung" from on -> off
    await user.click(screen.getByRole('button', partialName('AI kiểm tra ảnh')))
    await user.click(screen.getByRole('button', exactName('Lưu cài đặt')))

    await waitFor(() => expect(saved.length).toBeGreaterThan(0))
    expect(saved.at(-1).image_ai_validation_enabled).toBe(false)
  })

  it('reverts unsaved edits when the dialog is closed with "Hủy"', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const saved = []
    global.fetch = routedFetch(makeState(), saved)
    const { container } = render(<App />)
    await waitFor(() => expect(container.querySelector('.icon-action')).toBeTruthy())

    // Edit then cancel
    await openSettings(user, container)
    await user.click(screen.getByRole('button', partialName('AI kiểm tra ảnh')))
    await user.click(screen.getByRole('button', exactName('Hủy')))

    // Reopen and save without touching anything: should persist the ORIGINAL value
    await openSettings(user, container)
    await user.click(screen.getByRole('button', exactName('Lưu cài đặt')))

    await waitFor(() => expect(saved.length).toBeGreaterThan(0))
    expect(saved.at(-1).image_ai_validation_enabled).toBe(true)
  })
})
