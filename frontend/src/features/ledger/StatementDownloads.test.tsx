import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 30_000 })

const csv = vi.hoisted(() => ({ calls: [] as { name: string; headers: string[]; rows: (string | number)[][] }[] }))
vi.mock('@/lib/utils', async (orig) => ({
  ...(await orig<typeof import('@/lib/utils')>()),
  downloadCsv: (name: string, headers: string[], rows: (string | number)[][]) => { csv.calls.push({ name, headers, rows }) },
}))

const statement = (master: unknown) => ({
  party: 'Kokapet LLP', party_type: 'client', master, our: {}, opening: 0, closing: 5000, billed: 12000, moved: 7000, closing_words: 'Five thousand rupees only',
  rows: [{ date: '2026-11-01', kind: 'RA bill', number: 'RA-1', billed: 12000, moved: 0, balance: 12000 }, { date: '2026-11-10', kind: 'Receipt', number: 'RCT-1', billed: 0, moved: 7000, balance: 5000 }],
})
let master: unknown = null

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url.startsWith('/api/ledger/statement')) return statement(master)
    if (url.startsWith('/api/ledger/parties')) return { parties: [{ party_type: 'client', party: 'Kokapet LLP', billed: 12000, moved: 7000, last: '2026-11-10', balance: 5000 }], summary: {} }
    if (url.startsWith('/api/bank-accounts')) return { accounts: [{ id: 1, name: 'HDFC current', kind: 'Bank', bank_name: '', account_no: '', ifsc: '', opening_balance: 0, opening_date: '', is_active: true }] }
    if (url.startsWith('/api/money/book')) return { opening: 1000, rows: [{ id: 1, date: '2026-11-02', number: 'RCT-1', party: 'Kokapet LLP', against: 'RA-1', mode: 'Bank transfer', reference: 'UTR1', received: 7000, paid: 0, balance: 8000 }], received: 7000, paid: 0, closing: 8000 }
    if (url === '/api/money/entries') return { entries: [], summary: { received: 0, paid: 0, expenses: 0, transferred: 0, entries: 0 } }
    if (url.startsWith('/api/ledger/openings') || url.startsWith('/api/openings')) return { openings: [] }
    if (url.startsWith('/api/jobs')) return { jobs: [] }
    return {}
  }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ user: { type: 'client' }, can: () => true }) }))

import { StatementModal } from './StatementModal'
import { PartiesTab } from './PartiesTab'
import { BankTab } from './BankTab'
import { EntriesTab } from './EntriesTab'

beforeAll(async () => { await Promise.all([import('./PartiesTab'), import('./BankTab'), import('./EntriesTab')]) })
beforeEach(() => { csv.calls.length = 0; master = null })

const wrap = (ui: React.ReactNode) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>,
)

describe('downloading statements in Ledgers & Bank', () => {
  it('a client\'s statement opens even though a client has no record of its own, and its PDF link is there', async () => {
    wrap(<StatementModal target={{ type: 'client', party: 'Kokapet LLP' }} onClose={() => undefined} />)
    const pdf = await screen.findByRole('link', { name: /PDF/ })
    expect(pdf).toHaveAttribute('href', '/api/ledger/statement.pdf?party_type=client&party=Kokapet%20LLP')
    expect(screen.getByText('RA-1')).toBeInTheDocument()
    expect(screen.getByText(/Balance due from you/)).toBeInTheDocument()
  })

  it('shows the GSTIN and PAN of a party that has a record', async () => {
    master = { name: 'ACC Ltd', gstin: '29ABCDE1234F1Z5', pan: 'ABCDE1234F', phone: '9999' }
    wrap(<StatementModal target={{ type: 'supplier', party: 'ACC Ltd' }} onClose={() => undefined} />)
    expect(await screen.findByText(/GSTIN 29ABCDE1234F1Z5/)).toBeInTheDocument()
  })

  it('each party in the list has a direct download for its statement', async () => {
    wrap(<PartiesTab />)
    const link = await screen.findByRole('link', { name: 'Download the statement of Kokapet LLP (PDF)' })
    expect(link).toHaveAttribute('href', '/api/ledger/statement.pdf?party_type=client&party=Kokapet%20LLP')
  })

  it('the bank book downloads as a spreadsheet: opening, every movement with its balance, closing', async () => {
    const user = userEvent.setup()
    wrap(<BankTab />)
    const button = await screen.findByRole('button', { name: /Download statement/ })
    await screen.findByText('RCT-1')
    await user.click(button)
    expect(csv.calls).toHaveLength(1)
    expect(csv.calls[0].name).toBe('bank-book-hdfc-current')
    expect(csv.calls[0].headers).toEqual(['Date', 'No.', 'Party', 'Against', 'Mode', 'Reference', 'In', 'Out', 'Balance'])
    expect(csv.calls[0].rows[0][2]).toBe('Opening balance')
    expect(csv.calls[0].rows[1]).toEqual(['2026-11-02', 'RCT-1', 'Kokapet LLP', 'RA-1', 'Bank transfer', 'UTR1', 7000, '', 8000])
    expect(csv.calls[0].rows.at(-1)?.[2]).toBe('Closing balance')
  })

  it('receipts and payments can be downloaded as Excel', async () => {
    wrap(<EntriesTab />)
    const link = await within(document.body).findByRole('link', { name: /Download \(Excel\)/ })
    expect(link).toHaveAttribute('href', '/api/money/entries.xlsx')
  })
})
