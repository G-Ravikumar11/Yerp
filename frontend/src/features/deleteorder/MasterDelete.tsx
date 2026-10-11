import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button, Modal, Skeleton } from '@/components/ui'
import { masterDelete, useMasterPreview, type MasterKind } from '@/api/masterDelete'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { DeleteButton } from './DeleteButton'

/** "3 payments, 2 RA bills": what a delete takes, as the server counted it. */
const list = (counts: Record<string, number>) => Object.entries(counts).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${k}`).join(', ')

/**
 * The Master's delete for any record: it says first what goes with it, then takes it away from every screen.
 * `onDeleted` is where to go next when the record was the page being looked at.
 */
export function MasterDeleteDialog({ open, onOpenChange, kind, id, label, noun, onDeleted }: { open: boolean; onOpenChange: (o: boolean) => void; kind: MasterKind; id: number; label: string; noun?: string; onDeleted?: () => void }) {
  const qc = useQueryClient()
  const preview = useMasterPreview(kind, id, open)
  const p = preview.data
  const remove = useAction(() => masterDelete(kind, id), {
    invalidate: [],
    onSuccess: async () => {
      // Close first, so the question about what it is tied to is not asked again of a record that is gone.
      onOpenChange(false)
      qc.removeQueries({ queryKey: ['master-preview'] })
      // Everything that listed it - the lists, the books, the totals - starts over.
      await qc.invalidateQueries()
      onDeleted?.()
    },
  })
  const goes = p ? list(p.counts) : ''
  const kept = p?.kept && list(p.kept)
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete ${noun ? noun + ' ' : ''}${label}?`}
      description="This takes it away from every screen. It cannot be undone."
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
          <p>{goes ? <>Along with it: <strong>{goes}</strong>.</> : 'Nothing else hangs off it.'}</p>
          {kept && <p className="text-muted-foreground">Kept, and no longer linked to it: {kept}.</p>}
          {kind === 'project' && <p className="text-muted-foreground">Everything recorded against the project goes: its orders and bills, measurements, purchase orders, payments, diary, drawings, quality and safety records, schedule, budgets, chat and photos.</p>}
          <p className="text-muted-foreground">Delete only what should never have existed. Cancelling keeps the record.</p>
        </div>
      )}
    </Modal>
  )
}

/** The delete icon for a row, shown only to the Master, with its confirmation. */
export function MasterDelete({ kind, id, label, noun, onDeleted }: { kind: MasterKind; id: number; label: string; noun?: string; onDeleted?: () => void }) {
  const { isOwner } = useSession()
  const [open, setOpen] = useState(false)
  if (!isOwner) return null
  return (
    <>
      <DeleteButton label={label} onClick={() => setOpen(true)} />
      <MasterDeleteDialog open={open} onOpenChange={setOpen} kind={kind} id={id} label={label} noun={noun} onDeleted={onDeleted} />
    </>
  )
}
