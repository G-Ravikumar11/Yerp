import { useRef, useState } from 'react'
import { Columns2, FileUp, Paperclip, Trash2 } from 'lucide-react'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Modal } from '@/components/ui'
import { api } from '@/lib/api'
import { billKeys, type SubBill } from '@/api/subbills'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { cn, formatINR } from '@/lib/utils'

const isImage = (type: string) => type.startsWith('image/')

function attach(id: number, file: File, amount: string) {
  const form = new FormData()
  form.append('file', file)
  form.append('amount', amount)
  return api<{ bill: SubBill; message: string }>(`/api/sub-bills/${id}/hardcopy`, { method: 'POST', body: form })
}

/** The contractor's own bill as it came on paper, scanned: attached before the bill is sent, read beside ours by whoever approves it. */
export function HardCopy({ bill, canAttach, onChanged }: { bill: SubBill; canAttach: boolean; onChanged: () => void }) {
  const file = useRef<HTMLInputElement>(null)
  const [amount, setAmount] = useState(() => (bill.hardcopy?.amount != null ? String(bill.hardcopy.amount) : ''))
  const [comparing, setComparing] = useState(false)
  const h = bill.hardcopy
  const url = `/api/sub-bills/${bill.id}/hardcopy`
  const draft = bill.status === 'DRAFT'

  const put = useAction((f: File) => attach(bill.id, f, amount), { invalidate: [billKeys.all], success: (r) => r.message, onSuccess: onChanged })
  const remove = useAction(() => api<{ message: string }>(`/api/sub-bills/${bill.id}/hardcopy`, { method: 'DELETE' }), { invalidate: [billKeys.all], onSuccess: onChanged })

  if (!h && !(canAttach && draft)) return null
  const differs = h?.difference != null && Math.abs(h.difference) > 0.5

  return (
    <Card className={cn(!h && bill.scan_required && 'border-warning/50')}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Paperclip className="size-4" /> The contractor&apos;s own bill
        </CardTitle>
        <CardDescription>{h ? 'Read it beside this bill before approving: the figures and the quantities should agree.' : bill.scan_required ? 'Attach their bill, as it came on paper (a PDF, or a photo of it), before sending this for approval.' : 'Optional: their bill as it came on paper.'}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {h ? (
          <div className="flex flex-wrap items-center gap-3 text-[13.5px]">
            <a href={url} target="_blank" rel="noopener" className="font-medium text-primary underline underline-offset-4">
              {h.name}
            </a>
            <span className="text-muted-foreground">
              attached by {h.by} on {formatDate(h.at.slice(0, 10))}
            </span>
            {h.amount != null && (
              <span className="tabular">
                Their bill: <strong>{formatINR(h.amount)}</strong> of work
              </span>
            )}
            {h.difference != null && <Badge tone={differs ? 'danger' : 'success'}>{differs ? `this bill is ${formatINR(Math.abs(h.difference))} ${h.difference > 0 ? 'more' : 'less'}` : 'the amounts agree'}</Badge>}
          </div>
        ) : null}
        <div className="flex flex-wrap items-end gap-2">
          {canAttach && draft && (
            <>
              <div className="w-56">
                <label htmlFor="scan-amount" className="mb-1 block text-xs text-muted-foreground">
                  Amount of work on their bill (optional)
                </label>
                <Input id="scan-amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="Before tax" />
              </div>
              <input
                ref={file}
                type="file"
                hidden
                accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                aria-label="The contractor's bill"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  e.target.value = ''
                  if (f) put.mutate(f)
                }}
              />
              <Button variant={h ? 'outline' : 'primary'} size="sm" loading={put.isPending} onClick={() => file.current?.click()}>
                <FileUp /> {h ? 'Replace it' : 'Attach their bill'}
              </Button>
              {h && (
                <Button variant="ghost" size="sm" loading={remove.isPending} onClick={() => remove.mutate()}>
                  <Trash2 /> Remove
                </Button>
              )}
            </>
          )}
          {h && (
            <Button variant="outline" size="sm" onClick={() => setComparing(true)}>
              <Columns2 /> Compare side by side
            </Button>
          )}
        </div>
      </CardContent>
      {h && (
        <Modal open={comparing} onOpenChange={setComparing} size="xl" title={`${bill.number}: ours and theirs`} description="The bill drawn up from the measurement book, and the contractor's own bill as they sent it.">
          <div className="grid gap-3 lg:grid-cols-2">
            <div>
              <p className="mb-1 text-[13px] font-medium">This bill - {formatINR(bill.this_bill)} of work</p>
              <iframe title="This bill" src={`/api/sub-bills/${bill.id}/document.pdf`} className="h-[65vh] w-full rounded-lg border border-border bg-white" />
            </div>
            <div>
              <p className="mb-1 text-[13px] font-medium">Their bill{h.amount != null ? ` - ${formatINR(h.amount)} of work` : ''}</p>
              {isImage(h.type) ? (
                <div className="h-[65vh] overflow-auto rounded-lg border border-border bg-white">
                  <img src={url} alt="The contractor's bill" className="w-full" />
                </div>
              ) : (
                <iframe title="The contractor's bill" src={url} className="h-[65vh] w-full rounded-lg border border-border bg-white" />
              )}
            </div>
          </div>
        </Modal>
      )}
    </Card>
  )
}
