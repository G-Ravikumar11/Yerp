import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { Button, Field, Input, Modal, Skeleton } from '@/components/ui'
import { buttonVariants } from '@/components/ui/button'
import { get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { Section } from './Section'

interface WipePreview {
  phrase: string
  subcontract: number
  client: number
  sub_bills: number
  ra_bills: number
}

/** The owner's reset: every work order, with everything attached, gone. Typed out to confirm; backup first. */
export function WipeWorkOrders() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  const q = useQuery({ queryKey: ['settings', 'wipe'], queryFn: () => get<WipePreview>('/api/work-orders/delete-all-preview'), retry: false, staleTime: 0 })
  const wipe = useAction(() => post<{ message?: string }>('/api/work-orders/delete-all', { confirm: typed }), {
    invalidate: [],
    onSuccess: async () => {
      setOpen(false)
      setTyped('')
      await qc.invalidateQueries()
    },
  })
  // Not the owner, or not signed in as one: the server said no, so the block is left out.
  if (q.isError) return null
  const p = q.data
  return (
    <Section title="Delete all work orders" description="A full reset of work orders: gang orders and client orders, with their measurements, bills, payments, receipts, retention and files. There is no undo.">
      {q.isPending || !p ? <Skeleton className="h-16 w-full" /> : (
        <>
          <p className="text-sm text-muted-foreground">
            {p.subcontract} gang order{p.subcontract === 1 ? '' : 's'} with {p.sub_bills} bill{p.sub_bills === 1 ? '' : 's'}, and {p.client} client order{p.client === 1 ? '' : 's'} with {p.ra_bills} RA bill{p.ra_bills === 1 ? '' : 's'}.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <a className={buttonVariants({ variant: 'outline' })} href="/api/backup?files=1" download><Download /> Download a backup first</a>
            <Button variant="danger" disabled={p.subcontract + p.client === 0} onClick={() => setOpen(true)}>Delete all work orders</Button>
          </div>
          <Modal
            open={open}
            onOpenChange={setOpen}
            title="Delete every work order?"
            description="Payments and receipts on them go too. GST and TDS already filed are not changed, so your filings and books will differ."
            footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Keep them</Button><Button variant="danger" loading={wipe.isPending} disabled={typed.trim() !== p.phrase} onClick={() => wipe.mutate()}>Delete everything</Button></>}
          >
            <Field label={`Type ${p.phrase} to confirm`} htmlFor="wipe-phrase">
              <Input id="wipe-phrase" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
            </Field>
          </Modal>
        </>
      )}
    </Section>
  )
}
