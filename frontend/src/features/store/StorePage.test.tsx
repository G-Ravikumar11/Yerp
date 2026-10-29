import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const urls: string[] = []
let rights: (p: string) => boolean = () => true
let hits: unknown[] = []
let dashboard: unknown = null
const DASHBOARD = {
  as_on: '2026-10-24',
  waiting: [{ label: 'Goods receipts', action: 'to approve', count: 3, path: '/store/hub/inward/grn?status=SUBMITTED' }],
  stock: { stores: 2, items_in_stock: 14, lines_in_stock: 16, total_value: '125000.00', low_stock: 2, out_of_stock: 1,
    low_rows: [{ store_id: 1, store_code: 'CS1', item_id: 9, item_code: 'PIPE-1', item_name: 'GI pipe', base_uom: 'nos', qty: '0.000', reorder_level: '2.000', suggested_qty: '4.000' }] },
  recent: [{ id: 1, date: '2026-10-24', store_code: 'CS1', item_id: 4, item_code: 'SND-1', item_name: 'River sand', movement_type: 'ISSUE_OUT', qty: '-30.000', value: '300.00', reversal: false, doc_number: 'ISS-0007', doc_path: '/store/hub/outward/issue/7' }],
  overdue_returnables: 0,
  budgets: { rows: [{ project_id: 5, project: 'P-1 Tower A', allocated: '1000.00', committed: '600.00', store_material: '500.00', left: '-100.00', over: true, used_pct: 110 }], projects: 1, over: 1, totals: { allocated: '1000.00', committed: '600.00', store_material: '500.00', left: '-100.00' } },
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    urls.push(url)
    if (url.startsWith('/api/store/enquiry/quick')) return { rows: hits }
    if (url.startsWith('/api/stock/cutover')) return { done: null }
    if (url.startsWith('/api/store/dashboard')) return dashboard
    return {}
  }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: (p: string) => rights(p) }) }))

import StorePage from './StorePage'

function Where() { const l = useLocation(); return <div data-testid="where">{l.pathname + l.search}</div> }

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/store/hub']}>
        <Routes><Route path="/store/hub" element={<StorePage />} /><Route path="*" element={<Where />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => { urls.length = 0; rights = () => true; hits = []; dashboard = DASHBOARD })

describe('Store home page', () => {
  it('shows the old-store card together with the search, the one-click jobs and the sections', async () => {
    mount()
    expect(await screen.findByText('Move the old store into the Hub')).toBeTruthy()
    expect(screen.getByLabelText('Find an item')).toBeTruthy()
    expect(screen.getByText('Receive goods')).toBeTruthy()
    expect(screen.getByText('Do something')).toBeTruthy()
    expect(screen.getByText('Browse')).toBeTruthy()
  })

  it('searches only after two characters and a short pause, then lists matches with the stock held', async () => {
    hits = [{ item_id: 1, item_code: 'CEM-1', item_name: 'Cement OPC 53', uom: 'kg', qty: '5000', stores: 2 }, { item_id: 2, item_code: 'CEM-2', item_name: 'Cement PPC', uom: 'kg', qty: '0', stores: 0 }]
    mount()
    await screen.findByText('Move the old store into the Hub')
    await userEvent.type(screen.getByLabelText('Find an item'), 'c')
    await new Promise((r) => setTimeout(r, 350))
    expect(urls.some((u) => u.startsWith('/api/store/enquiry/quick'))).toBe(false)
    await userEvent.type(screen.getByLabelText('Find an item'), 'em')
    expect(await screen.findByText('Cement OPC 53')).toBeTruthy()
    expect(screen.getByText('5,000 kg in 2 stores')).toBeTruthy()
    expect(screen.getByText('Cement PPC').closest('button')?.textContent).toContain('Out of stock')
    expect(urls.filter((u) => u.startsWith('/api/store/enquiry/quick'))).toEqual(['/api/store/enquiry/quick?q=cem'])
  })

  it('says so when nothing matches, and opens the enquiry for a chosen item', async () => {
    mount()
    await screen.findByText('Move the old store into the Hub')
    await userEvent.type(screen.getByLabelText('Find an item'), 'zzz')
    expect(await screen.findByText('No matching item.')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: /check stock/i }))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/store/hub/enquiry?q=zzz'))
  })

  it('disables the search without the enquiry right and hides jobs the person cannot do', async () => {
    rights = (p) => !p.includes('enquiry') && !p.includes('create')
    mount()
    await screen.findByText('Move the old store into the Hub')
    expect((screen.getByLabelText('Find an item') as HTMLInputElement).disabled).toBe(true)
    expect(screen.getByText('Stock enquiry is not enabled for your account.')).toBeTruthy()
    expect(screen.queryByText('Receive goods')).toBeNull()
    expect(screen.getAllByText('Reports').length).toBeGreaterThan(0)
  })

  it('shows the real figures, each opening the screen it comes from', async () => {
    mount()
    expect(await screen.findByText('Stock value')).toBeTruthy()
    expect(screen.getByText('14 items held in 2 stores')).toBeTruthy()
    expect(screen.getByText('None left')).toBeTruthy()
    expect(screen.getByText('ISS-0007').closest('a')?.getAttribute('href')).toBe('/store/hub/outward/issue/7')
    expect(screen.getByText('P-1 Tower A').closest('a')?.getAttribute('href')).toBe('/projects/5')
    expect(screen.getByText('1 project is over.')).toBeTruthy()
    await userEvent.click(screen.getByText(/goods receipts to approve/))
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/store/hub/inward/grn?status=SUBMITTED'))
  })

  it('opens each one-click job at a page that exists', async () => {
    mount()
    await screen.findByText('Receive goods')
    const href = (label: string) => screen.getByText(label).closest('a')?.getAttribute('href')
    expect(href('Issue material')).toBe('/store/hub/outward/issue/new')
    expect(href('Request material')).toBe('/store/hub/outward/indent/new')
    expect(href('Transfer stock')).toBe('/store/hub/control/transfer/new')
    expect(href('Count stock')).toBe('/store/hub/control/count/new')
  })

  it('does not ask for the figures without any Store right', async () => {
    rights = () => false
    mount()
    await screen.findByText('Move the old store into the Hub')
    expect(urls.some((u) => u.startsWith('/api/store/dashboard'))).toBe(false)
    expect(screen.queryByText('Stock value')).toBeNull()
  })
})
