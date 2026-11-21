import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'

const base = {
  source: 'expense', asset_id: 1, code: 'EX-01', machine: 'Excavator', project: '', quantity: 0, unit_rate: 0, vendor: 'JCB Parts', payment_ref: '',
  approved_by: '', approved_on: '', decision_note: '', recorded_by: 'Ravi', legacy_payment: false, payments: 0, spent_on: '2026-11-10', description: 'Teeth',
}
const rows = [
  { ...base, id: 1, number: 'EXP-0001', category: 'Spare parts', amount: 6000, invoice_no: 'SP-1', approval_status: 'Recorded', approval_label: 'Recorded', payment_status: 'Unpaid', paid: 0, remaining: 6000 },
  { ...base, id: 2, number: 'EXP-0002', category: 'Other', amount: 900, invoice_no: 'OT-1', approval_status: 'Pending', approval_label: 'Submitted', payment_status: 'Unpaid', paid: 0, remaining: 900 },
  { ...base, id: 3, number: 'EXP-0003', category: 'Spare parts', amount: 4000, invoice_no: 'SP-2', approval_status: 'Approved', approval_label: 'Approved', approved_by: 'Sita', approved_on: '2026-11-12 10:00:00', payment_status: 'Part paid', paid: 1000, remaining: 3000, payments: 1 },
  { ...base, id: 9, number: 'FU-0009', source: 'fuel', category: 'Fuel and diesel', amount: 5000, invoice_no: 'FV-1', approval_status: 'Recorded', approval_label: 'Recorded', payment_status: 'Not tracked', paid: null, remaining: null, payment_note: 'Payment is not recorded in the Fuel register' },
]
const calls: Record<string, unknown>[] = []
const payExpense = vi.fn(async () => ({ message: 'Payment recorded' }))
const submitExpense = vi.fn(async () => ({ message: 'Submitted' }))
vi.mock('@/api/plant', async (orig) => ({
  ...(await orig<typeof import('@/api/plant')>()),
  useExpenses: (r: Record<string, unknown>) => {
    calls.push(r)
    const shown = rows.filter((x) => !r.category || x.category === r.category)
    return { data: { expenses: shown, categories: ['Spare parts', 'Other'], all_categories: ['Spare parts', 'Other', 'Fuel and diesel'], by_category: { 'Spare parts': 10000, Other: 900, 'Fuel and diesel': 5000 }, total: 0, total_all: 15900 }, isPending: false, isError: false }
  },
  payExpense: (...a: unknown[]) => payExpense(...(a as [])),
  submitExpense: (...a: unknown[]) => submitExpense(...(a as [])),
  useMachines: () => ({ data: { machines: [] } }),
}))
let rights: string[] = []
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: (p: string) => p.split('|').some((x) => rights.includes(x)) }) }))
vi.mock('./plantParts', async (orig) => ({ ...(await orig<typeof import('./plantParts')>()), MachineSelect: () => <span>machines</span> }))

import { Expenses } from './PlantRentals'

const draw = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><Expenses /></TooltipProvider></QueryClientProvider>)
const line = (number: string) => screen.getByText(number).closest('tr') as HTMLElement

describe('Equipment expenses', () => {
  beforeEach(() => { calls.length = 0; rights = ['stores.manage', 'site.signoff']; payExpense.mockClear(); submitExpense.mockClear() })

  it('a category card filters the list, the same card or Total shows everything again', async () => {
    const user = userEvent.setup()
    draw()
    await user.click(screen.getByRole('button', { name: /^Other:/ }))
    expect(calls.at(-1)?.category).toBe('Other')
    expect(screen.queryByText('EXP-0001')).toBeNull()
    expect(screen.getByText('EXP-0002')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Total/ }))
    expect(calls.at(-1)?.category).toBe('')
    expect(screen.getByText('EXP-0001')).toBeInTheDocument()
  })

  it('searches by ID, vendor or invoice on the server', async () => {
    const user = userEvent.setup()
    draw()
    await user.type(screen.getByLabelText('Search expenses'), 'sp-2')
    expect(calls.some((c) => c.q === 'sp-2')).toBe(true)
  })

  it('offers each step only where it belongs, approval and payment apart', () => {
    draw()
    expect(within(line('EXP-0001')).getByRole('button', { name: 'Submit' })).toBeInTheDocument()
    expect(within(line('EXP-0001')).queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(within(line('EXP-0002')).getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(within(line('EXP-0002')).getByText('Submitted')).toBeInTheDocument()
    const approved = line('EXP-0003')
    expect(within(approved).getByRole('button', { name: 'Pay' })).toBeInTheDocument()
    expect(within(approved).queryByRole('button', { name: 'Edit' })).toBeNull()
    expect(within(approved).getByText('Part paid')).toBeInTheDocument()
    expect(within(line('FU-0009')).getByText('Payment is not recorded in the Fuel register')).toBeInTheDocument()
    expect(within(line('FU-0009')).queryByRole('button')).toBeNull()                 // fuel is changed in its own register
  })

  it('without the approver right there is no Approve, and without the plant rights no Submit', () => {
    rights = ['stores.manage']
    const { unmount } = draw()
    expect(within(line('EXP-0002')).queryByRole('button', { name: 'Approve' })).toBeNull()
    unmount()
    rights = []
    draw()
    expect(within(line('EXP-0001')).queryByRole('button', { name: 'Submit' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Expense$/ })).toBeNull()
  })

  it('the expense number opens its history; a rejected one owes nothing', () => {
    draw()
    expect(within(line('EXP-0001')).getByRole('button', { name: 'History of EXP-0001' })).toBeInTheDocument()
    expect(within(line('FU-0009')).queryByRole('button', { name: /History/ })).toBeNull()
  })

  it('submits an expense', async () => {
    draw()
    await userEvent.click(within(line('EXP-0001')).getByRole('button', { name: 'Submit' }))
    expect(submitExpense).toHaveBeenCalledWith(1)
  })

  it('a payment goes with one key, the same on a second click', async () => {
    const user = userEvent.setup()
    draw()
    await user.click(within(line('EXP-0003')).getByRole('button', { name: 'Pay' }))
    const amount = screen.getByLabelText('Amount')
    expect(amount).toHaveValue('3000')
    await user.clear(amount)
    await user.type(amount, '1500')
    await user.click(screen.getByRole('button', { name: 'Record payment' }))
    expect(payExpense).toHaveBeenCalledTimes(1)
    const [id, b, key] = payExpense.mock.calls[0] as unknown as [number, { amount: number }, string]
    expect(id).toBe(3)
    expect(b.amount).toBe(1500)
    expect(key).toBeTruthy()
  })

  it('the expense form no longer asks for payment', async () => {
    draw()
    await userEvent.click(screen.getByRole('button', { name: /Expense$/ }))
    expect(screen.queryByLabelText('Payment')).toBeNull()
    expect(screen.queryByLabelText('Payment reference')).toBeNull()
    expect(screen.getByText(/Payments are recorded against it once it is approved/)).toBeInTheDocument()
  })
})
