import { Button } from '@/components/ui'

/** The bottom of a small form: the server's reason on the left, Cancel and the action on the right. */
export function Footer({ error, busy, label, disabled, onClose, onSave }: { error?: string; busy: boolean; label: string; disabled?: boolean; onClose: () => void; onSave: () => void }) {
  return (
    <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
      {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
      <Button variant="ghost" onClick={onClose}>Cancel</Button>
      <Button loading={busy} disabled={disabled} onClick={onSave}>{label}</Button>
    </div>
  )
}
