import { useRef, useState } from 'react'
import { Camera, Check, FileText, Plus, Printer, Settings2, Wallet, X } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, ConfirmDialog, Field, Input, Modal, NumField, Select, Tabs } from '@/components/ui'
import { ledgerKeys, useMoneyHeads, voucherUrl } from '@/api/ledger'
import { useEmployees } from '@/api/people'
import { projectLabel, useProjects } from '@/api/projects'
import {
  attachBillPhoto, cashStatementUrl, decideSiteExpense, setCashBox, siteCashKeys, spendSiteCash, useSiteCash,
  type CashBox, type SiteExpense, type SiteExpenseStatus,
} from '@/api/sitecash'
import { TransferModal } from '@/features/ledger/VoucherModals'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

const TONE: Record<SiteExpenseStatus, 'warning' | 'success' | 'danger'> = { SUBMITTED: 'warning', APPROVED: 'success', REJECTED: 'danger' }
const LABEL: Record<SiteExpenseStatus, string> = { SUBMITTED: 'Waiting for accounts', APPROVED: 'Booked', REJECTED: 'Not accepted' }
const FILTERS = [{ value: 'SUBMITTED', label: 'Waiting' }, { value: '', label: 'All' }]

/**
 * Site cash (imprest). The site engineer enters each payment out of the box from site, with a photo of the bill;
 * accounts check it and it is booked against the site; head office tops the box back up to its float.
 * The same page for both: accounts see every box, a site engineer the one they hold.
 */
