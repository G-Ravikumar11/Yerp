import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 30_000 })

let hold = ''
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url.startsWith('/api/money/outstanding')) return { number: 'SB-1', worth: 50000, settled: 0, outstanding: 50000, ahead_of_goods: null, payee_hold: hold, entries: [] }
    if (url.startsWith('/api/bank-accounts')) return { accounts: [{ id: 1, name: 'HDFC current', kind: 'Bank', balance: 100000 }] }
    if (url.startsWith('/api/payment-requests/rules')) return { on: false, free_below: 0, md_above: 100000, master: true }
    return {}
  }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ user: { type: 'client' }, can: () => true }) }))

import { PayModal } from './PayModal'

beforeAll(async () => { await import('./PayModal') })

const open = (verb = 'Pay') => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><PayModal docType="sub_bill" docId={1} title="SB-1" verb={verb} open onOpenChange={() => undefined} invalidate={[]} /></MemoryRouter>
  </QueryClientProvider>,
)

describe('paying a contractor whose bank details wait for approval', () => {
  it('says so and will not pay, with a way to the approval', async () => {
    hold = "Sri Ram Works's bank or tax details were changed and are waiting for approval, so nothing can be paid to them yet. Approve the change in Approvals first."
    open()
    expect(await screen.findByText(/waiting for approval, so nothing can be paid/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Approvals' })).toHaveAttribute('href', '/approvals')
    expect(screen.getByRole('button', { name: /Pay/ })).toBeDisabled()
  })

  it('pays as usual when nothing is held', async () => {
    hold = ''
    open()
    expect(await screen.findByRole('button', { name: /Pay/ })).toBeEnabled()
    expect(screen.queryByText(/waiting for approval/)).not.toBeInTheDocument()
  })

  it('never stops a receipt', async () => {
    hold = 'held'
    open('Receive')
    expect(await screen.findByRole('button', { name: /Receive/ })).toBeEnabled()
  })
})
