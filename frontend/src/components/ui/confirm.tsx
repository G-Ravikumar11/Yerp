import { useState } from 'react'
import { Button } from './button'
import { Field, Textarea } from './input'
import { Modal } from './modal'

export interface ConfirmProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  confirmLabel: string
  tone?: 'primary' | 'danger'
  /** Ask for a reason. The server refuses a bare "cancel" and so does this. */
  reason?: { label: string; placeholder?: string; required?: boolean }
  loading?: boolean
  /** What to do. Gets the reason typed, when one was asked for. */
  onConfirm: (reason: string) => void | Promise<void>
  children?: React.ReactNode
}

/**
 * "Are you sure" that can also ask why. Used for every move that cannot be
 * quietly taken back: cancelling an order, sending a bill back, certifying.
 */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, tone = 'primary', reason, loading, onConfirm, children }: ConfirmProps) {
  const [text, setText] = useState('')
  const [touched, setTouched] = useState(false)
  const missing = !!reason?.required && !text.trim()

  const submit = async () => {
    setTouched(true)
    if (missing) return
    await onConfirm(text.trim())
  }

  return (
    <Modal
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setText('')
          setTouched(false)
        }
        onOpenChange(o)
      }}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Not now
          </Button>
          <Button variant={tone === 'danger' ? 'danger' : 'primary'} loading={loading} onClick={submit}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
      {reason && (
        <Field label={reason.label} htmlFor="confirm-reason" error={touched && missing ? 'Say why - it goes on the record.' : undefined} className={children ? 'mt-4' : undefined}>
          <Textarea id="confirm-reason" autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder={reason.placeholder} aria-invalid={touched && missing ? true : undefined} />
        </Field>
      )}
    </Modal>
  )
}
