import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

// App now derives its screen from the URL, so it must render inside a Router.
function renderApp() {
  return render(<MemoryRouter><App /></MemoryRouter>)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
// Vietnamese text can be stored in different Unicode normalization forms (NFC
// vs NFD), so all text matching here is normalization-insensitive.
const nfc = (s) => (s || '').normalize('NFC')

// Robust button finder: scans all rendered buttons by textContent so it isn't
// affected by accessible-name computation changes (which broke the role+name
// function matcher after a dependency refresh).
function findButtonByText(text) {
  const normalised = nfc(text)
  const btn = screen.getAllByRole('button').find(
    (b) => nfc(b.textContent).includes(normalised)
  )
  if (!btn) throw new Error(`Unable to find button with text "${text}"`)
  return btn
}

// Async version — waits for the button to appear (e.g. after dialog opens).
async function findButtonByTextAsync(text) {
  const normalised = nfc(text)
  return waitFor(() => {
    const btn = screen.getAllByRole('button').find(
      (b) => nfc(b.textContent).includes(normalised)
    )
    if (!btn) throw new Error(`Unable to find button with text "${text}"`)
    return btn
  })
}

function makeState(settingsOverrides = {}) {
  return {
    settings: {
      projects_dir: 'C:/Projects',
      script_workflow_steps: [],
      script_workflow_input: '',
      image_ai_validation_enabled: true,
      // Provide a dummy key so the "Thiếu Gemini API key" notice dialog does
      // not open and cover the settings button under an aria-hidden overlay.
      gemini_api_key: 'test-key',
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
  // The header gear button (aria-label="Cài đặt") opens the settings dialog.
  // We click the second .icon-action (the settings gear), not the first (help).
  const iconActions = container.querySelectorAll('.icon-action')
  // Settings button is the second icon-action in the header
  const settingsBtn = Array.from(iconActions).find(
    (el) => el.getAttribute('aria-label') === 'Cài đặt'
  ) || iconActions[iconActions.length - 1]
  await user.click(settingsBtn)
  // Wait for dialog to open — use robust textContent-based check
  await findButtonByTextAsync('Lưu cài đặt')
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
    const { container } = renderApp()
    await waitFor(() => expect(container.querySelector('.icon-action')).toBeTruthy())

    await openSettings(user, container)
    // Toggle "AI kiểm tra ảnh có đúng nội dung" from on -> off
    await user.click(findButtonByText('AI kiểm tra ảnh'))
    await user.click(findButtonByText('Lưu cài đặt'))

    await waitFor(() => expect(saved.length).toBeGreaterThan(0))
    expect(saved.at(-1).image_ai_validation_enabled).toBe(false)
  })

  it('reverts unsaved edits when the dialog is closed with "Hủy"', async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 })
    const saved = []
    global.fetch = routedFetch(makeState(), saved)
    const { container } = renderApp()
    await waitFor(() => expect(container.querySelector('.icon-action')).toBeTruthy())

    // Edit then cancel
    await openSettings(user, container)
    await user.click(findButtonByText('AI kiểm tra ảnh'))
    await user.click(findButtonByText('Hủy'))

    // Reopen and save without touching anything: should persist the ORIGINAL value
    await openSettings(user, container)
    await user.click(findButtonByText('Lưu cài đặt'))

    await waitFor(() => expect(saved.length).toBeGreaterThan(0))
    expect(saved.at(-1).image_ai_validation_enabled).toBe(true)
  })
})
