import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const item = (over: object) => ({ item_id: 1, item_code: 'ST-1', item_name: 'TMT 12 mm (loose)', diameter_mm: 12, unit: 'kg', quantity: 1000, weight_per_piece_kg: null, total_kg: 1000, status: 'WEIGHED', reason: '', ...over })
const bad = item({ item_id: 9, item_code: 'ST-9', item_name: 'TMT 12 mm (old bars)', unit: 'nos', quantity: 50, total_kg: null, status: 'MISSING_WEIGHT_PER_PIECE', reason: 'Weight per piece is missing for this steel item. Update the item master to continue BBS weight validation.' })
const steel = {
  allowance_pct: 2, checked: true, blocked: true, unweighed: ['TMT 12 mm (old bars)'], problems: [bad],
  rows: [{ diameter_mm: 12, bbs_kg: 1066.7, allowed_kg: 1088, issued_kg: 2067, wastage_kg: 1000.3, wastage_pct: 93.8, status: 'OVER' }],
  items: [item({}), item({ item_id: 2, item_code: 'ST-2', item_name: 'TMT 12 mm (bars)', unit: 'nos', quantity: 100, weight_per_piece_kg: 10.67, total_kg: 1067 }), bad],
  summary: { bbs_kg: 1066.7, issued_kg: 2067, wastage_kg: 1000.3, over: [12] },
}
const data = { entries: [{ id: 1, job_id: 5, project: 'Tower', block: 'A', floor: 'G', element: 'Column', member_ref: 'C1', bar_mark: 'M1', diameter_mm: 12, grade: 'Fe500D', shape: 'Straight', dims: {}, num_bars: 100, cutting_length_mm: 12000, total_length_m: 1200, unit_weight_kg_m: 0.889, total_weight_kg: 1066.7, remarks: '', status: 'Draft', revision: 0, approved_by: '' }],
  elements: [], grades: [], shapes: [], summary: { entries: 1, total_length_m: 1200, total_weight_kg: 1066.7, by_diameter: [], by_group: [] } }

vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), get: vi.fn(async (url: string) => (url.startsWith('/api/bbs/steel') ? steel : data)) }))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true }) }))
vi.mock('@/components/data/ProjectPicker', () => ({ ProjectPicker: ({ onChange }: { onChange: (id: number) => void }) => <button type="button" onClick={() => onChange(5)}>choose project</button> }))

import BbsPage from './BbsPage'

describe('BBS steel weights', () => {
  it('shows every steel item with how it was weighed, names the one that cannot be, links to its item and holds the approval', async () => {
    const user = userEvent.setup()
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><BbsPage /></MemoryRouter></QueryClientProvider>)
    await user.click(await screen.findByRole('button', { name: 'choose project' }))
    const alert = (await screen.findAllByRole('alert'))[0]
    expect(alert.textContent).toMatch(/Steel weight validation is blocked: 1 steel item/)
    expect(within(alert).getByText(/item 9, ST-9, unit nos/)).toBeTruthy()
    expect(alert.textContent).toContain('Weight per piece is missing for this steel item. Update the item master to continue BBS weight validation.')
    expect(within(alert).getByRole('link', { name: 'Open in the item master' }).getAttribute('href')).toBe('/store/items?item=9')
    const table = screen.getByRole('table', { name: 'Steel items issued' })
    const bars = within(table).getByText('TMT 12 mm (bars)').closest('tr')!
    expect(within(bars).getByText('10.67 kg/piece')).toBeTruthy()
    expect(within(bars).getByText('1,067.0 kg')).toBeTruthy()
    expect(within(bars).getByText('Weighed')).toBeTruthy()
    expect(within(within(table).getByText('TMT 12 mm (loose)').closest('tr')!).getByText('Weighed')).toBeTruthy()
    const old = within(table).getByText('TMT 12 mm (old bars)').closest('tr')!
    expect(within(old).getByText('Missing weight per piece')).toBeTruthy()                    // never shown as weighed, and not just "Not weighed"
    expect(screen.queryByText(/Not weighed/i)).toBeNull()
    expect((screen.getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true)
  })
})
