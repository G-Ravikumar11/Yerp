import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'
import type { ItemSheet, ItemSheetRow } from '@/api/itemSheet'

const row = (over: Partial<ItemSheetRow>): ItemSheetRow => ({
  item_id: 1, item_code: 'CEM-01', item_name: 'Cement OPC', uom: 'kg', in_master: true, required: 312, without_wastage: 300, value: 2496,
  indented: 30, ordered: 50, on_way: 50, issued: 40, at_site: 60, to_arrange: 162, to_arrange_value: 1296, status: 'To arrange', unit_notes: [],
  lines: [
    { key: 'rcc', boq_line_id: 11, item_no: '1.2', description: 'M25 grade RCC in raft', boq_qty: 120, boq_unit: 'cum', per_unit: 2, budget_unit: 'kg', wastage_percent: 5, wastage_source: 'BUDGETING', required: 252, issued: 40 },
    { key: 'mas', boq_line_id: 14, item_no: '2.1', description: 'Brick masonry in CM 1:6', boq_qty: 60, boq_unit: 'cum', per_unit: 1, budget_unit: 'kg', wastage_percent: 0, wastage_source: 'BUDGETING', required: 60, issued: 0 },
  ],
  ...over,
})
const sheet: ItemSheet = {
  job_id: 7, code: 'KOK', name: 'Kokapet Towers', boq: true,
  totals: { items: 3, to_arrange: 1, over_issued: 1, not_in_master: 1, not_budgeted: 0, value: 120000, to_arrange_value: 1296, boq_lines: 4, boq_lines_with_materials: 2 },
  rows: [
    row({}),
    row({ item_id: 2, item_code: 'STL-12', item_name: 'TMT 12 mm', status: 'Issued past need', required: 100, without_wastage: 100, issued: 130, to_arrange: 0, to_arrange_value: 0, lines: [] }),
    row({ item_id: null, item_code: '', item_name: 'River sand', uom: 'cum', in_master: false, required: 60, without_wastage: 60, indented: 0, ordered: 0, on_way: 0, issued: 0, at_site: 0, to_arrange: 60, status: 'To arrange', lines: [] }),
  ],
}

vi.mock('@/api/itemSheet', async (orig) => ({ ...(await orig<typeof import('@/api/itemSheet')>()), useItemSheet: () => ({ data: sheet, isPending: false, isError: false }) }))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true }) }))
vi.mock('@/components/data/ProjectPicker', () => ({ ProjectPicker: () => <div>project picker</div> }))

import ItemSheetPage from './ItemSheetPage'

const wrap = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={['/projects/item-sheet?job=7']}><ItemSheetPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)

describe('Item sheet', () => {
  it('shows each material with what is needed, done and still to arrange', () => {
    wrap()
    const table = screen.getByRole('table', { name: 'Item sheet' })
    const cement = within(table).getByText('Cement OPC').closest('tr')!
    expect(cement).toHaveTextContent('312 kg')
    expect(cement).toHaveTextContent('300 + wastage')
    expect(cement).toHaveTextContent('162 kg')
    expect(cement).toHaveTextContent('To arrange')
    expect(within(table).getByText('Not in the item master')).toBeInTheDocument()
    expect(screen.getByText(/2 BOQ lines have no materials yet/)).toBeInTheDocument()
  })

  it('filters to what is issued past its need', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('tab', { name: /Issued past need/ }))
    const table = screen.getByRole('table', { name: 'Item sheet' })
    expect(within(table).getByText('TMT 12 mm')).toBeInTheDocument()
    expect(within(table).queryByText('Cement OPC')).not.toBeInTheDocument()
  })

  it('opens a material to show the BOQ lines its need comes from', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(within(screen.getByRole('table', { name: 'Item sheet' })).getByText('Cement OPC'))
    const lines = await screen.findByRole('table', { name: 'BOQ lines needing Cement OPC' })
    expect(within(lines).getByText(/M25 grade RCC in raft/)).toBeInTheDocument()
    expect(within(lines).getByText('+5% wastage')).toBeInTheDocument()
    expect(within(lines).getByText('252 kg')).toBeInTheDocument()
  })
})
