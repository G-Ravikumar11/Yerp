import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'
import type { ItemSheet, SheetMaterial } from '@/api/itemSheet'

const mat = (over: Partial<SheetMaterial>): SheetMaterial => ({
  id: 1, boq_key: 'rcc', item_id: 11, item_code: 'CEM-01', item_name: 'Cement OPC 53', hsn: '2523', unit: 'kg', qty: 65000, remarks: '',
  ordered: 40000, awaiting: 5000, received: 30000, indented: 20000, issued: 18000, should_use: 16250, ...over,
})
let sheet: ItemSheet
const base = (over: Partial<ItemSheet> = {}): ItemSheet => ({
  job_id: 7, code: 'KOK', name: 'Kokapet Towers', exists: true, status: 'APPROVED', has_boq: true, group_codes: ['RCC', 'RFT'],
  groups: [
    { code: 'RCC', lines: [
      { key: 'rcc', line_id: 101, item_no: '2.1', description: 'M25 RCC in raft', unit: 'cum', qty: 1200, boq_item_code: 'FG-1', done_qty: 300, done_from: 'measured',
        work: { id: 90, code: 'FG-1', name: 'RCC M25', unit: 'cum', norms: 2, from: 'boq' }, materials: [
        mat({}), mat({ id: 2, item_id: 12, item_code: 'STL-12', item_name: 'TMT 12 mm', hsn: '7214', qty: 90000, ordered: 0, awaiting: 0, received: 0, indented: 0, issued: 0 })] },
      { key: 'col', line_id: 102, item_no: '2.2', description: 'RCC columns', unit: 'cum', qty: 300, boq_item_code: '', done_qty: null, done_from: '',
        work: { id: 91, code: 'FG-2', name: 'RCC M25 columns', unit: 'cum', norms: 1, from: 'sheet' }, materials: [] },
    ] },
    { code: 'RFT', lines: [{ key: 'rft', line_id: 103, item_no: '3.1', description: 'Waterproofing of roof', unit: 'sqm', qty: 800, boq_item_code: '', done_qty: null, done_from: '', work: null, materials: [] }] },
  ],
  orphans: [], material_count: 2, item_count: 2, approved: true, changed_since_approval: false, approved_by: 'Master', approved_at: '2026-11-25T10:00:00',
  submitted_by: '', submitted_at: '', returned_note: '', updated_by: '', updated_at: '',
  totals: [{ item_id: 11, item_code: 'CEM-01', item_name: 'Cement OPC 53', hsn: '2523', unit: 'kg', on_sheet: true, required: 65000, approved_qty: 65000,
    ordered: 40000, awaiting: 5000, received: 30000, indented: 20000, issued: 18000, at_site: 12000, to_order: 25000, to_receive: 10000 }],
  prices: { 11: { last_rate: 7.5, last_supplier: 'Old Supplier', last_date: '2026-11-01', gst: '28', contracts: [{ supplier: 'Shree Traders', rate: 7.2, valid_to: '2026-12-31' }] } },
  orders: [{ id: 5, number: 'PO-0005', supplier: 'Shree Traders', status: 'Approved', date: '2026-11-25', total: 320000, receivable: true,
    lines: [{ po_line_id: 51, item_id: 11, item_code: 'CEM-01', item_name: 'Cement OPC 53', boq_key: 'rcc', unit: 'kg', po_qty: 40000, po_uom: 'kg', price: 8, ordered: 40000, received: 30000, pending: 10000 }] }],
  receipts: [{ id: 8, number: 'GRN-8', status: 'SUBMITTED', date: '2026-11-25', po_id: 5, po_number: 'PO-0005', supplier: 'Shree Traders', store_code: 'SS1' }],
  indents: [{ id: 9, number: 'IND-9', status: 'OPEN', date: '2026-11-25', store_id: 3, store_code: 'SS1', boq_key: 'rcc', boq_item: '2.1 M25 RCC in raft', activity: '', requested_by: 'Ravi' }],
  issues: [], stores: [{ id: 3, code: 'SS1', name: 'Site store', type: 'SITE', this_project: true }], units: ['Kgs', 'Bags'], is_master: true, ...over,
})

