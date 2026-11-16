import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const stock = { stock: [{ item_code: 'CEM-1', item_name: 'Cement OPC', received: 200, issued: 40, on_hand: 160, uom: 'bag', rate: 350, value: 56000, negative: false, below_level: false, reorder_level: 0 }], summary: { items_held: 1, value_on_hand: 56000, below_reorder: 0, negative_lines: 0 } }
const issues = { issues: [{ id: 3, number: 'SI-0003', work_order: 'WO-1', purpose: 'Raft', issued_to: 'Suresh', issued_on: '2026-01-05', total_value: 14000, status: 'POSTED' }], summary: { notes: 1, not_yet_posted: 0, issued_value: 14000 } }
const receipts = { goods_receipts: [{ id: 7, number: 'GRN-0007', challan_number: 'C-9', supplier_name: 'Shree Traders', purchase_order: 'PO-4', project: 'Tower A', received_on: '2026-01-03', accepted_value: 70000, rejected_value: 0, status: 'POSTED', actions: [] }], summary: { count: 1, awaiting_posting: 0, accepted_value: 70000, rejected_value: 0 } }
const vouchers = { vouchers: [{ id: 2, number: 12, voucher_on: '2026-01-06', project: 'P-1 Tower A', indented_by: 'Ravi', issued_by: 'Store', issued_for: 'Slab', lines: [{ description: 'Cement', uom: 'bag', issued_qty: 10, returned_qty: 0, remarks: '' }] }], summary: { vouchers: 1, lines: 1 } }

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => (url.startsWith('/api/stock-issues') ? issues : url.startsWith('/api/stock') ? stock : url.startsWith('/api/grn') ? receipts : url.startsWith('/api/match') ? { orders: [], summary: {} } : vouchers)),
}))
vi.mock('@/components/data/ProjectPicker', () => ({ ProjectPicker: () => <div>project picker</div> }))

import OldStoreRecords from './OldStoreRecords'

const at = (path: string) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><Routes><Route path="/store/hub/reports/old-store/*" element={<OldStoreRecords />} /></Routes></MemoryRouter>
  </QueryClientProvider>,
)
const WRITES = /^(Post|Post it|Cancel|Cancel the note|Issue to site|Send to another site|Count|Receive a delivery|Remove)/

describe('Old store records', () => {
  it('shows the old stock and issue notes to read, with nothing to change', async () => {
    at('/store/hub/reports/old-store')
    expect(await screen.findByText('Cement OPC')).toBeTruthy()
    expect(screen.getByText('SI-0003')).toBeTruthy()
    expect(screen.getByRole('status').textContent).toMatch(/kept to read/)
    expect(screen.getByRole('link', { name: /Slip/ }).getAttribute('href')).toBe('/api/stock-issues/3/document.pdf')
    expect(screen.queryAllByRole('button', { name: WRITES })).toEqual([])
  })

  it('shows the goods receipts and the three-way match, and the vouchers with their printed form', async () => {
    const user = userEvent.setup()
    const { unmount } = at('/store/hub/reports/old-store/receipts')
    expect(await screen.findByText('GRN-0007')).toBeTruthy()
    expect(screen.getByRole('table', { name: 'Three-way match' })).toBeTruthy()
    expect(screen.queryAllByRole('button', { name: WRITES })).toEqual([])
    unmount()
    at('/store/hub/reports/old-store/vouchers')
    const table = await screen.findByRole('table', { name: 'Voucher register' })
    expect(await within(table).findByText('12')).toBeTruthy()
    expect(within(table).getByRole('link', { name: /PDF/ }).getAttribute('href')).toBe('/api/material-vouchers/2/document.pdf')
    expect(screen.queryAllByRole('button', { name: /Remove|Trash/ })).toEqual([])
    await user.click(screen.getByRole('link', { name: 'Stock & issue notes' }))
  })
})
