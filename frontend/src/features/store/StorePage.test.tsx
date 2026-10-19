import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const urls: string[] = []
let rights: (p: string) => boolean = () => true
let hits: unknown[] = []

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    urls.push(url)
    if (url.startsWith('/api/store/enquiry/quick')) return { rows: hits }
    if (url.startsWith('/api/stock/cutover')) return { done: null }
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

beforeEach(() => { urls.length = 0; rights = () => true; hits = [] })

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
    expect(screen.getByText('Out of stock')).toBeTruthy()
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
})
