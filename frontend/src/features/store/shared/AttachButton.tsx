import { useState } from 'react'
import { Paperclip } from 'lucide-react'
import { Button } from '@/components/ui'
import { FilesModal } from '@/components/data/FilesModal'

/** The Store record a file may be kept against, by the name the server knows it as. */
export const ATTACH_TYPE = {
  inward: { grn: 'store_grn', returns: 'store_purchase_return', 'client-supply': 'store_client_supply', opening: 'store_opening' },
  outward: { issue: 'store_issue', returns: 'store_issue_return' },
  control: { transfer: 'store_transfer', count: 'store_count', scrap: 'store_scrap' },
} as const

/** Photos and papers kept against a store document: a delivery challan, a damage photo, a mill certificate. */
export function AttachButton({ type, id, title }: { type?: string; id: number; title: string }) {
  const [open, setOpen] = useState(false)
  if (!type) return null
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}><Paperclip /> Photos and files</Button>
      {open && <FilesModal type={type} id={id} title={title} onClose={() => setOpen(false)} />}
    </>
  )
}
