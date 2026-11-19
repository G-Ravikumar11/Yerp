import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 30_000 })

const asked: string[] = []
const entry = (over: Record<string, unknown>) => ({
  id: 1, number: 'PMT-0001', direction: 'OUT', party_type: 'other', party_name: 'Landlord', doc_type: 'expense', doc_number: '', account: 'HDFC', amount: 25000, paid_on: '2026-11-10', mode: 'Bank transfer',
  reference: 'UTR1', note: '', voided: false, void_reason: '', head: 'Rent', job_id: 7, payee_bank: 'State Bank of India', payee_account: '30123456789', payee_ifsc: 'SBIN0001234', ...over,
})

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    asked.push(url)
    if (url.startsWith('/api/ledger/parties')) return { parties: [{ party_type: 'supplier', party: 'ACC Ltd', billed: 0, moved: 1000, last: '', balance: -1000 }], summary: {} }
    if (url === '/api/money/entries') return { entries: [entry({}), entry({ id: 2, number: 'PMT-0002', party_name: 'Other site vendor', job_id: 8, payee_account: '' })], summary: { received: 0, paid: 50000, expenses: 50000, transferred: 0, entries: 2 } }
    if (url.startsWith('/api/jobs')) return { jobs: [{ id: 7, number: 'P-7', name: 'Tower C' }, { id: 8, number: 'P-8', name: 'Beta Homes' }] }
    if (url.startsWith('/api/openings') || url.startsWith('/api/ledger/openings')) return { openings: [] }
    return {}
  }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ user: { type: 'client' }, can: () => true }) }))

import LedgerPage from './LedgerPage'

beforeAll(async () => { await import('./EntriesTab'); await import('./PartiesTab') })

const mount = (path: string) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><LedgerPage /></MemoryRouter>
  </QueryClientProvider>,
)

describe('the ledgers of one project', () => {
  it('asks only for that project\'s party ledgers, and says so', async () => {
    mount('/money/ledgers?project=7')
    expect(await screen.findByText(/Showing the ledgers of/)).toBeInTheDocument()
    expect(await screen.findByText('ACC Ltd')).toBeInTheDocument()
    expect(asked.some((u) => u.startsWith('/api/ledger/parties') && u.includes('job_id=7'))).toBe(true)
  })

  it('lists only that project\'s vouchers, with where a bank transfer went', async () => {
    mount('/money/ledgers?tab=entries&project=7')
    const table = within(await screen.findByRole('table', { name: 'Receipts and payments' }))
    expect(await table.findByText('PMT-0001')).toBeInTheDocument()
    expect(table.queryByText('PMT-0002')).not.toBeInTheDocument()
    expect(table.getByText(/to State Bank of India - 30123456789 - SBIN0001234/)).toBeInTheDocument()
  })

  it('shows every project again when asked', async () => {
    mount('/money/ledgers?tab=entries&project=7')
    await screen.findByText(/Showing the ledgers of/)
    await userEvent.click(screen.getByRole('button', { name: 'Show every project' }))
    const table = within(await screen.findByRole('table', { name: 'Receipts and payments' }))
    expect(await table.findByText('PMT-0002')).toBeInTheDocument()
    expect(screen.queryByText(/Showing the ledgers of/)).not.toBeInTheDocument()
  })
})
