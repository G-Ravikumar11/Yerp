import { useMemo, useState } from 'react'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Field, Input, Modal, NumField, Select, Stat, StatGrid, Tabs } from '@/components/ui'
import { contractorBrief, type ContractorBrief } from '@/api/aiSubcontracts'
import { addDocument, cancelBackCharge, complianceKeys, raiseBackCharge, rateContractor, removeDocument, useBackCharges, useComplianceHome, useContractorDetail, useSettlement, type BackCharge, type ContractorStatus } from '@/api/compliance'
import { useOrders } from '@/api/orders'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

type Tab = 'papers' | 'charges' | 'settlement'
const TONE = { valid: 'success', expiring: 'warning', expired: 'danger', missing: 'danger' } as const

export default function CompliancePage() {
  const [tab, setTab] = useState<Tab>('papers')
  return (
    <>
      <PageHeader
        eyebrow="Subcontractors"
        title="Compliance & Settlement"
        description="Whether each contractor's papers are in order, what has been charged back to them, how they have performed, and where each order stands in money."
      />
      <div className="mb-5">
        <Tabs label="Compliance" value={tab} onChange={setTab} items={[{ value: 'papers', label: 'Papers & rating' }, { value: 'charges', label: 'Back-charges' }, { value: 'settlement', label: 'Order settlement' }]} />
      </div>
      {tab === 'papers' && <PapersTab />}
      {tab === 'charges' && <ChargesTab />}
      {tab === 'settlement' && <SettlementTab />}
    </>
  )
}

/* --- Papers ---------------------------------------------------------------- */

function PapersTab() {
  const home = useComplianceHome()
  const [open, setOpen] = useState<ContractorStatus | null>(null)
  const rows = home.data?.contractors ?? []
  const columns: TableColumn<ContractorStatus>[] = [
    { id: 'c', header: 'Contractor', sort: (r) => r.contractor, cell: (r) => <div><div className="font-medium">{r.contractor}</div><div className="font-mono text-xs text-muted-foreground">{r.vendor_code}</div></div> },
    { id: 'p', header: 'Papers', cell: (r) => <div className="flex flex-wrap gap-1">{r.required.map((d) => <Badge key={d.kind} tone={TONE[d.state]}>{d.label.split(' ')[0]} {d.state}</Badge>)}</div> },
    { id: 's', header: 'Rating', hideBelow: 'md', align: 'right', sort: (r) => r.score.overall ?? 0, cell: (r) => (r.score.overall ? `${r.score.overall} / 5 (${r.score.count})` : 'not rated') },
    { id: 'o', header: 'Safe to pay', cell: (r) => <Badge tone={r.ok ? 'success' : 'danger'}>{r.ok ? 'Yes' : 'No'}</Badge> },
  ]
  return (
    <>
      <StatGrid className="xl:grid-cols-3">
        <Stat label="Contractors" value={rows.length} loading={home.isPending} />
        <Stat label="Papers in order" value={rows.filter((r) => r.ok).length} loading={home.isPending} />
        <Stat label="Papers missing or lapsed" value={rows.filter((r) => !r.ok).length} tone={rows.some((r) => !r.ok) ? 'danger' : undefined} loading={home.isPending} />
      </StatGrid>
      <DataTable label="Contractor compliance" rows={rows} columns={columns} rowKey={(r) => r.contractor_id} loading={home.isPending} onRowClick={setOpen} empty="No contractors yet. Register one in the Vendor Register." />
      {open && <ContractorModal contractor={open} kinds={home.data?.kinds ?? {}} onClose={() => setOpen(null)} />}
    </>
  )
}

