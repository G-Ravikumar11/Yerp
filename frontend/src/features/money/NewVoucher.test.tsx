import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 20_000 })

const perms = vi.hoisted(() => ({ set: new Set<string>() }))

vi.mock('@/lib/session', () => ({ useSession: () => ({ can: (p: string) => perms.set.has(p) }) }))

// The five forms are used on their own pages already; here only which one opens, and with what, is in question.
vi.mock('@/features/ledger/VoucherModals', () => ({
  ExpenseModal: ({ kind }: { kind: string }) => <div>expense form ({kind})</div>,
  TransferModal: () => <div>transfer form</div>,
}))
vi.mock('@/features/ledger/OnAccountModal', () => ({ OnAccountModal: ({ direction }: { direction: string }) => <div>on account form ({direction})</div> }))
vi.mock('@/features/money/PayModal', () => ({
  PayModal: ({ verb, title, docType, docId }: { verb: string; title: string; docType: string; docId: number }) => <div>{`${verb} form: ${title} (${docType} ${docId})`}</div>,
}))
vi.mock('@/features/money/JournalModal', () => ({ JournalModal: ({ ledgers }: { ledgers: unknown[] }) => <div>journal form ({ledgers.length} ledgers)</div> }))
vi.mock('@/api/journals', () => ({ useJournals: () => ({ data: { ledgers: [{ key: 'a', label: 'A' }, { key: 'b', label: 'B' }] }, isError: false }) }))
vi.mock('@/api/owed', () => ({
  owedKeys: { all: ['owed'] },
  useOwedPayables: () => ({
    isPending: false, isError: false,
    data: { rows: [
      { id: 11, doc_type: 'supplier_bill', number: 'SB-0011', party: 'ACC Ltd', project: 'Tower C', due_date: '2026-10-01', outstanding: 11800, bucket: '0-30', days_overdue: 14, approved: true },
      { id: 12, doc_type: 'sub_bill', number: 'RA-02', party: 'Sri Ram Works', project: '', due_date: '2026-12-01', outstanding: 40000, bucket: 'Not due', days_overdue: 0, approved: true },
      { id: 13, doc_type: 'supplier_bill', number: 'SB-0013', party: 'Not Approved Ltd', project: '', due_date: '', outstanding: 500, bucket: 'Not due', days_overdue: 0, approved: false },
    ] },
  }),
  useOwedReceivables: () => ({
    isPending: false, isError: false,
    data: { rows: [
      { id: 7, doc_type: 'ra_bill', number: 'RA-0007', customer: 'Kokapet LLP', project: 'Tower C', due_date: '2026-09-01', outstanding: 250000, bucket: '31-60', days_overdue: 40 },
      { id: 8, number: 'INV-0008', kind: 'Invoice', customer: 'Fairview Homes', project: '', due_date: '', outstanding: 90000, bucket: '0-30', days_overdue: 5 },      // a tax invoice: no doc_type
    ] },
  }),
}))

import { NewVoucherHost } from './NewVoucherHost'
import { useVoucher } from '@/stores/voucher'

const mount = () => render(<QueryClientProvider client={new QueryClient()}><NewVoucherHost /></QueryClientProvider>)
const altV = () => fireEvent.keyDown(document.body, { key: 'v', code: 'KeyV', altKey: true })
const EVERYTHING = ['money.view', 'bills.pay', 'accounts.manage']

// The screen is fetched the first time it is opened; the first test should not pay for loading it.
beforeAll(async () => { await import('./NewVoucher') }, 60_000)

beforeEach(() => {
  perms.set = new Set(EVERYTHING)
  act(() => useVoucher.setState({ open: false }))
})

