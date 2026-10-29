import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { Budget, BudgetRow } from '@/api/budgeting'

const line = (key: string, description: string, under: string): BudgetRow => ({
  key, under, item_no: '', group_code: 'SUB STRUCTURE WORKS', description, uom: 'cum', quantity: 10, rate: 1000, revenue: 10000, rate_only: false, item_code: '', budgeted: false, items: [],
  unit_material: 0, unit_labour: 0, unit_other: 0, unit_cost: 0, material: 0, labour: 0, other: 0, direct: 0, overheads: 0, contingency: 0, cost: 0, profit: null, margin: null,
})
const budget = {
  job: { id: 8, number: 'P-8', name: 'Tower' }, boq: { id: 2, number: 'BOQ-2', revision: 0 }, overhead_percent: 0, contingency_percent: 0, note: '', updated_by_name: '',
  rows: [line('a', 'PCC M10 below footings', 'h1'), line('b', 'PCC M10 flooring bed', 'h1'), line('c', 'RCC footings', 'h2')],
  headings: [{ key: 'h1', item_no: '', description: 'PLAIN CEMENT CONCRETE', before: 'a' }, { key: 'h2', item_no: '', description: 'REINFORCED CEMENT CONCRETE', before: 'c' }],
  total: { boq_value: 30000, budgeted_value: 0, unbudgeted_value: 30000, material: 0, labour: 0, other: 0, direct: 0, overheads: 0, contingency: 0, cost: 0, profit: 0, margin: null, lines: 3, lines_budgeted: 0, losing: 0, projected_profit: null },
  sections: [],
} as unknown as Budget

vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), get: vi.fn(async () => budget) }))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true }) }))
vi.mock('@/components/data/ProjectPicker', () => ({ ProjectPicker: () => <div>project picker</div> }))

import BudgetingPage from './BudgetingPage'

const mount = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={['/projects/budgeting?job=8']}><BudgetingPage /></MemoryRouter>
  </QueryClientProvider>,
)

describe('Budgeting: the BOQ headings fold and open', () => {
  it('start folded, open on the arrow, and fold again on a second click', async () => {
    const user = userEvent.setup()
    mount()
    const pcc = await screen.findByRole('button', { name: /Show the lines under PLAIN CEMENT CONCRETE/ })
    expect(screen.getByText('REINFORCED CEMENT CONCRETE')).toBeTruthy()           // both headings are there, in bold
    expect(pcc.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByText('PCC M10 below footings')).toBeNull()                // the lines under them are not
    expect(screen.getByText('2 lines')).toBeTruthy()

    await user.click(pcc)                                                          // open the first section only
    expect(screen.getByText('PCC M10 below footings')).toBeTruthy()
    expect(screen.getByText('PCC M10 flooring bed')).toBeTruthy()
    expect(screen.queryByText('RCC footings')).toBeNull()
    expect(screen.getByRole('button', { name: /Hide the lines under PLAIN CEMENT CONCRETE/ }).getAttribute('aria-expanded')).toBe('true')

    await user.click(screen.getByRole('button', { name: /Hide the lines under PLAIN CEMENT CONCRETE/ }))   // and fold it again
    expect(screen.queryByText('PCC M10 below footings')).toBeNull()
  })

  it('open and fold every section at once', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Open all sections' }))
    expect(screen.getByText('PCC M10 below footings')).toBeTruthy()
    expect(screen.getByText('RCC footings')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Fold all sections' }))
    expect(screen.queryByText('RCC footings')).toBeNull()
  })
})
