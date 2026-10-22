import { useState } from 'react'
import { Check, FileText, X } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import { ledgerKeys, useAccounts, voucherUrl } from '@/api/ledger'
import { PAY_MODES } from '@/api/money'
import {
  cancelPaymentRequest, decidePaymentRequest, payPaymentRequest, paymentKeys, usePaymentRequests, usePaymentRules,
  type PaymentRequest, type RequestStatus,
} from '@/api/payments'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

const TONE: Record<RequestStatus, 'warning' | 'info' | 'success' | 'neutral' | 'danger' | 'ember'> = {
  PENDING: 'warning', AWAITING_MD: 'ember', APPROVED: 'info', PAID: 'success', REJECTED: 'danger', CANCELLED: 'neutral',
}
const FILTERS = [{ value: 'open', label: 'Open' }, { value: 'paid', label: 'Paid' }, { value: '', label: 'All' }]
const against = (r: PaymentRequest) => r.doc_number || r.head || (r.doc_type === 'on_account' ? 'Advance on account' : '')

/**
 * Payments waiting on a signature: with the accounts head, with the MD over the limit, approved and waiting to be paid.
 * Whoever may decide does so here (or from the Approvals inbox); accounts pay what is approved.
 */
export function RequestsTab() {
  const { can } = useSession()
  const rules = usePaymentRules()
  const [filter, setFilter] = useState('open')
  const q = usePaymentRequests(filter)
  const r = rules.data
  const [paying, setPaying] = useState<PaymentRequest | null>(null)
  const [rejecting, setRejecting] = useState<PaymentRequest | null>(null)
  const done = { invalidate: [paymentKeys.all, ledgerKeys.all, ['owed'], ['approvals']] }
  const approve = useAction((x: PaymentRequest) => decidePaymentRequest(x.id, 'approve'), done)
  const reject = useAction((a: { x: PaymentRequest; note: string }) => decidePaymentRequest(a.x.id, 'reject', a.note), { ...done, onSuccess: () => setRejecting(null) })
  const withdraw = useAction((x: PaymentRequest) => cancelPaymentRequest(x.id), done)
  const mayDecide = (x: PaymentRequest) => x.requested_by !== r?.me || !!r?.master
    ? (x.status === 'PENDING' && !!r?.can_check) || (x.status === 'AWAITING_MD' && !!r?.can_release) : false
  const s = q.data?.summary

  const columns: TableColumn<PaymentRequest>[] = [
    { id: 'no', header: 'No.', cell: (x) => <div><span className="font-mono text-[13px]">{x.number}</span><div className="text-xs text-muted-foreground">{formatDate(x.requested_at.slice(0, 10))}</div></div> },
    { id: 'party', header: 'Pay to', cell: (x) => <div>{x.party_name}<div className="text-xs text-muted-foreground">{against(x)}{x.project && ` · ${x.project}`}</div></div> },
    { id: 'amount', header: 'Amount', align: 'right', cell: (x) => <span className="font-semibold tabular-nums">{formatINR(x.amount)}</span> },
    {
      id: 'status', header: 'Where it is', cell: (x) => (
        <div>
          <Badge tone={TONE[x.status]} dot>{x.status_label}</Badge>
          <div className="mt-0.5 text-xs text-muted-foreground">
            Asked by {x.requested_by_name}{x.checked_by_name && ` · checked by ${x.checked_by_name}`}{x.approved_by_name && ` · approved by ${x.approved_by_name}`}
            {x.reject_reason && <span className="text-danger"> · {x.rejected_by_name}: {x.reject_reason}</span>}
          </div>
          {x.note && <div className="max-w-72 truncate text-xs text-muted-foreground" title={x.note}>{x.note}</div>}
        </div>
      ),
    },
    {
      id: 'act', header: '', align: 'right', cell: (x) => (
        <div className="flex flex-wrap justify-end gap-1.5">
          {mayDecide(x) && <>
            <Button size="sm" loading={approve.isPending && approve.variables?.id === x.id} onClick={() => approve.mutate(x)}><Check /> {x.status === 'AWAITING_MD' ? 'Release' : 'Approve'}</Button>
            <Button size="sm" variant="outline" className="text-danger" onClick={() => setRejecting(x)}><X /> Reject</Button>
          </>}
          {x.status === 'APPROVED' && can('bills.pay') && <Button size="sm" onClick={() => setPaying(x)}>Pay</Button>}
          {x.status === 'PAID' && x.entry_id && <Button size="icon-sm" variant="ghost" asChild><a href={voucherUrl(x.entry_id)} target="_blank" rel="noreferrer" aria-label={`Voucher for ${x.number}`} title="Print the voucher"><FileText /></a></Button>}
          {['PENDING', 'AWAITING_MD', 'APPROVED'].includes(x.status) && (x.requested_by === r?.me || r?.can_check) && (
            <Button size="sm" variant="ghost" loading={withdraw.isPending && withdraw.variables?.id === x.id} onClick={() => withdraw.mutate(x)}>Withdraw</Button>
          )}
        </div>
      ),
    },
  ]

  return (
    <>
      {r && !r.on && (
        <p className="mb-4 rounded-lg border border-border bg-muted/40 p-3 text-sm">
          Payments are made without approval. {r.master ? 'To have them checked by the accounts head (and the MD over a limit) before they go out, turn it on in Settings, Company, Payment approval.' : 'The Master can turn approval on in Settings.'}
        </p>
      )}
      {r?.on && <p className="mb-4 text-sm text-muted-foreground">{r.free_below > 0 ? `Payments over ${formatINR(r.free_below)} are approved` : 'Every payment is approved'} before it is made; over {formatINR(r.md_above)} the MD releases it as well.</p>}
      <StatGrid className="xl:grid-cols-4">
        <Stat label="With the accounts head" value={compactINR(s?.with_accounts)} loading={q.isPending} />
        <Stat label="With the MD" value={compactINR(s?.with_md)} loading={q.isPending} />
        <Stat label="Approved, to pay" value={compactINR(s?.to_pay)} tone={s?.to_pay ? 'warning' : undefined} loading={q.isPending} />
        <Stat label="Open requests" value={s?.open ?? 0} loading={q.isPending} />
      </StatGrid>
      <div className="mb-3 max-w-xs"><Tabs label="Requests" value={filter} onChange={setFilter} items={FILTERS} /></div>
      <DataTable label="Payment requests" rows={q.data?.requests ?? []} columns={columns} rowKey={(x) => x.id} loading={q.isPending}
        empty={filter === 'open' ? 'Nothing waiting. A payment sent for approval from a bill, an advance or an expense voucher shows here.' : 'No payment requests yet.'} />
      {paying && <PayRequestModal request={paying} onClose={() => setPaying(null)} />}
      <ConfirmDialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title={`Reject ${rejecting?.number ?? ''}?`}
        description={rejecting ? `${formatINR(rejecting.amount)} to ${rejecting.party_name}. Whoever asked sees why.` : undefined}
        confirmLabel="Reject" tone="danger" reason={{ label: 'Why is it rejected?', required: true }} loading={reject.isPending}
        onConfirm={(note) => { if (rejecting) reject.mutate({ x: rejecting, note }) }} />
    </>
  )
}

