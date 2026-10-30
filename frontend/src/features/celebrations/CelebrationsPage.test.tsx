import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sent: { url: string; body: unknown }[] = []
let manage = false

const feed = () => ({
  today: [
    { key: 'birthday:7:2026', kind: 'birthday', date: '2026-11-02', title: 'Asha Rao\'s birthday', emoji: '🎂', message: '', employee_id: 7, employee_name: 'Asha Rao', job_title: 'Site Engineer',
      reactions: [{ emoji: '🎉', count: 2, mine: false, names: ['Ravi', 'Meena'] }], wishes: [{ id: 3, author: 'Ravi', message: 'Many happy returns', at: '', mine: false, can_delete: false }] },
  ],
  upcoming: [{ key: 'festival:2026-11-08', kind: 'festival', date: '2026-11-08', title: 'Diwali', emoji: '🪔', message: '', days_away: 6 }],
  emojis: ['🎂', '🎉', '👏'],
  can_manage: manage,
})

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => (url === '/api/celebrations' ? feed() : [])),
  post: vi.fn(async (url: string, body: unknown) => { sent.push({ url, body }); return { reacted: true, id: 1, announced: 0 } }),
  del: vi.fn(async () => ({ message: 'ok' })),
}))

import CelebrationsPage from './CelebrationsPage'

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><CelebrationsPage /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => { sent.length = 0; manage = false })

describe('Celebrations', () => {
  it('shows today\'s birthday with its reactions and messages, and what is coming', async () => {
    show()
    expect(await screen.findByText("Asha Rao's birthday")).toBeInTheDocument()
    expect(screen.getByText('Many happy returns')).toBeInTheDocument()
    expect(screen.getByText('Diwali')).toBeInTheDocument()
    expect(screen.getByText('In 6 days')).toBeInTheDocument()
  })

  it('sends an emoji reaction', async () => {
    show()
    await screen.findByText("Asha Rao's birthday")
    await userEvent.click(screen.getByRole('button', { name: 'React with 🎂' }))
    await waitFor(() => expect(sent).toContainEqual({ url: '/api/celebrations/react', body: { celebration: 'birthday:7:2026', emoji: '🎂' } }))
  })

  it('sends a birthday message', async () => {
    show()
    await userEvent.type(await screen.findByLabelText("Write to Asha Rao's birthday"), 'Have a great day!')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(sent).toContainEqual({ url: '/api/celebrations/wishes', body: { celebration: 'birthday:7:2026', message: 'Have a great day!' } }))
  })

  it('offers adding a special day only to HR and the Master', async () => {
    show()
    await screen.findByText("Asha Rao's birthday")
    expect(screen.queryByRole('button', { name: /Add a special day/ })).toBeNull()
  })

  it('lets HR add a special day', async () => {
    manage = true
    show()
    await userEvent.click(await screen.findByRole('button', { name: /Add a special day/ }))
    await userEvent.type(screen.getByLabelText('Name'), 'Safety Week')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await waitFor(() => expect(sent.find((s) => s.url === '/api/celebrations/special-days')?.body).toMatchObject({ name: 'Safety Week', yearly: false }))
  })
})
