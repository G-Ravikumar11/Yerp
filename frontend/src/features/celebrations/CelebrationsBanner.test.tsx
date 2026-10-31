import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

let feed: unknown
vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), get: vi.fn(async () => feed) }))

import { CelebrationsBanner } from './CelebrationsBanner'

const show = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><CelebrationsBanner /></MemoryRouter></QueryClientProvider>)

describe('the Celebrations banner is there every day', () => {
  it('says so when there is nothing today, and names what is next', async () => {
    feed = { today: [], upcoming: [{ key: 'festival:2026-11-08', kind: 'festival', date: '2026-11-08', title: 'Diwali', emoji: '🪔', message: '', days_away: 6 }], emojis: [], can_manage: false }
    show()
    expect(await screen.findByText(/No birthdays or special days today/)).toHaveTextContent('Next: Diwali, 8 Nov')
    expect(screen.getByRole('link', { name: 'Celebrations' })).toHaveAttribute('href', '/celebrations')
  })
  it('still shows when there is nothing today or coming', async () => {
    feed = { today: [], upcoming: [], emojis: [], can_manage: false }
    show()
    expect(await screen.findByText(/No birthdays or special days today/)).toBeInTheDocument()
  })
  it('shows today\'s celebrations when there are some', async () => {
    feed = { today: [{ key: 'birthday:1:2026', kind: 'birthday', date: '2026-11-02', title: "Asha's birthday", emoji: '🎂', message: '', reactions: [], wishes: [] }], upcoming: [], emojis: [], can_manage: false }
    show()
    expect(await screen.findByText(/Asha's birthday/)).toBeInTheDocument()
    expect(screen.getByText('Send wishes')).toBeInTheDocument()
  })
})
