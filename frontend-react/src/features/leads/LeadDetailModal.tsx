import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Skeleton } from '@/components/ui'
import { addActivity, leadKeys, moveLead, priceLead, useLead, type Lead, type LeadStatus } from '@/api/leads'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const OPEN: LeadStatus[] = ['NEW', 'QUALIFIED', 'ESTIMATING', 'SUBMITTED']
const STAGES: [LeadStatus, string][] = [['NEW', 'New'], ['QUALIFIED', 'Qualified']]

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 py-1 text-sm">
      <dt className="w-28 shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  )
}

/** One tender in full: where it stands, what can happen next, and what has been done about it. */
export function LeadDetailModal({ id, onClose, onEdit }: { id: number | null; onClose: () => void; onEdit: (l: Lead) => void }) {
  return (
    <Modal open={!!id} onOpenChange={(o) => !o && onClose()} size="xl" title="Tender">
      {id ? <Detail id={id} onEdit={onEdit} /> : null}
    </Modal>
  )
}

function Detail({ id, onEdit }: { id: number; onEdit: (l: Lead) => void }) {
  const q = useLead(id)
  const [losing, setLosing] = useState(false)
  const [dropping, setDropping] = useState(false)
  const [kind, setKind] = useState('Call')
  const [note, setNote] = useState('')
  const [next, setNext] = useState('')
  const [nextOn, setNextOn] = useState('')
  const [why, setWhy] = useState('')
  const [who, setWho] = useState('')
  const [at, setAt] = useState(0)
  const refresh = [leadKeys.all]

  const move = useAction((b: Parameters<typeof moveLead>[1]) => moveLead(id, b), { invalidate: refresh, onSuccess: () => { setLosing(false); setDropping(false) } })
  const price = useAction(() => priceLead(id), { invalidate: [...refresh, ['estimates']] })
  const log = useAction(() => addActivity(id, { kind, note, next_action: next, next_on: nextOn }), { invalidate: refresh, onSuccess: () => { setNote(''); setNext(''); setNextOn('') } })

  const l = q.data
  if (!l) return <Skeleton className="h-64 w-full" />
  const open = OPEN.includes(l.status)
  const cls = 'text-muted-foreground'

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-xs text-muted-foreground">{l.number}</p>
          <h3 className="text-lg font-semibold">{l.title}</h3>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={l.status === 'WON' ? 'success' : l.status === 'LOST' ? 'danger' : l.status === 'DROPPED' ? 'neutral' : 'ember'}>{l.status.charAt(0) + l.status.slice(1).toLowerCase()}</Badge>
          {open && !l.estimate_id && STAGES.filter(([s]) => s !== l.status).map(([s, label]) => (
            <Button key={s} size="sm" variant="outline" onClick={() => move.mutate({ status: s })}>{label}</Button>
          ))}
          {open && !l.estimate_id && <Button size="sm" loading={price.isPending} onClick={() => price.mutate()}>Price it</Button>}
          {l.estimate_id && (
            <Button size="sm" variant="outline" asChild>
              <Link to="/clients/estimates">Estimate {l.estimate_number}</Link>
            </Button>
          )}
          {open && <Button size="sm" variant="outline" onClick={() => setLosing(true)}>Lost</Button>}
          {open && <Button size="sm" variant="outline" onClick={() => setDropping(true)}>Drop</Button>}
          <Button size="sm" variant="outline" onClick={() => onEdit(l)}>Edit</Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <dl>
          <Row label="Client">{l.customer_name || '-'}{l.contact_person && <span className={cls}> · {l.contact_person}</span>}{l.phone && <span className={cls}> · {l.phone}</span>}</Row>
          <Row label="Where">{l.location || '-'} <span className={cls}>· Source: {l.source || '-'}</span></Row>
          <Row label="Reference">{l.tender_reference || '-'}</Row>
          <Row label="Value">{formatINR(l.estimated_value)}{l.our_price > 0 && <span className={cls}> · our price {formatINR(l.our_price)}</span>}</Row>
          <Row label="Dates"><span className={cls}>Site visit</span> {formatDate(l.site_visit_on) || '-'} · <span className={cls}>pre-bid</span> {formatDate(l.prebid_on) || '-'} · <span className={cls}>bid due</span> {formatDate(l.bid_due_on) || '-'}</Row>
          <Row label="EMD">{l.emd_amount ? <>{formatINR(l.emd_amount)} {l.emd_mode} {l.emd_reference}{l.emd_returned_on ? ` - back ${formatDate(l.emd_returned_on)}` : l.emd_paid_on ? ` - paid ${formatDate(l.emd_paid_on)}` : ''}</> : '-'}</Row>
          {l.lost_reason && <Row label="Lost">{l.lost_reason}{l.winning_bidder && <> - {l.winning_bidder}{l.winning_price > 0 && ` at ${formatINR(l.winning_price)}`}</>}</Row>}
        </dl>
        <div>
          <div className="mb-2 grid grid-cols-[7rem_1fr] gap-2">
            <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} options={['Call', 'Visit', 'Meeting', 'Email', 'Note'].map((k) => ({ value: k, label: k }))} />
            <Input aria-label="What happened" placeholder="What happened" value={note} onChange={(e) => setNote(e.target.value)} />
          </div>
          <div className="mb-3 grid grid-cols-[1fr_9rem_auto] gap-2">
            <Input aria-label="Next step" placeholder="Next step" value={next} onChange={(e) => setNext(e.target.value)} />
            <Input aria-label="Next on" type="date" value={nextOn} onChange={(e) => setNextOn(e.target.value)} />
            <Button loading={log.isPending} disabled={!note.trim()} onClick={() => log.mutate()}>Add</Button>
          </div>
          <ul className="max-h-56 overflow-y-auto text-[13px]">
            {l.activities.map((a) => (
              <li key={a.id} className="border-t border-border py-2">
                <strong>{a.kind}</strong> <span className={cls}>{a.at.slice(0, 16)} {a.by}</span>
                <div>{a.note}</div>
                {a.next_action && <div className="text-primary">Next: {a.next_action}{a.next_on && ` by ${formatDate(a.next_on)}`}</div>}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <Modal open={losing} onOpenChange={setLosing} title={`Why was ${l.number} lost?`}>
        <div className="grid gap-4">
          <Field label="Why (price, eligibility, time...)" htmlFor="lose-why"><Input id="lose-why" value={why} onChange={(e) => setWhy(e.target.value)} autoFocus /></Field>
          <Field label="Who won it" htmlFor="lose-who" hint="Leave blank if not known."><Input id="lose-who" value={who} onChange={(e) => setWho(e.target.value)} /></Field>
          <Field label="At what price" htmlFor="lose-at"><NumField id="lose-at" value={at} onValue={setAt} /></Field>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <Button variant="ghost" onClick={() => setLosing(false)}>Cancel</Button>
            <Button loading={move.isPending} disabled={!why.trim()} onClick={() => move.mutate({ status: 'LOST', lost_reason: why, winning_bidder: who, winning_price: at })}>Record the loss</Button>
          </div>
        </div>
      </Modal>
      <ConfirmDialog open={dropping} onOpenChange={setDropping} title={`Drop ${l.number}?`} confirmLabel="Drop it" tone="danger" reason={{ label: 'Why is it being dropped?', required: true }} loading={move.isPending} onConfirm={(r) => move.mutate({ status: 'DROPPED', note: r })} />
    </div>
  )
}
