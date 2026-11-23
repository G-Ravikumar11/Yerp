import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'
import type { BudgetSummary, OrderBudgetCheck } from '@/api/budgetControl'

const sum = (over: Partial<BudgetSummary>): BudgetSummary => ({
  lines: 4, budgeted: 4, partial: 0, unbudgeted: 0, approved_value: 1472800, budgeted_value: 1472800, remaining_value: 0, completion_percent: 100, value_percent: 100, status: 'Complete', ...over,
})
const projects = [
  { job_id: 1, code: 'KOK', name: 'Kokapet Towers', summary: sum({ budgeted: 2, partial: 1, unbudgeted: 1, budgeted_value: 1074000, remaining_value: 398800, completion_percent: 50, status: 'Incomplete' }) },
  { job_id: 2, code: 'VIZ', name: 'Vizag High Rise', summary: sum({}) },
]
const line = (over: object) => ({
  key: 'k', item_no: '1.1', item_code: '', description: 'Excavation', unit: 'cum', status: 'Budgeted', approved_qty: 500, approved_value: 90000, budgeted_qty: 500, budgeted_value: 90000,
  remaining_qty: 0, remaining_value: 0, budget_per_unit: 160, contractor_budget: 80000, committed_qty: 300, committed_value: 48000, available_qty: 200, available_value: 32000, ...over,
})
const control = {
  job_id: 1, code: 'KOK', name: 'Kokapet Towers', live: true, summary: projects[0].summary,
  lines: [line({ key: 'exc' }), line({ key: 'mas', item_no: '2.1', description: 'Brick masonry', status: 'Not budgeted', approved_qty: 60, approved_value: 366000, budgeted_qty: 0, budgeted_value: 0, remaining_qty: 60, remaining_value: 366000, budget_per_unit: 0, contractor_budget: 0, committed_qty: 0, committed_value: 0, available_qty: 60, available_value: 0 }),
    line({ key: 'fwk', item_no: '1.3', description: 'Shuttering', unit: 'sqm', status: 'Partially budgeted', approved_qty: 80, approved_value: 32800, budgeted_qty: 0, budgeted_value: 0, remaining_qty: 80, remaining_value: 32800 })],
}
vi.mock('@/api/budgetControl', async (orig) => ({
  ...(await orig<typeof import('@/api/budgetControl')>()),
  useHoBudgetControl: () => ({ data: { projects }, isPending: false, isError: false }),
  useProjectBudgetControl: () => ({ data: control, isPending: false, isError: false }),
}))

import { HoBudgetControl } from '@/features/headoffice/HoBudgetControl'
import { BudgetControlView } from './BudgetControlView'
import { OrderBudgetPanel } from '@/features/orders/OrderBudgetPanel'

const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter>{ui}</MemoryRouter></TooltipProvider></QueryClientProvider>)

describe('HO QS budget control - the projects', () => {
  it('lists each live project with its lines, completion, value left and status, and filters them', async () => {
    const user = userEvent.setup()
    wrap(<HoBudgetControl />)
    const kok = screen.getByText('KOK').closest('tr') as HTMLElement
    expect(within(kok).getByText('50%')).toBeInTheDocument()
    expect(within(kok).getByText('Incomplete')).toBeInTheDocument()
    expect(within(kok).getByText('₹3,98,800.00')).toBeInTheDocument()
    expect(screen.getByText(/1 project still to finish/)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Budget status'), 'Complete')
    expect(screen.queryByText('KOK')).toBeNull()
    expect(screen.getByText('VIZ')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Budget status'), '')
    await user.type(screen.getByLabelText('Search projects'), 'kokapet')
    expect(screen.getByText('KOK')).toBeInTheDocument()
    expect(screen.queryByText('VIZ')).toBeNull()
  })
})

describe('HO QS budget control - one project', () => {
  it('shows the lines still to budget first, every line on request, and opens a line to budget it', async () => {
    const user = userEvent.setup()
    const onEdit = vi.fn()
    wrap(<BudgetControlView job={1} onEdit={onEdit} />)
    expect(screen.getByText(/No work order on this project is sent or approved/)).toBeInTheDocument()
    expect(screen.getByText('Brick masonry')).toBeInTheDocument()
    expect(screen.getByText('Shuttering')).toBeInTheDocument()
    expect(screen.queryByText('Excavation')).toBeNull()                       // budgeted: under All lines
    await user.click(screen.getByRole('tab', { name: /All lines/ }))
    const exc = screen.getByText('Excavation').closest('tr') as HTMLElement
    expect(within(exc).getByText('₹32,000.00')).toBeInTheDocument()          // left for contractors
    expect(within(exc).getByText('200 cum left')).toBeInTheDocument()
    await user.click(screen.getByText('Brick masonry'))
    expect(onEdit).toHaveBeenCalledWith('mas')
  })
})

describe('A work order against the HO QS budget', () => {
  const base: OrderBudgetCheck = { applies: true, can_send: true, project: { job_id: 1, code: 'KOK', name: 'Kokapet Towers' }, missing: [], over_quantity: [], over_value: [], lines: [] }
  it('says the order cannot be sent while lines are still to budget, and links to them', () => {
    wrap(<OrderBudgetPanel check={{ ...base, can_send: false, missing: [{ key: 'mas', item: '2.1 Brick masonry', status: 'Not budgeted', unit: 'cum', quantity: 60, value: 366000 }] }} />)
    expect(screen.getByRole('alert').textContent).toMatch(/KOK Kokapet Towers: the HO QS budget is not complete - 1 BOQ line still to budget/)
    expect(screen.getByText(/2.1 Brick masonry - not budgeted, ₹3,66,000.00/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Budget them/ })).toHaveAttribute('href', '/projects/budgeting?job=1')
  })
  it('shows quantity and value past what is left with the rule each follows', () => {
    const l = { key: 'exc', item: '1.1 Excavation', unit: 'cum', this_order_qty: 250, this_order_value: 40000, available_qty: 200, available_value: 32000, budget_per_unit: 160 }
    wrap(<OrderBudgetPanel check={{ ...base, over_quantity: [{ ...l, short_qty: 50 }], over_value: [{ ...l, short_value: 8000 }] }} />)
    expect(screen.getByText(/Master overrides this at approval/)).toBeInTheDocument()
    expect(screen.getByText(/250 cum on this order, 200 cum left \(50 cum short\)/)).toBeInTheDocument()
    expect(screen.getByText(/send it with the reason/)).toBeInTheDocument()
    expect(screen.getByText(/₹8,000.00 more/)).toBeInTheDocument()
  })
  it('says so when all is within the budget, and nothing where the budget does not apply', () => {
    const { unmount } = wrap(<OrderBudgetPanel check={base} />)
    expect(screen.getByText(/fully budgeted and every line of this order is within/)).toBeInTheDocument()
    unmount()
    const { container } = wrap(<OrderBudgetPanel check={{ ...base, applies: false }} />)
    expect(container.textContent).toBe('')
  })
})
