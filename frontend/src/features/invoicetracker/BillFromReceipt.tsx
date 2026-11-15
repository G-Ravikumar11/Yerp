import { Link } from 'react-router-dom'
import { FilePlus2 } from 'lucide-react'
import { Badge, Button } from '@/components/ui'
import { billFromReceipt, trackerKeys, type ReceiptBill } from '@/api/invoiceTracker'
import { billKeys } from '@/api/bills'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'

/** Who may draw a draft bill from a receipt: the store, purchase, or accounts. Accounts then check and accept it. */
export const BILL_FROM_RECEIPT = 'stores.receive|stores.manage|purchase.manage|accounts.manage|bills.pay|store.inward.post|store.admin'

/** The bills drawn from one posted receipt, and a button to draw a draft bill for what is not on one yet.
 *  `grnId` is as the tracker keys receipts: an old store receipt's id, or minus a Store Hub receipt's. */
export function BillFromReceipt({ grnId, bills, billable, size = 'sm' }: { grnId: number; bills: ReceiptBill[]; billable: boolean; size?: 'sm' | 'md' }) {
  const { can } = useSession()
  const make = useAction(() => billFromReceipt(grnId), { invalidate: [trackerKeys.all, billKeys.all] })
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {bills.map((b) => (
        <Link key={b.id} to="/money/supplier-bills" title={`${b.status} - open Supplier Bills`}>
          <Badge tone={b.status === 'Draft' ? 'warning' : 'success'} dot>{b.number}</Badge>
        </Link>
      ))}
      {billable && can(BILL_FROM_RECEIPT) && (
        <Button size={size} variant="outline" loading={make.isPending} onClick={() => make.mutate()}>
          <FilePlus2 /> {bills.length ? 'Bill the rest' : 'Create bill'}
        </Button>
      )}
      {!billable && !bills.length && <span className="text-xs text-muted-foreground">-</span>}
    </div>
  )
}
