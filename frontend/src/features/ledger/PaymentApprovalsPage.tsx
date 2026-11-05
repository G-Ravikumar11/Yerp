import { PageHeader } from '@/components/layout/PageHeader'
import { RequestsTab } from './RequestsTab'

/** Payments waiting on a signature, on a page of their own: the accounts head checks, the MD releases what is over the limit, accounts pay. */
export default function PaymentApprovalsPage() {
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Payment Approvals" description="Payments waiting for a decision. Accounts ask, the accounts head checks, the MD releases those over the limit, and accounts pay what is approved." />
      <RequestsTab />
    </>
  )
}
