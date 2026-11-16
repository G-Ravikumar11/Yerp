import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 20_000 })

const sent: { method: string; url: string; body: unknown }[] = []

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url.startsWith('/api/ledger/parties')) return { parties: [{ party_type: 'supplier', party: 'ACC Ltd', billed: 0, moved: 0, last: '', balance: 0 }], summary: {} }
    if (url.startsWith('/api/suppliers')) return { suppliers: [{ id: 1, name: 'Sri Sai Steel' }], unregistered: [] }
    if (url.startsWith('/api/jobs')) return { jobs: [{ id: 7, number: 'P-7', name: 'Tower C' }] }
    return {}
  }),
  post: vi.fn(async (url: string, body: unknown) => { sent.push({ method: 'POST', url, body }); return { message: 'kept', opening: {} } }),
  put: vi.fn(async (url: string, body: unknown) => { sent.push({ method: 'PUT', url, body }); return { message: 'saved', opening: {} } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ user: { type: 'client' }, can: () => true }) }))

import { OpeningModal } from './OpeningModal'
import type { Opening } from '@/api/ledger'

const mount = (target: Opening | 'new') => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><OpeningModal target={target} onClose={() => undefined} /></MemoryRouter>
  </QueryClientProvider>,
)

beforeEach(() => { sent.length = 0 })

describe('the opening balance form', () => {
  it('says which way a balance runs in the words of the party type, and sends what was entered', async () => {
    const user = userEvent.setup()
    mount('new')
    // A supplier: we owe them, or we paid them ahead.
    const side = await screen.findByLabelText('Which way it runs')
    expect(screen.getByRole('option', { name: 'We owe them' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'We paid them in advance' })).toBeInTheDocument()
    // A client: the other words, and the side goes back to the usual one.
    await user.selectOptions(screen.getByLabelText('Party type'), 'client')
    expect(screen.getByRole('option', { name: 'They owe us' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'We owe them' })).not.toBeInTheDocument()
    expect((side as HTMLSelectElement).value).toBe('owed')

    const save = screen.getByRole('button', { name: 'Add the opening balance' })
    expect(save).toBeDisabled()                                                  // no name, no amount yet
    await user.type(screen.getByLabelText('Name'), 'Kokapet LLP')
    await user.type(screen.getByLabelText('Amount'), '120000')
    await user.selectOptions(side, 'advance')
    expect(screen.getByText(/They paid us in advance/i, { selector: 'p *, p' })).toBeInTheDocument()
    await user.click(save)
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].method).toBe('POST')
    expect(sent[0].url).toBe('/api/ledger/openings')
    expect(sent[0].body).toMatchObject({ party_type: 'client', party_name: 'Kokapet LLP', side: 'advance', amount: 120000, job_id: null, note: '' })
    expect((sent[0].body as { as_on: string }).as_on).toMatch(/^\d{4}-04-01$/)       // starts at the financial year's 1 April
  })

  it('opens an entered one to change, and saves it where it is', async () => {
    const user = userEvent.setup()
    const o: Opening = { id: 4, number: 'OB-0004', party_type: 'supplier', party: 'ACC Ltd', side: 'owed', means: 'We owe them', amount: 50000, balance: 50000, as_on: '2026-04-01', job_id: 7, project: 'P-7 Tower C', note: 'their statement', created_by_name: 'A', created_at: '' }
    mount(o)
    expect(await screen.findByDisplayValue('ACC Ltd')).toBeInTheDocument()
    expect(screen.getByDisplayValue('their statement')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toMatchObject({ method: 'PUT', url: '/api/ledger/openings/4', body: { party_name: 'ACC Ltd', amount: 50000, as_on: '2026-04-01', job_id: 7 } })
  })
})
