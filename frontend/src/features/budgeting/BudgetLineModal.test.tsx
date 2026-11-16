import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { BudgetRow, WastageAnswer } from '@/api/budgeting'

type Ask = { kind: string; item_code: string; wastage_percent: number }
const calls: { url: string; body: unknown }[] = []
/** The server's rule, stood in for: a norm of 8% for RM-1 on this line, none for anything else. */
const serverAnswer = (a: Ask): WastageAnswer => {
  const norm = a.kind === 'MATERIAL' && a.item_code === 'RM-1' ? 8 : null
  const differs = norm !== null && norm !== a.wastage_percent
  return {
    budgeting_wastage_percent: a.kind === 'MATERIAL' ? a.wastage_percent : 0, store_norm_wastage_percent: norm, effective_wastage_percent: norm ?? (a.kind === 'MATERIAL' ? a.wastage_percent : 0),
    wastage_source: norm === null ? 'BUDGETING' : 'STORE_NORM', has_wastage_mismatch: differs,
    mismatch_message: differs ? `Budgeting wastage is ${a.wastage_percent}%, but Store Material Norm wastage is ${norm}%. Store Norm percentage is being used.` : null,
  }
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  post: vi.fn(async (url: string, body?: unknown) => { calls.push({ url, body }); return { items: (body as { items: Ask[] }).items.map(serverAnswer) } }),
  put: vi.fn(async (url: string, body?: unknown) => { calls.push({ url, body }); return {} }),
}))

import { BudgetLineModal } from './BudgetLineModal'

const row = (items: BudgetRow['items']): BudgetRow => ({
  key: 'k1', under: '', item_no: '3', group_code: 'RCC', description: 'RCC M25', uom: 'cum', quantity: 1000, rate: 100, revenue: 100000, rate_only: false, item_code: '', budgeted: true, items,
  unit_material: 0, unit_labour: 0, unit_other: 0, unit_cost: 0, material: 0, labour: 0, other: 0, direct: 0, overheads: 0, contingency: 0, cost: 0, profit: 0, margin: 0,
})
const cement = { kind: 'MATERIAL' as const, description: 'Cement', uom: 'kg', coefficient: 2, rate: 10, wastage_percent: 5 }

const mount = (items: BudgetRow['items']) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <BudgetLineModal job={8} row={row(items)} overhead={0} contingency={0} onClose={() => {}} />
  </QueryClientProvider>,
)

beforeEach(() => { calls.length = 0 })

describe('Budget line: which wastage % is used', () => {
  it('shows both figures, the one used, the warning and the quantities when the store norm differs', async () => {
    mount([{ ...cement, item_code: 'RM-1' }])
    const detail = await screen.findByTestId('wastage-detail')
    expect(detail.textContent).toContain('Budgeting Wastage: 5%')
    expect(detail.textContent).toContain('Store Norm Wastage: 8%')
    expect(detail.textContent).toContain('Effective Wastage Used: 8% (Store Norm)')
    // 1000 x 2 kg = 2000; 8% = 160; 2160 in all.
    expect(detail.textContent).toContain('Base Material Quantity: 2,000 kg · Wastage Quantity: 160 kg · Final Required Quantity: 2,160 kg')
    const warning = screen.getByRole('alert')
    expect(warning.textContent).toContain('Wastage Percentage Mismatch')
    expect(warning.textContent).toContain('The Store Norm wastage percentage (8%) is being used for Budgeting calculations.')
    expect(calls[0].url).toBe('/api/jobs/8/budget/lines/k1/wastage')                 // the answer came from the server
    expect(calls[0].body).toEqual({ items: [{ kind: 'MATERIAL', item_code: 'RM-1', wastage_percent: 5 }] })
  })

  it('says the budget figure is used when no store norm is set, with no warning', async () => {
    mount([{ ...cement, item_code: 'RM-2' }])
    const detail = await screen.findByTestId('wastage-detail')
    expect(detail.textContent).toContain('Store Norm Wastage: not configured')
    expect(detail.textContent).toContain('Effective Wastage Used: 5% (Budgeting)')
    expect(detail.textContent).toContain('Store Material Norm not configured. Budgeting wastage percentage is being used.')
    expect(detail.textContent).toContain('Final Required Quantity: 2,100 kg')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('does not warn when the two figures match, and saves the budget own figure untouched', async () => {
    mount([{ ...cement, item_code: 'RM-1', wastage_percent: 8 }])
    expect((await screen.findByTestId('wastage-detail')).textContent).toContain('Effective Wastage Used: 8% (Store Norm)')
    expect(screen.queryByRole('alert')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/jobs/8/budget/lines/k1')).toBe(true))
    const saved = calls.find((c) => c.url === '/api/jobs/8/budget/lines/k1')!.body as { items: { wastage_percent: number; item_code: string }[] }
    expect(saved.items).toEqual([{ kind: 'MATERIAL', description: 'Cement', uom: 'kg', coefficient: 2, rate: 10, item_code: 'RM-1', wastage_percent: 8 }])
  })
})
