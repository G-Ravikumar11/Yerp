import { Skeleton, Modal } from '@/components/ui'
import { useEway, useEwayMeta, type EwayMeta } from '@/api/eway'
import { EwayForm } from './EwayForm'

/** One e-way bill: a draft is edited and checked for what the portal would refuse; once the portal issues it, its number is recorded. */
export function EwayModal({ id, fromTransfer, open, onClose }: { id: number | null; fromTransfer: string; open: boolean; onClose: () => void }) {
  const meta = useEwayMeta()
  const q = useEway(id)
  const ready = meta.data && (id === null || q.data)
  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()} title={q.data && id ? `${q.data.number}${q.data.ewb_no ? ` - EWB ${q.data.ewb_no}` : ''}` : `E-way bill${fromTransfer ? ` for ${fromTransfer}` : ''}`} size="xl">
      {open && (!ready ? <Skeleton className="h-64 w-full" /> : <EwayForm key={id ? q.data?.id : `new-${fromTransfer}`} meta={meta.data as EwayMeta} bill={id === null ? null : (q.data ?? null)} fromTransfer={fromTransfer} onClose={onClose} />)}
    </Modal>
  )
}
