import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.setConfig({ testTimeout: 20_000 })

const sent: { url: string; body: unknown }[] = []
const heads = vi.hoisted(() => ({ states: true }))

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url.startsWith('/api/money/heads')) return { expense: ['Rent', 'Interest on loans'], income: ['Scrap sale'], ...(!heads.states ? {} : { states: [{ value: '37', label: 'Andhra Pradesh' }, { value: '29', label: 'Karnataka' }, { value: '36', label: 'Telangana' }] }) }
    if (url.startsWith('/api/bank-accounts')) return { accounts: [{ id: 1, name: 'Cash box', kind: 'Cash', balance: 0 }] }
    if (url.startsWith('/api/jobs')) return { jobs: [] }
    if (url.startsWith('/api/payment-requests/rules')) return { on: false, free_below: 0, md_above: 100000, master: true }
    return {}
  }),
  post: vi.fn(async (url: string, body: unknown) => { sent.push({ url, body }); return { message: 'ok', entry: undefined } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ user: { type: 'client' }, can: () => true }) }))

import { ExpenseModal } from './VoucherModals'

const mount = (kind: 'expense' | 'income' = 'expense') => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><ExpenseModal kind={kind} onClose={() => undefined} /></MemoryRouter>
  </QueryClientProvider>,
)

beforeEach(() => { sent.length = 0; heads.states = true })

const fill = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.type(screen.getByLabelText('Paid to'), 'Landlord')
  await user.type(screen.getByLabelText('Amount'), '25000')
}

