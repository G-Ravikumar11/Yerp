import { useMemo, useRef, useState } from 'react'
import { Camera, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { attachClaimPhoto, cancelClaim, claimAgainstAdvance, decideClaim, payoutKeys, submitClaim, useClaims, type Claim } from '@/api/payouts'
import { useMoneyHeads } from '@/api/ledger'
import { owedKeys } from '@/api/owed'
import { projectLabel, useProjects } from '@/api/projects'
import { useEmployees } from '@/api/people'
import { PayModal } from '@/features/money/PayModal'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const TONE = { SUBMITTED: 'warning', APPROVED: 'info', SETTLED: 'success', REJECTED: 'danger', CANCELLED: 'neutral' } as const
const LABEL = { SUBMITTED: 'Waiting for accounts', APPROVED: 'Approved - to be paid', SETTLED: 'Settled', REJECTED: 'Sent back', CANCELLED: 'Withdrawn' } as const
const INVALIDATE = [payoutKeys.all, owedKeys.all, ['ledger'], ['approvals'], ['projects']]

/** A member of staff's own claims: money they spent for the company, claimed back with the bill. */
export default function MyClaimsPage() {
  return (
    <>
      <PageHeader eyebrow="My work" title="Expense Claims"
        description="Money you spent yourself for the company - a bus fare, a meal on site, a part bought in town. Claim it with a photo of the bill; once accounts approve it, it is paid back or set against an advance you hold." />
      <ClaimsPanel mine />
    </>
  )
}

/** The claims list: a person's own (mine), or everybody's for accounts to check, pay or set against an advance. */
export function ClaimsPanel({ mine = false }: { mine?: boolean }) {
  const { can } = useSession()
  const q = useClaims(mine)
  const [making, setMaking] = useState(false)
  const [rejecting, setRejecting] = useState<Claim | null>(null)
  const [paying, setPaying] = useState<Claim | null>(null)
  const decide = useAction((v: { id: number; decision: 'approve' | 'reject'; note?: string }) => decideClaim(v.id, v.decision, v.note), { invalidate: INVALIDATE, onSuccess: () => setRejecting(null) })
  const setOff = useAction((id: number) => claimAgainstAdvance(id), { invalidate: INVALIDATE })
  const withdraw = useAction((id: number) => cancelClaim(id), { invalidate: INVALIDATE })
  const checker = !mine && !!q.data?.can_decide
  const me = q.data?.me

  const cols: TableColumn<Claim>[] = [
    { id: 'n', header: 'Claim', cell: (r) => <div><div className="font-mono text-xs font-medium">{r.number}</div><div className="text-xs text-muted-foreground">{formatDate(r.spent_on)}</div></div> },
    ...(mine ? [] : [{ id: 'who', header: 'Who', cell: (r: Claim) => r.employee_name } as TableColumn<Claim>]),
    { id: 'w', header: 'What', cell: (r) => <div className="max-w-sm"><div className="truncate">{r.description}</div><div className="truncate text-xs text-muted-foreground">{r.head}{r.project ? ` - ${r.project}` : ''}</div></div> },
    { id: 'a', header: 'Amount', align: 'right', cell: (r) => <div className="tabular-nums"><div className="font-semibold">{formatINR(r.amount)}</div>{r.against_advance > 0 && <div className="text-xs text-muted-foreground">{formatINR(r.against_advance)} off advance</div>}</div> },
    {
      id: 'b', header: 'Bill', hideBelow: 'sm',
      cell: (r) => r.photos.length ? <Button size="icon-sm" variant="ghost" asChild><a href={`/api/files/${r.photos[0].id}`} target="_blank" rel="noreferrer" aria-label={`Bill for ${r.number}`}><Camera /></a></Button>
        : r.status === 'SUBMITTED' && (mine || checker) ? <PhotoButton id={r.id} /> : <span className="text-xs text-muted-foreground">no photo</span>,
    },
    { id: 's', header: 'Status', cell: (r) => <Badge tone={TONE[r.status]} title={r.decision_note || undefined}>{LABEL[r.status]}</Badge> },
    {
      id: 'x', header: '', align: 'right',
      cell: (r) => (
        <div className="flex justify-end gap-1">
          {checker && r.status === 'SUBMITTED' && r.employee_id !== me && <Button size="sm" loading={decide.isPending && decide.variables?.id === r.id} onClick={() => decide.mutate({ id: r.id, decision: 'approve' })}>Approve</Button>}
          {checker && r.status === 'SUBMITTED' && r.employee_id !== me && <Button size="sm" variant="outline" onClick={() => setRejecting(r)}>Send back</Button>}
          {!mine && r.status === 'APPROVED' && can('bills.pay') && <Button size="sm" onClick={() => setPaying(r)}>Pay</Button>}
          {!mine && r.status === 'APPROVED' && can('bills.pay') && <Button size="sm" variant="outline" loading={setOff.isPending && setOff.variables === r.id} onClick={() => setOff.mutate(r.id)}>Off advance</Button>}
          {r.status === 'SUBMITTED' && r.employee_id === me && <Button size="sm" variant="ghost" loading={withdraw.isPending} onClick={() => withdraw.mutate(r.id)}>Withdraw</Button>}
        </div>
      ),
    },
  ]
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{mine ? 'Claims you have made.' : 'Claims from staff. Approved, a claim is owed to them and charged to its project; pay it, or set it against an advance they hold.'}</p>
        {(mine || can('bills.pay')) && <Button onClick={() => setMaking(true)}><Plus /> New claim</Button>}
      </div>
      <DataTable label="Expense claims" rows={q.data?.claims ?? []} columns={cols} rowKey={(r) => r.id} loading={q.isPending}
        empty={mine ? 'No claims yet. Spent your own money for the company? Claim it here with the bill.' : 'No expense claims.'} />
      {making && <ClaimModal forSomeone={!mine} onClose={() => setMaking(false)} />}
      <ConfirmDialog open={!!rejecting} onOpenChange={(o) => !o && setRejecting(null)} title={`Send ${rejecting?.number ?? ''} back`} confirmLabel="Send back" tone="danger"
        reason={{ label: 'Why', required: true }} loading={decide.isPending} onConfirm={(note) => { if (rejecting) decide.mutate({ id: rejecting.id, decision: 'reject', note }) }} />
      {paying && <PayModal docType="expense_claim" docId={paying.id} title={`${paying.number} - ${paying.employee_name}`} open onOpenChange={(o) => !o && setPaying(null)} invalidate={INVALIDATE} />}
    </>
  )
}