const fillFromNorms = vi.fn()
vi.mock('@/api/itemSheet', async (orig) => ({
  ...(await orig<typeof import('@/api/itemSheet')>()),
  fillFromNorms: (...a: unknown[]) => fillFromNorms(...a),
  useItemSheet: () => ({ data: sheet, isPending: false, isError: false }),
  useItemSheets: () => ({ data: { items: [], is_master: true }, isPending: false }),
}))
vi.mock('@/api/rfq', () => ({ useSupplierNames: () => ({ data: [{ name: 'Shree Traders' }] }) }))
let rights: (p: string) => boolean = () => true
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: (p: string) => rights(p) }) }))
vi.mock('@/components/data/ProjectPicker', () => ({ ProjectPicker: () => <div>project picker</div> }))
vi.mock('@/features/store/shared', () => ({ ItemPicker: ({ value, id }: { value: { name: string } | null; id?: string }) => <input id={id} readOnly value={value?.name ?? ''} /> }))

import ItemSheetPage from './ItemSheetPage'

const wrap = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={['/store/item-sheet?job=7']}><ItemSheetPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)

describe('Item sheet', () => {
  beforeEach(() => { sheet = base(); rights = () => true; fillFromNorms.mockReset() })

  it('lists the BOQ lines under their group codes, each with its materials and how far they have got', () => {
    wrap()
    expect(screen.getByRole('region', { name: 'Group RCC' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Group RFT' })).toHaveTextContent('Waterproofing of roof')
    const table = screen.getByRole('table', { name: 'Materials for 2.1 M25 RCC in raft' })
    const cement = within(table).getByText('Cement OPC 53').closest('tr')!
    expect(cement).toHaveTextContent('2523')
    expect(cement).toHaveTextContent('65,000 kg')
    expect(cement).toHaveTextContent('5,000 awaiting approval')
    expect(cement).toHaveTextContent('18,000 kg')
    expect(screen.getAllByText('No materials yet.')).toHaveLength(2)
  })

  it('shows each material over the whole project on the Tracking tab', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('tab', { name: 'Tracking' }))
    const row = within(screen.getByRole('table', { name: 'Tracking' })).getByText('Cement OPC 53').closest('tr')!
    expect(row).toHaveTextContent('25,000 kg')
    expect(row).toHaveTextContent('12,000 kg')
  })

  it('raises a purchase order for what is left to order, line by line', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('button', { name: /Raise purchase order/ }))
    const qty = screen.getByRole('textbox', { name: 'Quantity of Cement OPC 53 for RCC · 2.1 M25 RCC in raft' }) as HTMLInputElement
    expect(qty.value).toBe('20000')                                         // 65,000 - 40,000 ordered - 5,000 awaiting
    expect((screen.getByRole('textbox', { name: 'Quantity of TMT 12 mm for RCC · 2.1 M25 RCC in raft' }) as HTMLInputElement).value).toBe('90000')
    expect(screen.getByRole('button', { name: /Raise order/ })).toBeDisabled()          // no supplier yet
  })

  it('asks for material for a BOQ line, and receives and issues from the documents tab', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getAllByRole('button', { name: 'Ask for material' })[0])
    expect((screen.getByRole('textbox', { name: 'Ask for Cement OPC 53' }) as HTMLInputElement).value).toBe('45000')   // 65,000 less 20,000 indented
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('tab', { name: /Orders & store/ }))
    await user.click(screen.getByRole('button', { name: /Receive/ }))
    expect((screen.getByRole('textbox', { name: 'Received now of Cement OPC 53' }) as HTMLInputElement).value).toBe('10000')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(within(screen.getByRole('table', { name: 'Goods received' })).getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Indents' })).getByRole('button', { name: /Issue/ })).toBeInTheDocument()
  })

  it('offers no ordering or indenting until the sheet is approved, and approving only to the Master', () => {
    sheet = base({ status: 'SUBMITTED', approved: false, is_master: false })
    wrap()
    expect(screen.queryByRole('button', { name: /Raise purchase order/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ask for material' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
  })

  it('hides the next step of a document from someone without the right to take it', async () => {
    rights = (p) => !p.includes('store.inward.approve') && p !== 'store.inward.approve|store.admin'
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('tab', { name: /Orders & store/ }))
    expect(within(screen.getByRole('table', { name: 'Goods received' })).queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('edits materials under each BOQ line', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('button', { name: /Edit materials/ }))
    const rft = screen.getByRole('region', { name: 'Group RFT' })
    await user.click(within(rft).getByRole('button', { name: /Add material/ }))
    expect(within(rft).getByText('Not in the Item Master? Add it')).toBeInTheDocument()
    await user.click(within(rft).getByText('Not in the Item Master? Add it'))
    expect(screen.getByRole('dialog', { name: 'Add a material to the Item Master' })).toBeInTheDocument()
  })

  it('asks for a BOQ first when the project has none', () => {
    sheet = base({ exists: false, status: null, has_boq: false, groups: [], group_codes: [], material_count: 0, approved: false })
    wrap()
    expect(screen.getByText(/This project has no BOQ yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Upload Excel/ })).toBeDisabled()
  })

  it('starts each order line at the rate last paid, and at the rate contract of the supplier once chosen', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('button', { name: /Raise purchase order/ }))
    const rate = screen.getByRole('textbox', { name: 'Rate of Cement OPC 53 for RCC · 2.1 M25 RCC in raft' }) as HTMLInputElement
    expect(rate.value).toBe('7.5')
    expect(screen.getByText(/last paid to Old Supplier on 2026-11-01/)).toBeInTheDocument()
    expect((screen.getByRole('combobox', { name: 'GST on Cement OPC 53' }) as HTMLSelectElement).value).toBe('28')
    await user.type(screen.getByLabelText('Supplier'), 'Shree Traders')
    expect(rate.value).toBe('7.2')
    expect(screen.getByText(/rate contract to 2026-12-31/)).toBeInTheDocument()
  })

  it('fills empty lines from the norms of their work items, to look over before saving', async () => {
    fillFromNorms.mockResolvedValue({
      proposals: { col: [{ item_id: 11, item_code: 'CEM-01', item_name: 'Cement OPC 53', hsn: '2523', unit: 'kg', qty: 102000, remarks: 'Norm of FG-2: 340 per cum' }] },
      skipped: [{ key: 'rft', why: '3.1 Waterproofing of roof: no work item, and the same work is on no sheet yet.' }],
    })
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('button', { name: /Edit materials/ }))
    expect(screen.getByText(/chosen on the sheet/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Fill 2 empty lines from norms/ }))
    expect(fillFromNorms).toHaveBeenCalledWith(7, ['col', 'rft'])
    expect(await screen.findByDisplayValue('102000')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Norm of FG-2: 340 per cum')).toBeInTheDocument()
    expect(screen.getByText('1 line had nothing to fill from')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Match 1 line to work items/ })).toBeInTheDocument()
  })

  it('checks what the work done should have used against what was issued', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('tab', { name: 'Consumption' }))
    const row = within(screen.getByRole('table', { name: 'Consumption for 2.1 M25 RCC in raft' })).getByText('Cement OPC 53').closest('tr')!
    expect(row).toHaveTextContent('16,250 kg')
    expect(row).toHaveTextContent('18,000 kg')
    expect(row).toHaveTextContent('+1,750 kg (+11%)')
    expect(row).toHaveTextContent('over')
    expect(screen.getByText(/Done 300 of 1,200 cum \(25%\) · measured on work orders/)).toBeInTheDocument()
  })
})
