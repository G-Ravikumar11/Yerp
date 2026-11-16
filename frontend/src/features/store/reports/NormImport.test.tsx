import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SheetPreview } from './api'

const calls: { url: string; body: unknown }[] = []
const preview: SheetPreview = {
  project_id: 4, project: 'P-1 - Tower A', mode: 'add',
  summary: { total: 2, valid: 1, invalid: 1, insert: 1, update: 0, unchanged: 0, skip: 0, missing_boq: 1, missing_material: 0, duplicate: 0, invalid_qty: 0 },
  rows: [
    { line: 2, boq_text: '1', material_text: 'RM-1', qty_text: '50', wastage_text: '5', boq_item_id: 9, boq_item: '1 Brickwork', item_id: 3, item_code: 'RM-1', item_name: 'Cement', base_uom: 'kg', qty_per_unit: '50.000000', wastage_pct: '5.00', valid: true, action: 'insert', errors: [], flags: [], current: null },
    { line: 3, boq_text: 'Roofing', material_text: 'RM-1', qty_text: '1', wastage_text: '0', boq_item_id: null, boq_item: '', item_id: 3, item_code: 'RM-1', item_name: 'Cement', base_uom: 'kg', qty_per_unit: '1.000000', wastage_pct: '0.00', valid: false, action: 'error', errors: ["'Roofing' is not a BOQ item of this project."], flags: ['missing_boq'], current: null },
  ],
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  post: vi.fn(async (url: string, body?: unknown) => {
    calls.push({ url, body })
    return url.endsWith('/preview') ? preview : { inserted: 1, updated: 0, unchanged: 0, skipped_existing: 0, invalid: 1, total: 2, message: 'Import finished: 1 added, 0 updated, 1 skipped.' }
  }),
}))

import { NormImportDialog } from './NormImport'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><NormImportDialog projectId={4} projectLabel="P-1 - Tower A" onClose={() => {}} /></QueryClientProvider>)
}

beforeEach(() => { calls.length = 0 })

describe('Import material norms', () => {
  it('refuses a file that is not a sheet before sending anything', async () => {
    mount()
    await userEvent.upload(screen.getByLabelText('Sheet to import'), new File(['x'], 'notes.pdf', { type: 'application/pdf' }), { applyAccept: false })
    expect(screen.getByRole('alert').textContent).toMatch(/Excel workbook/)
    expect((screen.getByRole('button', { name: /Upload and check/ }) as HTMLButtonElement).disabled).toBe(true)
    expect(calls).toHaveLength(0)
  })

  it('sends the real file, shows good and bad rows apart, and imports only after confirming', async () => {
    mount()
    const file = new File(['PK'], 'norms.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    await userEvent.upload(screen.getByLabelText('Sheet to import'), file)
    await userEvent.click(screen.getByRole('button', { name: /Upload and check/ }))
    expect(await screen.findByText('Rows that cannot be imported (1)')).toBeTruthy()
    expect(screen.getByText('Rows ready to import (1)')).toBeTruthy()
    expect(screen.getAllByText('BOQ item not found').length).toBeGreaterThan(0)
    const sent = calls[0].body as FormData
    expect(calls[0].url).toBe('/api/store/reports/norms/import/preview')
    expect((sent.get('file') as File).name).toBe('norms.xlsx')
    expect([sent.get('project_id'), sent.get('mode')]).toEqual(['4', 'add'])

    await userEvent.click(screen.getByRole('button', { name: 'Import 1 row' }))
    expect(calls).toHaveLength(1)                                     // nothing saved before the confirmation
    await userEvent.click(await screen.findByRole('button', { name: 'Import' }))
    await waitFor(() => expect(calls[1]?.url).toBe('/api/store/reports/norms/import/commit'))
    expect(await screen.findByText('Import finished: 1 added, 0 updated, 1 skipped.')).toBeTruthy()
  })
})
