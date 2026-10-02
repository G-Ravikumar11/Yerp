import { useQueryClient } from '@tanstack/react-query'
import { Button, Modal, Skeleton } from '@/components/ui'
import { deleteWorkOrder, useDeletePreview, type OrderKind } from '@/api/deleteOrder'
import { useAction } from '@/lib/mutate'
import { plural } from '@/lib/format'

const LABEL: Record<string, [string, string]> = {
  versions: ['version', 'versions'],
  orders: ['work order', 'work orders'],
  logins: ['portal login', 'portal logins'],
  items: ['schedule line', 'schedule lines'],
  lines: ['schedule line', 'schedule lines'],
  measurements: ['measurement', 'measurements'],
  bills: ['bill', 'bills'],
  variations: ['variation', 'variations'],
  files: ['file', 'files'],
}

/**
 * Deleting a work order, which is the owner's alone: it goes from every screen, with what hangs off it.
 * The dialog says what that is first, and refuses outright when money has moved against the order.
 */
export function DeleteOrderDialog({ open, onOpenChange, kind, id, number, onDeleted }: { open: boolean; onOpenChange: (o: boolean) => void; kind: OrderKind; id: number; number: string; onDeleted: () => void }) {
  const qc = useQueryClient()
  const preview = useDeletePreview(kind, id, open)
  const p = preview.data
  const remove = useAction(() => deleteWorkOrder(kind, id), {
    // Everything that listed it - the measurement book, bills, approvals, the lists - starts over.
    invalidate: [],
    onSuccess: async () => {
      qc.removeQueries({ queryKey: ['delete-preview'] })
      await qc.invalidateQueries()
      onOpenChange(false)
      onDeleted()
    },
  })
  const goes = p ? Object.entries(p.counts).filter(([k, n]) => n > 0 && LABEL[k] && !(k === 'versions' && n === 1)).map(([k, n]) => plural(n, ...(kind === 'bill' && k === 'lines' ? (['bill line', 'bill lines'] as [string, string]) : LABEL[k]))) : []
  const several = (p?.numbers.length ?? 0) > 1
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete ${number}?`}
      description={kind === 'vendor' ? 'This takes the vendor and everything of theirs away from every screen. It cannot be undone.' : 'This takes it away from every screen. It cannot be undone.'}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Keep it</Button>
          <Button variant="danger" loading={remove.isPending} disabled={!p?.can_delete} onClick={() => remove.mutate()}>Delete everywhere</Button>
        </>
      }
    >
      {preview.isPending ? (
        <Skeleton className="h-16 w-full" />
      ) : preview.isError || !p ? (
        <p className="text-sm text-danger">Could not check what this is tied to. Try again.</p>
      ) : (
        <div className="grid gap-3 text-sm">
          {(p.warnings ?? []).length > 0 && (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger-soft px-3 py-2.5 text-danger">
              <p className="font-medium">Money is recorded against it. It goes too.</p>
              <ul className="mt-1 list-disc pl-5">{p.warnings.map((b) => <li key={b}>{b}</li>)}</ul>
            </div>
          )}
          {several && <p>It was amended, so every version goes together: <strong>{p.numbers.join(', ')}</strong>.</p>}
          <p>{goes.length ? <>Along with it: <strong>{goes.join(', ')}</strong>.</> : 'Nothing else hangs off it.'}</p>
          {kind === 'bill' && <p>What the bill measured is free to be billed again.</p>}
          <p className="text-muted-foreground">{kind === 'bill' ? 'Cancelling a bill keeps its record. Delete only what should never have existed.' : 'Cancelling keeps the record. Delete only what should never have existed.'}</p>
        </div>
      )}
    </Modal>
  )
}
