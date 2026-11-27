import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LowRow, RaiseAnswer } from './api'

const calls: { url: string; body?: unknown }[] = []
const row = (over: Partial<LowRow>): LowRow => ({
  key: '1-9', alert_id: 5, store_id: 1, store_code: 'CS1', store_name: 'Central', project_id: null, project: '', item_id: 9, item_code: 'CEM-1', item_name: 'Cement OPC', category: 'CONSUMABLE', base_uom: 'kg',
  on_hand: '3000.000', unusable: '500.000', reserved: '0.000', available: '2500.000', reorder_level: '3000.000', min_qty: '0.000', max_qty: '8000.000', target_level: '8000.000', suggest_basis: 'Up to the maximum stock level (8000)',
  suggested_qty: '5500.000', on_order: '1000.000', to_order: '4500.000', alerted_at: '2026-11-10T07:00:00', last_checked_at: '2026-11-16T07:00:00', times_raised: 1, status: 'LOW_STOCK', stage: 'ALERT ACTIVE', shortage: '500.000', action: '', action_ref: '',
  action_doc_id: null, action_doc_status: '', action_live: false, action_qty: null, action_by: '', action_at: '', ...over,
})
const rows = [row({}), row({ key: '1-10', alert_id: 6, item_id: 10, item_code: 'SND-1', item_name: 'River sand', available: '10.000', on_hand: '10.000', suggested_qty: '90.000', to_order: '90.000', on_order: '0.000', shortage: '2990.000', status: 'INDENT_RAISED', stage: 'INDENT RAISED', action: 'INDENT', action_ref: 'IND-0007', action_doc_status: 'SUBMITTED', action_live: true, action_qty: '90.000' })]

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => { calls.push({ url }); return url.includes('view=history') ? { items: [] } : { items: rows, can_indent: true, can_enquire: true } }),
  post: vi.fn(async (url: string, body?: unknown) => {
    calls.push({ url, body })
    const sent = (body as { lines: { store_id: number; item_id: number }[] }).lines
    return { ok: false, action: 'INDENT', created: [{ type: 'INDENT', id: 7, number: 'IND-0008', lines: 1, store_code: 'CS1', status: 'SUBMITTED' }], raised: 1, failed: sent.length - 1,
      message: 'Raised IND-0008 for 1 material; 1 could not be raised - see each line.',
      results: sent.map((l, i) => (i === 0 ? { store_id: l.store_id, item_id: l.item_id, ok: true, message: 'On IND-0008, waiting for approval.', ref: 'IND-0008' } : { store_id: l.store_id, item_id: l.item_id, ok: false, message: 'No longer low: 4000.000 available.' })) } satisfies RaiseAnswer
  }),
}))
vi.mock('@/api/projects', async (orig) => ({ ...(await orig<typeof import('@/api/projects')>()), useProjects: () => ({ data: [{ id: 3, number: 'P-3', name: 'Tower' }] }) }))
vi.mock('../shared', () => ({ StorePicker: () => <div>store picker</div> }))

import { LowStockList } from './LowStockPage'

const mount = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><LowStockList storeId={1} /></MemoryRouter>
  </QueryClientProvider>,
)

beforeEach(() => { calls.length = 0 })

describe('Low stock list', () => {
  it('shows available stock, the suggested quantity and the alert status as the server gave them, and keeps the raise button off until something is ticked', async () => {
    mount()
    expect(await screen.findByText('Cement OPC')).toBeTruthy()
    expect(screen.getByText('LOW STOCK')).toBeTruthy()
    expect(screen.getByText('INDENT RAISED')).toBeTruthy()                         // raised is not resolved: still on the list
    expect(screen.getByText(/Material request IND-0007 - submitted for 90/)).toBeTruthy()
    expect(screen.getByText('3,000 on hand')).toBeTruthy()                          // on hand differs from what is available
    expect(screen.getByText('1,000 already coming')).toBeTruthy()
    expect(screen.getByText('0 selected')).toBeTruthy()
    expect((screen.getByRole('button', { name: /Ask to buy all selected/ }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows how far each alert has got to replenishment and how far under its level it stands', async () => {
    rows.push(row({ key: '1-11', alert_id: 8, item_id: 11, item_code: 'STL-8', item_name: 'TMT 8mm', status: 'INDENT_RAISED', stage: 'GOODS RECEIVED', shortage: '120.000', action: 'INDENT', action_ref: 'IND-0003', action_doc_status: 'APPROVED', action_live: true }))
    mount()
    const cement = (await screen.findByText('Cement OPC')).closest('tr') as HTMLElement
    expect(within(cement).getByText('ALERT ACTIVE')).toBeTruthy()
    expect(within(cement).getByText('500 short')).toBeTruthy()
    const steel = screen.getByText('TMT 8mm').closest('tr') as HTMLElement
    expect(within(steel).getByText('INDENT RAISED')).toBeTruthy()                   // the alert's status stays until stock recovers
    expect(within(steel).getByText('GOODS RECEIVED')).toBeTruthy()                  // a receipt is waiting for posting: not resolved yet
    const sand = screen.getByText('River sand').closest('tr') as HTMLElement
    expect(within(sand).getAllByText('INDENT RAISED')).toHaveLength(1)             // the stage is not repeated when it says the same
    expect(within(sand).getByText('2,990 short')).toBeTruthy()
    rows.pop()
  })

  it('selects every row, previews with the quantity to order filled in, and shows each line own result', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('Cement OPC')
    await user.click(screen.getByRole('checkbox', { name: 'Select every row' }))
    expect(screen.getByText('2 selected')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /Ask to buy all selected/ }))
    const dialog = await screen.findByRole('dialog')
    const cement = within(dialog).getByLabelText('Requested quantity of Cement OPC in CS1') as HTMLInputElement
    expect(cement.value).toBe('4500.000')                                           // the suggested quantity less what is coming
    await user.clear(cement)
    await user.type(cement, '4000')
    await user.click(within(dialog).getByRole('combobox', { name: /Project/ }))
    await user.selectOptions(within(dialog).getByRole('combobox', { name: /Project/ }), '3')
    await user.click(within(dialog).getByRole('button', { name: /Raise indent for 2 materials/ }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/store/levels/low-stock/raise')).toBe(true))
    const sent = calls.find((c) => c.url === '/api/store/levels/low-stock/raise')!.body as { action: string; request_key: string; project_id: number; lines: { qty: string; alert_id: number }[] }
    expect(sent.action).toBe('INDENT')
    expect(sent.project_id).toBe(3)
    expect(sent.lines.map((l) => [l.qty, l.alert_id])).toEqual([['4000', 5], ['90.000', 6]])
    expect(sent.request_key.length).toBeGreaterThan(8)                              // one key for one press: a repeat raises nothing twice
    expect(await within(dialog).findByText(/Raised IND-0008 for 1 material; 1 could not be raised/)).toBeTruthy()
    expect(within(dialog).getByText(/Not raised: No longer low/)).toBeTruthy()
    expect(within(dialog).getByText(/does not add stock/)).toBeTruthy()
  })
})
