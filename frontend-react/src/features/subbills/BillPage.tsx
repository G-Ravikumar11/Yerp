import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Clock, Download, FileText, Save } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, ConfirmDialog, Field, Input, Modal, NumField, Skeleton, Stat, StatGrid, StatusBadge, Textarea } from '@/components/ui'
import { billKeys, editBill, moveBill, useSubBill, type BillEdit, type BillLine, type BillMove, type SubBill } from '@/api/subbills'
import { PayModal } from '@/features/money/PayModal'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { ApiError } from '@/lib/api'
import { formatDate, formatQty } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'

export default function BillPage() {
  const { id } = useParams()
  const bill = useSubBill(Number(id))
  const [seed, setSeed] = useState(0)

  if (bill.isPending) {
    return (
      <div className="space-y-4" role="status" aria-label="Loading">
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    )
  }
  if (bill.isError || !bill.data) {
    return (
      <div className="mx-auto max-w-md py-20 text-center">
        <h1 className="text-2xl font-semibold">{bill.error instanceof ApiError && bill.error.status === 404 ? 'No such bill' : 'Could not open it'}</h1>
        <Button asChild className="mt-6">
          <Link to="/subcontractors/ra-bills">Back to RA bills</Link>
        </Button>
      </div>
    )
  }
  return <BillView key={`${bill.data.id}:${seed}`} bill={bill.data} reseed={() => setSeed((s) => s + 1)} />
}

const editFrom = (b: SubBill): BillEdit => ({
  period_from: b.period_from,
  period_to: b.period_to,
  bill_date: b.bill_date,
  work_type: b.work_type,
  work_name: b.work_name,
  hsn_sac: b.hsn_sac,
  debit_notes: b.debit_notes,
  advance_recovery: b.advance_recovery,
  other_deductions: Math.max(0, b.other_deductions - (b.material_recovered ?? 0)),
  deduction_notes: b.deduction_notes,
})

function Row({ label, value, strong, muted, negative, note }: { label: string; value: React.ReactNode; strong?: boolean; muted?: boolean; negative?: boolean; note?: string }) {
  return (
    <tr className={cn('border-b border-border last:border-0', strong && 'font-semibold', muted && 'text-muted-foreground')}>
      <td className="py-2 pr-4">
        {label}
        {note && <span className="ml-1.5 text-xs font-normal text-subtle">{note}</span>}
      </td>
      <td className={cn('tabular py-2 text-right', negative && 'text-danger')}>{value}</td>
    </tr>
  )
}

