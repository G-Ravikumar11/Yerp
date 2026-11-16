import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { url: string; body?: unknown }[] = []
const base = { id: 1, transfer_number: 'TRF/SA/00001', date: '2026-11-10', from_project: 'Tower A', to_project: 'Tower B', amount: '3500.00', adjusted_by: 'Accounts', note: '' }
const items = [
  { ...base, id: 1, status: 'ADJUSTED', adjusted_on: '2026-11-11', reversed: false, reversed_on: '', txn_date: '2026-11-11', original_reference: 'XC-TRF/SA/00001', reversal_reference: '', original_amount: '3500.00', reversed_amount: null, export: { original: 'EXPORTED', reversal: 'NONE', error: '' } },
  { ...base, id: 2, transfer_number: 'TRF/SA/00002', status: 'REVERSE', adjusted_on: '2026-11-11', reversed: true, reversed_on: '2026-11-14T10:30:00', txn_date: '2026-11-14', original_reference: 'XC-TRF/SA/00002', reversal_reference: 'XCR-TRF/SA/00002', original_amount: '3500.00', reversed_amount: '3500.00', export: { original: 'EXPORTED', reversal: 'PENDING_EXPORT', error: '' } },
  { ...base, id: 3, transfer_number: 'TRF/SA/00003', status: 'REVERSE', adjusted_on: '2026-11-11', reversed: true, reversed_on: '', txn_date: '', original_reference: 'XC-TRF/SA/00003', reversal_reference: 'XCR-TRF/SA/00003', original_amount: '3500.00', reversed_amount: '3500.00', export: { original: 'PENDING_EXPORT', reversal: 'NEEDS_DATE', error: 'This adjustment was reversed before the reversal date was kept. Give the date it was reversed.' } },
]

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => (url.endsWith('/summary') ? { as_on: '2026-11-16', stock_value: '0', by_category: [], scrap_to_collect: '0', scrap_sales_open: 0, cross_charges_pending: '0', cross_charges_open: 0, accounts_view: true } : { items })),
  post: vi.fn(async (url: string, body?: unknown) => { calls.push({ url, body }); return { reversed_on: '2026-11-15T00:00:00' } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true }) }))
vi.mock('@/api/money', () => ({ useBankAccounts: () => ({ data: [] }) }))

import AccountsPage from './AccountsPage'

const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AccountsPage /></QueryClientProvider>)

beforeEach(() => { calls.length = 0 })

describe('Cross-charges between projects', () => {
  it('shows an adjustment on its adjustment date and a reversal on its reversal date, each with its Tally state', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('tab', { name: 'Between projects' }))
    const table = await screen.findByRole('table', { name: 'Between projects' })
    const adjusted = within(table).getByText('TRF/SA/00001').closest('tr')!
    expect(within(adjusted).getByText('11 Nov 2026')).toBeTruthy()
    expect(within(adjusted).getByText('Adjustment')).toBeTruthy()
    expect(within(adjusted).getByText('Adjustment exported')).toBeTruthy()
    const reversed = within(table).getByText('TRF/SA/00002').closest('tr')!
    expect(within(reversed).getByText('14 Nov 2026')).toBeTruthy()                       // the reversal's day, not the adjustment's 11th
    expect(within(reversed).getByText('Reversal')).toBeTruthy()
    expect(within(reversed).getByText('Reversed - put back')).toBeTruthy()
    expect(within(reversed).getByText('Reversal pending export')).toBeTruthy()
    expect(within(table).getByText('Reversal needs a date')).toBeTruthy()
  })

  it('opens a reversal beside its original, and lets accounts give a missing reversal date', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('tab', { name: 'Between projects' }))
    const table = await screen.findByRole('table', { name: 'Between projects' })
    await user.click(within(table).getByText('TRF/SA/00002'))
    let dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Original adjustment')).toBeTruthy()
    expect(within(dialog).getByText('REVERSED')).toBeTruthy()
    expect(within(dialog).getAllByText('XC-TRF/SA/00002').length).toBeGreaterThan(0)    // the original it reverses
    expect(within(dialog).getByText('XCR-TRF/SA/00002')).toBeTruthy()
    expect(within(dialog).getByText('14 Nov 2026')).toBeTruthy()
    expect(within(dialog).getAllByText('3,500.00')).toHaveLength(2)                      // the original amount and the reversed amount
    await user.click(within(dialog).getAllByRole('button', { name: /close/i })[0])
    await user.click(within(table).getByText('TRF/SA/00003'))
    dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('alert').textContent).toMatch(/reversal date/)
    const day = within(dialog).getByLabelText('Date it was reversed') as HTMLInputElement
    await user.clear(day)
    await user.type(day, '2026-11-15')
    await user.click(within(dialog).getByRole('button', { name: 'Save reversal date' }))
    await waitFor(() => expect(calls[0]).toEqual({ url: '/api/store/accounts/cross-charges/3/reversal-date', body: { reversed_on: '2026-11-15' } }))
  })
})
