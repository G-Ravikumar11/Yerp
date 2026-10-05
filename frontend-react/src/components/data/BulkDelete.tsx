import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { Button, Input, Modal } from '@/components/ui'
import { BATCH, bulkDeleteBatch, type BulkKind } from '@/api/bulkDelete'
import { plural } from '@/lib/format'
import { toast } from '@/stores/toast'

/**
 * The strip that appears over a list once rows are ticked: how many, a way to clear the ticks, and Delete.
 * "Select all" is the box in the table's heading - it ticks every row the filters leave showing.
 */
export function BulkBar({ count, noun, shown, onClear, onDelete }: { count: number; noun: string; shown: number; onClear: () => void; onDelete: () => void }) {
  if (count === 0) return null
  return (
    <div role="region" aria-label="Selected rows" className="sticky top-16 z-10 mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-primary/40 bg-primary-soft px-4 py-2.5 text-sm">
      <span className="font-medium">
        {plural(count, noun, noun + 's')} selected
      </span>
      {count < shown && <span className="text-muted-foreground">of {shown} shown</span>}
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear
      </Button>
      <Button size="sm" variant="danger" className="ml-auto" onClick={onDelete}>
        <Trash2 /> Delete {count}
      </Button>
    </div>
  )
}

/**
 * Deletes the ticked rows a few at a time, so a large clearing shows its progress and can be stopped, and one
 * that is refused is named without holding up the rest. Typing DELETE is asked when there are several.
 */
export function BulkDeleteDialog({ open, onOpenChange, kind, noun, ids, onFinished, detail }: { open: boolean; onOpenChange: (o: boolean) => void; kind: BulkKind; noun: string; ids: number[]; onFinished: () => void; detail?: string }) {
  const qc = useQueryClient()
  const [typed, setTyped] = useState('')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [outcome, setOutcome] = useState<{ deleted: number; gone: number; failed: { id: number; reason: string }[]; left: number; broke: string } | null>(null)
  const stop = useRef(false)
  const many = ids.length >= 5
  const ready = !many || typed.trim().toUpperCase() === 'DELETE'

  const close = (o: boolean) => {
    if (running) return
    if (!o) {
      setTyped('')
      setOutcome(null)
      setProgress(0)
      // The ticks are cleared only when every row was tried; rows that were deleted drop off the list by themselves.
      if (outcome && !outcome.left) onFinished()
    }
    onOpenChange(o)
  }

  const run = async () => {
    stop.current = false
    setRunning(true)
    setOutcome(null)
    const total = { deleted: 0, gone: 0, failed: [] as { id: number; reason: string }[], left: ids.length, broke: '' }
    const size = BATCH[kind]
    try {
      for (let at = 0; at < ids.length && !stop.current; at += size) {
        const res = await bulkDeleteBatch(kind, ids.slice(at, at + size))
        total.deleted += res.deleted
        total.gone += res.gone
        total.failed.push(...res.failed)
        total.left = Math.max(0, ids.length - (at + size))
        setProgress(Math.min(ids.length, at + size))
      }
    } catch (e) {
      total.broke = e instanceof Error ? e.message : 'Deleting stopped.'
      toast.error(total.broke)
    } finally {
      setRunning(false)
      setOutcome(total)
      // Everything that listed what went - the lists, the book, the bills - starts over.
      qc.removeQueries({ queryKey: ['delete-preview'] })
      await qc.invalidateQueries()
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={close}
      title={outcome ? 'Done' : `Delete ${ids.length} ${ids.length === 1 ? noun : noun + 's'}?`}
      description={outcome ? undefined : detail ?? 'Everything attached to each goes with it, from every screen. This cannot be undone.'}
      footer={
        outcome ? (
          <Button onClick={() => close(false)}>Close</Button>
        ) : running ? (
          <Button variant="outline" onClick={() => (stop.current = true)}>
            Stop after this batch
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={() => close(false)}>
              Keep them
            </Button>
            <Button variant="danger" disabled={!ready || ids.length === 0} onClick={() => void run()}>
              Delete {ids.length}
            </Button>
          </>
        )
      }
    >
      {outcome ? (
        <div className="grid gap-2 text-sm" aria-live="polite">
          <p>
            <strong>{outcome.deleted}</strong> deleted{outcome.gone ? `, ${outcome.gone} already gone` : ''}
            {outcome.left ? `. Stopped with ${outcome.left} not tried - they are still there and still ticked.` : '.'}
          </p>
          {outcome.broke && (
            <p role="alert" className="text-danger">
              {outcome.broke}
            </p>
          )}
          {outcome.failed.length > 0 && (
            <div role="alert" className="rounded-lg border border-danger/40 bg-danger-soft px-3 py-2 text-danger">
              <p className="font-medium">{outcome.failed.length} could not be deleted:</p>
              <ul className="mt-1 max-h-40 list-disc overflow-y-auto pl-5">
                {outcome.failed.map((f) => (
                  <li key={f.id}>{f.reason}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : running ? (
        <div aria-live="polite" className="grid gap-2 text-sm">
          <p>
            Deleting... {progress} of {ids.length}
          </p>
          <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={progress} aria-valuemax={ids.length}>
            <div className="h-full bg-primary transition-all" style={{ width: `${(progress / Math.max(1, ids.length)) * 100}%` }} />
          </div>
        </div>
      ) : many ? (
        <div className="grid gap-1.5">
          <label htmlFor="bulk-confirm" className="text-sm">
            That is a lot. Type <strong>DELETE</strong> to go ahead.
          </label>
          <Input id="bulk-confirm" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus autoComplete="off" />
        </div>
      ) : null}
    </Modal>
  )
}