function PhotoButton({ id }: { id: number }) {
  const ref = useRef<HTMLInputElement>(null)
  const up = useAction((f: File) => attachClaimPhoto(id, f), { invalidate: [payoutKeys.all] })
  return (
    <>
      <input ref={ref} type="file" accept="image/*,application/pdf" capture="environment" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f) }} />
      <Button size="sm" variant="outline" loading={up.isPending} onClick={() => ref.current?.click()}><Camera /> Add bill</Button>
    </>
  )
}

function ClaimModal({ forSomeone, onClose }: { forSomeone: boolean; onClose: () => void }) {
  const heads = useMoneyHeads()
  const projects = useProjects()
  const people = useEmployees('active')
  const [f, setF] = useState({ spent_on: today(), head: 'Travel & conveyance', job_id: 0, amount: 0, description: '', bill_no: '', employee_id: 0 })
  const [file, setFile] = useState<File | null>(null)
  const save = useAction(async () => {
    const c = await submitClaim({ ...f, job_id: f.job_id || null, employee_id: forSomeone ? f.employee_id : undefined })
    if (file) await attachClaimPhoto(c.id, file)
    return c
  }, { invalidate: INVALIDATE, onSuccess: onClose })
  const sites = useMemo(() => (projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) })), [projects.data])
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New expense claim" size="md"
      footer={<><Button variant="ghost" onClick={onClose}>Not now</Button>
        <Button loading={save.isPending} disabled={f.amount <= 0 || f.description.trim().length < 3 || (forSomeone && !f.employee_id)} onClick={() => save.mutate()}>Claim {formatINR(f.amount)}</Button></>}>
      <div className="grid gap-3 sm:grid-cols-2">
        {forSomeone && <Field label="Whose claim" className="sm:col-span-2"><Select value={f.employee_id || ''} onChange={(e) => setF((s) => ({ ...s, employee_id: Number(e.target.value) }))} placeholder="Choose a member of staff"
          options={(people.data ?? []).map((p) => ({ value: p.id, label: `${p.first_name} ${p.last_name}`.trim() }))} /></Field>}
        <Field label="Spent on"><Input type="date" value={f.spent_on} max={today()} onChange={(e) => setF((s) => ({ ...s, spent_on: e.target.value }))} /></Field>
        <Field label="Amount"><NumField value={f.amount} onValue={(n) => setF((s) => ({ ...s, amount: n }))} /></Field>
        <Field label="For"><Select value={f.head} onChange={(e) => setF((s) => ({ ...s, head: e.target.value }))} options={(heads.data?.expense ?? []).map((h) => ({ value: h, label: h }))} /></Field>
        <Field label="Project"><Select value={f.job_id || ''} onChange={(e) => setF((s) => ({ ...s, job_id: Number(e.target.value) }))} placeholder="Head office" options={sites} /></Field>
        <Field label="What was it" className="sm:col-span-2"><Input value={f.description} onChange={(e) => setF((s) => ({ ...s, description: e.target.value }))} placeholder="Bus from Vizag to site and back" /></Field>
        <Field label="Bill no."><Input value={f.bill_no} onChange={(e) => setF((s) => ({ ...s, bill_no: e.target.value }))} /></Field>
        <Field label="Photo of the bill"><Input type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
      </div>
    </Modal>
  )
}
