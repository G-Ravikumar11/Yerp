import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Copy, Download, FileText, Save, Trash2 } from 'lucide-react'
import { Badge, Button, ConfirmDialog, Skeleton, Stat, StatGrid, StatusBadge, Tabs } from '@/components/ui'
import {
  copyOrder,
  moveOrder,
  orderKeys,
  saveHead,
  saveSchedule,
  saveTerms,
  useOrder,
  useOrderVocabulary,
  type Move,
  type Order,
  type OrderTerm,
} from '@/api/orders'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { ApiError } from '@/lib/api'
import { DeleteOrderDialog } from '@/features/deleteorder/DeleteOrderDialog'
import { ApprovalTab } from './ApprovalTab'
import { CostCentreModal } from './CostCentreModal'
import { HeadForm, headFrom } from './HeadForm'
import { linesFrom, ScheduleTab, toPayload } from './ScheduleTab'
import { TermsTab } from './TermsTab'

type Tab = 'details' | 'schedule' | 'terms' | 'approval'

export default function OrderPage() {
  const { id } = useParams()
  const order = useOrder(Number(id))
  const [seed, setSeed] = useState(0)

  if (order.isPending) {
    return (
      <div className="space-y-4" role="status" aria-label="Loading">
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    )
  }
  if (order.isError || !order.data) {
    return (
      <div className="mx-auto max-w-md py-20 text-center">
        <h1 className="text-2xl font-semibold">{order.error instanceof ApiError && order.error.status === 404 ? 'No such work order' : 'Could not open it'}</h1>
        <p className="mt-2 text-muted-foreground">{order.error instanceof ApiError ? order.error.message : 'Try again in a moment.'}</p>
        <Button asChild className="mt-6">
          <Link to="/subcontractors/work-orders">Back to work orders</Link>
        </Button>
      </div>
    )
  }
  // Remounted after every save or move, so the form always starts from what the server now holds.
  return <OrderEditor key={`${order.data.id}:${seed}`} order={order.data} reseed={() => setSeed((s) => s + 1)} />
}

const MOVE_LABEL: Record<string, string> = { SUBMIT: 'Submit for approval', APPROVE: 'Approve', REJECT: 'Send back', EXECUTE: 'Mark as executed', AMEND: 'Amend', CANCEL: 'Cancel order' }

