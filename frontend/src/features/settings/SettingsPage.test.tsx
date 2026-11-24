import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Who is signed in, and what they hold.
let who: { type: 'owner' | 'employee'; held: string[] } = { type: 'owner', held: [] }
vi.mock('@/lib/session', () => ({
  useSession: () => ({ user: { type: who.type }, can: (p: string) => who.type === 'owner' || p.split('|').some((x) => who.held.includes(x)) }),
}))
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url === '/api/website/sections') {
      return { sections: [
        { key: 'hero', label: 'Opening banner', draft: { title: 'T', sub: 'S' }, published: { title: 'T', sub: 'S' }, unpublished_changes: false },
        { key: 'lead', label: 'Opening line', draft: 'New', published: 'Old', unpublished_changes: true },
      ], latest: null }
    }
    return {}
  }),
}))
// The Master's other tabs are not what is being tested here; each stands in as its name.
for (const [file, name] of [['./CompanyTab', 'Company tab'], ['./DocumentsTab', 'Documents tab'], ['./ApprovalsTab', 'Approvals tab'], ['./AccessTab', 'Access tab'], ['./DataTab', 'Data tab'], ['./ErrorLogTab', 'Errors tab']]) {
  vi.doMock(file, () => ({ default: () => <p>{name}</p> }))
}

import SettingsPage from './SettingsPage'

const mount = () => render(
  <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><SettingsPage /></QueryClientProvider></MemoryRouter>,
)

describe('Settings -> Website', () => {
  beforeEach(() => { who = { type: 'owner', held: [] } })

  it('is one of the Master\'s tabs', () => {
    mount()
    expect(screen.getByRole('tab', { name: 'Website' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Company' })).toBeTruthy()
  })

  it('is all a member of staff with "Manage website" sees, and says when a draft is waiting', async () => {
    who = { type: 'employee', held: ['website.manage'] }
    mount()
    expect(screen.queryByRole('tab', { name: 'Company' })).toBeNull()
    expect(await screen.findByRole('navigation', { name: 'Parts of the website' })).toBeTruthy()
    expect(screen.getByText(/Draft ready: 1 section changed/)).toBeTruthy()
  })

  it('shows staff without the right none of Settings', () => {
    who = { type: 'employee', held: ['people.manage'] }
    mount()
    expect(screen.queryByRole('tab')).toBeNull()
    expect(screen.queryByText('Website')).toBeNull()
    expect(screen.getByText('Settings are kept by the Master.')).toBeTruthy()
  })
})
