import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { financialYears } from '@/api/payroll'

const posts: { url: string; body?: unknown }[] = []
const gets: string[] = []

const settlement = {
  last_day: '2026-03-13', start_date: '2018-04-01', monthly_salary: 65000, last_basic: 26000,
  service: { completed_years: 7, years_counted: 8 },
  gratuity: { eligible: true, amount: 120000, reason: '', years_counted: 8 },
  leave: { unused_days: 5, day_pay: 1000, amount: 5000 },
  arrears: { rows: [{ payslip: 'PS-0007', period_end: '2026-02-28', paid_on_salary: 30000, salary_now: 33000, amount: 3000 }], total: 3000 },
  parts: [
    { item: 'Salary for the final month', amount: 29545.45, note: '10 of 22 working days' },
    { item: 'Leave encashment', amount: 5000, note: '5 unused day(s) at 1000 a day (basic / 26)' },
    { item: 'Gratuity', amount: 120000, note: '15/26 x 26000 x 8 year(s)' },
    { item: 'Arrears of salary', amount: 3000, note: '1 payslip(s) short after a backdated increment' },
  ],
  total: 157545.45,
}
const ledger = {
  year: 2026, enabled: true, balance: { annual_total: 12, annual_remaining: 9, sick_total: 6, sick_remaining: 6 },
  entries: [
    { id: 1, leave_type: 'annual', kind: 'accrual', date: '2026-01-01', days: 2, note: '1/12 of 24 days', by: 'system' },
    { id: 2, leave_type: 'annual', kind: 'lapse', date: '2026-12-31', days: -3, note: 'Unused beyond the 10 day(s) that carry over', by: 'system' },
  ],
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => { gets.push(url); return url.includes('full-and-final') ? settlement : ledger }),
  post: vi.fn(async (url: string, body: unknown) => { posts.push({ url, body }); return { message: 'Leave adjusted' } }),
}))

import { EmployeePayTools } from './EmployeePayTools'

function mount(endDate?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><EmployeePayTools id={7} endDate={endDate} /></QueryClientProvider>)
}

beforeEach(() => { posts.length = 0; gets.length = 0 })

describe('Settlement, tax and leave for one person', () => {
  it('offers Form 16 for the chosen financial year', async () => {
    const user = userEvent.setup()
    mount()
    const years = financialYears()
    const link = screen.getByRole('link', { name: /form 16/i })
    expect(link.getAttribute('href')).toContain(`/api/employees/7/form16?fy=${years[0]}`)
    await user.selectOptions(screen.getByLabelText('Financial year'), years[1])
    expect(screen.getByRole('link', { name: /form 16/i }).getAttribute('href')).toContain(`fy=${years[1]}`)
  })

  it('shows the full and final settlement for their last day, part by part', async () => {
    const user = userEvent.setup()
    mount('2026-03-13')
    await user.click(screen.getByRole('button', { name: /full and final settlement/i }))
    expect(await screen.findByText('Gratuity')).toBeTruthy()
    expect(gets.at(-1)).toBe('/api/employees/7/full-and-final?last_day=2026-03-13')
    expect(screen.getByText('15/26 x 26000 x 8 year(s)')).toBeTruthy()
    expect(screen.getByText(/7 year\(s\) completed/)).toBeTruthy()
    const total = screen.getByText('Total payable').closest('tr')!
    expect(within(total).getByText(/1,57,545/)).toBeTruthy()
    expect(screen.getByRole('link', { name: /pdf/i }).getAttribute('href')).toContain('/api/employees/7/full-and-final.pdf?last_day=2026-03-13')
  })

  it('asks again when the last day is changed', async () => {
    const user = userEvent.setup()
    mount('2026-03-13')
    await user.click(screen.getByRole('button', { name: /full and final settlement/i }))
    await screen.findByText('Gratuity')
    const day = screen.getByLabelText('Last working day')
    await user.clear(day)
    await user.type(day, '2026-04-30')
    await waitFor(() => expect(gets.at(-1)).toBe('/api/employees/7/full-and-final?last_day=2026-04-30'))
  })

  it('lists the leave ledger and will not adjust without days and a reason', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(screen.getByRole('button', { name: /leave ledger/i }))
    expect(await screen.findByText('Accrued')).toBeTruthy()
    expect(screen.getByText('Lapsed')).toBeTruthy()
    expect(screen.getByText('+2')).toBeTruthy()
    expect(screen.getByText('-3')).toBeTruthy()
    const adjust = screen.getByRole('button', { name: 'Adjust' })
    expect((adjust as HTMLButtonElement).disabled).toBe(true)
    await user.type(screen.getByLabelText(/days \(negative/i), '2')
    expect((adjust as HTMLButtonElement).disabled).toBe(true)         // days, but no reason yet
    await user.type(screen.getByLabelText('Why'), 'Worked a holiday')
    expect((adjust as HTMLButtonElement).disabled).toBe(false)
    await user.click(adjust)
    await waitFor(() => expect(posts).toEqual([{ url: '/api/employees/7/leave-ledger', body: { leave_type: 'annual', days: 2, note: 'Worked a holiday' } }]))
  })

  it('says so when monthly accrual is off', async () => {
    const user = userEvent.setup()
    ledger.enabled = false
    mount()
    await user.click(screen.getByRole('button', { name: /leave ledger/i }))
    expect(await screen.findByText(/monthly accrual is off/i)).toBeTruthy()
    ledger.enabled = true
  })
})
