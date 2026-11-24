import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'
import { billLabel, billTone } from './rentalLabels'

const row = (over: object) => ({
  rental_id: 1, number: 'RNT-0001', agreement_no: 'AG-1', code: 'CR-02', machine: 'Hydra crane', supplier: 'Sai Cranes', project: 'Vizag STP', billing: 'Monthly', rate: 90000, overtime_rate: 0, min_billable_hours: 0,
  kind: 'invoice', invoice_id: 11, invoice_no: 'H-1', invoice_date: '2026-09-30', month: '2026-09', period_from: '2026-09-01', period_to: '2026-09-30', days_on_hire: 30, minimum_hours: 0, actual_hours: 0, overtime_hours: 0,
  expected: 90000, actual: 90500, difference: 500, difference_percent: 0.56, billed_days: 30, unbilled_days: 0, billed_hours: 0, return_charges: 0,
  status: 'Matched', detail: '', verification_status: '', verified_by: '', verification_note: '', ...over,
})
const rows = [
  row({}),
  row({ invoice_id: 12, invoice_no: 'H-2', actual: 99000, difference: 9000, difference_percent: 10, status: 'Mismatch' }),
  row({ invoice_id: 13, invoice_no: 'H-3', status: 'Matched', verification_status: 'Approved', verified_by: 'Accounts' }),
  row({ kind: 'missing', invoice_id: null, invoice_no: '', month: '2026-10', actual: null, difference: null, difference_percent: null, billed_days: 10, unbilled_days: 21, status: 'Incomplete', detail: '21 of 31 days on hire have no invoice.' }),
]
vi.mock('@/api/plant', async (orig) => ({
  ...(await orig<typeof import('@/api/plant')>()),
  useRentalVerification: () => ({ data: { rows, tolerance_percent: 2, summary: { Matched: 2, Mismatch: 1, Duplicate: 0, Missing: 0, Incomplete: 1 } }, isPending: false, isError: false }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true }) }))

import { RentalVerification } from './PlantChecks'

describe('Rental bill labels', () => {
  it('reads finance\'s decision first, then what the check found', () => {
    expect(billLabel('Matched')).toBe('Received')
    expect(billLabel('Mismatch')).toBe('Difference Found')
    expect(billLabel('Mismatch', 'Approved')).toBe('Verified')
    expect(billLabel('Matched', 'Disputed')).toBe('Disputed')
    expect(billLabel('In progress')).toBe('In Progress')
    expect(billTone('Verified')).toBe('success')
    expect(billTone('Difference Found')).toBe('danger')
  })
})

describe('Rental bill verification', () => {
  const draw = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><RentalVerification /></TooltipProvider></QueryClientProvider>)
  const line = (text: string) => screen.getByText(text).closest('tr') as HTMLElement

  it('shows each bill in the new words, with the difference as a share and the days billed and not', () => {
    draw()
    expect(within(line('H-1')).getByText('Received')).toBeInTheDocument()
    expect(within(line('H-2')).getByText('Difference Found')).toBeInTheDocument()
    expect(within(line('H-2')).getByText('+10%')).toBeInTheDocument()
    expect(within(line('H-3')).getByText('Verified')).toBeInTheDocument()
    const gap = screen.getByText('21 not billed').closest('tr') as HTMLElement
    expect(within(gap).getByText('Incomplete')).toBeInTheDocument()
    expect(within(gap).getByText('10 billed')).toBeInTheDocument()
  })

  it('asks finance to decide on a bill within tolerance too - it is never approved by itself', () => {
    draw()
    expect(within(line('H-1')).getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(within(line('H-2')).getByRole('button', { name: 'Dispute' })).toBeInTheDocument()
    expect(within(line('H-3')).queryByRole('button', { name: 'Approve' })).toBeNull()      // already decided
  })
})

describe('Returning a hired machine', () => {
  it('sends the reading, condition and charges, and wants a reason for the charges', async () => {
    const { ReturnModalForTest } = await import('./PlantRentals')
    const onReturn = vi.fn()
    const rental = { code: 'CR-02', start_date: '2026-09-01', expected_return: '2026-09-30', provider: { name: 'Sai Cranes' } }
    render(<TooltipProvider><ReturnModalForTest open rental={rental as never} busy={false} onClose={vi.fn()} onReturn={onReturn} /></TooltipProvider>)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('Final meter reading'), '1250')
    await user.selectOptions(screen.getByLabelText('Condition'), 'Fair')
    const charges = screen.getByLabelText('Extra or damage charges')
    await user.clear(charges)
    await user.type(charges, '4000')
    const confirm = screen.getByRole('button', { name: 'Confirm the return' })
    expect(confirm).toBeDisabled()
    expect(screen.getByText('Say what the charges are for.')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Note'), 'Dent on boom')
    await user.click(confirm)
    expect(onReturn).toHaveBeenCalledWith(expect.objectContaining({ final_meter: 1250, condition: 'Fair', extra_charges: 4000, note: 'Dent on boom' }))
  })
})
