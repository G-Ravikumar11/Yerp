import { useState } from 'react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Stat, StatGrid } from '@/components/ui'
import { actOnVariation, bookKeys, raiseVariation, useVariationSuggestion, useVariations, type Variation } from '@/api/clientBook'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { compactINR, formatINR } from '@/lib/utils'
import { FilterBar, useListFilters } from '@/components/data/filters'

const TONE: Record<string, 'neutral' | 'warning' | 'success' | 'danger'> = { DRAFT: 'neutral', SUBMITTED: 'warning', APPROVED: 'success', REJECTED: 'danger', CANCELLED: 'danger' }

/** The book already knows which lines ran past the order. This turns that into a priced, approved change without retyping it. */
export function VariationsPanel({ workOrderId }: { workOrderId: number }) {
  const { can } = useSession()
  const vars = useVariations(workOrderId)
  const suggest = useVariationSuggestion(workOrderId)
  const [raising, setRaising] = useState(false)
  const [sendingBack, setSendingBack] = useState<Variation | null>(null)
  const refresh = [bookKeys.all]

  const raise = useAction((reason: string) => raiseVariation(workOrderId, reason), { invalidate: refresh, onSuccess: () => setRaising(false) })
  const act = useAction((a: { v: Variation; action: 'submit' | 'approve' | 'reject'; comments?: string }) => actOnVariation(a.v.id, a.action, a.comments ?? ''), { invalidate: refresh, onSuccess: () => setSendingBack(null) })

  const s = vars.data?.summary
  const columns: TableColumn<Variation>[] = [
    {
      id: 'no',
      header: 'Variation',
      cell: (v) => (
        <div>
          <span className="font-mono text-[13px] font-semibold">{v.number}</span>
          {v.origin === 'measured' && <div className="text-xs text-muted-foreground">from the book</div>}
        </div>
      ),
    },
    { id: 'reason', header: 'Reason', hideBelow: 'md', cell: (v) => v.reason || '-' },
    { id: 'value', header: 'Value', align: 'right', cell: (v) => <span className="font-semibold">{formatINR(v.value)}</span> },
    { id: 'order', header: 'Order value', hideBelow: 'lg', align: 'right', cell: (v) => `${formatINR(v.order_value_before)} → ${formatINR(v.order_value_after)}` },
    {
      id: 'status',
      header: 'Status',
      cell: (v) => (
        <div>
          <Badge tone={TONE[v.status] ?? 'neutral'}>{v.status.charAt(0) + v.status.slice(1).toLowerCase()}</Badge>
          {v.rejection_reason && <div className="mt-1 text-xs text-danger">{v.rejection_reason}</div>}
        </div>
      ),
    },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (v) => (
        <div className="flex justify-end gap-1.5">
          {v.actions.includes('SUBMIT') && (
            <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ v, action: 'submit' })}>
              Submit
            </Button>
          )}
          {v.actions.includes('APPROVE') && can('subcontracts.approve') && (
            <>
              <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ v, action: 'approve' })}>
                Approve
              </Button>
              <Button size="sm" variant="outline" onClick={() => setSendingBack(v)}>
                Send back
              </Button>
            </>
          )}
        </div>
      ),
    },
  ]

  const filters = useListFilters(vars.data?.variations, {
    search: (v) => [v.number, v.origin, v.reason, v.status, v.value].join(' '),
    status: (v) => v.status,
  })
  return (
    <section aria-label="Variations" className="mt-10">
      <h2 className="mb-3 text-lg font-semibold">Variations</h2>
      {!!suggest.data?.count && (
        <div className="mb-4 flex flex-wrap items-center gap-4 rounded-lg border-l-4 border-warning bg-warning-soft px-4 py-3">
          <div className="min-w-60 flex-1">
            <p className="font-semibold">
              {suggest.data.count} line{suggest.data.count > 1 ? 's have' : ' has'} been built past the order.
            </p>
            <p className="mt-0.5 text-[13px] text-muted-foreground">{formatINR(suggest.data.value)} of work is done, measured, and not covered by the order. Raise a variation and it becomes billable.</p>
          </div>
          {can('billing.manage') && <Button onClick={() => setRaising(true)}>Raise it from the book</Button>}
        </div>
      )}
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Variations raised" value={s?.raised ?? 0} loading={vars.isPending} />
        <Stat label="Awaiting approval" value={s?.awaiting_approval ?? 0} tone={s?.awaiting_approval ? 'warning' : undefined} loading={vars.isPending} />
        <Stat label="Agreed" value={compactINR(s?.approved_value)} loading={vars.isPending} />
        <Stat label="Asked for, not agreed" value={compactINR(s?.pending_value)} loading={vars.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search variations..." />
      <DataTable label="Variations" rows={filters.filtered} columns={columns} rowKey={(v) => v.id} loading={vars.isPending} empty="No variations on this order." />

      <ConfirmDialog open={raising} onOpenChange={setRaising} title="Raise a variation from the book" description="The lines built past the order become a priced variation." confirmLabel="Raise it" reason={{ label: 'Why did the work run over? (goes on the variation)' }} loading={raise.isPending} onConfirm={(reason) => raise.mutate(reason)} />
      <ConfirmDialog
        open={!!sendingBack}
        onOpenChange={(o) => !o && setSendingBack(null)}
        title={`Send ${sendingBack?.number ?? ''} back?`}
        confirmLabel="Send back"
        reason={{ label: 'Why is this going back?', required: true }}
        loading={act.isPending}
        onConfirm={(comments) => {
          if (sendingBack) act.mutate({ v: sendingBack, action: 'reject', comments })
        }}
      />
    </section>
  )
}
