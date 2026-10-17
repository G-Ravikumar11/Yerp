import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Tracker } from '@/api/invoiceTracker'

const calls: { url: string; method: string; body?: unknown }[] = []
const tracker: Tracker = {
  job_id: 0, gst_percent: 18, markup_percent: 20,
  summary: { rows: [{ category: 'Plumbing', purchase_amount: 11800, wo_amount: 9000, wo_suggested: 9000, wo_source: 'work orders', difference: -2800, remarks: '' }], purchase_amount: 11800, wo_amount: 9000, difference: -2800 },
  invoices: [{ grn_id: 7, grn: 'GRN-0001', supplier: 'Sudhakar PVC', invoice_number: 'SSMA-2718', invoice_date: '', received_on: '2026-01-02', po_number: 'PO-1', vehicle: '', amount: 10000, gst: 1800, freight: 0, insurance: 0, hamali: 0, total: 11800, trades: ['Plumbing'], remark: 'SOME COILS NOT RECEIVED', invoice_amount: 11000, difference: -800 }],
  categories: [{ name: 'Plumbing', invoice_ids: [7], total: 10000, gst: 1800, with_gst: 11800, markup: 2000, with_markup: 12000, working_total: 7000, note: 'Balance to come', footer: [{ grn_id: 7, amount: 10000, gst: 1800, total: 11800, freight: 0, insurance: 0, hamali: 0, invoice_amount: 11000, difference: -800, whole: true, remark: 'SOME COILS NOT RECEIVED' }], materials: [
    { key: 'PL-1', sl: 1, item_code: 'PL-1', description: '75MM PVC pipe', uom: 'Nos', total_qty: 100, total_amount: 10000, total_rate: 100, avg_rate: 100, working_rate: 70, working_amount: 7000, on_hand: 40, counted: true, cells: [{ grn_id: 7, qty: 100, rate: 100, amount: 10000 }] },
    { key: 'PL-9', sl: 2, item_code: 'PL-9', description: 'Gully trap', uom: 'Nos', total_qty: 0, total_amount: 0, total_rate: 0, avg_rate: 0, working_rate: null, working_amount: null, on_hand: 0, counted: false, cells: [] },
  ] }],
  rmc: { rows: [{ line_id: 3, n: 1, grn_id: 7, invoice_date: '2026-01-02', supplier: 'Techno', po_number: 'PO-2', vehicle: 'AP39UZ4477', invoice_number: 'T-1', grade: 'M15', qty: 7, rate: 3500, amount: 24500, block: 'B-21' }], blocks: [{ block: 'B-21', loads: 1, qty: 7, amount: 24500 }], qty: 7, amount: 24500, gst: 4410, total: 28910 },
  stock: [{ category: 'Plumbing', items: [{ item_code: 'PL-1', item_name: '75MM PVC pipe', uom: 'Nos', on_hand: 40, counted: true }, { item_code: 'PL-2', item_name: 'Elbow', uom: 'Nos', on_hand: 0, counted: false }] }],
  totals: { invoices: 1, amount: 10000, gst: 1800, freight: 0, insurance: 0, hamali: 0, total: 11800, unchecked: 0, mismatched: 1 },
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => { calls.push({ url, method: 'GET' }); return url.startsWith('/api/invoice-tracker') ? tracker : [] }),
  post: vi.fn(async (url: string, body?: unknown) => { calls.push({ url, method: 'POST', body }); return { message: 'ok', difference: 0 } }),
  put: vi.fn(async (url: string, body?: unknown) => { calls.push({ url, method: 'PUT', body }); return { ok: true } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true }) }))
vi.mock('@/api/stock', () => ({ stockKeys: { all: ['stock'] }, countStock: (code: string, counted: number) => import('@/lib/api').then((m) => m.post('/api/stock/adjustments', { item_code: code, counted })) }))
vi.mock('@/components/data/ProjectPicker', () => ({ ProjectPicker: () => <div>project picker</div> }))

import InvoiceTrackerPage from './InvoiceTrackerPage'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><InvoiceTrackerPage /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => { calls.length = 0 })

