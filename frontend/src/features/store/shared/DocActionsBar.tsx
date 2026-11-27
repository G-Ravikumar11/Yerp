import { useState } from 'react'
import { Button, ConfirmDialog } from '@/components/ui'
import type { DocStatus } from '@/api/store'

export type DocAction = 'submit' | 'approve' | 'post' | 'cancel'

/** Which buttons a document in this status offers, before looking at what the person may do. */
const BY_STATUS: Record<DocStatus, readonly DocAction[]> = {
  DRAFT: ['submit', 'cancel'],
  SUBMITTED: ['approve', 'cancel'],
  APPROVED: ['post', 'cancel'],
  POSTED: ['cancel'], // cancelling a posted document reverses its stock movements
  CANCELLED: [],
}

/** The actions to show: those the status allows and the person has been given. */
export function availableActions(status: DocStatus, can: Partial<Record<DocAction, boolean>> = {}): DocAction[] {
  return BY_STATUS[status].filter((a) => can[a] === true)
}

export interface DocActionsBarProps {
  status: DocStatus
  /** Which actions this person may take (store.<slice>.create submits; approve, post and cancel are their own rights). Absent = not allowed. */
  can: Partial<Record<DocAction, boolean>>
  /** The action running now, to show its spinner and hold the others. */
  busy?: DocAction | null
  /** Called with the action, and for cancel the reason typed. Reject to leave the dialog open. */
  onAction: (action: DocAction, reason?: string) => void | Promise<void>
  disabled?: boolean
}

const LABEL: Record<DocAction, string> = { submit: 'Send for approval', approve: 'Approve', post: 'Save to stock', cancel: 'Cancel' }

/** Submit / approve / post / cancel for a store document. Post and cancel ask first - both move stock. */
export function DocActionsBar({ status, can, busy = null, onAction, disabled }: DocActionsBarProps) {
  const [asking, setAsking] = useState<'post' | 'cancel' | null>(null)
  const actions = availableActions(status, can)
  if (!actions.length) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      {actions.map((a) => (
        <Button
          key={a}
          variant={a === 'cancel' ? 'outline' : a === 'post' ? 'primary' : 'soft'}
          size="sm"
          loading={busy === a}
          disabled={disabled || (!!busy && busy !== a)}
          onClick={() => (a === 'post' || a === 'cancel' ? setAsking(a) : void onAction(a))}
        >
          {a === 'cancel' && status === 'POSTED' ? 'Cancel and undo stock' : LABEL[a]}
        </Button>
      ))}
      <ConfirmDialog
        open={asking === 'post'}
        onOpenChange={(o) => !o && setAsking(null)}
        title="Save to stock?"
        description="The stock will change now. You cannot edit it after this. To undo it, cancel it."
        confirmLabel="Save to stock"
        loading={busy === 'post'}
        onConfirm={async () => {
          await onAction('post')
          setAsking(null)
        }}
      />
      <ConfirmDialog
        open={asking === 'cancel'}
        onOpenChange={(o) => !o && setAsking(null)}
        title={status === 'POSTED' ? 'Cancel it and undo the stock?' : 'Cancel it?'}
        description={status === 'POSTED' ? 'The stock goes back to what it was before.' : undefined}
        confirmLabel="Yes, cancel it"
        cancelLabel="Keep it"
        tone="danger"
        reason={{ label: 'Why are you cancelling it?', required: true }}
        loading={busy === 'cancel'}
        onConfirm={async (reason) => {
          await onAction('cancel', reason)
          setAsking(null)
        }}
      />
    </div>
  )
}
