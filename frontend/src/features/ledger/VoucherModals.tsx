import { useState } from 'react'
import { Check } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { ledgerKeys, recordVoucher, transferMoney, useAccounts, useMoneyHeads, voucherUrl, type Entry } from '@/api/ledger'
import { PAY_MODES } from '@/api/money'
import { mustAsk, paymentKeys, raisePaymentRequest, usePaymentRules } from '@/api/payments'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { INDIAN_STATES } from '@/lib/states'
import { GST_RATES, gstSplit } from '@/lib/gstSplit'

/** After saving, the voucher opens to print or hand over. */
const openVoucher = (e?: Entry) => { if (e) window.open(voucherUrl(e.id), '_blank', 'noopener') }

/**
 * Money out with no bill behind it - diesel at the pump, the lorry, the site's sundries - booked under a head and
 * charged to the project it was for; or money in the same way (scrap sold, interest). A bill with GST on it goes in as
 * a supplier bill instead, so its input credit is claimed.
 */
export function ExpenseModal({ kind, onClose }: { kind: 'expense' | 'income' | null; onClose: () => void }) {
  return (
    <Modal open={!!kind} onOpenChange={(o) => !o && onClose()} title={kind === 'income' ? 'Other receipt' : 'Expense voucher'}
      description={kind === 'income' ? 'Money in with no bill of ours behind it: scrap sold, interest, a deposit back.'
        : 'Money paid with no supplier bill behind it: diesel, transport, site sundries. A bill with GST goes in as a supplier bill, so the GST is claimed.'}>
      {kind && <ExpenseForm kind={kind} onClose={onClose} />}
    </Modal>
  )
}

