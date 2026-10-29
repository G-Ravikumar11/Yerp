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

const LABEL: Record<DocAction, string> = { submit: 'Submit', approve: 'Approve', post: 'Post to stock', cancel: 'Cancel' }

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
          {a === 'cancel' && status === 'POSTED' ? 'Cancel & reverse' : LABEL[a]}
        </Button>
      ))}
      <ConfirmDialog
        open={asking === 'post'}
        onOpenChange={(o) => !o && setAsking(null)}
        title="Post to stock?"
        description="This adds to or takes from the stock held and cannot be edited afterwards. It can only be undone by cancelling it."
        confirmLabel="Post"
        loading={busy === 'post'}
        onConfirm={async () => {
          await onAction('post')
          setAsking(null)
        }}
      />
      <ConfirmDialog
        open={asking === 'cancel'}
        onOpenChange={(o) => !o && setAsking(null)}
        title={status === 'POSTED' ? 'Cancel and reverse this document?' : 'Cancel this document?'}
        description={status === 'POSTED' ? 'Every stock movement it made is reversed.' : undefined}
        confirmLabel="Cancel document"
        cancelLabel="Keep it"
        tone="danger"
        reason={{ label: 'Why is it being cancelled?', required: true }}
        loading={busy === 'cancel'}
        onConfirm={async (reason) => {
          await onAction('cancel', reason)
          setAsking(null)
        }}
      />
    </div>
  )
}
