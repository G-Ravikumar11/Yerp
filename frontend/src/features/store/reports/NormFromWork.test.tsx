import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const calls: { url: string; body?: unknown }[] = []
const row = (over: object) => ({
  boq_item_id: 9, boq_item: '2.1 RCC M25 in raft', boq_uom: 'cum', work_item_id: 5, work_code: 'FG-1', work_name: 'RCC M25', work_uom: 'cum',
  item_id: 3, item_code: 'CE0003', item_name: 'Cement OPC 53', base_uom: 'Bags', qty_per_unit: '8.200000', wastage_pct: '2.000', status: 'insert', current: null, ...over,
})
const preview = {
  project: { id: 4, label: 'SR-01 - Sunrise Residency' },
  rows: [row({}), row({ boq_item_id: 10, boq_item: '3.1 Brick masonry', work_code: 'FG-9', work_name: 'Masonry by the tonne', work_uom: 'MT', status: 'unit' })],
  summary: { total: 2, insert: 1, update: 0, unchanged: 0, skip: 0, unit: 1, no_material: 0, no_work: 1, no_norms: 2 },
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => { calls.push({ url }); return preview }),
  post: vi.fn(async (url: string, body?: unknown) => { calls.push({ url, body }); return { inserted: 1, updated: 0, unchanged: 0, skipped_existing: 0, message: "From the work items' norms: 1 added, 0 updated." } }),
}))

import { NormFromWorkDialog } from './NormFromWork'

const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
  <NormFromWorkDialog projectId={4} projectLabel="SR-01 - Sunrise Residency" onClose={() => {}} /></QueryClientProvider>)

describe('Norms from the work items', () => {
  beforeEach(() => { calls.length = 0 })

  it('shows what each BOQ item would take, and skips a work item counted in another unit', async () => {
    mount()
    expect(await screen.findByText('1 to add')).toBeInTheDocument()
    expect(screen.getByText('1 in a different unit')).toBeInTheDocument()
    expect(screen.getByText('Units differ - skipped')).toBeInTheDocument()
    expect(calls[0].url).toContain('/norms/from-work/preview')
    expect(calls[0].url).toContain('mode=add')
    expect(screen.getByRole('button', { name: /Bring in 1 norm$/ })).toBeEnabled()
  })

  it('brings them in after confirming', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /Bring in 1 norm$/ }))
    await user.click(screen.getByRole('button', { name: 'Bring in' }))
    const sent = calls.find((c) => c.url.endsWith('/norms/from-work'))
    expect(sent?.body).toEqual({ project_id: 4, mode: 'add' })
    expect(await screen.findByText(/1 added, 0 replaced/)).toBeInTheDocument()
  })
})