function OrderEditor({ order, reseed }: { order: Order; reseed: () => void }) {
  const nav = useNavigate()
  const { can, isOwner } = useSession()
  const [deleting, setDeleting] = useState(false)
  const vocab = useOrderVocabulary()

  const [tab, setTab] = useState<Tab>('details')
  const [head, setHead] = useState(() => headFrom(order))
  const [lines, setLines] = useState(() => linesFrom(order))
  const [terms, setTerms] = useState<OrderTerm[]>(() => (order.terms ?? []).map((t) => ({ clause_category: t.clause_category, clause_text: t.clause_text })))
  const [dialog, setDialog] = useState<'approve' | 'reject' | 'cancel' | 'amend' | 'execute' | 'self-approve' | null>(null)
  const [override, setOverride] = useState(false)
  const [costCentre, setCostCentre] = useState(false)

  // What the form started from - not the latest copy from the server. A change made on the
  // server (charging the lines to a cost centre) must not read as something the person edited.
  const [initial] = useState(() => JSON.stringify({ head: headFrom(order), lines: linesFrom(order), terms: (order.terms ?? []).map((t) => [t.clause_category, t.clause_text]) }))
  const current = JSON.stringify({ head, lines, terms: terms.map((t) => [t.clause_category, t.clause_text]) })
  const parts = useMemo(() => {
    const a = JSON.parse(initial)
    const b = JSON.parse(current)
    return { head: JSON.stringify(a.head) !== JSON.stringify(b.head), lines: JSON.stringify(a.lines) !== JSON.stringify(b.lines), terms: JSON.stringify(a.terms) !== JSON.stringify(b.terms) }
  }, [initial, current])
  const dirty = parts.head || parts.lines || parts.terms

  const editable = order.editable && can('workorders.manage')
  const canDecide = can('subcontracts.approve')
  const has = (a: string) => order.actions.some((x) => x === a)

  /** Everything that changed, in the order the server needs it: the head before the schedule it prices. */
  const persist = async () => {
    if (parts.head) await saveHead(order.id, head)
    if (parts.lines) await saveSchedule(order.id, toPayload(lines))
    if (parts.terms) await saveTerms(order.id, terms.filter((t) => t.clause_text.trim()))
  }

  const save = useAction(
    async () => {
      await persist()
      return { message: 'Saved.' }
    },
    { invalidate: [orderKeys.all], onSuccess: reseed },
  )

  const move = useAction(
    async (m: Move) => {
      // Sent for approval, or signed, as it stands on screen - not as it was last saved.
      if ((m.action === 'submit' || m.action === 'self-approve') && editable && dirty) await persist()
      return moveOrder(order.id, m)
    },
    {
      invalidate: [orderKeys.all],
      onSuccess: (res, m) => {
        setDialog(null)
        setOverride(false)
        if (m.action === 'amend') nav(`/subcontractors/work-orders/${res.order.id}`)
        else reseed()
      },
      onError: () => {
        // A refusal leaves the dialog open with the server's reason in the toast.
      },
    },
  )

  const copy = useAction(() => copyOrder(order.id), { invalidate: [orderKeys.all], onSuccess: (res) => nav(`/subcontractors/work-orders/${res.order.id}`) })

  const budgetWarnings = order.budget_warnings ?? []
  const label = (s: string) => MOVE_LABEL[s] ?? s

  return (
    <>
      <div className="mb-6">
        <Link to="/subcontractors/work-orders" className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft className="size-3.5" /> Work orders
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-mono text-2xl font-semibold sm:text-3xl">{order.wo_number}</h1>
              <StatusBadge status={order.status} />
              {order.amendment_no > 0 && <Badge tone="neutral">Revision {order.amendment_no}</Badge>}
            </div>
            <p className="mt-2 max-w-2xl text-[15px] text-muted-foreground">
              {order.contractor || 'No sub contractor yet'}
              {order.vendor_code && <span className="ml-1.5 font-mono text-xs">{order.vendor_code}</span>}
              {order.project && ` · ${order.project}`}
              {order.subject && ` · ${order.subject}`}
            </p>
            {order.copied_from && <p className="mt-1 text-xs text-muted-foreground">Copied from {order.copied_from}</p>}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/wo/orders/${order.id}/document.pdf`} target="_blank" rel="noopener">
                <FileText /> PDF
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/wo/orders/${order.id}/boq.xlsx`}>
                <Download /> Schedule
              </a>
            </Button>
            {can('workorders.manage') && (
              <Button variant="outline" size="sm" loading={copy.isPending} onClick={() => copy.mutate()}>
                <Copy /> Copy
              </Button>
            )}
            {editable && (
              <Button variant="secondary" loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
                <Save /> Save
              </Button>
            )}
            {has('SUBMIT') && editable && (
              <Button loading={move.isPending && move.variables?.action === 'submit'} onClick={() => move.mutate({ action: 'submit' })}>
                {label('SUBMIT')}
              </Button>
            )}
            {isOwner && order.status === 'DRAFT' && (
              <Button variant="outline" onClick={() => setDialog('self-approve')}>
                Approve and issue
              </Button>
            )}
            {has('APPROVE') && canDecide && order.status === 'PROVISIONAL' && <Button onClick={() => setDialog('approve')}>{label('APPROVE')}</Button>}
            {order.status === 'PROVISIONAL' && canDecide && (
              <Button variant="outline" onClick={() => setDialog('reject')}>
                {label('REJECT')}
              </Button>
            )}
            {has('EXECUTE') && <Button onClick={() => setDialog('execute')}>{label('EXECUTE')}</Button>}
            {has('AMEND') && can('workorders.manage') && (
              <Button variant="outline" onClick={() => setDialog('amend')}>
                {label('AMEND')}
              </Button>
            )}
            {isOwner && (
              <Button variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" onClick={() => setDeleting(true)}>
                <Trash2 /> Delete
              </Button>
            )}
            {has('CANCEL') && canDecide && (
              <Button variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" onClick={() => setDialog('cancel')}>
                {label('CANCEL')}
              </Button>
            )}
          </div>
        </div>
      </div>

      {(order.revision_blockers ?? []).length > 0 && (
        <div role="alert" className="mb-5 rounded-xl border border-danger/30 bg-danger-soft p-3.5 text-[13.5px] text-danger">
          <p className="mb-1 font-semibold">This revision cannot be approved yet</p>
          {(order.revision_blockers ?? []).map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      )}

      {budgetWarnings.length > 0 && (
        <div role="alert" className="mb-5 rounded-xl border border-warning/30 bg-warning-soft p-3.5 text-[13.5px] text-warning">
          {budgetWarnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      )}

      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Basic value" value={formatINR(order.gross_amount)} sub={`${order.item_count} lines`} />
        <Stat label="GST" value={formatINR(order.gst_amount)} sub={`${order.gst_rate}%`} />
        <Stat label="Retention held" value={formatINR(order.retention_amount)} sub={`${order.retention_percent}% of each bill`} />
        <Stat label="Net order value" value={formatINR(order.net_order_value)} sub={order.approved_at ? `Approved ${formatDate(order.approved_at)}` : undefined} />
      </StatGrid>

      <div className="mb-5">
        <Tabs
          label="Order sections"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'details', label: 'Details' },
            { value: 'schedule', label: 'Schedule', count: lines.filter((l) => l.item_description.trim()).length },
            { value: 'terms', label: 'Conditions', count: terms.length },
            { value: 'approval', label: 'Approval' },
          ]}
        />
      </div>

      {tab === 'details' && <HeadForm head={head} onChange={(p) => setHead((h) => ({ ...h, ...p }))} disabled={!editable} order={order} />}
      {tab === 'schedule' && (
        <ScheduleTab order={order} rows={lines} onRows={setLines} disabled={!editable} vocab={vocab.data} onCostCentre={() => setCostCentre(true)} dirty={parts.lines} onCharged={reseed} />
      )}
      {tab === 'terms' && <TermsTab terms={terms} onTerms={setTerms} disabled={!editable} vocab={vocab.data} />}
      {tab === 'approval' && <ApprovalTab order={order} />}

      <CostCentreModal open={costCentre} onOpenChange={setCostCentre} jobId={order.job_id} />

      <ConfirmDialog
        open={dialog === 'approve' || dialog === 'self-approve'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={dialog === 'self-approve' ? 'Approve and issue this order?' : `Approve ${order.wo_number}?`}
        description={dialog === 'self-approve' ? 'You are raising and signing it yourself. It is checked as any order is, and the history says so.' : `${formatINR(order.net_order_value)} to ${order.contractor || 'the gang'}.`}
        confirmLabel="Approve"
        reason={{ label: budgetWarnings.length && override ? 'Why is the allocation being exceeded?' : 'Note (optional)', required: !!budgetWarnings.length && override }}
        loading={move.isPending}
        onConfirm={(comments) => move.mutate({ action: dialog === 'self-approve' ? 'self-approve' : 'approve', comments, override })}
      >
        {budgetWarnings.length > 0 && (
          <label className="flex items-start gap-2.5 rounded-lg bg-warning-soft p-3 text-[13px] text-warning">
            <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="mt-0.5 size-4 accent-[var(--warning)]" />
            <span>This order overruns its project allocation. Approve it anyway - the reason is kept beside the figures.</span>
          </label>
        )}
      </ConfirmDialog>
      <ConfirmDialog
        open={dialog === 'reject'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Send it back?"
        description="It returns to a draft for the person who raised it."
        confirmLabel="Send back"
        reason={{ label: 'What needs putting right?', required: true }}
        loading={move.isPending}
        onConfirm={(comments) => move.mutate({ action: 'reject', comments })}
      />
      <ConfirmDialog
        open={dialog === 'cancel'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Cancel ${order.wo_number}?`}
        description="A cancelled order cannot be measured or billed. It is refused while work or bills stand against it."
        confirmLabel="Cancel the order"
        tone="danger"
        reason={{ label: 'Why is it being cancelled?', required: true }}
        loading={move.isPending}
        onConfirm={(comments) => move.mutate({ action: 'cancel', comments })}
      />
      <ConfirmDialog
        open={dialog === 'amend'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Amend this order?"
        description="A revision opens as a draft carrying everything across. This order stays live for measuring and billing until the revision is approved, and then its measurements and bills move to it."
        confirmLabel="Open a revision"
        loading={move.isPending}
        onConfirm={() => move.mutate({ action: 'amend' })}
      />
      <ConfirmDialog
        open={dialog === 'execute'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Mark as executed?"
        description="The counter-signed copy is back. From here it carries RA bills."
        confirmLabel="Mark as executed"
        loading={move.isPending}
        onConfirm={() => move.mutate({ action: 'execute' })}
      />
      <DeleteOrderDialog open={deleting} onOpenChange={setDeleting} kind="subcontract" id={order.id} number={order.wo_number} onDeleted={() => nav('/subcontractors/work-orders')} />
    </>
  )
}
