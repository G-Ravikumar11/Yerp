import { useState } from 'react'
import { Download } from 'lucide-react'
import { Button, ConfirmDialog, Field, Input, Modal, Skeleton, Textarea } from '@/components/ui'
import { cancelIrn, einvoiceKeys, recordIrn, useEInvoice, type IrnInput } from '@/api/einvoice'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

/**
 * The bill as the GST portal's e-invoice: download the file, register it on the portal, then paste back
 * what the portal returns so the IRN and signed QR go on the printed bill.
 */
export function EInvoiceModal({ docType, docId, onClose }: { docType: string; docId: number | null; onClose: () => void }) {
  return (
    <Modal open={docId != null} onOpenChange={(o) => !o && onClose()} title="e-Invoice" size="lg">
      {docId != null && <Body type={docType} id={docId} onClose={onClose} />}
    </Modal>
  )
}

function Body({ type, id, onClose }: { type: string; id: number; onClose: () => void }) {
  const q = useEInvoice(type, id, true)
  const [pasted, setPasted] = useState('')
  const [irn, setIrn] = useState('')
  const [ack, setAck] = useState('')
  const [ackDt, setAckDt] = useState('')
  const [qr, setQr] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const refresh = [einvoiceKeys.one(type, id), ['client-book'], ['owed']]
  const body = (): IrnInput => (pasted.trim() ? { response: pasted.trim() } : { irn: irn.trim(), ack_no: ack.trim(), ack_date: ackDt.trim(), signed_qr: qr.trim() })
  const save = useAction(() => recordIrn(type, id, body()), { invalidate: refresh })
  const cancel = useAction((reason: string) => cancelIrn(q.data!.irn!.id, reason), { invalidate: refresh, onSuccess: () => setCancelling(false) })

  const d = q.data
  if (!d) return <Skeleton className="h-40 w-full" />
  const v = d.payload?.ValDtls
  return (
    <div>
      <p className="mb-3 font-mono text-sm font-semibold">{d.number}</p>
      {d.irn ? (
        <div className="flex flex-wrap items-start gap-4">
          <img src={d.irn.qr_url} alt="Signed QR" className="size-36 rounded-md border border-border" />
          <div className="min-w-56 flex-1 text-sm">
            <p className="mb-1.5 font-bold text-success">Registered on the e-invoice portal</p>
            <p className="text-xs text-muted-foreground">IRN</p>
            <p className="break-all font-mono text-xs">{d.irn.irn}</p>
            <p className="mt-1.5"><span className="text-xs text-muted-foreground">Ack no.</span> {d.irn.ack_no} <span className="ml-2 text-xs text-muted-foreground">on</span> {d.irn.ack_date}</p>
            {d.irn.ewb_no && <p><span className="text-xs text-muted-foreground">E-way bill</span> {d.irn.ewb_no}</p>}
            <p className="mt-1.5 text-xs text-muted-foreground">Recorded by {d.irn.created_by_name}. The QR prints on the bill.</p>
          </div>
        </div>
      ) : d.ready && d.payload && v ? (
        <div>
          <table className="mb-3 w-full text-sm">
            <tbody>
              <tr><td>Invoice no.</td><td className="text-right font-mono">{d.payload.DocDtls.No}</td></tr>
              <tr><td>Buyer GSTIN</td><td className="text-right font-mono">{d.payload.BuyerDtls.Gstin}</td></tr>
              <tr><td>Taxable value</td><td className="text-right">{formatINR(v.AssVal)}</td></tr>
              <tr><td>GST</td><td className="text-right">{formatINR(v.CgstVal + v.SgstVal + v.IgstVal)}</td></tr>
              <tr className="font-semibold"><td>Invoice value</td><td className="text-right">{formatINR(v.TotInvVal)}</td></tr>
            </tbody>
          </table>
          <p className="mb-3 text-[13px] text-muted-foreground">1. Download the file and upload it at einvoice1.gst.gov.in. 2. Paste back what the portal returns, so the IRN and QR go on the bill.</p>
          <Field label="The portal's response (JSON)" htmlFor="ei-json">
            <Textarea id="ei-json" rows={4} value={pasted} onChange={(e) => setPasted(e.target.value)} placeholder='{"AckNo": ..., "AckDt": ..., "Irn": ..., "SignedQRCode": ...}' />
          </Field>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer">Or type the fields in</summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="IRN" htmlFor="ei-irn" className="sm:col-span-2"><Input id="ei-irn" className="font-mono" value={irn} onChange={(e) => setIrn(e.target.value)} /></Field>
              <Field label="Ack no." htmlFor="ei-ack"><Input id="ei-ack" value={ack} onChange={(e) => setAck(e.target.value)} /></Field>
              <Field label="Ack date and time" htmlFor="ei-ackdt"><Input id="ei-ackdt" placeholder="26/09/2026 11:02:00" value={ackDt} onChange={(e) => setAckDt(e.target.value)} /></Field>
              <Field label="Signed QR code" htmlFor="ei-qr" className="sm:col-span-2"><Textarea id="ei-qr" rows={3} value={qr} onChange={(e) => setQr(e.target.value)} /></Field>
            </div>
          </details>
        </div>
      ) : (
        <div className="text-sm">
          <p>The portal will not take this bill yet. Still needed:</p>
          <ul className="mt-2 list-disc pl-5">{(d.missing ?? []).map((m) => <li key={m} className="my-1">{m}</li>)}</ul>
        </div>
      )}
      {!!d.history?.length && <p className="mt-3 text-xs text-muted-foreground">Earlier: {d.history.map((h) => `IRN ${h.irn.slice(0, 12)}... cancelled ${h.cancelled_at.slice(0, 10)} (${h.cancel_reason})`).join('; ')}</p>}

      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Close</Button>
        {d.irn?.cancellable && <Button variant="outline" className="text-danger" onClick={() => setCancelling(true)}>Cancelled on the portal</Button>}
        {!d.irn && d.ready && (
          <>
            <Button variant="outline" asChild><a href={`/api/einvoice/${type}/${id}/json`}><Download /> Download the file</a></Button>
            <Button loading={save.isPending} disabled={!pasted.trim() && !irn.trim()} onClick={() => save.mutate()}>Record the IRN</Button>
          </>
        )}
      </div>
      <ConfirmDialog open={cancelling} onOpenChange={setCancelling} title="Record the IRN as cancelled?" description="The portal cancels an IRN only within a day of registering it." confirmLabel="Record it" tone="danger" reason={{ label: 'The reason you gave on the portal (duplicate, data entry mistake, order cancelled)', required: true }} loading={cancel.isPending} onConfirm={(r) => cancel.mutate(r)} />
    </div>
  )
}
