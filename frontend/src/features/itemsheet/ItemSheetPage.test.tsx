import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'
import type { ItemSheet } from '@/api/itemSheet'

let sheet: ItemSheet
const base = (over: Partial<ItemSheet> = {}): ItemSheet => ({
  job_id: 7, code: 'KOK', name: 'Kokapet Towers', exists: true, status: 'SUBMITTED', groups: ['PCC', 'RCC', 'MAS'],
  lines: [
    { id: 1, group_code: 'RCC', item_id: 11, item_code: 'CEM-01', item_name: 'Cement OPC 53', hsn: '2523', unit: 'kg', qty: 65000, remarks: 'Raft and columns' },
    { id: 2, group_code: 'MAS', item_id: 12, item_code: 'BRK-01', item_name: 'Red brick', hsn: '6901', unit: 'Nos', qty: 30000, remarks: '' },
  ],
  approved: false, changed_since_approval: false, approved_by: '', approved_at: '', submitted_by: 'Ravi', submitted_at: '2026-11-25T10:00:00',
  returned_note: '', updated_by: 'Ravi', updated_at: '', usage: [], item_count: 2, is_master: true, ...over,
})
const approve = vi.fn()

vi.mock('@/api/itemSheet', async (orig) => ({
  ...(await orig<typeof import('@/api/itemSheet')>()),
  useItemSheet: () => ({ data: sheet, isPending: false, isError: false }),
  useItemSheets: () => ({ data: { items: [], is_master: true }, isPending: false }),
  approveItemSheet: (...a: unknown[]) => { approve(...a); return Promise.resolve(sheet) },
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true }) }))
vi.mock('@/components/data/ProjectPicker', () => ({ ProjectPicker: () => <div>project picker</div> }))
vi.mock('@/features/store/shared', () => ({ ItemPicker: ({ value }: { value: { name: string } | null }) => <div>{value?.name ?? 'pick an item'}</div> }))

import ItemSheetPage from './ItemSheetPage'

const wrap = () => render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter initialEntries={['/store/item-sheet?job=7']}><ItemSheetPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)

describe('Item sheet', () => {
  beforeEach(() => { sheet = base(); approve.mockClear() })

  it('lists each material under its BOQ group code with its HSN and quantity', () => {
    wrap()
    const cement = within(screen.getByRole('table', { name: 'Item sheet' })).getByText('Cement OPC 53').closest('tr')!
    expect(cement).toHaveTextContent('RCC')
    expect(cement).toHaveTextContent('2523')
    expect(cement).toHaveTextContent('65,000 kg')
    expect(screen.getByText('Waiting for the Master')).toBeInTheDocument()
  })

  it('lets the Master approve a sheet sent to them', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('button', { name: /Approve/ }))
    expect(approve).toHaveBeenCalledWith(7)
  })

  it('hides approving from anyone but the Master', () => {
    sheet = base({ is_master: false })
    wrap()
    expect(screen.queryByRole('button', { name: /Approve/ })).not.toBeInTheDocument()
  })

  it('asks for the BOQ group codes first when the BOQ has none', () => {
    sheet = base({ exists: false, status: null, groups: [], lines: [] })
    wrap()
    expect(screen.getByText(/BOQ has no group codes yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Upload Excel/ })).toBeDisabled()
  })

  it('edits lines in the app with the group codes of the BOQ', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(screen.getByRole('button', { name: /Edit/ }))
    const group = screen.getAllByLabelText('Group code')[0] as HTMLSelectElement
    expect(group.value).toBe('RCC')
    expect([...group.options].map((o) => o.value)).toEqual(['', 'PCC', 'RCC', 'MAS'])
    await user.click(screen.getByRole('button', { name: /Add line/ }))
    expect(screen.getAllByLabelText('Group code')).toHaveLength(3)
  })
})