function ContractorModal({ contractor, kinds, onClose }: { contractor: ContractorStatus; kinds: Record<string, string>; onClose: () => void }) {
  const { can } = useSession()
  const q = useContractorDetail(contractor.contractor_id)
  const [kind, setKind] = useState('labour_licence')
  const [number, setNumber] = useState('')
  const [until, setUntil] = useState('')
  const [score, setScore] = useState({ quality: 3, speed: 3, safety: 3, discipline: 3 })
  const manage = can('billing.manage')
  const [brief, setBrief] = useState<ContractorBrief | null>(null)
  const askBrief = useAction(() => contractorBrief(contractor.contractor_id), { success: false, onSuccess: setBrief })
  const add = useAction(() => addDocument({ contractor_id: contractor.contractor_id, kind, number, valid_to: until }), { invalidate: [complianceKeys.all], onSuccess: () => { setNumber(''); setUntil('') } })
  const drop = useAction((id: number) => removeDocument(id), { invalidate: [complianceKeys.all] })
  const rate = useAction(() => rateContractor({ contractor_id: contractor.contractor_id, ...score }), { invalidate: [complianceKeys.all] })
  const d = q.data
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg" title={contractor.contractor} description="The papers they must hold, and how their work has been rated.">
      <div className="grid gap-5">
        {d?.warnings.length ? <ul className="grid gap-1 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">{d.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : <p className="text-sm text-muted-foreground">All required papers are in order.</p>}
        <table aria-label="Papers on record" className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase text-muted-foreground"><th className="py-1">Paper</th><th>Number</th><th>Valid until</th><th /><th /></tr></thead>
          <tbody>
            {(d?.documents ?? []).map((x) => (
              <tr key={x.id} className="border-t border-border">
                <td className="py-1.5">{x.kind_label}</td><td className="font-mono text-xs">{x.number || '-'}</td><td>{formatDate(x.valid_to)}</td>
                <td><Badge tone={TONE[x.state]}>{x.state === 'expiring' ? `${x.days_left} days left` : x.state}</Badge></td>
                <td className="text-right">{manage && <Button size="sm" variant="ghost" onClick={() => drop.mutate(x.id)}>Remove</Button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {manage && (
          <div className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
            <Field label="Paper" htmlFor="cd-kind"><Select id="cd-kind" value={kind} onChange={(e) => setKind(e.target.value)} options={Object.entries(kinds).map(([value, label]) => ({ value, label }))} /></Field>
            <Field label="Number" htmlFor="cd-number"><Input id="cd-number" value={number} onChange={(e) => setNumber(e.target.value)} /></Field>
            <Field label="Valid until" htmlFor="cd-until"><Input id="cd-until" type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></Field>
            <Button loading={add.isPending} disabled={!until} onClick={() => add.mutate()}><Plus /> Add</Button>
          </div>
        )}
        <div className="border-t border-border pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Standing for the next order</h3>
            <Button size="sm" variant="outline" loading={askBrief.isPending} onClick={() => askBrief.mutate()}>Get a brief</Button>
          </div>
          {brief && (
            <div aria-label="Contractor brief" className="mt-2 grid gap-1 text-sm">
              <p><Badge tone={brief.standing.verdict === 'careful' ? 'danger' : brief.standing.verdict === 'good' ? 'success' : 'neutral'}>{brief.standing.verdict}</Badge> {brief.standing.orders} order(s), {brief.standing.certified_bills} certified bill(s), {formatINR(brief.standing.work_certified)} of work, {formatINR(brief.standing.back_charged)} charged back.</p>
              {brief.standing.flags.length > 0 && <p className="text-warning">{brief.standing.flags.join('; ')}.</p>}
              {brief.summary ? <p>{brief.summary}</p> : <p className="text-muted-foreground">{brief.ai_message ?? 'The written summary needs the AI key; the figures above are from the books.'}</p>}
            </div>
          )}
        </div>
        <div className="border-t border-border pt-4">
          <h3 className="mb-2 text-sm font-semibold">Rate their work {d?.score.overall ? <span className="font-normal text-muted-foreground">(average {d.score.overall} of {d.score.count})</span> : null}</h3>
          <div className="grid gap-3 sm:grid-cols-4">
            {(['quality', 'speed', 'safety', 'discipline'] as const).map((f) => (
              <Field key={f} label={f[0].toUpperCase() + f.slice(1)} htmlFor={`rt-${f}`}>
                <Select id={`rt-${f}`} value={String(score[f])} onChange={(e) => setScore({ ...score, [f]: Number(e.target.value) })} options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} />
              </Field>
            ))}
          </div>
          {manage && <Button className="mt-3" variant="outline" loading={rate.isPending} onClick={() => rate.mutate()}>Save rating</Button>}
        </div>
      </div>
    </Modal>
  )
}

/* --- Back-charges ---------------------------------------------------------- */

const CHARGE_TONE = { OPEN: 'warning', APPLIED: 'success', CANCELLED: 'neutral' } as const

function ChargesTab() {
  const { can } = useSession()
  const [status, setStatus] = useState('')
  const charges = useBackCharges(status)
  const [raising, setRaising] = useState(false)
  const cancel = useAction((id: number) => cancelBackCharge(id), { invalidate: [complianceKeys.all] })
  const rows = charges.data?.back_charges ?? []
  const columns: TableColumn<BackCharge>[] = [
    { id: 'n', header: 'No.', cell: (r) => <span className="font-mono text-[13px]">{r.number}</span> },
    { id: 'c', header: 'Contractor', sort: (r) => r.contractor, cell: (r) => r.contractor },
    { id: 'k', header: 'For', hideBelow: 'md', cell: (r) => <div><div>{r.kind}</div><div className="text-xs text-muted-foreground">{r.reason}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', sort: (r) => r.amount, cell: (r) => formatINR(r.amount) },
    { id: 's', header: 'Status', cell: (r) => <div><Badge tone={CHARGE_TONE[r.status]}>{r.status === 'APPLIED' ? `on ${r.applied_bill}` : r.status.toLowerCase()}</Badge></div> },
    { id: 'x', header: '', align: 'right', cell: (r) => (r.status === 'OPEN' && can('billing.manage') ? <Button size="sm" variant="ghost" onClick={() => cancel.mutate(r.id)}>Cancel</Button> : null) },
  ]
  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="w-48"><Select aria-label="Show" value={status} onChange={(e) => setStatus(e.target.value)} options={[{ value: '', label: 'All' }, { value: 'OPEN', label: 'Open' }, { value: 'APPLIED', label: 'On a bill' }, { value: 'CANCELLED', label: 'Cancelled' }]} /></div>
        {can('billing.manage') && <Button onClick={() => setRaising(true)}><Plus /> Raise back-charge</Button>}
      </div>
      <DataTable label="Back-charges" rows={rows} columns={columns} rowKey={(r) => r.id} loading={charges.isPending} empty="Nothing has been charged back. A back-charge is taken off the contractor's next bill." />
      {raising && <RaiseModal onClose={() => setRaising(false)} />}
    </>
  )
}

function RaiseModal({ onClose }: { onClose: () => void }) {
  const home = useComplianceHome()
  const orders = useOrders()
  const [contractor, setContractor] = useState('')
  const [order, setOrder] = useState('')
  const [kind, setKind] = useState('Wastage')
  const [reason, setReason] = useState('')
  const [amount, setAmount] = useState(0)
  const mine = useMemo(() => (orders.data?.orders ?? []).filter((o) => String(o.contractor_id) === contractor), [orders.data, contractor])
  const go = useAction(() => raiseBackCharge({ contractor_id: Number(contractor), order_id: order ? Number(order) : null, kind, reason, amount }), { invalidate: [complianceKeys.all], onSuccess: onClose })
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="md" title="Raise a back-charge" description="It is taken off this contractor's next draft bill, with the reason printed on it."
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button loading={go.isPending} disabled={!contractor || !reason.trim() || amount <= 0} onClick={() => go.mutate()}>Raise it</Button></>}>
      <div className="grid gap-4">
        <Field label="Contractor" htmlFor="bc-con"><Select id="bc-con" value={contractor} onChange={(e) => { setContractor(e.target.value); setOrder('') }} placeholder="Choose the contractor" options={(home.data?.contractors ?? []).map((c) => ({ value: String(c.contractor_id), label: c.contractor }))} /></Field>
        <Field label="Order (optional)" htmlFor="bc-order"><Select id="bc-order" value={order} onChange={(e) => setOrder(e.target.value)} placeholder="Not tied to one order" options={mine.map((o) => ({ value: String(o.id), label: o.wo_number }))} /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Kind" htmlFor="bc-kind"><Select id="bc-kind" value={kind} onChange={(e) => setKind(e.target.value)} options={(home.data?.back_charge_kinds ?? ['Wastage']).map((k) => ({ value: k, label: k }))} /></Field>
          <Field label="Amount (₹)" htmlFor="bc-amount"><NumField id="bc-amount" value={amount} onValue={setAmount} /></Field>
        </div>
        <Field label="What it is for" htmlFor="bc-reason"><Input id="bc-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Cement wasted beyond the allowance in March" /></Field>
      </div>
    </Modal>
  )
}

/* --- Settlement ------------------------------------------------------------ */

function SettlementTab() {
  const orders = useOrders()
  const [order, setOrder] = useState('')
  const s = useSettlement(Number(order) || 0)
  const d = s.data
  return (
    <>
      <div className="mb-4 max-w-md"><Select aria-label="Order" value={order} onChange={(e) => setOrder(e.target.value)} placeholder="Choose an order" options={(orders.data?.orders ?? []).map((o) => ({ value: String(o.id), label: `${o.wo_number} - ${o.contractor}` }))} /></div>
      {!d ? <p className="text-sm text-muted-foreground">Choose an order to see where it stands.</p> : (
        <>
          <StatGrid className="xl:grid-cols-4">
            <Stat label="Work certified" value={formatINR(d.work_certified)} />
            <Stat label="Certified, net of deductions" value={formatINR(d.certified_net)} />
            <Stat label="Paid" value={formatINR(d.paid)} />
            <Stat label="Still to pay" value={formatINR(d.still_to_pay)} tone={d.still_to_pay > 0.5 ? 'warning' : undefined} />
            <Stat label="Retention held" value={formatINR(d.retention_balance)} />
            <Stat label="Advance outstanding" value={formatINR(d.advance_outstanding)} tone={d.advance_outstanding > 0.5 ? 'warning' : undefined} />
            <Stat label="Back-charges on bills" value={formatINR(d.back_charges_applied)} />
            <Stat label="Back-charges still open" value={formatINR(d.back_charges_open)} tone={d.back_charges_open > 0 ? 'warning' : undefined} />
          </StatGrid>
          <p className="mt-4 text-sm">
            {d.can_close ? <Badge tone="success">Nothing is owed on this order</Badge> : <Badge tone="warning">Not ready to close</Badge>}{' '}
            <span className="text-muted-foreground">{d.open_bills ? `${d.open_bills} bill(s) not yet certified. ` : ''}{d.still_to_pay > 0.5 ? 'Certified money is still unpaid. ' : ''}{d.back_charges_open > 0 ? 'Open back-charges are waiting for a bill.' : ''}</span>
          </p>
        </>
      )}
    </>
  )
}
