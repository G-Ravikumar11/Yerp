import { act, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// The app watches for newer builds only in a production build; each test loads the module afresh as one.
async function load() {
  vi.resetModules()
  vi.stubEnv('PROD', true)
  return import('./freshness')
}

const replace = vi.fn()

describe('coming back to an app left open over a deploy', () => {
  beforeEach(() => {
    replace.mockReset()
    Object.defineProperty(window, 'location', { configurable: true, value: { href: 'http://localhost/next/', search: '', replace } })
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { headers: { 'X-App-Build': 'a-newer-build' } })))
    sessionStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  const comeBack = async () => {
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
      await new Promise((r) => setTimeout(r, 0))
    })
  }

  it('loads the new build at once when nothing is being typed', async () => {
    const { FreshBuild } = await load()
    render(<MemoryRouter><FreshBuild /></MemoryRouter>)
    await comeBack()
    // From the server, not a saved copy: the address carries the build asked for, which no saved copy answers.
    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith('http://localhost/next/?_build=a-newer-build'))
  })

  it('offers the reload instead when a form is open, and does not take what was typed', async () => {
    const { FreshBuild } = await load()
    render(<MemoryRouter><form><input aria-label="Quantity" /></form><FreshBuild /></MemoryRouter>)
    await comeBack()
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('A new version of Y ERP is ready.'))
    expect(replace).not.toHaveBeenCalled()
  })
})
