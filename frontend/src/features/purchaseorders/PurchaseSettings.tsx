import { useState } from 'react'
import { Settings2 } from 'lucide-react'
import { Button, Field, Input, Modal } from '@/components/ui'
import { priceKeys, savePurchaseControls, usePurchaseControls, type PurchaseControls } from '@/api/poControls'
import { useAction } from '@/lib/mutate'

/** Purchasing's settings: the rate alert, where the monthly supplier scorecard goes, and whether late suppliers are emailed. */
export function PurchaseSettingsButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}><Settings2 /> Purchase settings</Button>
      {open && <SettingsModal onClose={() => setOpen(false)} />}
    </>
  )
}

function SettingsModal({ onClose }: { onClose: () => void }) {
  const q = usePurchaseControls()
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Purchase settings" size="md">
      {q.data ? <Form start={q.data} onClose={onClose} /> : <p className="text-sm text-muted-foreground">Loading...</p>}
    </Modal>
  )
}

function Form({ start, onClose }: { start: PurchaseControls; onClose: () => void }) {
  const [f, setF] = useState({ rate_alert_pct: String(start.rate_alert_pct), purchasing_emails: start.purchasing_emails, late_delivery_emails: start.late_delivery_emails })
  const save = useAction(() => savePurchaseControls({ rate_alert_pct: Number(f.rate_alert_pct), purchasing_emails: f.purchasing_emails, late_delivery_emails: f.late_delivery_emails }),
    { invalidate: [priceKeys.all], success: 'Purchase settings saved', onSuccess: onClose })
  return (
    <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <Field label="Flag an order rate this % over the last price" htmlFor="ps-pct" hint="Or over a rate contract in force.">
        <Input id="ps-pct" inputMode="decimal" value={f.rate_alert_pct} onChange={(e) => setF({ ...f, rate_alert_pct: e.target.value })} />
      </Field>
      <Field label="Purchasing's email" htmlFor="ps-mail" hint="The monthly supplier scorecard goes here. Several addresses: separate them with commas. Empty: no scorecard is emailed.">
        <Input id="ps-mail" value={f.purchasing_emails} onChange={(e) => setF({ ...f, purchasing_emails: e.target.value })} placeholder="buying@yourcompany.com" />
      </Field>
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-1" checked={f.late_delivery_emails} onChange={(e) => setF({ ...f, late_delivery_emails: e.target.checked })} />
        <span>Email suppliers when a delivery is late<span className="block text-xs text-muted-foreground">The buyer is always told. With this on, the supplier is also emailed on the first day late and every 3 days, until goods arrive.</span></span>
      </label>
      <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button type="submit" loading={save.isPending}>Save</Button>
      </div>
    </form>
  )
}
