import { useState } from 'react'
import { Button, Field, Input, Modal } from '@/components/ui'

export interface PromptField { key: string; label: string; initial?: string; required?: boolean }

/** A short form asked for when something is closed: a cause and a fix, a closing note. */
export function PromptModal({ open, title, description, fields, confirm, busy, error, onSubmit, onClose }: { open: boolean; title: string; description?: string; fields: PromptField[]; confirm: string; busy?: boolean; error?: string; onSubmit: (v: Record<string, string>) => void; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={title} description={description}>
      {open && <Body fields={fields} confirm={confirm} busy={busy} error={error} onSubmit={onSubmit} onClose={onClose} />}
    </Modal>
  )
}

function Body({ fields, confirm, busy, error, onSubmit, onClose }: { fields: PromptField[]; confirm: string; busy?: boolean; error?: string; onSubmit: (v: Record<string, string>) => void; onClose: () => void }) {
  const [v, setV] = useState<Record<string, string>>(Object.fromEntries(fields.map((f) => [f.key, f.initial ?? ''])))
  return (
    <div>
      <div className="grid gap-4">{fields.map((f, i) => <Field key={f.key} label={f.label} htmlFor={`pm-${f.key}`}><Input id={`pm-${f.key}`} autoFocus={i === 0} value={v[f.key]} onChange={(e) => setV((x) => ({ ...x, [f.key]: e.target.value }))} /></Field>)}</div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={fields.some((f) => f.required && !v[f.key].trim())} onClick={() => onSubmit(v)}>{confirm}</Button>
      </div>
    </div>
  )
}