function ExpenseForm({ kind, onClose }: { kind: 'expense' | 'income'; onClose: () => void }) {
  const heads = useMoneyHeads()
  const accounts = useAccounts()
  const projects = useProjects()
  const list = (kind === 'expense' ? heads.data?.expense : heads.data?.income) ?? []
  const [head, setHead] = useState('')
  // An expense is taxable or not; a taxable one is local or non local. Chosen on the voucher, before the project and the rest.
  const [tax, setTax] = useState('')
  const [supply, setSupply] = useState('')
  // A non local supply comes from a state: every state and union territory of India, by name.
  const [state, setState] = useState('')
  // The amount paid already includes the tax; the rate says how much of it is tax.
  const [rate, setRate] = useState('18')
  const [party, setParty] = useState('')
  const [job, setJob] = useState('')
  const [amount, setAmount] = useState(0)
  const [on, setOn] = useState(today())
  const [mode, setMode] = useState('Cash')
  const [ref, setRef] = useState('')
  const [note, setNote] = useState('')
  const [account, setAccount] = useState('')
  // A bank transfer out: where it went. Kept with the voucher, and so in the ledgers and the books.
  const [payeeBank, setPayeeBank] = useState('')
  const [payeeAccount, setPayeeAccount] = useState('')
  const [payeeIfsc, setPayeeIfsc] = useState('')
  const only = accounts.data?.length === 1 ? String(accounts.data[0].id) : ''
  const rules = usePaymentRules()
  // An expense, where the company approves payments first: sent for approval, paid once approved.
  const ask = kind === 'expense' && mustAsk(rules.data, amount)
  const isExpense = kind === 'expense'
  const stateName = (heads.data?.states?.length ? heads.data.states : INDIAN_STATES).find((s) => s.value === state)?.label ?? ''
  const bankTransfer = kind === 'expense' && mode === 'Bank transfer'
  const ifscOk = /^[A-Z]{4}0[A-Z0-9]{6}$/.test(payeeIfsc.trim().toUpperCase())
  const accountOk = /^\d{6,20}$/.test(payeeAccount.replace(/\s/g, ''))
  const bankReady = !bankTransfer || (!!(account || only) && !!ref.trim() && !!payeeBank.trim() && accountOk && ifscOk)
  const taxReady = !isExpense || tax === 'non_taxable' || (tax === 'taxable' && (supply === 'local' || (supply === 'non_local' && !!state)))
  const fields = { head: head || list[0] || '', ...(isExpense ? { ...(bankTransfer ? { payee_bank: payeeBank.trim(), payee_account: payeeAccount.replace(/\s/g, ''), payee_ifsc: payeeIfsc.trim().toUpperCase() } : {}), tax, supply: tax === 'taxable' ? supply : '', supply_state: tax === 'taxable' && supply === 'non_local' ? state : '', gst_rate: tax === 'taxable' ? Number(rate) : undefined } : {}), party_name: party.trim(), amount, mode, note, account_id: Number(account || only) || null, job_id: Number(job) || null }
  const save = useAction(async () => (ask
    ? { ...(await raisePaymentRequest({ doc_type: 'expense', ...fields })), entry: undefined }
    : recordVoucher({ doc_type: kind, ...fields, paid_on: on, reference: ref })), {
    invalidate: [ledgerKeys.all, ['owed'], ['projects'], ['costs'], paymentKeys.all],
    onSuccess: (r) => { onClose(); openVoucher(r.entry) },
  })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={kind === 'expense' ? 'Expense head' : 'Receipt head'} htmlFor="ev-head"><Select id="ev-head" value={head || list[0] || ''} onChange={(e) => setHead(e.target.value)} options={list.map((h) => ({ value: h, label: h }))} /></Field>
        <Field label={kind === 'expense' ? 'Paid to' : 'Received from'} htmlFor="ev-party"><Input id="ev-party" value={party} onChange={(e) => setParty(e.target.value)} placeholder={kind === 'expense' ? 'HP pump, Gajuwaka' : 'Sri Sai Scrap'} autoFocus /></Field>
        {isExpense && (
          <div className="grid gap-4 sm:col-span-2">
            <Field label="Tax selection" htmlFor="ev-tax">
              <Select id="ev-tax" value={tax} onChange={(e) => { setTax(e.target.value); setSupply(''); setState('') }} placeholder="Choose taxable or non taxable"
                options={[{ value: 'taxable', label: 'Taxable' }, { value: 'non_taxable', label: 'Non taxable' }]} />
            </Field>
            {tax === 'taxable' && !supply && (
              <div role="group" aria-label="Supply" className="grid grid-cols-2 gap-3">
                {([['local', 'Local'], ['non_local', 'Non local']] as const).map(([value, label]) => (
                  <Button key={value} type="button" variant="outline" onClick={() => setSupply(value)}>{label}</Button>
                ))}
              </div>
            )}
            {tax === 'taxable' && supply && (
              <p className="flex items-center gap-2 text-sm" aria-live="polite">
                <Check className="size-4 text-success" aria-hidden="true" /> Taxable, {supply === 'local' ? 'local' : 'non local'}
                <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={() => { setSupply(''); setState('') }}>Change</button>
              </p>
            )}
            {tax === 'taxable' && supply === 'non_local' && (
              <Field label="State" htmlFor="ev-state" hint="The state the supply comes from.">
                <Select id="ev-state" value={state} onChange={(e) => setState(e.target.value)} placeholder="Choose the state"
                  options={(heads.data?.states?.length ? heads.data.states : INDIAN_STATES).map((s) => ({ value: s.value, label: s.label }))} />
              </Field>
            )}
            {tax === 'taxable' && (supply === 'local' || (supply === 'non_local' && !!state)) && (() => {
              const r = Number(rate)
              const g = gstSplit(amount, r, supply as 'local' | 'non_local')
              return (
                <div className="grid gap-3">
                  <Field label="GST rate" htmlFor="ev-rate" hint="The amount you paid already includes the tax.">
                    <Select id="ev-rate" value={rate} onChange={(e) => setRate(e.target.value)} options={GST_RATES.map((x) => ({ value: String(x), label: `${x}%` }))} />
                  </Field>
                  <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm" aria-label="Tax worked out" role="group">
                    {supply === 'non_local'
                      ? <p className="font-medium">{stateName}: IGST {r}% = {formatINR(g.igst)}</p>
                      : <p className="font-medium">CGST {r / 2}% = {formatINR(g.cgst)} + SGST {r / 2}% = {formatINR(g.sgst)}</p>}
                    <p className="mt-0.5 text-[13px] text-muted-foreground">Before tax {formatINR(g.base)}, tax {formatINR(g.tax)}, paid {formatINR(amount)}.</p>
                  </div>
                </div>
              )
            })()}
          </div>
        )}
        <Field label="Project" htmlFor="ev-job" hint={kind === 'expense' ? 'Charged to its cost' : undefined} className="sm:col-span-2"><Select id="ev-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder="Head office (no project)" options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Amount" htmlFor="ev-amount"><NumField id="ev-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="Date" htmlFor="ev-date"><Input id="ev-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Mode" htmlFor="ev-mode"><Select id="ev-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={PAY_MODES.map((m) => ({ value: m, label: m }))} /></Field>
        <Field label={bankTransfer ? 'UTR / reference number' : 'Reference'} htmlFor="ev-ref"><Input id="ev-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder={bankTransfer ? 'The bank transaction number' : 'Bill no., UTR or cheque no.'} /></Field>
        <Field label={kind === 'expense' ? 'Paid from' : 'Received into'} htmlFor="ev-account" className="sm:col-span-2"><Select id="ev-account" value={account || only} onChange={(e) => setAccount(e.target.value)} placeholder={bankTransfer ? 'Choose our bank account' : 'Not recorded against an account'} options={(accounts.data ?? []).map((a) => ({ value: a.id, label: `${a.name} (${a.kind})` }))} /></Field>
        {bankTransfer && (
          <fieldset className="grid gap-4 rounded-lg border border-border p-3 sm:col-span-2 sm:grid-cols-3">
            <legend className="px-1 text-[13px] font-medium">Bank transfer: where the money went</legend>
            <Field label="Payee bank name" htmlFor="ev-pbank"><Input id="ev-pbank" value={payeeBank} onChange={(e) => setPayeeBank(e.target.value)} placeholder="State Bank of India" /></Field>
            <Field label="Account number" htmlFor="ev-pacct" hint={payeeAccount && !accountOk ? '6 to 20 digits' : undefined}><Input id="ev-pacct" inputMode="numeric" value={payeeAccount} onChange={(e) => setPayeeAccount(e.target.value)} placeholder="30123456789" /></Field>
            <Field label="IFSC" htmlFor="ev-pifsc" hint={payeeIfsc && !ifscOk ? 'Like SBIN0001234' : undefined}><Input id="ev-pifsc" value={payeeIfsc} onChange={(e) => setPayeeIfsc(e.target.value.toUpperCase())} placeholder="SBIN0001234" maxLength={11} /></Field>
          </fieldset>
        )}
        <Field label="Details" htmlFor="ev-note" className="sm:col-span-2"><Input id="ev-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder={kind === 'expense' ? 'JCB 3DX, 50 litres' : ''} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!party.trim() || amount <= 0 || !list.length || !taxReady || !bankReady} onClick={() => save.mutate()}>{ask ? 'Send for approval' : 'Save and print the voucher'}</Button>
      </div>
    </div>
  )
}