describe('the expense voucher tax selection', () => {
  it('non taxable is done there: no local or non local to choose', async () => {
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await fill(user)
    const save = screen.getByRole('button', { name: /Save and print/ })
    expect(save).toBeDisabled()                                                  // nothing chosen yet
    await user.selectOptions(tax, 'non_taxable')
    expect(screen.queryByRole('group', { name: 'Supply' })).not.toBeInTheDocument()
    expect(save).toBeEnabled()
    await user.click(save)
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toMatchObject({ doc_type: 'expense', tax: 'non_taxable', supply: '' })
  })

  it('taxable brings two choices, local and non local; local is done, non local asks for the state', async () => {
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await fill(user)
    await user.selectOptions(tax, 'taxable')
    const save = screen.getByRole('button', { name: /Save and print/ })
    expect(save).toBeDisabled()
    expect(screen.queryByLabelText('State')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Non local' }))
    // Once chosen, the two choices are gone and only the answer is shown, with the state to pick.
    expect(screen.queryByRole('group', { name: 'Supply' })).not.toBeInTheDocument()
    expect(screen.getByText(/Taxable, non local/)).toBeInTheDocument()
    const state = screen.getByLabelText('State')
    expect(screen.getByRole('option', { name: 'Karnataka' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Telangana' })).toBeInTheDocument()
    expect(save).toBeDisabled()                                                  // no state yet
    await user.selectOptions(state, '29')
    expect(save).toBeEnabled()
    await user.click(save)
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toMatchObject({ doc_type: 'expense', tax: 'taxable', supply: 'non_local', supply_state: '29' })
  })

  it('local needs no state', async () => {
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await fill(user)
    await user.selectOptions(tax, 'taxable')
    await user.click(screen.getByRole('button', { name: 'Local' }))
    expect(screen.queryByLabelText('State')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Save and print/ }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toMatchObject({ tax: 'taxable', supply: 'local', supply_state: '' })
  })

  it('switching back to non taxable clears the supply', async () => {
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await fill(user)
    await user.selectOptions(tax, 'taxable')
    await user.click(screen.getByRole('button', { name: 'Local' }))
    // Changed their mind: the choices come back.
    await user.click(screen.getByRole('button', { name: 'Change' }))
    expect(screen.getByRole('group', { name: 'Supply' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Non local' }))
    await user.selectOptions(screen.getByLabelText('State'), '36')
    await user.selectOptions(tax, 'non_taxable')
    expect(screen.queryByText(/Taxable,/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Save and print/ }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toMatchObject({ tax: 'non_taxable', supply: '', supply_state: '' })
  })

  it('a receipt has no tax selection', async () => {
    mount('income')
    await screen.findByLabelText('Receipt head')
    expect(screen.queryByLabelText('Tax selection')).not.toBeInTheDocument()
  })

  it('still lists every state and union territory when an older saved answer has none', async () => {
    heads.states = false
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await user.selectOptions(tax, 'taxable')
    await user.click(screen.getByRole('button', { name: 'Non local' }))
    const state = screen.getByLabelText('State') as HTMLSelectElement
    expect(state.querySelectorAll('option')).toHaveLength(37)                  // the placeholder and 36
    for (const name of ['Andhra Pradesh', 'Telangana', 'Karnataka', 'Delhi', 'Jammu & Kashmir', 'Ladakh', 'West Bengal', 'Lakshadweep']) {
      expect(screen.getByRole('option', { name })).toBeInTheDocument()
    }
  })

  it('works out the tax inside the amount: IGST for the state chosen, CGST and SGST for a local supply', async () => {
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await user.type(screen.getByLabelText('Paid to'), 'Landlord')
    await user.type(screen.getByLabelText('Amount'), '11800')
    await user.selectOptions(tax, 'taxable')
    await user.click(screen.getByRole('button', { name: 'Non local' }))
    expect(screen.queryByLabelText('Tax worked out')).not.toBeInTheDocument()   // no state yet
    await user.selectOptions(screen.getByLabelText('State'), '29')
    const calc = within(screen.getByLabelText('Tax worked out'))
    expect(calc.getByText(/Karnataka: IGST 18% = /)).toBeInTheDocument()
    expect(calc.getAllByText(/1,800/).length).toBeGreaterThan(0)
    expect(calc.getByText(/Before tax .*10,000/)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('GST rate'), '12')
    expect(within(screen.getByLabelText('Tax worked out')).getByText(/Karnataka: IGST 12% = /)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Save and print/ }))
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toMatchObject({ tax: 'taxable', supply: 'non_local', supply_state: '29', gst_rate: 12, amount: 11800 })
  })

  it('shows half CGST and half SGST for a local supply, with no state', async () => {
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await user.type(screen.getByLabelText('Amount'), '11800')
    await user.selectOptions(tax, 'taxable')
    await user.click(screen.getByRole('button', { name: 'Local' }))
    expect(within(screen.getByLabelText('Tax worked out')).getByText(/CGST 9% = .*900.* \+ SGST 9% = .*900/)).toBeInTheDocument()
    expect(screen.queryByLabelText('State')).not.toBeInTheDocument()
  })

  it('a bank transfer asks where the money went and will not save without it', async () => {
    const user = userEvent.setup()
    mount()
    const tax = await screen.findByLabelText('Tax selection')
    await fill(user)
    await user.selectOptions(tax, 'non_taxable')
    const save = screen.getByRole('button', { name: /Save and print/ })
    expect(save).toBeEnabled()                                                   // cash needs none of it
    expect(screen.queryByLabelText('Account number')).not.toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Mode'), 'Bank transfer')
    expect(save).toBeDisabled()
    await user.selectOptions(screen.getByLabelText('Paid from'), '1')
    await user.type(screen.getByLabelText('UTR / reference number'), 'UTR998877')
    await user.type(screen.getByLabelText('Payee bank name'), 'State Bank of India')
    await user.type(screen.getByLabelText('Account number'), '12AB')
    await user.type(screen.getByLabelText('IFSC'), 'sbin0001234')
    expect(save).toBeDisabled()                                                  // the account number is not digits
    expect(screen.getByText('6 to 20 digits')).toBeInTheDocument()
    await user.clear(screen.getByLabelText('Account number'))
    await user.type(screen.getByLabelText('Account number'), '30123456789')
    expect(save).toBeEnabled()
    await user.click(save)
    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0].body).toMatchObject({ mode: 'Bank transfer', reference: 'UTR998877', account_id: 1, payee_bank: 'State Bank of India', payee_account: '30123456789', payee_ifsc: 'SBIN0001234' })
  })
})
