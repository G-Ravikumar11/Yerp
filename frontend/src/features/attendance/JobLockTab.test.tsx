import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const puts: { url: string; body?: unknown }[] = []
let canManage = true

const lock = {
  on: true, office_set: true, sites_without_location: [],
  staff: [],
  refused: [
    { id: 1, at: '2026-11-10 09:05:00', employee_id: 7, employee: 'Ravi Kumar', exempt: false, reason: 'You are 4.2 km from Tellapur Towers.', lat: 17.4, lng: 78.3, accuracy: 20, distance_m: 4200, nearest: 'Tellapur Towers' },
    { id: 2, at: '2026-11-10 09:20:00', employee_id: 8, employee: 'Asha Rao', exempt: true, reason: 'Outside every site.', lat: 0, lng: 0, accuracy: 20, distance_m: null, nearest: '' },
  ],
  flagged: [],
}
const week = {
  from: '2026-11-10', to: '2026-11-16', refused: 4, people: 2, previous_refused: 1, change: 3, flagged_punches: 1, repeat_people: 1,
  by_day: [{ date: '2026-11-10', count: 4 }, { date: '2026-11-11', count: 0 }],
  by_person: [
    { employee_id: 7, name: 'Ravi Kumar', job_title: 'Surveyor', refused: 3, days: 2, last_at: '2026-11-12 09:05:00', reason: 'You are 4.2 km from Tellapur Towers.', nearest: 'Tellapur Towers', farthest_m: 4200, repeat: true, exempt: false },
    { employee_id: 8, name: 'Asha Rao', job_title: '', refused: 1, days: 1, last_at: '2026-11-10 09:20:00', reason: 'Outside every site.', nearest: '', farthest_m: null, repeat: false, exempt: true },
  ],
  by_place: [],
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => (url.includes('/weekly') ? week : lock)),
  put: vi.fn(async (url: string, body: unknown) => { puts.push({ url, body }); return { message: 'Ravi can clock in anywhere.' } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => canManage }) }))

import { JobLockTab } from './JobLockTab'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<MemoryRouter><QueryClientProvider client={qc}><JobLockTab /></QueryClientProvider></MemoryRouter>)
}

beforeEach(() => { puts.length = 0; canManage = true })

describe('Site Lock: refusals and the weekly summary', () => {
  it('lets HR allow a refused person in one click, from the refusal list or the weekly summary', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('This week')
    const buttons = await screen.findAllByRole('button', { name: 'Allow Ravi Kumar' })
    expect(buttons).toHaveLength(2)                             // the refusal and the week's row
    await user.click(buttons[0])
    await vi.waitFor(() => expect(puts).toEqual([{ url: '/api/attendance/job-lock/exempt/7', body: { exempt: true } }]))
  })

  it('says so, instead of offering the button, for somebody already allowed anywhere', async () => {
    mount()
    await screen.findByText('This week')
    expect(screen.queryByRole('button', { name: 'Allow Asha Rao' })).toBeNull()
    expect(screen.getAllByText('Allowed anywhere').length).toBeGreaterThanOrEqual(2)
  })

  it('shows the week against the one before, with those refused again and again', async () => {
    mount()
    expect(await screen.findByText('Up 3 on the week before')).toBeTruthy()
    expect(screen.getAllByText('Again and again')).toHaveLength(2)            // the tile, and the badge on Ravi's row
    expect(screen.getByText('Surveyor')).toBeTruthy()
  })

  it('offers no button to somebody who cannot manage people', async () => {
    canManage = false
    mount()
    await screen.findByText('This week')
    expect(screen.queryByRole('button', { name: /allow/i })).toBeNull()
  })
})
