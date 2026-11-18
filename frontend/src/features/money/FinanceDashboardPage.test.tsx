import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 30_000 })

const asked: string[] = []
let data: unknown
const project = {
  project: {
    job_id: 7, number: 'P-7', name: 'Tower C', customer_name: 'L&T', status: 'ACTIVE', contract_value: 5000000, billed: 300000, paid: 0, unpaid: 0, incurred: 1200000, commitment: 400000,
    forecast_cost: 4000000, invoiced: 2000000, received: 1500000, outstanding: 500000, retention_held: 100000, retention_percent: 5, margin: 1000000, margin_percent: 20, percent_complete: 40,
    over_billed: 0, labour: 0, bills_awaiting_approval: 0, categories: [{ key: 'material', label: 'Material', amount: 800000 }],
    bill_list: [{ id: 1, number: 'SB-1', supplier: 'ACC Ltd', status: 'Awaiting Payment', total: 59000 }], purchase_order_list: [], subcontract_list: [], work_order_list: [],
  },
  to_receive: [{ id: 3, number: 'RA-3', kind: 'RA bill', customer: 'L&T', due_date: '2026-12-01', outstanding: 500000, bucket: 'Not due', days_overdue: 0 }],
  to_pay: [{ id: 1, number: 'SB-1', kind: 'Supplier bill', party: 'ACC Ltd', due_date: '2026-11-20', outstanding: 59000, bucket: 'Not due', days_overdue: 0, approved: true,
    payment_request: { number: 'PRQ-0002', status: 'APPROVED', label: 'Approved - to pay' } }],
  receive_total: 500000, pay_total: 59000, overdue_receive: 0, overdue_pay: 0,
  entries: [{ id: 9, number: 'RCP-1', direction: 'IN', party_name: 'L&T', doc_number: 'RA-2', doc_type: 'ra_bill', head: '', amount: 1500000, paid_on: '2026-11-01', mode: 'Bank transfer' }],
  payment_requests: [{ id: 2, number: 'PRQ-0002', doc_number: 'SB-1', party_name: 'ACC Ltd', head: '', amount: 59000, status: 'APPROVED', status_label: 'Approved - to pay', expired: false, requested_by_name: 'Asha', requested_at: '2026-11-10 10:00:00', approved_by_name: 'Raju', rejected_by_name: '', reject_reason: '' }],
  request_summary: { with_accounts: 0, with_md: 0, to_pay: 59000, open: 1 }, monthly: [{ month: '2026-11', received: 1500000, paid: 0 }],
  received: 1500000, paid: 0, advances: { contractors: 0, suppliers: 0, on_account_contractors: 0, staff: 0, other: 0 }, site_cash: [], journal_cost: 0, debit_notes: 0,
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    asked.push(url)
    if (url === '/api/jobs-pnl') return { projects: [{ job_id: 7, number: 'P-7', name: 'Tower C' }, { job_id: 8, number: 'P-8', name: 'Beta Homes' }], summary: {} }
    if (url === '/api/money/project-accounts/7') return data ?? project
    if (url === '/api/reports/balance-sheet') return { assets: { bank_and_cash: 100000 }, liabilities: {} }
    if (url === '/api/reports/profit-loss') return { months: [], revenue: [], expenses: [], profit: [], total_expenses: 0 }
    if (url.startsWith('/api/money/cash-flow')) return { months: [] }
    if (url === '/api/attention') return { items: [], summary: {} }
    if (url === '/api/money/receivables') return { invoices: [], buckets: {}, summary: { owed: 0, overdue: 0 } }
    if (url === '/api/money/payables') return { bills: [], buckets: {}, summary: { owed: 0, overdue: 0 } }
    return {}
  }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ user: { type: 'client' }, can: () => true }) }))

import FinanceDashboardPage from './FinanceDashboardPage'

beforeAll(async () => { await import('./ProjectAccounts') })

const mount = (path = '/money/dashboard') => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><FinanceDashboardPage /></MemoryRouter>
  </QueryClientProvider>,
)

describe('the finance dashboard for one project', () => {
  it('shows the whole company until a project is chosen, then only that project', async () => {
    mount()
    const pick = await screen.findByRole('combobox', { name: 'Project' })
    expect(await within(pick).findByRole('option', { name: 'P-7 Tower C' })).toBeInTheDocument()
    expect(screen.getByText('Total Receivables')).toBeInTheDocument()
    await userEvent.selectOptions(pick, '7')
    expect(await screen.findByText('Money in: what the client pays')).toBeInTheDocument()
    expect(asked).toContain('/api/money/project-accounts/7')
    expect(screen.queryByText('Total Receivables')).not.toBeInTheDocument()
    // The bills behind the figures, and where the payment approval stands.
    expect(within(screen.getByRole('table', { name: 'Bills to receive' })).getByText('RA-3')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Bills to pay' })).getByText('approved - to pay')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Payments and receipts' })).getByText('RCP-1')).toBeInTheDocument()
    // Its payment requests, as Payment Approvals lists them, and the money by month.
    expect(within(screen.getByRole('table', { name: 'Payment requests' })).getByText('PRQ-0002')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Money by month' })).getByText('2026-11')).toBeInTheDocument()
    // Back to every project.
    await userEvent.selectOptions(pick, '')
    expect(await screen.findByText('Total Receivables')).toBeInTheDocument()
  })

  it('opens straight on a project from its link', async () => {
    mount('/money/dashboard?project=7')
    expect(await screen.findByText('Money in: what the client pays')).toBeInTheDocument()
    expect(screen.getByText('Tower C')).toBeInTheDocument()
  })

  it('does not break on an older answer kept from before a field was added', async () => {
    const { payment_requests: _a, request_summary: _b, monthly: _c, ...old } = project
    data = old
    mount('/money/dashboard?project=7')
    expect(await screen.findByText('Payment approvals for this project')).toBeInTheDocument()
    expect(screen.getByText('No payment has been asked for on this project.')).toBeInTheDocument()
    data = project
  })
})