/** What a transfer opens with: a site's cash box topped up shows the box and the amount already filled in. */
export interface TransferDefaults { to?: number; amount?: number; note?: string }

/** A contra: cash drawn from the bank for a site's cash box, paid back in, or moved between two banks. */
export function TransferModal({ open, onClose, defaults, invalidate = [] }: { open: boolean; onClose: () => void; defaults?: TransferDefaults; invalidate?: readonly (readonly unknown[])[] }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title="Transfer between accounts" description="Cash drawn from the bank for a site, a cash box paid back in, or money moved between two banks. It is neither received nor paid: one contra voucher, in both books.">
      {open && <TransferForm onClose={onClose} defaults={defaults} invalidate={invalidate} />}
    </Modal>
  )
}

function TransferForm({ onClose, defaults, invalidate }: { onClose: () => void; defaults?: TransferDefaults; invalidate: readonly (readonly unknown[])[] }) {
  const accounts = useAccounts()
  const list = accounts.data ?? []
  const [from, setFrom] = useState('')
  const [to, setTo] = useState(defaults?.to ? String(defaults.to) : '')
  const [amount, setAmount] = useState(defaults?.amount ?? 0)
  const [on, setOn] = useState(today())
  const [mode, setMode] = useState('Cheque')
  const [ref, setRef] = useState('')
  const [note, setNote] = useState(defaults?.note ?? '')
  const options = list.map((a) => ({ value: a.id, label: `${a.name} (${a.kind})` }))
  const save = useAction(() => transferMoney({ from_account_id: Number(from), to_account_id: Number(to), amount, paid_on: on, mode, reference: ref, note }), {
    invalidate: [ledgerKeys.all, ...invalidate.map((k) => [...k])],
    onSuccess: (r) => { onClose(); openVoucher(r.entry) },
  })
  if (accounts.data && list.length < 2) return <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">A transfer needs two accounts. Add the bank account and a cash box for the site on the Bank book tab first.</p>
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="From" htmlFor="tr-from"><Select id="tr-from" value={from} onChange={(e) => setFrom(e.target.value)} placeholder="Choose the account" options={options} /></Field>
        <Field label="To" htmlFor="tr-to"><Select id="tr-to" value={to} onChange={(e) => setTo(e.target.value)} placeholder="Choose the account" options={options.map((o) => ({ ...o, disabled: String(o.value) === from }))} /></Field>
        <Field label="Amount" htmlFor="tr-amount"><NumField id="tr-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="Date" htmlFor="tr-date"><Input id="tr-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Mode" htmlFor="tr-mode"><Select id="tr-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={PAY_MODES.filter((m) => m !== 'Adjustment').map((m) => ({ value: m, label: m }))} /></Field>
        <Field label="Cheque or UTR no." htmlFor="tr-ref"><Input id="tr-ref" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
        <Field label="Note" htmlFor="tr-note" className="sm:col-span-2"><Input id="tr-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Imprest for Vizag site, week 43" /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!from || !to || from === to || amount <= 0} onClick={() => save.mutate()}>Save and print the voucher</Button>
      </div>
    </div>
  )
}