export default function SiteCashPage() {
  const [filter, setFilter] = useState('SUBMITTED')
  const q = useSiteCash(filter)
  const d = q.data
  const [spending, setSpending] = useState<CashBox | null>(null)
  const [setting, setSetting] = useState<CashBox | null>(null)
  const [topping, setTopping] = useState<CashBox | null>(null)
  const [rejecting, setRejecting] = useState<SiteExpense | null>(null)
  const done = { invalidate: [siteCashKeys.all, ledgerKeys.all, ['approvals'], ['projects']] }
  const accept = useAction((x: SiteExpense) => decideSiteExpense(x.id, 'approve'), done)
  const reject = useAction((a: { x: SiteExpense; note: string }) => decideSiteExpense(a.x.id, 'reject', a.note), { ...done, onSuccess: () => setRejecting(null) })
  const boxName = (id: number) => d?.boxes.find((b) => b.id === id)?.name ?? ''

  const columns: TableColumn<SiteExpense>[] = [
    { id: 'date', header: 'Spent', sort: (x) => x.spent_on, cell: (x) => <div>{formatDate(x.spent_on)}<div className="font-mono text-xs text-muted-foreground">{x.number}</div></div> },
    { id: 'what', header: 'What', cell: (x) => <div>{x.head}<div className="text-xs text-muted-foreground">{x.paid_to}{x.bill_no && ` · bill ${x.bill_no}`}</div>{x.note && <div className="max-w-64 truncate text-xs text-muted-foreground" title={x.note}>{x.note}</div>}</div> },
    { id: 'box', header: 'Cash box', hideBelow: 'md', cell: (x) => <div className="text-[13px]">{boxName(x.account_id)}<div className="text-xs text-muted-foreground">{x.submitted_by_name}</div></div> },
    { id: 'amount', header: 'Amount', align: 'right', cell: (x) => <span className="font-semibold tabular-nums">{formatINR(x.amount)}</span> },
    {
      id: 'status', header: '', cell: (x) => (
        <div>
          <Badge tone={TONE[x.status]} dot>{LABEL[x.status]}</Badge>
          {x.status === 'REJECTED' && <div className="mt-0.5 max-w-48 text-xs text-danger">{x.checked_by_name}: {x.reject_reason}</div>}
          {x.status === 'APPROVED' && <div className="mt-0.5 text-xs text-muted-foreground">by {x.checked_by_name}</div>}
        </div>
      ),
    },
    {
      id: 'act', header: '', align: 'right', cell: (x) => (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {x.photo ? <Button size="icon-sm" variant="ghost" asChild><a href={`/api/files/${x.photo.id}`} target="_blank" rel="noreferrer" aria-label={`Bill for ${x.number}`} title="The bill"><Camera /></a></Button>
            : x.status === 'SUBMITTED' && <PhotoButton expense={x} />}
          {x.entry_id && <Button size="icon-sm" variant="ghost" asChild><a href={voucherUrl(x.entry_id)} target="_blank" rel="noreferrer" aria-label={`Voucher for ${x.number}`} title="The expense voucher"><FileText /></a></Button>}
          {d?.manage && x.status === 'SUBMITTED' && (d.me === null ? !x.submitted_by_master : x.submitted_by !== d.me) && <>
            <Button size="sm" loading={accept.isPending && accept.variables?.id === x.id} disabled={!!x.bill_needed && !x.photo} title={x.bill_needed && !x.photo ? 'Add the photo of the bill first' : undefined} onClick={() => accept.mutate(x)}><Check /> Accept</Button>
            <Button size="sm" variant="outline" className="text-danger" onClick={() => setRejecting(x)}><X /> Reject</Button>
          </>}
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader eyebrow={d?.manage ? 'Accounts' : 'My work'} title="Site Cash"
        description={d?.manage ? 'Each site’s cash box: what it should hold, what the site has spent and is waiting to be checked, and what tops it back up.'
          : 'The cash box you hold for the site. Enter each payment as you make it, with a photo of the bill; accounts check it.'} />
      {q.isPending ? null : !d?.boxes.length ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">
          {d?.manage ? 'No cash boxes yet. Add one for each site under Payments & Ledgers, Bank book ("Bank account or cash box", kind Cash), then set its site, who holds it and its float here.'
            : 'You do not hold a site cash box. Accounts set one up for you.'}
        </p>
      ) : (
        <div className="mb-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {d.boxes.map((b) => (
            <Card key={b.id} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 font-semibold"><Wallet className="size-4 text-primary" />{b.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{b.project || 'No site set'}{b.custodian && ` · held by ${b.custodian}`}</p>
                </div>
                {d.manage && <Button size="icon-sm" variant="ghost" aria-label={`Set up ${b.name}`} title="Site, custodian and float" onClick={() => setSetting(b)}><Settings2 /></Button>}
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">Should be in hand</dt><dd className="text-right text-base font-semibold tabular-nums">{formatINR(b.in_hand)}</dd>
                <dt className="text-muted-foreground">In the books</dt><dd className="text-right tabular-nums">{formatINR(b.balance)}</dd>
                <dt className="text-muted-foreground">Waiting to be checked</dt><dd className={`text-right tabular-nums ${b.pending ? 'text-warning' : ''}`}>{formatINR(b.pending)}</dd>
                <dt className="text-muted-foreground">Float</dt><dd className="text-right tabular-nums">{b.imprest_amount ? formatINR(b.imprest_amount) : '-'}</dd>
              </dl>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button size="sm" onClick={() => setSpending(b)}><Plus /> Spent</Button>
                {d.manage && <Button size="sm" variant="outline" onClick={() => setTopping(b)}>Top up{b.top_up ? ` ${formatINR(b.top_up)}` : ''}</Button>}
                <Button size="sm" variant="ghost" asChild><a href={cashStatementUrl(b.id)} target="_blank" rel="noreferrer"><Printer /> Cash book</a></Button>
              </div>
            </Card>
          ))}
        </div>
      )}
      {!!d?.boxes.length && <>
        <div className="mb-3 max-w-xs"><Tabs label="Site expenses" value={filter} onChange={setFilter} items={FILTERS} /></div>
        <DataTable label="Site expenses" rows={d.expenses} columns={columns} rowKey={(x) => x.id} loading={q.isPending}
          empty={filter === 'SUBMITTED' ? 'Nothing waiting to be checked.' : 'Nothing spent out of the boxes yet.'} />
      </>}
      {spending && <SpendModal box={spending} onClose={() => setSpending(null)} />}
      {setting && <BoxModal box={setting} onClose={() => setSetting(null)} />}
      <TransferModal open={!!topping} onClose={() => setTopping(null)} invalidate={[siteCashKeys.all]}
        defaults={topping ? { to: topping.id, amount: topping.top_up, note: `Top-up for ${topping.name}` } : undefined} />
      <ConfirmDialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title={`Not accept ${rejecting?.number ?? ''}?`}
        description={rejecting ? `${formatINR(rejecting.amount)} to ${rejecting.paid_to}. It is not booked, and ${rejecting.submitted_by_name || 'the custodian'} accounts for the cash.` : undefined}
        confirmLabel="Reject" tone="danger" reason={{ label: 'Why is it not accepted?', required: true }} loading={reject.isPending}
        onConfirm={(note) => { if (rejecting) reject.mutate({ x: rejecting, note }) }} />
    </>
  )
}