function BillView({ bill, reseed }: { bill: SubBill; reseed: () => void }) {
  const { can } = useSession()
  const [f, setF] = useState(() => editFrom(bill))
  const [initial] = useState(() => JSON.stringify(editFrom(bill)))
  const dirty = JSON.stringify(f) !== initial
  const [dialog, setDialog] = useState<'certify' | 'reject' | 'cancel' | 'accept' | null>(null)
  const [paying, setPaying] = useState(false)
  const [gangName, setGangName] = useState('')

  const editable = bill.editable && can('billing.manage')
  const set = <K extends keyof BillEdit>(k: K, v: BillEdit[K]) => setF((s) => ({ ...s, [k]: v }))
  const has = (a: string) => bill.actions.some((x) => x === a)

  const save = useAction(() => editBill(bill.id, f), { invalidate: [billKeys.all], onSuccess: reseed })
  const move = useAction(
    async (m: BillMove) => {
      // Sent as it stands on screen, not as it was last saved.
      if (m.action === 'submit' && editable && dirty) await editBill(bill.id, f)
      return moveBill(bill.id, m)
    },
    { invalidate: [billKeys.all, ['mb']], onSuccess: () => { setDialog(null); reseed() } },
  )

  const waiting = bill.route.find((r) => r.status === 'waiting')
  const lastStep = !waiting || waiting.step === bill.route.length
  const lines = bill.lines ?? []

  const columns: TableColumn<BillLine>[] = [
    { id: 'a', header: 'Activity', cell: (l) => <span className="font-mono text-xs">{l.activity_no}</span>, width: '5rem' },
    { id: 'd', header: 'Description', cell: (l) => <span className="line-clamp-2 max-w-md">{l.description}</span> },
    { id: 'o', header: 'Ordered', align: 'right', cell: (l) => `${formatQty(l.ordered_qty)} ${l.uom}`, hideBelow: 'lg' },
    { id: 'm', header: 'Measured to date', align: 'right', cell: (l) => formatQty(l.measured_to_date), hideBelow: 'md' },
    { id: 'p', header: 'Previously billed', align: 'right', cell: (l) => <span className="text-muted-foreground">{formatQty(l.previously_billed_qty)}</span>, hideBelow: 'md' },
    { id: 't', header: 'This bill', align: 'right', cell: (l) => <span className="font-medium">{formatQty(l.this_bill_qty)}</span> },
    { id: 'r', header: 'Rate', align: 'right', cell: (l) => formatINR(l.rate), hideBelow: 'lg' },
    { id: 'amt', header: 'Amount', align: 'right', cell: (l) => <span className="font-medium">{formatINR(l.amount)}</span> },
    { id: 'up', header: 'Up to date', align: 'right', cell: (l) => formatINR(l.upto_date_amount), hideBelow: 'xl' },
  ]

  const gst = bill.igst_amount ? [['IGST', bill.igst_amount, bill.gst_percent]] : [['CGST', bill.cgst_amount, bill.gst_percent / 2], ['SGST', bill.sgst_amount, bill.gst_percent / 2]]

  return (
    <>
      <div className="mb-6">
        <Link to={`/subcontractors/ra-bills?order=${bill.order_id}`} className="mb-3 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft className="size-3.5" /> RA bills
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-mono text-2xl font-semibold sm:text-3xl">{bill.number}</h1>
              <StatusBadge status={bill.status} />
            </div>
            <p className="mt-2 text-[15px] text-muted-foreground">
              {bill.contractor}
              {bill.vendor_code && <span className="ml-1.5 font-mono text-xs">{bill.vendor_code}</span>}
              {bill.project && ` · ${bill.project}`}
            </p>
            {bill.status === 'SUBMITTED' && bill.waiting_on && <p className="mt-1 text-[13px] text-warning">Waiting with {bill.waiting_on}.</p>}
            {bill.remarks && bill.status === 'DRAFT' && <p className="mt-2 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">Sent back: {bill.remarks}</p>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/sub-bills/${bill.id}/document.pdf`} target="_blank" rel="noopener">
                <FileText /> Certificate PDF
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <a href={`/api/sub-bills/${bill.id}/export.xlsx`}>
                <Download /> Excel
              </a>
            </Button>
            {editable && (
              <Button variant="secondary" loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
                <Save /> Save
              </Button>
            )}
            {has('SUBMIT') && can('billing.manage') && (
              <Button loading={move.isPending && move.variables?.action === 'submit'} onClick={() => move.mutate({ action: 'submit' })}>
                Submit
              </Button>
            )}
            {has('CERTIFY') && can('subcontracts.approve') && <Button onClick={() => setDialog('certify')}>{lastStep ? 'Certify' : 'Sign and pass on'}</Button>}
            {has('REJECT') && can('subcontracts.approve') && (
              <Button variant="outline" onClick={() => setDialog('reject')}>
                Send back
              </Button>
            )}
            {has('PAY') && can('bills.pay') && <Button onClick={() => setPaying(true)}>Pay</Button>}
            {bill.status !== 'DRAFT' && bill.status !== 'CANCELLED' && !bill.accepted_by_name && can('billing.manage') && (
              <Button variant="outline" size="sm" onClick={() => setDialog('accept')}>
                Gang accepted
              </Button>
            )}
            {has('CANCEL') && can('billing.manage') && (
              <Button variant="ghost" className="text-danger hover:bg-danger-soft hover:text-danger" onClick={() => setDialog('cancel')}>
                Cancel bill
              </Button>
            )}
          </div>
        </div>
      </div>

      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label="Previously billed" value={formatINR(bill.previously_billed)} />
        <Stat label="This bill" value={formatINR(bill.this_bill)} />
        <Stat label="Billed up to date" value={formatINR(bill.gross_to_date)} />
        <Stat label="Net payable" value={formatINR(bill.net_payable)} sub={bill.amount_in_words} />
      </StatGrid>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="min-w-0 space-y-5 lg:col-span-2">
          <div>
            <h2 className="mb-3 text-lg font-semibold">What is being claimed</h2>
            <DataTable
              label="Bill lines"
              rows={lines}
              columns={columns}
              rowKey={(l) => l.id}
              empty="Nothing on this bill."
              footer={
                <span className="tabular flex justify-between gap-4 text-foreground">
                  <span>{lines.length} lines</span>
                  <span className="font-semibold">{formatINR(lines.reduce((s, l) => s + l.amount, 0))}</span>
                </span>
              }
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>The certificate</CardTitle>
              <CardDescription>{editable ? 'The boxes on the certificate of payment. Put them right before sending it.' : 'As it prints.'}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Bill date" htmlFor="b-date">
                <Input id="b-date" type="date" disabled={!editable} value={f.bill_date} onChange={(e) => set('bill_date', e.target.value)} />
              </Field>
              <Field label="Period from" htmlFor="b-from">
                <Input id="b-from" type="date" disabled={!editable} value={f.period_from} onChange={(e) => set('period_from', e.target.value)} />
              </Field>
              <Field label="Period to" htmlFor="b-to">
                <Input id="b-to" type="date" disabled={!editable} value={f.period_to} onChange={(e) => set('period_to', e.target.value)} />
              </Field>
              <Field label="Type of work" htmlFor="b-type">
                <Input id="b-type" disabled={!editable} value={f.work_type} onChange={(e) => set('work_type', e.target.value)} />
              </Field>
              <Field label="Name of the work" htmlFor="b-name" className="lg:col-span-2">
                <Input id="b-name" disabled={!editable} value={f.work_name} onChange={(e) => set('work_name', e.target.value)} />
              </Field>
              <Field label="SAC / HSN" htmlFor="b-sac">
                <Input id="b-sac" disabled={!editable} value={f.hsn_sac} onChange={(e) => set('hsn_sac', e.target.value)} className="font-mono" />
              </Field>
              <Field label="Recoveries in debit notes (₹)" htmlFor="b-debit">
                <NumField id="b-debit" disabled={!editable} value={f.debit_notes} onValue={(n) => set('debit_notes', n)} />
              </Field>
              <Field label="Advance recovered (₹)" htmlFor="b-adv" hint="Never more than is still owed.">
                <NumField id="b-adv" disabled={!editable} value={f.advance_recovery} onValue={(n) => set('advance_recovery', n)} />
              </Field>
              <Field label="Other deductions (₹)" htmlFor="b-other" hint={bill.material_recovered ? `Besides ${formatINR(bill.material_recovered)} of material recovered.` : undefined}>
                <NumField id="b-other" disabled={!editable} value={f.other_deductions} onValue={(n) => set('other_deductions', n)} />
              </Field>
              <Field label="Deduction notes" htmlFor="b-notes" className="sm:col-span-2 lg:col-span-3">
                <Textarea id="b-notes" disabled={!editable} value={f.deduction_notes} onChange={(e) => set('deduction_notes', e.target.value)} rows={2} />
              </Field>
            </CardContent>
          </Card>
        </div>

        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader>
              <CardTitle>Certificate of payment</CardTitle>
              {bill.order_detail && (
                <CardDescription>
                  {bill.order_detail.number} · {bill.order_detail.subject}
                </CardDescription>
              )}
            </CardHeader>
            <CardContent>
              <table className="w-full text-[13.5px]">
                <tbody>
                  <Row label="Work measured in this bill" value={formatINR(bill.this_bill)} note="4.01" />
                  {bill.debit_notes > 0 && <Row label="Recoveries in debit notes" value={formatINR(bill.debit_notes)} negative />}
                  <Row label="Gross value" value={formatINR(bill.gross_value)} strong />
                  {gst.map(([name, amt, pct]) => (
                    <Row key={String(name)} label={`${name} @ ${pct}%`} value={formatINR(Number(amt))} muted />
                  ))}
                  {bill.advance_recovery > 0 && <Row label="Advance recovered" value={`- ${formatINR(bill.advance_recovery)}`} negative />}
                  {bill.other_deductions > 0 && <Row label="Material and other recoveries" value={`- ${formatINR(bill.other_deductions)}`} negative />}
                  <Row label={`Retention @ ${bill.retention_percent}%`} value={`- ${formatINR(bill.retention_amount)}`} negative />
                  <Row label={`TDS @ ${bill.tds_percent}%`} value={`- ${formatINR(bill.tds_amount)}`} negative />
                  {bill.labour_cess_amount > 0 && <Row label={`Labour cess @ ${bill.labour_cess_percent}%`} value={`- ${formatINR(bill.labour_cess_amount)}`} negative />}
                  <Row label="Net amount payable" value={formatINR(bill.net_payable)} strong />
                </tbody>
              </table>
              {bill.place_of_supply_name && <p className="mt-3 text-xs text-muted-foreground">Place of supply: {bill.place_of_supply_name}</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Signatures</CardTitle>
              <CardDescription>Prepared, certified in turn up the line, then approved.</CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3 text-[13.5px]">
                {bill.submitted_by_name && (
                  <li className="flex items-start gap-2.5">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                    <span>
                      Prepared by <strong>{bill.submitted_by_name}</strong>
                      <span className="block text-xs text-muted-foreground">{formatDate(bill.submitted_at)}</span>
                    </span>
                  </li>
                )}
                {bill.route.map((r) => (
                  <li key={r.step} className="flex items-start gap-2.5">
                    {r.status === 'approved' ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <Clock className={cn('mt-0.5 size-4 shrink-0', r.status === 'waiting' ? 'text-warning' : 'text-subtle')} />}
                    <span>
                      {r.name}
                      <Badge tone={r.status === 'approved' ? 'success' : r.status === 'waiting' ? 'warning' : 'neutral'} className="ml-2">
                        {r.status === 'approved' ? 'Signed' : r.status === 'waiting' ? 'Waiting' : 'Later'}
                      </Badge>
                      {r.decided_at && <span className="block text-xs text-muted-foreground">{formatDate(r.decided_at)}</span>}
                    </span>
                  </li>
                ))}
                {bill.accepted_by_name && (
                  <li className="flex items-start gap-2.5">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                    <span>
                      Accepted for the sub contractor by <strong>{bill.accepted_by_name}</strong>
                      <span className="block text-xs text-muted-foreground">{formatDate(bill.accepted_at)}</span>
                    </span>
                  </li>
                )}
                {bill.paid_at && (
                  <li className="flex items-start gap-2.5">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                    <span>
                      Paid {formatDate(bill.paid_at)}
                      {bill.paid_reference && <span className="block text-xs text-muted-foreground">{bill.paid_reference}</span>}
                    </span>
                  </li>
                )}
                {!bill.submitted_by_name && bill.route.length === 0 && <li className="text-muted-foreground">Not sent yet.</li>}
              </ol>
            </CardContent>
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={dialog === 'certify'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={lastStep ? `Certify ${bill.number}?` : 'Sign and pass it on?'}
        description={lastStep ? `Agreeing to pay ${formatINR(bill.net_payable)} to ${bill.contractor}.` : `Your signature goes on it, and it moves to the next person up the line.`}
        confirmLabel={lastStep ? 'Certify' : 'Sign and pass on'}
        reason={{ label: 'Note (optional)' }}
        loading={move.isPending}
        onConfirm={(comments) => move.mutate({ action: 'certify', comments })}
      />
      <ConfirmDialog
        open={dialog === 'reject'}
        onOpenChange={(o) => !o && setDialog(null)}
        title="Send it back?"
        description="It returns to a draft and its measurements are freed to be billed again."
        confirmLabel="Send back"
        reason={{ label: 'What needs putting right?', required: true }}
        loading={move.isPending}
        onConfirm={(comments) => move.mutate({ action: 'reject', comments })}
      />
      <ConfirmDialog
        open={dialog === 'cancel'}
        onOpenChange={(o) => !o && setDialog(null)}
        title={`Cancel ${bill.number}?`}
        description="Its measurements go back to waiting for the next bill. Refused while money has been paid against it."
        confirmLabel="Cancel the bill"
        tone="danger"
        reason={{ label: 'Why is it being cancelled?', required: true }}
        loading={move.isPending}
        onConfirm={(comments) => move.mutate({ action: 'cancel', comments })}
      />
      <Modal
        open={dialog === 'accept'}
        onOpenChange={(o) => !o && setDialog(null)}
        size="sm"
        title="Accepted for the sub contractor"
        description="The gang has signed the certificate. Recorded from the signed copy."
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>
              Not now
            </Button>
            <Button loading={move.isPending} onClick={() => move.mutate({ action: 'accept', name: gangName })}>
              Record it
            </Button>
          </>
        }
      >
        <Field label="Who signed for them?" htmlFor="b-signer" hint="Blank: the gang's contact person.">
          <Input id="b-signer" value={gangName} onChange={(e) => setGangName(e.target.value)} autoFocus />
        </Field>
      </Modal>
      <PayModal docType="sub_bill" docId={bill.id} title={bill.number} open={paying} onOpenChange={(o) => { setPaying(o); if (!o) reseed() }} invalidate={[billKeys.all]} />
    </>
  )
}
