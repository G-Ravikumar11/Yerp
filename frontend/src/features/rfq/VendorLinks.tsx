import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Copy, ExternalLink, FileText, Link2, Mail, MessageCircle, Trash2, UserPlus } from 'lucide-react'
import { Badge, Button, Field, Input, Modal } from '@/components/ui'
import { emailLink, inviteSupplier, inviteUrl, rfqKeys, useSupplierNames, whatsappLink, withdrawInvite, type RfqInvite, type Statement } from '@/api/rfq'
import { ApiError } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { useSession } from '@/lib/session'
import { toast } from '@/stores/toast'

const STATUS: Record<RfqInvite['status'], { label: string; tone: 'neutral' | 'info' | 'success' | 'warning' }> = {
  sent: { label: 'Link sent, not opened', tone: 'neutral' },
  opened: { label: 'Opened, no quote yet', tone: 'info' },
  quoted: { label: 'Quote received', tone: 'success' },
  document: { label: 'Sent a file: add the rates', tone: 'warning' },
}

/** Send the link: WhatsApp or email with the message written, or copy it. Nothing is sent until the buyer sends it. */
function SendButtons({ inv, statement }: { inv: RfqInvite; statement: Statement }) {
  const { user } = useSession()
  const company = user?.company || ''
  const [copied, setCopied] = useState(false)
  const copy = () => {
    void navigator.clipboard?.writeText(inviteUrl(inv))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      <Button size="sm" variant="outline" asChild><a href={whatsappLink(inv, company, statement.rfq)} target="_blank" rel="noopener"><MessageCircle /> WhatsApp</a></Button>
      <Button size="sm" variant="outline" asChild><a href={emailLink(inv, company, statement.rfq)}><Mail /> Email</a></Button>
      <Button size="sm" variant="ghost" onClick={copy}>{copied ? <Check /> : <Copy />} {copied ? 'Copied' : 'Copy link'}</Button>
    </div>
  )
}

/** Ask a supplier to quote on their own: a link to this enquiry, sent by WhatsApp or email. */
export function AskSuppliersModal({ statement, open, onClose }: { statement: Statement; open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} size="lg" title="Ask suppliers to quote"
      description="Each supplier gets their own link. They open it on their phone, see the items and quantities (not anyone else's prices), and type their rates or upload their quotation in whatever form they have it. It comes straight into this comparison.">
      {open && <AskForm statement={statement} onClose={onClose} />}
    </Modal>
  )
}

function AskForm({ statement, onClose }: { statement: Statement; onClose: () => void }) {
  const qc = useQueryClient()
  const suppliers = useSupplierNames()
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [made, setMade] = useState<RfqInvite | null>(null)
  const pick = (v: string) => {
    setName(v)
    const known = (suppliers.data ?? []).find((s) => s.name.toLowerCase() === v.trim().toLowerCase())
    if (known) { setPhone((p) => p || known.phone || ''); setEmail((e) => e || known.email || '') }
  }
  const make = async () => {
    setBusy(true)
    setError('')
    try {
      const out = await inviteSupplier(statement.rfq.id, { supplier_name: name.trim(), phone: phone.trim(), email: email.trim() })
      setMade(out.invite)
      await qc.invalidateQueries({ queryKey: rfqKeys.all })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The link could not be made. Try again.')
    } finally {
      setBusy(false)
    }
  }
  const another = () => { setMade(null); setName(''); setPhone(''); setEmail('') }
  if (made) {
    return (
      <div className="grid gap-4">
        <div className="rounded-lg border border-success/40 bg-success/5 p-4">
          <p className="flex items-center gap-2 text-sm font-medium"><Link2 className="size-4 text-success" /> Link ready for {made.supplier_name}</p>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{inviteUrl(made)}</p>
          <div className="mt-3"><SendButtons inv={made} statement={statement} /></div>
          {!made.phone && <p className="mt-2 text-xs text-muted-foreground">No phone number given: WhatsApp will ask you to choose the chat.</p>}
        </div>
        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button variant="outline" onClick={another}><UserPlus /> Ask another supplier</Button>
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    )
  }
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Supplier" htmlFor="as-name" className="sm:col-span-3"><Input id="as-name" list="as-names" value={name} onChange={(e) => pick(e.target.value)} placeholder="Choose from your suppliers or type a new one" autoFocus /></Field>
        <datalist id="as-names">{(suppliers.data ?? []).map((s) => <option key={s.name} value={s.name} />)}</datalist>
        <Field label="WhatsApp number" htmlFor="as-phone" className="sm:col-span-1"><Input id="as-phone" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="98765 43210" /></Field>
        <Field label="Email" htmlFor="as-email" className="sm:col-span-2"><Input id="as-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="optional" /></Field>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {error && <p role="alert" className="mr-auto text-[13px] text-danger">{error}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={busy} disabled={!name.trim()} onClick={() => void make()}><Link2 /> Make the link</Button>
      </div>
    </div>
  )
}

/** Who has been asked through a link, and how far each has got: sent, opened, quoted, or sent a file to be read. */
export function SupplierLinks({ statement, onAddFromFile }: { statement: Statement; onAddFromFile: (supplier: string) => void }) {
  const qc = useQueryClient()
  const invites = statement.invites ?? []
  const [open, setOpen] = useState<number | null>(null)
  if (!invites.length) return null
  const withdraw = async (inv: RfqInvite) => {
    try {
      const out = await withdrawInvite(statement.rfq.id, inv.id)
      toast.success(out.message)
      await qc.invalidateQueries({ queryKey: rfqKeys.all })
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Could not take the link back.')
    }
  }
  return (
    <div className="border-b border-border px-5 py-4">
      <h3 className="mb-2 text-sm font-semibold">Suppliers asked by link</h3>
      <ul className="grid gap-2">
        {invites.map((inv) => {
          const s = STATUS[inv.status]
          return (
            <li key={inv.id} className="rounded-lg border border-border px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <strong className="mr-1">{inv.supplier_name}</strong>
                <Badge tone={s.tone} dot>{s.label}</Badge>
                {inv.submitted_at && <span className="text-xs text-muted-foreground">sent {formatDate(inv.submitted_at.slice(0, 10))}</span>}
                <div className="ml-auto flex flex-wrap gap-1.5">
                  {inv.document && <Button size="sm" variant="outline" asChild><a href={`/api/files/${inv.document.id}`} target="_blank" rel="noopener"><FileText /> Their file</a></Button>}
                  {inv.status === 'document' && <Button size="sm" onClick={() => onAddFromFile(inv.supplier_name)}>Add the rates</Button>}
                  {statement.rfq.status === 'OPEN' && inv.status !== 'quoted' && <Button size="sm" variant="ghost" onClick={() => setOpen(open === inv.id ? null : inv.id)}><ExternalLink /> Send again</Button>}
                  {statement.rfq.status === 'OPEN' && <Button size="icon-sm" variant="ghost" aria-label={`Take back the link for ${inv.supplier_name}`} title="Take the link back: it stops working" onClick={() => void withdraw(inv)}><Trash2 /></Button>}
                </div>
              </div>
              {inv.message && <p className="mt-1 text-[13px] text-muted-foreground">"{inv.message}"</p>}
              {open === inv.id && <div className="mt-2"><SendButtons inv={inv} statement={statement} /></div>}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
