import { useState } from 'react'
import { FileText, Link2, Pencil, Plus, Send, Trash2 } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog } from '@/components/ui'
import { rfqKeys, withdrawInvite, type RfqInvite, type Statement } from '@/api/rfq'
import { compare, supplierRows, type SupplierRow } from '@/lib/rfqCompare'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'
import { MasterDelete } from '@/features/deleteorder/MasterDelete'
import { AttachQuotation } from './QuoteCheck'
import { SendLinkModal } from './VendorLinks'

const norm = (s: string) => s.trim().toLowerCase()

function status(r: SupplierRow): { label: string; tone: 'neutral' | 'info' | 'success' | 'warning' } {
  if (r.quote) return { label: r.quote.source === 'vendor' ? 'Quoted through the link' : 'Quote entered', tone: 'success' }
  const s = r.invite?.status
  if (s === 'document') return { label: 'Sent a file: enter the rates', tone: 'warning' }
  if (s === 'opened') return { label: 'Opened the link', tone: 'info' }
  return { label: 'Link sent', tone: 'neutral' }
}

/** Who has been asked and who has answered, with what to do about each. */
export function SuppliersTab({ d, onAsk, onQuote }: { d: Statement; onAsk: () => void; onQuote: (supplier?: string) => void }) {
  const open = d.rfq.status === 'OPEN'
  const [sending, setSending] = useState<RfqInvite | null>(null)
  const [withdrawing, setWithdrawing] = useState<RfqInvite | null>(null)
  const withdraw = useAction((inv: RfqInvite) => withdrawInvite(d.rfq.id, inv.id), { invalidate: [rfqKeys.all], onSuccess: () => setWithdrawing(null) })
  const rank = compare(d, d.suppliers.map((s) => s.supplier_name)).rank
  const rows = supplierRows(d)

  const columns: TableColumn<SupplierRow>[] = [
    {
      id: 'name',
      header: 'Supplier',
      cell: (r) => (
        <div className="min-w-0">
          <div className="truncate font-medium">{r.name}</div>
          {r.invite && (r.invite.phone || r.invite.email) && <div className="truncate text-xs text-muted-foreground">{[r.invite.phone, r.invite.email].filter(Boolean).join(' · ')}</div>}
          {r.invite?.message && <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">“{r.invite.message}”</div>}
        </div>
      ),
    },
    { id: 'status', header: 'Status', width: '14rem', cell: (r) => { const s = status(r); return <Badge tone={s.tone} dot>{s.label}</Badge> } },
    {
      id: 'total',
      header: 'Total at site',
      width: '11rem',
      align: 'right',
      hideBelow: 'sm',
      cell: (r) => (r.quote ? (
        <div>
          <div className="inline-flex items-center gap-1.5 font-medium">
            {rank.get(r.name) && <span className={rank.get(r.name) === 'L1' ? 'rounded-md bg-success px-1.5 py-px text-[10px] font-bold text-white' : 'rounded-md bg-muted px-1.5 py-px text-[10px] font-bold text-muted-foreground'}>{rank.get(r.name)}</span>}
            {formatINR(r.quote.landed)}
          </div>
          {!r.quote.complete && <div className="text-xs text-warning">{r.quote.lines_quoted} of {d.lines.length} items priced</div>}
        </div>
      ) : <span className="text-muted-foreground">-</span>),
    },
    {
      id: 'file',
      header: 'Their quotation',
      width: '11rem',
      hideBelow: 'md',
      cell: (r) => {
        const doc = r.quote?.document ?? r.invite?.document
        if (doc) return <a className="inline-flex max-w-full items-center gap-1.5 text-[13px] text-primary hover:underline" href={`/api/files/${doc.id}`} target="_blank" rel="noopener"><FileText className="size-3.5 shrink-0" /><span className="truncate">{doc.name}</span></a>
        // A quote typed in from an email: keep the supplier's own file with it, for whoever checks the rates later.
        return open && r.quote ? <span className="text-[13px]"><AttachQuotation statement={d} supplier={r.quote} /></span> : <span className="text-muted-foreground">-</span>
      },
    },
    {
      id: 'act',
      header: '',
      width: open ? '15rem' : '3rem',
      align: 'right',
      cell: (r) => (
        <div className="flex items-center justify-end gap-1.5">
          {open && (r.quote
            ? <Button size="sm" variant="outline" onClick={() => onQuote(r.name)}><Pencil /> Edit quote</Button>
            : <Button size="sm" variant={r.invite?.status === 'document' ? 'primary' : 'outline'} onClick={() => onQuote(r.name)}>Enter the rates</Button>)}
          {open && r.invite && !r.quote && <Button size="icon-sm" variant="ghost" aria-label={`Send the link to ${r.name} again`} title="Send the link again" onClick={() => setSending(r.invite)}><Send /></Button>}
          {open && r.invite && !r.quote && <Button size="icon-sm" variant="ghost" aria-label={`Take back the link for ${r.name}`} title="Take the link back: it stops working" onClick={() => setWithdrawing(r.invite)}><Trash2 /></Button>}
          {open && r.quote && <MasterDelete kind="rfq_quote" id={r.quote.quote_id} label={`${r.name}'s quote`} noun="supplier quote" />}
        </div>
      ),
    },
  ]

  return (
    <section aria-label="Suppliers" className="grid gap-3">
      {open && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">Send each supplier a link to quote on their phone, or enter a quote they sent by email or WhatsApp.</p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onAsk}><Link2 /> Ask by link</Button>
            <Button onClick={() => onQuote()}><Plus /> Enter a quote</Button>
          </div>
        </div>
      )}
      <DataTable label="Suppliers on this enquiry" rows={rows} columns={columns} rowKey={(r) => norm(r.name)}
        empty={open ? 'Nobody asked yet. Ask suppliers by link, or enter a quote you already have.' : 'No supplier was asked.'} />
      <SendLinkModal invite={sending} statement={d} onClose={() => setSending(null)} />
      <ConfirmDialog open={!!withdrawing} onOpenChange={(o) => !o && setWithdrawing(null)} title={`Take back ${withdrawing?.supplier_name ?? ''}'s link?`}
        description="The link stops working. Ask them again later and they get a new one." confirmLabel="Take it back" tone="danger"
        loading={withdraw.isPending} onConfirm={() => { if (withdrawing) withdraw.mutate(withdrawing) }} />
    </section>
  )
}
