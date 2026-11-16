import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 20_000 })

const sent: { method: string; url: string; body?: unknown }[] = []
const perms = vi.hoisted(() => ({ set: new Set<string>() }))

const row = (over: Record<string, unknown>) => ({
  id: 1, payee: 'Sri Lakshmi Estates', head: 'Rent', job_id: null, project: '', amount: 25000, day_of_month: 5, start_date: '2026-11-01', end_date: '', next_due: '2026-12-05',
  status: 'Active', is_active: true, account_id: null, account: '', mode: '', note: '', raised_count: 3, last_raised_on: '2026-11-05', last_error: '', last_request: null, ...over,
})
const list = {
  payments: [
    row({ last_request: { number: 'PRQ-0012', status: 'Paid', due_on: '2026-11-05' } }),
    row({ id: 2, payee: 'Airtel Business', head: 'Telephone & internet', amount: 4200, day_of_month: 22, status: 'Paused', is_active: false, raised_count: 0 }),
    row({ id: 3, payee: 'Old Landlord', head: 'Rent', amount: 9000, last_error: 'Book it under one of: Rent.' }),
    row({ id: 4, payee: 'Insurance Co', head: 'Insurance', amount: 8000, status: 'Ended', is_active: false, next_due: '', end_date: '2026-10-15' }),
  ],
  summary: { active: 2, paused: 1, ended: 1, monthly: 34000, next_due: '2026-12-05', failing: 1 },
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url === '/api/recurring-payments') return list
    if (url.startsWith('/api/money/heads')) return { expense: ['Rent', 'Insurance', 'Telephone & internet'], income: [] }
    if (url.startsWith('/api/bank-accounts')) return { accounts: [] }
    if (url.startsWith('/api/jobs')) return { jobs: [{ id: 7, number: 'P-7', name: 'Tower C' }] }
    return {}
  }),
  post: vi.fn(async (url: string, body?: unknown) => { sent.push({ method: 'POST', url, body }); return { message: 'ok', payment: row({}) } }),
  put: vi.fn(async (url: string, body?: unknown) => { sent.push({ method: 'PUT', url, body }); return { message: 'ok', payment: row({}) } }),
  del: vi.fn(async (url: string) => { sent.push({ method: 'DELETE', url }); return { message: 'ok' } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ user: { type: 'client' }, can: (p: string) => perms.set.has(p) }) }))

import RecurringPage from './RecurringPage'

const mount = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><RecurringPage /></MemoryRouter>
  </QueryClientProvider>,
)

beforeEach(() => { sent.length = 0; perms.set = new Set(['accounts.manage', 'bills.view_all']) })

describe('the recurring payments page', () => {
  it('lists each one with when it falls due, where its last request stands, and its status', async () => {
    mount()
    expect(await screen.findByText('Sri Lakshmi Estates')).toBeInTheDocument()
    expect(screen.getAllByText('5th of every month').length).toBeGreaterThan(0)
    expect(screen.getByText('22nd of every month')).toBeInTheDocument()
    expect(screen.getByText('until 15 Oct 2026')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PRQ-0012' })).toHaveAttribute('href', '/money/approvals')
    const table = within(screen.getByRole('table', { name: 'Recurring payments' }))
    expect(table.getAllByText('Active')).toHaveLength(2)
    expect(table.getByText('Paused')).toBeInTheDocument()
    expect(table.getByText('Ended')).toBeInTheDocument()
    // A payment that could not be raised says why, on its own row.
    expect(screen.getByRole('alert')).toHaveTextContent('Could not be raised: Book it under one of: Rent.')
  })

  it('shows no controls to someone who may only read it', async () => {
    perms.set = new Set(['bills.view_all'])
    mount()
    await screen.findByText('Sri Lakshmi Estates')
    expect(screen.queryByRole('button', { name: /Recurring payment$/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Edit / })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Pause / })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Delete / })).not.toBeInTheDocument()
  })

  it('pauses an active one, resumes a paused one, and takes one away when asked twice', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('Sri Lakshmi Estates')
    await user.click(screen.getByRole('button', { name: 'Pause Sri Lakshmi Estates' }))
    await waitFor(() => expect(sent).toContainEqual(expect.objectContaining({ method: 'POST', url: '/api/recurring-payments/1/pause' })))
    await user.click(screen.getByRole('button', { name: 'Resume Airtel Business' }))
    await waitFor(() => expect(sent).toContainEqual(expect.objectContaining({ method: 'POST', url: '/api/recurring-payments/2/resume' })))
    await user.click(screen.getByRole('button', { name: 'Delete Airtel Business' }))
    expect(sent.some((s) => s.method === 'DELETE')).toBe(false)                          // not on the first click
    await user.click(await screen.findByRole('button', { name: 'Take off' }))
    await waitFor(() => expect(sent).toContainEqual(expect.objectContaining({ method: 'DELETE', url: '/api/recurring-payments/2' })))
  })

  it('sets one up: what is entered is what is sent, and the day reads back in words', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Recurring payment$/ }))
    const form = await screen.findByRole('dialog')
    const save = within(form).getByRole('button', { name: 'Set it up' })
    expect(save).toBeDisabled()                                                          // no payee, no amount yet
    await user.type(within(form).getByLabelText('Paid to'), 'Gulf Heavy Equipment')
    await user.type(within(form).getByLabelText('Amount each month'), '62000')
    await user.selectOptions(within(form).getByLabelText('Day of the month'), '15')
    await user.selectOptions(within(form).getByLabelText('Expense head'), 'Insurance')
    await user.selectOptions(within(form).getByLabelText('Project'), '7')
    expect(within(form).getByText(/on the/, { selector: 'p' })).toHaveTextContent('to Gulf Heavy Equipment on the 15th of every month')
    await user.click(save)
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toMatchObject({ method: 'POST', url: '/api/recurring-payments', body: { payee: 'Gulf Heavy Equipment', head: 'Insurance', amount: 62000, day_of_month: 15, end_date: '', job_id: 7, account_id: null, mode: '', note: '' } })
    expect((sent[0].body as { start_date: string }).start_date).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('opens one to change and saves it where it is', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Edit Sri Lakshmi Estates' }))
    const form = await screen.findByRole('dialog')
    expect(within(form).getByLabelText('Paid to')).toHaveValue('Sri Lakshmi Estates')
    const amount = within(form).getByLabelText('Amount each month')
    await user.clear(amount)
    await user.type(amount, '27500')
    await user.click(within(form).getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toMatchObject({ method: 'PUT', url: '/api/recurring-payments/1', body: { payee: 'Sri Lakshmi Estates', amount: 27500, day_of_month: 5 } })
  })
})
