import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 20_000 })

const sent = vi.hoisted(() => ({ calls: [] as { req: Record<string, unknown>; options: Record<string, unknown> | undefined }[] }))

vi.mock('@/stores/offline', () => ({
  useOffline: { getState: () => ({ online: true }) },   // read by useAction after a change
  sendOrQueue: vi.fn(async (req: Record<string, unknown>, options?: Record<string, unknown>) => {
    sent.calls.push({ req, options })
    return { queued: true as const }
  }),
}))
vi.mock('@/api/ledger', () => ({
  PARTY_LABEL: { supplier: 'Supplier' },
  useMoneyHeads: () => ({ data: { expense: ['Travel & conveyance', 'Site expenses'], income: ['Other income'] } }),
  useAccounts: () => ({ data: [] }),
}))
vi.mock('@/api/projects', () => ({ projectLabel: (p: { name: string }) => p.name, useProjects: () => ({ data: [{ id: 7, name: 'Tower C' }] }) }))
vi.mock('@/api/people', () => ({ useEmployees: () => ({ data: [{ id: 3, first_name: 'Asha', last_name: 'Rao' }] }) }))
vi.mock('@/api/journals', () => ({ JOURNAL_INVALIDATE: [], raiseJournal: vi.fn() }))

import { ClaimModal } from './ClaimsPanel'
import { JournalModal } from './JournalModal'
import { IncidentModal } from '@/features/safety/IncidentModal'

const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } })

beforeEach(() => { sent.calls.length = 0 })

describe('the journal voucher will not be sent until it is balanced, has an amount and says what it is for', () => {
  const send = () => screen.getByRole('button', { name: 'Send to the Master' })
  const open = () => wrap(<JournalModal ledgers={[{ key: 'a', label: 'A' }]} defaultJob={0} onClose={() => undefined} />)
  const narrate = (text: string) => type(screen.getByPlaceholderText('What it is for - this goes in the books'), text)

  it('starts closed to sending, with two lines that cannot be removed', () => {
    open()
    expect(send()).toBeDisabled()
    for (const b of screen.getAllByRole('button', { name: 'Remove line' })) expect(b).toBeDisabled()
  })

  it('says how far out it is, and sends only when debit equals credit', () => {
    open()
    narrate('Rent booked to the wrong site')
    const [dr1] = screen.getAllByLabelText('Debit')
    const [, cr2] = screen.getAllByLabelText('Credit')
    type(dr1, '1000')
    expect(screen.getByText(/out by/)).toBeInTheDocument()
    expect(send()).toBeDisabled()
    type(cr2, '900')
    expect(screen.getByText(/out by/)).toBeInTheDocument()
    expect(send()).toBeDisabled()
    type(cr2, '1000')
    expect(screen.queryByText(/out by/)).not.toBeInTheDocument()
    expect(send()).toBeEnabled()
  })

  it('wants a narration of at least three letters, and a real amount', () => {
    open()
    const [dr1] = screen.getAllByLabelText('Debit')
    const [, cr2] = screen.getAllByLabelText('Credit')
    type(dr1, '500')
    type(cr2, '500')
    expect(send()).toBeDisabled()          // balanced, but nothing says what it is for
    narrate('ab')
    expect(send()).toBeDisabled()
    narrate('abc')
    expect(send()).toBeEnabled()
    type(dr1, '0')
    type(cr2, '0')
    expect(send()).toBeDisabled()          // balanced at nothing
  })

  it('lets a third line be added and then removed again', () => {
    open()
    fireEvent.click(screen.getByRole('button', { name: /Add a line/ }))
    expect(screen.getAllByLabelText('Debit')).toHaveLength(3)
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove line' })[2])
    expect(screen.getAllByLabelText('Debit')).toHaveLength(2)
  })
})

describe('the expense claim is not sent until it has an amount and says what it was', () => {
  const claim = () => screen.getByRole('button', { name: /^Claim/ })
  // The fields are in a fixed order: Amount, What was it, Bill no. (the date, head and project are not text).
  const fields = () => screen.getAllByRole('textbox')

  it('needs an amount above nothing and a description of three letters', () => {
    wrap(<ClaimModal forSomeone={false} onClose={() => undefined} />)
    expect(claim()).toBeDisabled()
    type(fields()[0], '450')
    expect(claim()).toBeDisabled()
    type(screen.getByPlaceholderText('Bus from Vizag to site and back'), 'ab')
    expect(claim()).toBeDisabled()
    type(screen.getByPlaceholderText('Bus from Vizag to site and back'), 'Bus fare')
    expect(claim()).toBeEnabled()
    type(fields()[0], '0')
    expect(claim()).toBeDisabled()
  })

  it('for somebody else, wants to know whose claim it is', () => {
    wrap(<ClaimModal forSomeone onClose={() => undefined} />)
    type(fields()[0], '450')
    type(screen.getByPlaceholderText('Bus from Vizag to site and back'), 'Bus fare')
    expect(claim()).toBeDisabled()                  // nobody chosen yet
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: '3' } })
    expect(claim()).toBeEnabled()
  })

  it('keeps the claim and the bill on the phone when there is no signal, and opens on the site it was started from', async () => {
    const closed = vi.fn()
    wrap(<ClaimModal forSomeone={false} job={7} onClose={closed} />)
    type(fields()[0], '450')
    type(screen.getByPlaceholderText('Bus from Vizag to site and back'), 'Bus fare')
    const bill = new File(['x'], 'bill.jpg', { type: 'image/jpeg' })
    fireEvent.change(document.querySelector('input[type="file"]') as HTMLInputElement, { target: { files: [bill] } })
    fireEvent.click(claim())
    await waitFor(() => expect(sent.calls).toHaveLength(1))
    const { req, options } = sent.calls[0]
    expect(req).toMatchObject({ method: 'POST', url: '/api/expense-claims', body: { amount: 450, job_id: 7, description: 'Bus fare' } })
    expect(options).toMatchObject({ files: { items: [bill], via: 'claim', idFrom: 'id' } })
    await waitFor(() => expect(closed).toHaveBeenCalled())
  })
})

describe('the incident report is not sent until it says what happened', () => {
  it('opens closed to sending and opens up once there is a description', () => {
    wrap(<IncidentModal job={1} kinds={['Near miss']} open onClose={() => undefined} />)
    const report = screen.getByRole('button', { name: 'Report it' })
    expect(report).toBeDisabled()
    type(screen.getByLabelText('What happened'), '   ')
    expect(report).toBeDisabled()
    type(screen.getByLabelText('What happened'), 'A plank fell from level 3')
    expect(report).toBeEnabled()
  })
})
