import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PayrollMonth } from '@/api/payroll'
import { payslipTone } from '@/api/payroll'

const calls: { url: string; body?: unknown }[] = []
let months: PayrollMonth[] = []
let owner = true

const month = (status: PayrollMonth['status'], extra: Partial<PayrollMonth> = {}): PayrollMonth => ({
  month: '2026-10', status, payslips: 3, net_pay: 90000, approved_at: '', approved_by: '', paid_at: '', locked_at: '',
  locked_by: '', reopened_at: '', reopened_by: '', reopen_reason: '', ...extra,
})

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async () => months),
  post: vi.fn(async (url: string, body: unknown) => { calls.push({ url, body }); return { message: 'ok', ...months[0] } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ isOwner: owner }) }))

import { MonthPanel } from './MonthPanel'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MonthPanel /></QueryClientProvider>)
}

beforeEach(() => { calls.length = 0; owner = true })
afterEach(() => { vi.unstubAllGlobals() })

describe('The payroll month', () => {
  it('offers the next step and confirms it before moving the month', async () => {
    months = [month('Draft')]
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Approve month' }))
    expect(screen.getByText(/staff can see their payslips once the month is approved/i)).toBeTruthy()
    await user.click(screen.getAllByRole('button', { name: 'Approve month' }).at(-1)!)
    await waitFor(() => expect(calls).toEqual([{ url: '/api/payroll/month/approve', body: { month: '2026-10' } }]))
  })

  it.each([['Approved', 'Mark month paid', 'pay'], ['Paid', 'Lock month', 'lock']] as const)('a %s month is %s next', async (status, button, action) => {
    months = [month(status)]
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: button }))
    await user.click(screen.getAllByRole('button', { name: button }).at(-1)!)
    await waitFor(() => expect(calls[0]?.url).toBe(`/api/payroll/month/${action}`))
  })

  it('lets the Master reopen a locked month, only with a reason', async () => {
    months = [month('Locked', { locked_by: 'Master', locked_at: '2026-11-02 10:00:00' })]
    const user = userEvent.setup()
    mount()
    expect(await screen.findByText(/Locked by Master on 2026-11-02/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /reopen month/i }))
    await user.click(screen.getAllByRole('button', { name: /reopen month/i }).at(-1)!)
    expect(calls).toEqual([])                                   // no reason, nothing sent
    await user.type(screen.getByLabelText(/why is it being reopened/i), 'Wrong PF on two payslips')
    await user.click(screen.getAllByRole('button', { name: /reopen month/i }).at(-1)!)
    await waitFor(() => expect(calls).toEqual([{ url: '/api/payroll/month/reopen', body: { month: '2026-10', reopen_reason: 'Wrong PF on two payslips' } }]))
  })

  it('does not offer HR the reopen button', async () => {
    owner = false
    months = [month('Locked')]
    mount()
    expect(await screen.findByText(/only the master can reopen it/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /reopen month/i })).toBeNull()
  })

  it('names who is missing from a file and offers it without them', async () => {
    months = [month('Approved')]
    const fetched: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      fetched.push(url)
      return url.includes('allow_incomplete')
        ? new Response(new Blob(['a,b']), { status: 200, headers: { 'content-disposition': 'attachment; filename="Salary_NEFT_2026-10.xlsx"', 'X-Rows-Left-Out': '1' } })
        : new Response(JSON.stringify({ detail: '1 people cannot go in the file: Ravi Kumar (no IFSC).' }), { status: 400 })
    }))
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} }))
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /NEFT bank file/i }))
    expect(await screen.findByText(/Ravi Kumar \(no IFSC\)/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Download without them' }))
    await waitFor(() => expect(fetched.at(-1)).toContain('/api/payroll/exports/neft?month=2026-10&allow_incomplete=true'))
    await waitFor(() => expect(screen.queryByText(/Ravi Kumar \(no IFSC\)/)).toBeNull())
  })

  it('shows nothing when there is no payroll yet', async () => {
    months = []
    const { container } = mount()
    await waitFor(() => expect(container.textContent).toBe(''))
  })
})

describe('Payslip status colours', () => {
  it('are green for paid whatever the case', () => {
    expect(['Paid', 'paid', 'PAID'].map(payslipTone)).toEqual(['success', 'success', 'success'])
    expect(payslipTone('Sent')).toBe('info')
    expect(payslipTone('Draft')).toBe('neutral')
    expect(payslipTone('Void')).toBe('danger')
  })
})