describe('Invoice Tracker', () => {
  it('shows the trade summary, and the totals that need a look', async () => {
    mount()
    expect(await screen.findByText('Plumbing')).toBeTruthy()
    expect(screen.getByText('Bills that do not match')).toBeTruthy()
    expect(calls[0].url).toBe('/api/invoice-tracker?job_id=0&gst=18&markup=20')
  })

  it('saves a work-order amount when the box is left, and not when nothing was typed', async () => {
    mount()
    const box = await screen.findByLabelText('Work order amount for Plumbing')
    await userEvent.click(box)
    await userEvent.tab()
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
    await userEvent.clear(box)
    await userEvent.type(box, '7000')
    await userEvent.tab()
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ job_id: 0, category: 'Plumbing', wo_amount: 7000 }))
  })

  it('flags a bill that does not match and lets its amount be corrected or cleared', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: /^Invoices/ }))
    expect(await screen.findByText('-₹800.00')).toBeTruthy()
    const amount = screen.getByLabelText(/Amount on the supplier's bill SSMA-2718/)
    await userEvent.clear(amount)
    await userEvent.tab()
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ clear_amount: true }))
  })

  it('lays each material out against its supplier invoices', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: 'Received materials' }))
    const row = (await screen.findByText('75MM PVC pipe')).closest('tr') as HTMLElement
    expect(within(row).getAllByText('100').length).toBeGreaterThan(0)
    expect(screen.getByText('Sudhakar PVC')).toBeTruthy()
  })

  it('follows the list people keep: SL NO, the PO under each invoice, every material, and the totals, working rate and stock', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: 'Received materials' }))
    for (const head of ['SL NO', 'Total qty', 'Total rate', 'Total amount', 'Working rate', 'Working amount', 'Physical store stock']) expect((await screen.findAllByText(head)).length).toBeGreaterThan(0)
    expect(screen.getByText('PO PO-1')).toBeTruthy()
    expect(screen.getByText('Gully trap')).toBeTruthy()
    expect(screen.getByText('Note: Balance to come')).toBeTruthy()
  })

  it('saves a working rate, and clears it when emptied', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: 'Received materials' }))
    const box = await screen.findByLabelText('Working rate for PL-1')
    await userEvent.clear(box)
    await userEvent.tab()
    await waitFor(() => expect(calls.find((c) => c.url === '/api/invoice-tracker/working-rates')?.body).toEqual({ job_id: 0, item_key: 'PL-1', rate: null }))
    const gap = screen.getByLabelText('Working rate for PL-9')
    await userEvent.type(gap, '55')
    await userEvent.tab()
    await waitFor(() => expect(calls.filter((c) => c.url === '/api/invoice-tracker/working-rates').pop()?.body).toEqual({ job_id: 0, item_key: 'PL-9', rate: 55 }))
  })

  it('saves a remark against an invoice', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: /^Invoices/ }))
    const box = await screen.findByLabelText('Remark on invoice SSMA-2718')
    await userEvent.clear(box)
    await userEvent.type(box, 'Two coils short')
    await userEvent.tab()
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ remark: 'Two coils short' }))
  })

  it('records which block a lorry of concrete went into', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: /Ready-mix register/ }))
    const block = await screen.findByLabelText('Block for T-1')
    await userEvent.clear(block)
    await userEvent.type(block, 'C-16')
    await userEvent.tab()
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')).toMatchObject({ url: '/api/invoice-tracker/blocks/3', body: { block: 'C-16' } }))
  })

  it("says when a trade's work-order value came from the work orders", async () => {
    mount()
    expect(await screen.findByText('from work orders')).toBeTruthy()
  })

  it("shows the totals, the bill's charges and the markup under a trade's invoices", async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: 'Received materials' }))
    for (const label of ['Amount', 'GST 18%', 'Freight', 'Insurance', 'Hamali', 'Total amount', 'Invoice amount', 'Different amount']) expect((await screen.findAllByText(label)).length).toBeGreaterThan(0)
    expect(screen.getByText(/@ 20%/)).toBeTruthy()
    expect(screen.getByText(/total with markup/)).toBeTruthy()
    expect(screen.getByText('₹12,000.00')).toBeTruthy()
  })

  it('saves insurance and hamali on an invoice', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: /^Invoices/ }))
    const box = await screen.findByLabelText('Insurance for SSMA-2718')
    await userEvent.type(box, '75')
    await userEvent.tab()
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ insurance: 75 }))
  })

  it('lists every purchased material and posts a physical count', async () => {
    mount()
    await userEvent.click(await screen.findByRole('tab', { name: 'Physical stock' }))
    expect(await screen.findByText('Elbow')).toBeTruthy()
    const box = screen.getByLabelText('Physical stock of PL-2')
    await userEvent.type(box, '12')
    await userEvent.tab()
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')).toMatchObject({ url: '/api/stock/adjustments', body: { item_code: 'PL-2', counted: 12 } }))
  })
})