describe('who can open it', () => {
  it('opens on Alt+V and offers every kind of voucher', async () => {
    mount()
    expect(screen.queryByText('New voucher')).not.toBeInTheDocument()
    altV()
    expect(await screen.findByText('New voucher')).toBeInTheDocument()
    for (const name of ['Payment', 'Receipt', 'Contra', 'Expense', 'Other receipt', 'Journal']) expect(screen.getByRole('button', { name: new RegExp(`^${name}`) })).toBeInTheDocument()
  })

  it('offers only what the person may pass: the same rights the forms ask', async () => {
    perms.set = new Set(['money.view', 'bills.pay'])
    mount()
    altV()
    await screen.findByText('New voucher')
    expect(screen.getByRole('button', { name: /^Payment/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Journal/ })).not.toBeInTheDocument()
  })

  it('does nothing for someone with no right to pass a voucher, or no Accounts section', () => {
    perms.set = new Set(['money.view'])
    const { unmount } = mount()
    altV()
    expect(screen.queryByText('New voucher')).not.toBeInTheDocument()
    unmount()
    perms.set = new Set(['bills.pay', 'accounts.manage'])         // rights, but not the Accounts section
    mount()
    altV()
    expect(screen.queryByText('New voucher')).not.toBeInTheDocument()
  })

  it('is not opened over a form that is already open, or by other keys', () => {
    mount()
    const form = document.createElement('div')
    form.setAttribute('role', 'dialog')
    document.body.appendChild(form)
    altV()
    expect(screen.queryByText('New voucher')).not.toBeInTheDocument()
    form.remove()
    fireEvent.keyDown(document.body, { key: 'v', code: 'KeyV' })                                   // V alone
    fireEvent.keyDown(document.body, { key: 'v', code: 'KeyV', altKey: true, ctrlKey: true })      // with Ctrl
    fireEvent.keyDown(document.body, { key: 'b', code: 'KeyB', altKey: true })                     // another letter
    expect(screen.queryByText('New voucher')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    mount()
    altV()
    await screen.findByText('New voucher')
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByText('New voucher')).not.toBeInTheDocument())
  })
})

describe('what each kind opens', () => {
  const pick = async (key: string) => {
    const user = userEvent.setup()
    mount()
    altV()
    await screen.findByText('New voucher')
    await user.keyboard(key)
    return user
  }

  it('Expense, Other receipt, Contra and Journal go straight to their forms', async () => {
    await pick('e')
    expect(await screen.findByText('expense form (expense)')).toBeInTheDocument()
  })
  it('Other receipt is the income form', async () => {
    await pick('o')
    expect(await screen.findByText('expense form (income)')).toBeInTheDocument()
  })
  it('Contra is the transfer form', async () => {
    await pick('c')
    expect(await screen.findByText('transfer form')).toBeInTheDocument()
  })
  it('Journal is the journal form, given the books\' ledgers', async () => {
    await pick('j')
    expect(await screen.findByText('journal form (2 ledgers)')).toBeInTheDocument()
  })

  it('a Payment asks which bill, lists what can be paid, and opens that bill to pay', async () => {
    const user = await pick('p')
    expect(await screen.findByText('Payment voucher')).toBeInTheDocument()
    expect(screen.getByText('ACC Ltd')).toBeInTheDocument()
    expect(screen.getByText('Sri Ram Works')).toBeInTheDocument()
    expect(screen.queryByText('Not Approved Ltd')).not.toBeInTheDocument()                          // cannot be paid until approved
    expect(screen.getByText(/1 bill waiting for approval is not listed/)).toBeInTheDocument()
    await user.type(screen.getByLabelText('Find a bill'), 'sri ram')                                // searchable
    expect(screen.queryByText('ACC Ltd')).not.toBeInTheDocument()
    await user.click(screen.getByText('Sri Ram Works'))
    expect(await screen.findByText('Pay form: RA-02 (sub_bill 12)')).toBeInTheDocument()
  })

  it('a Payment with no bill is recorded on account, as money out', async () => {
    const user = await pick('p')
    await user.click(await screen.findByRole('button', { name: /On account, with no bill/ }))
    expect(await screen.findByText('on account form (OUT)')).toBeInTheDocument()
  })

  it('a Receipt lists what is owed to us, and receives against the one picked', async () => {
    const user = await pick('r')
    expect(await screen.findByText('Receipt voucher')).toBeInTheDocument()
    expect(screen.queryByText('Fairview Homes')).not.toBeInTheDocument()                           // an invoice has no receipt voucher...
    expect(screen.getByText(/1 invoice on Pay & Receive is not listed/)).toBeInTheDocument()        // ...and the list says so
    await user.click(screen.getByText('Kokapet LLP'))
    expect(await screen.findByText('Receive form: RA-0007 (ra_bill 7)')).toBeInTheDocument()
  })

  it('a Receipt with no bill is money in on account', async () => {
    const user = await pick('r')
    await user.click(await screen.findByRole('button', { name: /On account, with no bill/ }))
    expect(await screen.findByText('on account form (IN)')).toBeInTheDocument()
  })

  it('goes back from the bill list to the kinds', async () => {
    const user = await pick('p')
    await user.click(await screen.findByRole('button', { name: /Another kind of voucher/ }))
    expect(await screen.findByText('New voucher')).toBeInTheDocument()
    expect(screen.queryByText('Payment voucher')).not.toBeInTheDocument()
  })

  it('a key that is not a kind does nothing', async () => {
    await pick('z')
    expect(screen.getByText('New voucher')).toBeInTheDocument()
  })
})