/** A photo of the bill, taken on site after the expense was entered. */
function PhotoButton({ expense }: { expense: SiteExpense }) {
  const ref = useRef<HTMLInputElement>(null)
  const add = useAction((f: File) => attachBillPhoto(expense.id, f), { invalidate: [siteCashKeys.all] })
  return (
    <>
      <input ref={ref} type="file" hidden accept="image/*,application/pdf" capture="environment" aria-label={`Photo of the bill for ${expense.number}`}
        onChange={(e) => { const f = e.target.files?.[0]; if (f) add.mutate(f); e.target.value = '' }} />
      <Button size="icon-sm" variant="ghost" loading={add.isPending} aria-label={`Add the bill for ${expense.number}`} title="Add a photo of the bill" onClick={() => ref.current?.click()}><Camera className="text-warning" /></Button>
    </>
  )
}

/** A payment made out of the box, entered as it was made, with the bill. */
function SpendModal({ box, onClose }: { box: CashBox; onClose: () => void }) {
  const heads = useMoneyHeads()
  const list = heads.data?.expense ?? []
  const [head, setHead] = useState('')
  const [paidTo, setPaidTo] = useState('')
  const [amount, setAmount] = useState(0)
  const [on, setOn] = useState(today())
  const [billNo, setBillNo] = useState('')
  const [note, setNote] = useState('')
  const [photo, setPhoto] = useState<File | null>(null)
  const save = useAction(async () => {
    const r = await spendSiteCash({ account_id: box.id, amount, head: head || list[0] || '', paid_to: paidTo.trim(), spent_on: on, note, bill_no: billNo })
    if (photo) {
      try { await attachBillPhoto(r.expense.id, photo) } catch { toast.error('Saved, but the photo did not go up. Add it again from the list.') }
    }
    return r
  }, { invalidate: [siteCashKeys.all], onSuccess: (r) => { if (r.warning) toast.info(r.warning); onClose() } })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Spent from ${box.name}`} description={`${formatINR(box.in_hand)} should be in hand. Accounts check each payment against its bill before it is booked to ${box.project || 'the site'}.`}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="What for" htmlFor="sc-head"><Select id="sc-head" value={head || list[0] || ''} onChange={(e) => setHead(e.target.value)} options={list.map((h) => ({ value: h, label: h }))} /></Field>
        <Field label="Paid to" htmlFor="sc-to"><Input id="sc-to" value={paidTo} onChange={(e) => setPaidTo(e.target.value)} placeholder="HP pump, Gajuwaka" autoFocus /></Field>
        <Field label="Amount" htmlFor="sc-amount"><NumField id="sc-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="Date" htmlFor="sc-date"><Input id="sc-date" type="date" max={today()} value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Bill no." htmlFor="sc-bill" hint="Optional"><Input id="sc-bill" value={billNo} onChange={(e) => setBillNo(e.target.value)} /></Field>
        <Field label="Photo of the bill" htmlFor="sc-photo" hint={photo ? photo.name : 'From the camera or a file'}>
          <Input id="sc-photo" type="file" accept="image/*,application/pdf" capture="environment" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Details" htmlFor="sc-note" className="sm:col-span-2"><Input id="sc-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="JCB 3DX, 50 litres" /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!paidTo.trim() || amount <= 0 || !list.length} onClick={() => save.mutate()}>Send to accounts</Button>
      </div>
    </Modal>
  )
}

/** A cash box made a site's imprest: the site, who holds it, and the float it is kept at. */
function BoxModal({ box, onClose }: { box: CashBox; onClose: () => void }) {
  const projects = useProjects()
  const people = useEmployees('active')
  const [job, setJob] = useState(box.job_id ? String(box.job_id) : '')
  const [who, setWho] = useState(box.custodian_id ? String(box.custodian_id) : '')
  const [float, setFloat] = useState(box.imprest_amount)
  const save = useAction(() => setCashBox(box.id, { job_id: Number(job) || null, custodian_id: Number(who) || null, imprest_amount: float }), { invalidate: [siteCashKeys.all], onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Set up ${box.name}`} description="The site this cash is for, the member of staff who holds it (they see it under My work, Site Cash), and the float it is topped back up to.">
      <div className="grid gap-4">
        <Field label="Site" htmlFor="bx-job"><Select id="bx-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder="No site" options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Held by" htmlFor="bx-who"><Select id="bx-who" value={who} onChange={(e) => setWho(e.target.value)} placeholder="Nobody yet" options={(people.data ?? []).map((e) => ({ value: e.id, label: e.full_name || e.email }))} /></Field>
        <Field label="Float (imprest)" htmlFor="bx-float" hint="What the box is topped back up to"><NumField id="bx-float" value={float} onValue={setFloat} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </Modal>
  )
}
