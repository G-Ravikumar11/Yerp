import { useState } from 'react'
import { FileText } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, ConfirmDialog, Stat, StatGrid } from '@/components/ui'
import { actOnRaBill, bookKeys, useRaBills, type RaBill } from '@/api/clientBook'
import { PayModal } from '@/features/money/PayModal'
import { EInvoiceModal } from '@/features/einvoice/EInvoiceModal'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { compactINR, formatINR } from '@/lib/utils'

const TONE: Record<string, 'neutral' | 'warning' | 'success' | 'danger'> = { DRAFT: 'neutral', SUBMITTED: 'warning', CERTIFIED: 'success', PAID: 'success', CANCELLED: 'danger' }
const link = 'text-primary underline-offset-2 hover:underline'

/** The running account bills drawn from the book: submitted, certified, then paid. Each step shown only to whoever may take it. */
export function BillsPanel({ workOrderId }: { workOrderId: number }) {
  const { can } = useSession()
  const q = useRaBills(workOrderId)
  const [paying, setPaying] = useState<RaBill | null>(null)
  const [sendingBack, setSendingBack] = useState<RaBill | null>(null)
  const [einvoice, setEinvoice] = useState<number | null>(null)
  const refresh = [bookKeys.all]
  const act = useAction((a: { b: RaBill; action: 'submit' | 'certify' | 'reject'; comments?: string }) => actOnRaBill(a.b.id, a.action, a.comments ?? ''), { invalidate: refresh, onSuccess: () => setSendingBack(null) })

  const bills = q.data?.bills ?? []
  const s = q.data?.summary
  // What has fallen due in total, bill by bill: the net payable of this one and every one before it.
  const cumulative = new Map<number, number>()
  let running = 0
  bills
    .slice()
    .sort((a, b) => (a.sequence || 0) - (b.sequence || 0) || a.id - b.id)
    .forEach((b) => {
      if (b.status !== 'CANCELLED') running += b.net_payable || 0
      cumulative.set(b.id, running)
    })

  const step = (b: RaBill) => {
    if (b.actions.includes('SUBMIT') && can('billing.manage'))
      return (
        <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ b, action: 'submit' })}>
          Submit
        </Button>
      )
    if (b.actions.includes('CERTIFY') && can('subcontracts.approve'))
      return (
        <>
          <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ b, action: 'certify' })}>
            Certify
          </Button>
          <Button size="sm" variant="outline" onClick={() => setSendingBack(b)}>
            Send back
          </Button>
        </>
      )
    if (b.actions.includes('PAY') && can('bills.pay'))
      return (
        <Button size="sm" onClick={() => setPaying(b)}>
          Receive
        </Button>
      )
    return null
  }

  const columns: TableColumn<RaBill>[] = [
    { id: 'no', header: 'Bill', sort: (b) => b.sequence, cell: (b) => <span className="font-mono text-[13px] font-semibold">{b.number}</span> },
    { id: 'prev', header: 'Previous', hideBelow: 'lg', align: 'right', cell: (b) => formatINR(b.previously_billed) },
    { id: 'this', header: 'This bill', align: 'right', cell: (b) => formatINR(b.this_bill) },
    { id: 'upto', header: 'Up to date', hideBelow: 'lg', align: 'right', cell: (b) => formatINR(b.gross_to_date) },
    { id: 'ret', header: 'Retention', hideBelow: 'xl', align: 'right', cell: (b) => formatINR(b.retention_amount) },
    {
      id: 'tax',
      header: 'GST',
      hideBelow: 'md',
      align: 'right',
      cell: (b) => (
        <div className="text-xs leading-5">
          {b.igst_amount ? (
            <div>IGST {b.igst_percent}% <span className="tabular font-medium">{formatINR(b.igst_amount)}</span></div>
          ) : b.cgst_amount || b.sgst_amount ? (
            <>
              <div>CGST {b.cgst_percent}% <span className="tabular font-medium">{formatINR(b.cgst_amount)}</span></div>
              <div>SGST {b.sgst_percent}% <span className="tabular font-medium">{formatINR(b.sgst_amount)}</span></div>
            </>
          ) : (
            <span className="text-muted-foreground">-</span>
          )}
        </div>
      ),
    },
    { id: 'net', header: 'Net payable', align: 'right', cell: (b) => <span className="font-semibold">{formatINR(b.net_payable)}</span> },
    { id: 'cum', header: 'Cumulative net', hideBelow: 'xl', align: 'right', cell: (b) => formatINR(cumulative.get(b.id)) },
    {
      id: 'status',
      header: 'Status',
      cell: (b) => (
        <div>
          <Badge tone={TONE[b.status] ?? 'neutral'}>{b.status.charAt(0) + b.status.slice(1).toLowerCase()}</Badge>
          {b.certified_by_name && <div className="mt-1 text-xs text-muted-foreground">{b.certified_by_name}</div>}
        </div>
      ),
    },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (b) => (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          {step(b)}
          <Button size="sm" variant="outline" asChild>
            <a href={`/api/ra-bills/${b.id}/document.pdf`} target="_blank" rel="noopener" title="The bill in the ruled form it is signed on">
              <FileText /> PDF
            </a>
          </Button>
          <a className={`${link} text-xs`} href={`/api/ra-bills/${b.id}/export.xlsx`} title="As a workbook">
            Excel
          </a>
          {(b.status === 'CERTIFIED' || b.status === 'PAID') && can('accounts.manage') && (
            <button type="button" className={`${link} text-xs`} onClick={() => setEinvoice(b.id)} title="The file for the GST Invoice Registration Portal">
              e-Invoice
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <section aria-label="Running account bills" className="mt-10">
      <h2 className="mb-3 text-lg font-semibold">Running account bills</h2>
      <StatGrid>
        <Stat label="Claimed" value={compactINR(s?.claimed)} loading={q.isPending} />
        <Stat label="Awaiting certification" value={s?.awaiting_certification ?? 0} loading={q.isPending} />
        <Stat label="Certified, unpaid" value={compactINR(s?.certified_unpaid)} loading={q.isPending} />
        <Stat label="Retention held" value={compactINR(s?.retention_held)} loading={q.isPending} />
        <Stat label="Paid" value={compactINR(s?.paid)} loading={q.isPending} />
      </StatGrid>
      <DataTable label="Running account bills" rows={bills} columns={columns} rowKey={(b) => b.id} loading={q.isPending} empty="No bills yet. Measure the work, then draw one up." />

      <EInvoiceModal docType="ra_bill" docId={einvoice} onClose={() => setEinvoice(null)} />
      {paying && <PayModal docType="ra_bill" docId={paying.id} title={paying.number} verb="Receive" open onOpenChange={(o) => !o && setPaying(null)} invalidate={[bookKeys.all]} />}
      <ConfirmDialog
        open={!!sendingBack}
        onOpenChange={(o) => !o && setSendingBack(null)}
        title={`Send ${sendingBack?.number ?? ''} back?`}
        confirmLabel="Send back"
        reason={{ label: 'Why is this going back?', required: true }}
        loading={act.isPending}
        onConfirm={(comments) => {
          if (sendingBack) act.mutate({ b: sendingBack, action: 'reject', comments })
        }}
      />
    </section>
  )
}
