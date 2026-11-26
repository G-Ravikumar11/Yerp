import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: string[] = []
const notes = [
  { id: 1, title: 'Work order KOK-TWR-B-WO-2026-00045-REV-03-STRUCTURAL-STEEL waiting for approval', message: 'Signed by the project manager', type: 'warning', is_read: false, link: '', created_at: '2026-11-20 09:30:00' },
  { id: 2, title: 'Leave approved', message: 'Casual leave on 1 December', type: 'success', is_read: true, link: '', created_at: '2026-11-19 10:00:00' },
]
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async () => ({ notifications: notes, unread_count: 1 })),
  post: vi.fn(async (url: string) => { calls.push(`POST ${url}`); return {} }),
  api: vi.fn(async (url: string, o?: { method?: string }) => { calls.push(`${o?.method ?? 'GET'} ${url}`); return {} }),
}))

import { NotificationBell } from './NotificationBell'

const mount = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <header className="sticky top-0 backdrop-blur-xl"><NotificationBell /></header>
  </QueryClientProvider>,
)

beforeEach(() => { calls.length = 0 })

describe('Notification bell', () => {
  it('opens its panel outside the top bar, so the bar cannot clip or trap it, and keeps the desktop dropdown from 640px', async () => {
    const user = userEvent.setup()
    const { container } = mount()
    await user.click(await screen.findByRole('button', { name: 'Notifications, 1 unread' }))
    const panel = await screen.findByRole('dialog', { name: 'Notifications' })
    expect(container.querySelector('header')?.contains(panel)).toBe(false)               // drawn on the page body
    expect(panel.className).toMatch(/\bfixed\b/)
    expect(panel.className).toMatch(/inset-x-3/)                                         // a phone: the screen less a margin
    expect(panel.className).toMatch(/sm:w-80/)                                           // from 640px: the 320px dropdown
    expect(panel.style.getPropertyValue('--bell-top')).toMatch(/px$/)
    expect(await screen.findByText(/KOK-TWR-B-WO-2026-00045/)).toBeTruthy()
  })

  it('marks one read, marks all read, and closes on Escape and on a click outside', async () => {
    const user = userEvent.setup()
    mount()
    const bell = await screen.findByRole('button', { name: 'Notifications, 1 unread' })
    await user.click(bell)
    await user.click(await screen.findByText(/waiting for approval/))
    await waitFor(() => expect(calls).toContain('PATCH /api/employee/notifications/1/read'))
    await user.click(screen.getByRole('button', { name: 'Mark all read' }))
    await waitFor(() => expect(calls).toContain('POST /api/employee/notifications/read-all'))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Notifications' })).toBeNull()
    await user.click(bell)
    expect(await screen.findByRole('dialog', { name: 'Notifications' })).toBeTruthy()
    await user.click(document.body)
    expect(screen.queryByRole('dialog', { name: 'Notifications' })).toBeNull()
  })
})
