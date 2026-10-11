import { useEffect, useMemo, useState } from 'react'
import { Sparkles } from 'lucide-react'
import { DataGrid, type Column } from '@/components/grid'
import { Badge, Button, ConfirmDialog, Field, Modal, Skeleton, Textarea } from '@/components/ui'
import {
  boqKeys,
  createVariation,
  deleteVariation,
  moveVariation,
  suggestVariation,
  updateVariation,
  useBoqVariation,
  variationKeys,
  type BoqLine,
  type VariationInput,
  type VariationLine,
} from '@/api/boq'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { cn, formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface Row {
  kind: 'quantity' | 'extra'
  boq_key: string
  section_key: string
  sno: string
  description: string
  uom: string
  change_qty: number | null
  rate: number | null
  remarks: string
}

const blank = (): Row => ({ kind: 'quantity', boq_key: '', section_key: '', sno: '', description: '', uom: '', change_qty: null, rate: null, remarks: '' })
const fromLine = (l: VariationLine): Row => ({ kind: l.kind, boq_key: l.boq_key, section_key: l.section_key, sno: l.sno, description: l.description, uom: l.uom, change_qty: l.change_qty, rate: l.rate, remarks: l.remarks })
const KINDS = [
  { value: 'quantity', label: 'Quantity change' },
  { value: 'extra', label: 'Extra item' },
]
const TONE = { DRAFT: 'neutral', SUBMITTED: 'warning', APPROVED: 'success', CANCELLED: 'danger' } as const

/**
 * Raise, send and decide a variation to the BOQ: a quantity changed on a line it has, or an extra item it never
 * had, each with a rate. Approving it moves the BOQ to its next revision with the changes in.
 */
export function VariationDialog({ boqId, id, lines, open, onOpenChange }: { boqId: number; id: number | null; lines: BoqLine[]; open: boolean; onOpenChange: (o: boolean) => void }) {
  const { can } = useSession()
  const existing = useBoqVariation(open && id ? id : 0)
  const v = id ? existing.data : undefined
  const [reason, setReason] = useState('')
  const [rows, setRows] = useState<Row[]>([])
  const [back, setBack] = useState(false)
  const draft = !id || !!v?.editable

  useEffect(() => {
    if (!open) return
    if (!id) {
      setReason('')
      setRows([])
    } else if (v) {
      setReason(v.reason)
      setRows((v.lines ?? []).map(fromLine))
    }
  }, [open, id, v])

  const priced = useMemo(() => lines.filter((l) => l.kind === 'item' || l.kind === 'sub'), [lines])
  const sections = useMemo(() => lines.filter((l) => l.kind === 'section'), [lines])
  const byKey = useMemo(() => new Map(priced.map((l) => [l.key, l])), [priced])

  const columns = useMemo<Column<Row>[]>(
    () => [
      { id: 'kind', header: 'What', type: 'select', width: 116, options: KINDS, countsAsData: false },
      { id: 'boq_key', header: 'BOQ line', hint: 'For a quantity change', type: 'select', width: 190, options: priced.map((l) => ({ value: l.key, label: `${l.sno} ${l.description}`.slice(0, 60) })), readOnly: (r) => r.kind === 'extra' },
      { id: 'section_key', header: 'Under section', hint: 'For an extra item', type: 'select', width: 130, options: [{ value: '', label: 'At the end' }, ...sections.map((s) => ({ value: s.key, label: `${s.sno} ${s.description}`.slice(0, 40) }))], readOnly: (r) => r.kind === 'quantity', countsAsData: false },
      { id: 'description', header: 'Description', hint: 'The new item’s words', width: 200, readOnly: (r) => r.kind === 'quantity', get: (r) => (r.kind === 'quantity' ? (byKey.get(r.boq_key)?.description ?? '') : r.description) },
      { id: 'uom', header: 'Unit', width: 62, readOnly: (r) => r.kind === 'quantity', get: (r) => (r.kind === 'quantity' ? (byKey.get(r.boq_key)?.uom ?? '') : r.uom) },
      { id: 'change_qty', header: 'Add / (take)', hint: 'Quantity', type: 'number', decimals: 3, width: 104 },
      { id: 'rate', header: 'Rate', hint: 'Blank: BOQ rate', type: 'number', decimals: 2, width: 92 },
      {
        id: 'amount',
        header: 'Amount',
        type: 'number',
        width: 124,
        readOnly: true,
        get: (r) => {
          const rate = r.rate ?? (r.kind === 'quantity' ? (byKey.get(r.boq_key)?.rate ?? 0) : 0)
          return r.change_qty && rate ? Math.round(r.change_qty * rate * 100) / 100 : null
        },
        format: (x) => (typeof x === 'number' ? formatINR(x) : ''),
        summary: 'sum',
      },
    ],
    [priced, sections, byKey],
  )

  const payload = (): VariationInput[] =>
    rows
      .filter((r) => r.boq_key || r.description.trim() || r.change_qty)
      .map((r) => ({ kind: r.kind, boq_key: r.kind === 'quantity' ? r.boq_key : '', section_key: r.kind === 'extra' ? r.section_key : '', sno: r.sno, description: r.description, uom: r.uom, change_qty: r.change_qty ?? 0, rate: r.rate, remarks: r.remarks }))

  const refresh = [variationKeys.all, boqKeys.all, ['approvals']]
  const save = useAction(() => (id ? updateVariation(id, reason, payload()) : createVariation(boqId, reason, payload())), {
    invalidate: refresh,
    success: (r) => r.message,
    onSuccess: () => {
      if (!id) onOpenChange(false)
    },
  })
  const send = useAction(
    async () => {
      const saved = id ? await updateVariation(id, reason, payload()) : await createVariation(boqId, reason, payload())
      return moveVariation(saved.variation.id, 'submit')
    },
    { invalidate: refresh, success: (r) => r.message, onSuccess: () => onOpenChange(false) },
  )
  const move = useAction((a: { action: 'approve' | 'reject' | 'cancel'; comments?: string }) => moveVariation(id!, a.action, a.comments), {
    invalidate: refresh,
    success: (r) => r.message,
    onSuccess: () => {
      setBack(false)
      onOpenChange(false)
    },
  })
  const remove = useAction(() => deleteVariation(id!), { invalidate: refresh, success: (r) => r.message, onSuccess: () => onOpenChange(false) })
  const suggest = useAction(() => suggestVariation(boqId), {
    onSuccess: (r) => {
      if (!r.lines.length) return toast.info('Nothing has been executed past the BOQ.')
      setRows((cur) => [...cur.filter((x) => x.boq_key || x.description), ...r.lines.map((l) => ({ ...blank(), boq_key: l.boq_key, change_qty: l.change_qty, rate: l.rate }))])
      toast.success(`${r.lines.length} line${r.lines.length === 1 ? '' : 's'} added from the work already done.`)
    },
  })

  const total = rows.reduce((n, r) => n + (r.change_qty ?? 0) * (r.rate ?? (r.kind === 'quantity' ? (byKey.get(r.boq_key)?.rate ?? 0) : 0)), 0)
  const actions = v?.actions ?? []

  return (
    <>
      <Modal
        open={open}
        onOpenChange={onOpenChange}
        size="xl"
        title={v ? `${v.number}` : 'New variation to the BOQ'}
        description={v ? `${v.project} · drawn against ${v.basis_rev}${v.applied_rev ? ` · made ${v.applied_rev}` : ''}` : 'Quantities that ran past the BOQ, and extra items it never had - each with a rate. Approved, it becomes the BOQ’s next revision.'}
        footer={
          <div className="flex w-full flex-wrap items-center justify-between gap-2">
            <span className="tabular text-sm">
              {v && <Badge tone={TONE[v.status]} className="mr-2">{v.status === 'SUBMITTED' && v.waiting_on ? `with ${v.waiting_on}` : v.status.toLowerCase()}</Badge>}
              Adds <strong>{formatINR(v && !draft ? v.value : total)}</strong>
            </span>
            <div className="flex flex-wrap items-center gap-2">
              {id && draft && (
                <Button variant="ghost" loading={remove.isPending} onClick={() => remove.mutate()}>
                  Delete the draft
                </Button>
              )}
              {draft && (
                <Button variant="outline" loading={save.isPending} onClick={() => save.mutate()}>
                  Save the draft
                </Button>
              )}
              {draft && can('workorders.manage') && (
                <Button loading={send.isPending} onClick={() => send.mutate()}>
                  Send for approval
                </Button>
              )}
              {actions.includes('REJECT') && (
                <Button variant="outline" onClick={() => setBack(true)}>
                  Send back
                </Button>
              )}
              {actions.includes('APPROVE') && (
                <Button loading={move.isPending} onClick={() => move.mutate({ action: 'approve' })}>
                  Approve
                </Button>
              )}
              {actions.includes('CANCEL') && !draft && (
                <Button variant="ghost" onClick={() => move.mutate({ action: 'cancel' })}>
                  Cancel it
                </Button>
              )}
            </div>
          </div>
        }
      >
        {id && existing.isPending ? (
          <Skeleton className="h-60 w-full" />
        ) : (
          <div className="grid gap-4">
            <Field label="Why" htmlFor="bv-reason">
              <Textarea id="bv-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} readOnly={!draft} placeholder="What changed on site, or what the client has asked for" />
            </Field>
            {draft && (
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="outline" size="sm" loading={suggest.isPending} onClick={() => suggest.mutate()}>
                  <Sparkles /> Add what has been executed past the BOQ
                </Button>
                <span className="text-xs text-muted-foreground">Pick a BOQ line for a quantity change; leave the rate blank to use the BOQ&apos;s. For an extra item, give its words, quantity and rate.</span>
              </div>
            )}
            {v?.rejection_reason && v.status === 'DRAFT' && <p className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[13px]">Sent back: {v.rejection_reason}</p>}
            <DataGrid
              aria-label="Variation lines"
              columns={columns}
              rows={rows}
              onRowsChange={setRows}
              newRow={blank}
              readOnly={!draft}
              autoGrow={draft}
              minRows={draft ? 5 : 0}
              maxHeight={340}
              emptyText="No lines."
            />
            {v && v.route.length > 0 && (
              <ol aria-label="Approval route" className="flex flex-wrap gap-2 text-[13px]">
                {v.route.map((r) => (
                  <li key={r.step} className={cn('rounded-lg border px-3 py-1.5', r.status === 'waiting' ? 'border-primary bg-primary-soft' : 'border-border')}>
                    <span className="font-medium">{r.name}</span> <span className="text-muted-foreground">{r.status === 'waiting' ? 'now' : r.status}</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </Modal>
      <ConfirmDialog
        open={back}
        onOpenChange={setBack}
        title={`Send ${v?.number ?? ''} back`}
        description="It returns to a draft for the person who raised it to correct."
        confirmLabel="Send back"
        reason={{ label: 'Why it is going back', required: true }}
        loading={move.isPending}
        onConfirm={(note) => move.mutate({ action: 'reject', comments: note })}
      />
    </>
  )
}
