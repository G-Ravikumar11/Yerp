import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PayslipDetail } from '@/api/payroll'

const calls: { method: string; url: string; body?: unknown }[] = []
const components = [
  { id: 1, name: 'Basic', kind: 'earning', basis: 'percent', percent: 40, counts_as: 'basic', is_active: true, sort_order: 1 },
  { id: 2, name: 'HRA', kind: 'earning', basis: 'manual', percent: 0, counts_as: 'allowance', is_active: true, sort_order: 2 },
  { id: 3, name: 'PF', kind: 'deduction', basis: 'percent', percent: 12, counts_as: 'pf', is_active: false, sort_order: 3 },
]

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async () => ({ components })),
  post: vi.fn(async (url: string, body: unknown) => { calls.push({ method: 'POST', url, body }); return { message: 'ok' } }),
  put: vi.fn(async (url: string, body: unknown) => { calls.push({ method: 'PUT', url, body }); return { message: 'ok' } }),
  del: vi.fn(async (url: string) => { calls.push({ method: 'DELETE', url }); return { message: 'ok' } }),
}))

import { SalaryStructureModal } from './SalaryStructureModal'
import { payslipHtml } from './print'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><SalaryStructureModal open onClose={() => {}} /></QueryClientProvider>)
}

beforeEach(() => { calls.length = 0 })

describe('The salary structure screen', () => {
  it('lists each component and how it is worked out', async () => {
    mount()
    const basic = (await screen.findByText('Basic')).closest('tr')!
    expect(within(basic).getByText('40% of the monthly salary')).toBeTruthy()
    expect(within(screen.getByText('HRA').closest('tr')!).getByText('Typed on each payslip')).toBeTruthy()
    expect(within(screen.getByText('PF').closest('tr')!).getByText('Off')).toBeTruthy()
  })

  it('adds a component', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('Basic')
    await user.click(screen.getByRole('button', { name: /add a component/i }))
    await user.type(screen.getByLabelText('Name'), 'Site allowance')
    await user.clear(screen.getByLabelText('Percentage'))
    await user.type(screen.getByLabelText('Percentage'), '5')
    await user.click(screen.getByRole('button', { name: 'Add it' }))
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0]).toMatchObject({ method: 'POST', url: '/api/salary-structure', body: { name: 'Site allowance', kind: 'earning', basis: 'percent', percent: 5 } })
  })

  it('changes a percentage, switches a component off and moves one down', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('Basic')
    await user.click(screen.getByRole('button', { name: 'Edit Basic' }))
    await user.clear(screen.getByLabelText('Percentage'))
    await user.type(screen.getByLabelText('Percentage'), '50')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT' && c.url === '/api/salary-structure/1')).toBe(true))
    expect(calls.find((c) => c.url === '/api/salary-structure/1')!.body).toMatchObject({ percent: 50 })
    await user.click(screen.getByRole('switch', { name: 'Basic on payslips' }))
    await waitFor(() => expect(calls.some((c) => (c.body as { is_active?: boolean } | undefined)?.is_active === false)).toBe(true))
    await user.click(screen.getByRole('button', { name: 'Move Basic down' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/salary-structure/reorder')).toBe(true))
    expect(calls.find((c) => c.url === '/api/salary-structure/reorder')!.body).toEqual({ ids: [2, 1, 3] })
  })

  it('asks before removing one', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('Basic')
    await user.click(screen.getByRole('button', { name: 'Remove HRA' }))
    expect(calls.length).toBe(0)
    await user.click(screen.getByRole('button', { name: 'Remove it' }))
    await waitFor(() => expect(calls).toEqual([{ method: 'DELETE', url: '/api/salary-structure/2' }]))
  })
})

describe('The printed payslip', () => {
  const slip = {
    id: 1, number: 'PS-0001', employee: { full_name: 'A B', employee_id: 'E1', email: '', job_title: '', department_name: '', bank_name: '', bank_account: '', tax_id: '', start_date: '2025-08-16', work_location: '' },
    days: { total: 30, work: 30, balance_leaves: 0 }, period_start: '2026-09-01', period_end: '2026-09-30', pay_date: '2026-09-30',
    hours_worked: 0, overtime_hours: 0, overtime_rate: 0, basic_salary: 26000, overtime_pay: 0, bonus: 0, allowances: 19500, gross_pay: 45500,
    tax_amount: 0, insurance: 0, retirement: 7800, other_deductions: 0, standing_deduction: 0, total_deductions: 7800, net_pay: 37700,
    status: 'Draft', sent: false, notes: '', company: { name: 'Acme', address: '', email: '', phone: '' }, monthly_salary: 65000,
    lines: [
      { id: 1, name: 'Basic', kind: 'earning', basis: 'percent', percent: 40, counts_as: 'basic', amount: 26000 },
      { id: 2, name: 'Medical allowance', kind: 'earning', basis: 'percent', percent: 20, counts_as: 'allowance', amount: 13000 },
      { id: 3, name: 'PF', kind: 'deduction', basis: 'percent', percent: 12, counts_as: 'pf', amount: 7800 },
    ],
  } as unknown as PayslipDetail

  it('shows the structure\'s own components, and the monthly salary it was worked from', () => {
    const html = payslipHtml(slip)
    expect(html).toContain('Medical allowance')
    expect(html).toContain('>65000<')
    expect(html).not.toContain('Site Allowance')
  })

  it('keeps the office sheet\'s fixed columns for a payslip made without the structure', () => {
    const html = payslipHtml({ ...slip, lines: [], monthly_salary: undefined })
    expect(html).toContain('Site Allowance')
    expect(html).not.toContain('Medical allowance')
  })
})
