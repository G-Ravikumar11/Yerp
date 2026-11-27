import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const norms = {
  item_id: 5, item_code: 'FG-1', item_name: 'PCC M15', unit: 'cum', is_work: true,
  norms: [{ material_id: 11, item_code: 'CE0003', item_name: 'Cement OPC 53 grade', hsn: '2523', unit: 'Bags', qty_per_unit: 4.4, wastage_pct: 2, remarks: '', is_active: true }],
}
const puts: { url: string; body: unknown }[] = []
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => (url.startsWith('/api/items?')
    ? { items: [{ id: 12, item_code: 'SA0005', item_name: 'Sand', units_of_measure: 'cum' }] }
    : norms)),
  put: vi.fn(async (url: string, body: unknown) => { puts.push({ url, body }); return norms }),
}))

import { NormsSection } from './NormsSection'

const wrap = (manage = true) => render(<QueryClientProvider client={new QueryClient()}><NormsSection itemId={5} unit="cum" manage={manage} /></QueryClientProvider>)

describe('Material norms of a work item', () => {
  beforeEach(() => { puts.length = 0 })

  it('lists what one unit of the work uses, with its wastage', async () => {
    wrap(false)
    expect(await screen.findByText('Cement OPC 53 grade')).toBeInTheDocument()
    expect(screen.getByText('4.4 Bags')).toBeInTheDocument()
    expect(screen.getByText('2%')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit norms/ })).not.toBeInTheDocument()
  })

  it('adds a material and saves the norms', async () => {
    const user = userEvent.setup()
    wrap()
    await user.click(await screen.findByRole('button', { name: /Edit norms/ }))
    await user.click(screen.getByRole('textbox', { name: 'Add a material to the norms' }))
    await user.click(await screen.findByRole('button', { name: /Sand/ }))
    await user.type(screen.getByRole('textbox', { name: 'Sand per cum' }), '0.47')
    await user.type(screen.getByRole('textbox', { name: 'Wastage of Sand' }), '5')
    await user.click(screen.getByRole('button', { name: /Save norms/ }))
    expect(puts[0].url).toBe('/api/items/5/norms')
    expect(puts[0].body).toEqual({ rows: [
      { material_id: 11, qty_per_unit: 4.4, wastage_pct: 2, remarks: '' },
      { material_id: 12, qty_per_unit: 0.47, wastage_pct: 5, remarks: '' },
    ] })
  })
})
