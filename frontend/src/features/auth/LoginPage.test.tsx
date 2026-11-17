import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { url: string; body: unknown }[] = []
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  // Nobody is signed in; every sign-in is refused, so the page stays and the calls it made can be read.
  api: vi.fn(async (url: string, opts?: { body?: unknown }) => {
    calls.push({ url, body: opts?.body })
    const { ApiError } = await vi.importActual<typeof import('@/lib/api')>('@/lib/api')
    throw new ApiError(401, 'Invalid credentials')
  }),
}))

import LoginPage from './LoginPage'

const signIns = () => calls.filter((c) => /\/api\/(client|employee)\/(auth\/)?login$/.test(c.url))

describe('signing in', () => {
  beforeEach(() => { calls.length = 0 })

  it('takes an email or an employee ID', () => {
    render(<LoginPage />)
    expect(screen.getByLabelText('Email or employee ID')).toBeTruthy()
  })

  it('sends an employee ID to the staff door only, never the Master\'s', async () => {
    const user = userEvent.setup()
    render(<LoginPage />)
    await user.type(screen.getByLabelText('Email or employee ID'), 'EMP-0002')
    await user.type(screen.getByLabelText('Password'), 'secret-pass')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(signIns().length).toBeGreaterThan(0))
    expect(signIns().map((c) => c.url)).toEqual(['/api/employee/auth/login'])
    expect((signIns()[0].body as { email: string }).email).toBe('EMP-0002')
    expect(await screen.findByText(/email or employee ID and password did not match/i)).toBeTruthy()
  })

  it('still tries the Master\'s door first for an email', async () => {
    const user = userEvent.setup()
    render(<LoginPage />)
    await user.type(screen.getByLabelText('Email or employee ID'), 'owner@company.com')
    await user.type(screen.getByLabelText('Password'), 'secret-pass')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(signIns().length).toBe(2))
    expect(signIns().map((c) => c.url)).toEqual(['/api/client/login', '/api/employee/auth/login'])
  })
})
