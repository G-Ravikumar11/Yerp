import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { AvailableLine } from '@/api/boq'
import { headingTotals, type LineRow } from './ScheduleTab'

const head = (key: string, description: string, level: number, path: string[], notes = ''): AvailableLine => ({ kind: 'section', key, group_code: '', description, level, path, notes })
const item = (key: string, description: string, path: string[], material: string, left: number, uom: string, suggested = 0, from: AvailableLine['rate_from'] = ''): AvailableLine => ({
  kind: 'item', key, group_code: '', description, path, material, uom, quantity: left, rate: 7800, given: 0, left, suggested_rate: suggested, rate_from: from,
})
const lines: AvailableLine[] = [
  head('pcc', 'PLAIN CEMENT CONCRETE', 0, [], 'Plain Cement Concrete corresponding to Mix (1:3:6)'),
  item('f', 'Footings', ['pcc'], '', 277, 'Cum.', 650, 'budget'),
  head('rcc', 'REINFORCED CEMENT CONCRETE', 0, [], 'Vibrated Reinforced Cement Concrete'),
  head('b02', 'Basement-02(Grade Slab Lvl)', 1, ['rcc']),
  item('t', 'Tower Columns(Found to Plinth)', ['rcc', 'b02'], 'M60', 61, 'Cum', 1000, 'budget'),
  item('p', 'Podium Columns(Found to Plinth)', ['rcc', 'b02'], 'M60', 4, 'Cum', 2000, 'budget'),
  item('m', 'Podium beams', ['rcc', 'b02'], 'M40', 10, 'Cum'),
]

const post = vi.fn(async (_url: string, _body: unknown) => ({ lines: [], headings: [], rows: [], warnings: [] }))
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => (url === '/api/boqs' ? { boqs: [{ id: 2, job_id: 8, number: 'BOQ-0001', revision: 'R0' }] } : { boq: {}, lines })),
  post: (url: string, body: unknown) => post(url, body),
}))

import { BoqPicker } from './BoqPicker'

const mount = (startMode: 'lines' | 'headings' = 'lines') =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <BoqPicker orderId={5} jobId={8} open onOpenChange={() => {}} onAdd={() => {}} current={[]} startMode={startMode} />
    </QueryClientProvider>,
  )

describe('Building a work order from the BOQ, as the sheet reads', () => {
  it('shows every heading - main and sub - with its text, each line with its grade, and fills the rate in', async () => {
    const user = userEvent.setup()
    mount()
    const table = await screen.findByRole('table', { name: 'Lines of the project BOQ' })
    expect(within(table).getByText('REINFORCED CEMENT CONCRETE')).toBeTruthy()          // the main heading is not lost under its sub-heading
    expect(within(table).getByText('Basement-02(Grade Slab Lvl)')).toBeTruthy()
    expect(within(table).getByText('Vibrated Reinforced Cement Concrete')).toBeTruthy()  // the heading's own text
    expect(within(table).getAllByText('M60')).toHaveLength(2)
    await user.click(screen.getByRole('checkbox', { name: 'Take Footings' }))
    expect((screen.getByRole('textbox', { name: 'Contractor rate of Footings' }) as HTMLInputElement).value).toBe('650')
    expect(screen.getByText('from the budget')).toBeTruthy()
    // A heading ticks everything under it.
    await user.click(screen.getByRole('checkbox', { name: 'Take everything under REINFORCED CEMENT CONCRETE' }))
    expect((screen.getByRole('checkbox', { name: 'Take Podium beams' }) as HTMLInputElement).checked).toBe(true)
  })

  it('adds up under a heading with the grades apart, and sends the heading it stands for', async () => {
    const user = userEvent.setup()
    mount('headings')
    await screen.findByRole('table', { name: 'Headings of the project BOQ' })
    expect(screen.getByRole('checkbox', { name: 'Take REINFORCED CEMENT CONCRETE - M60' })).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: 'Take REINFORCED CEMENT CONCRETE - M40' })).toBeTruthy()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Add up under' }), '1')               // down to the sub-headings
    await user.click(screen.getByRole('checkbox', { name: 'Take Basement-02(Grade Slab Lvl) - M60' }))
    // 61 at 1000 and 4 at 2000: weighted by quantity
    expect((screen.getByRole('textbox', { name: 'Contractor rate of Basement-02(Grade Slab Lvl) - M60' }) as HTMLInputElement).value).toBe(String(Math.round(((61 * 1000 + 4 * 2000) / 65) * 100) / 100))
    await user.click(screen.getByRole('button', { name: /Add 1 line to the work order/ }))
    const body = post.mock.calls.at(-1)![1] as { groups: { heading_key: string; description: string; parts: { key: string }[] }[]; current: unknown[] }
    expect(body.groups[0].heading_key).toBe('b02')
    expect(body.groups[0].parts.map((p) => p.key)).toEqual(['t', 'p'])
    expect(body.current).toEqual([])
  })
})

describe('A heading shows what the lines under it add up to', () => {
  const row = (over: Partial<LineRow>): LineRow => ({
    activity_no: '', item_code: '', item_description: 'x', technical_spec: '', uom: 'cum', quantity: null, unit_rate: null, tolerance_percent: null,
    budget_id: '', is_header: false, boq_key: '', boq_parts: [], material: '', heading_level: 0, ...over,
  })
  it('down to the next heading as high as it', () => {
    const rows = [
      row({ is_header: true, heading_level: 1 }),
      row({ is_header: true, heading_level: 2 }),
      row({ quantity: 10, unit_rate: 100 }),
      row({ is_header: true, heading_level: 2 }),
      row({ quantity: 2, unit_rate: 50 }),
      row({ is_header: true, heading_level: 1 }),
      row({ quantity: 1, unit_rate: 7 }),
    ]
    expect(headingTotals(rows)).toEqual([1100, 1000, null, 100, null, 7, null])
  })
})