/** Pay an approved request: only how and when; what and to whom were approved. */
function PayRequestModal({ request: x, onClose }: { request: PaymentRequest; onClose: () => void }) {
  const accounts = useAccounts()
  const [amount, setAmount] = useState(x.amount)
  const [on, setOn] = useState(today())
  const [mode, setMode] = useState(x.mode || 'Bank transfer')
  const [ref, setRef] = useState('')
  const [account, setAccount] = useState(x.account_id ? String(x.account_id) : '')
  const save = useAction(() => payPaymentRequest(x.id, { paid_on: on, mode, reference: ref, account_id: Number(account) || null, amount }), {
    invalidate: [paymentKeys.all, ledgerKeys.all, ['owed'], ['money'], ['projects']],
    onSuccess: (res) => { onClose(); window.open(voucherUrl(res.entry.id), '_blank', 'noopener') },
  })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Pay ${x.number}`} description={`${x.party_name} · ${against(x)} · approved by ${x.approved_by_name || x.checked_by_name}`}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Amount" htmlFor="pr-amount" hint={`Approved: ${formatINR(x.amount)}`}><NumField id="pr-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="Date" htmlFor="pr-date"><Input id="pr-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Mode" htmlFor="pr-mode"><Select id="pr-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={PAY_MODES.map((m) => ({ value: m, label: m }))} /></Field>
        <Field label="UTR / cheque no." htmlFor="pr-ref" hint="Needed for a cheque."><Input id="pr-ref" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
        <Field label="Through account" htmlFor="pr-account" className="sm:col-span-2"><Select id="pr-account" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="Not recorded against an account" options={(accounts.data ?? []).map((a) => ({ value: a.id, label: `${a.name} (${a.kind}) - ${formatINR(a.balance)}` }))} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={amount <= 0 || amount > x.amount + 0.009} onClick={() => save.mutate()}>Pay {formatINR(amount)} and print the voucher</Button>
      </div>
    </Modal>
  )
}
