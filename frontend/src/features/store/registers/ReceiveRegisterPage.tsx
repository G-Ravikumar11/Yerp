import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { Badge, Button, Card } from '@/components/ui'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { formatDate } from '@/lib/format'
import { useSession } from '@/lib/session'
import { storePerm } from '@/api/store'
import { qty } from '../enquiry/api'
import { matching, useReceipts, type ReceiptLine } from './api'
import { RegisterFilters, RegisterHeader } from './RegisterParts'

const STATUS: Record<string, string> = { DRAFT: 'Draft', SUBMITTED: 'Waiting approval', APPROVED: 'Approved - to post' }

/** Store > Receive: every posted goods receipt, line by line. A new one is made on the goods receipt form, with its quality check. */
/** `storeId` given: it sits in the Store Desk, which chooses the store and has the heading. */
export function ReceiveList({ storeId: fixed }: { storeId?: number } = {}) {
  const embedded = fixed !== undefined
  const nav = useNavigate()
  const { can } = useSession()
  const [q, setQ] = useState('')
  const [own, setStoreId] = useState(0)
  const storeId = fixed ?? own
  const list = useReceipts(storeId)
  const rows = matching(list.data?.items ?? [], q, (r) => [r.item_name, r.item_code, r.supplier, r.number, r.po_number, r.received_by])
  const columns: TableColumn<ReceiptLine>[] = [
    { id: 'no', header: 'Receive #', width: '11.5rem', sort: (r) => r.number, cell: (r) => <div><span className="whitespace-nowrap font-mono text-[12.5px] font-medium text-primary">{r.number}</span>{r.status !== 'POSTED' && <div><Badge tone={r.status === 'APPROVED' ? 'info' : 'warning'}>{STATUS[r.status] ?? r.status}</Badge></div>}</div> },
    { id: 'item', header: 'Material', sort: (r) => r.item_name, cell: (r) => <span className="font-medium">{r.item_name}</span> },
    { id: 'qty', header: 'Quantity', align: 'right', width: '7rem', sort: (r) => Number(r.qty), cell: (r) => qty(r.qty) },
    { id: 'uom', header: 'Unit', width: '4rem', cell: (r) => r.uom },
    { id: 'vendor', header: 'Vendor', hideBelow: 'md', sort: (r) => r.supplier, cell: (r) => <div>{r.supplier || '-'}{r.po_number && <div className="font-mono text-xs text-muted-foreground">{r.po_number}</div>}</div> },
    { id: 'date', header: 'Date', width: '7.5rem', sort: (r) => r.date, cell: (r) => formatDate(r.date) },
    { id: 'by', header: 'Received by', width: '9rem', hideBelow: 'lg', cell: (r) => r.received_by || '-' },
  ]
  return (
    <div>
      <RegisterHeader embedded={embedded} title="Material Receive" description="Materials received from vendors." actions={!embedded && can(storePerm('inward', 'create')) &&
        <Button asChild><Link to="/store/receive/new"><Plus /> New Receive</Link></Button>} />
      <Card className="p-4">
        <RegisterFilters q={q} onQ={setQ} storeId={storeId} onStore={embedded ? undefined : setStoreId} />
        {list.isError ? <p role="alert" className="text-sm text-danger">Could not load the receipts.</p> : (
          <DataTable label="Material received" rows={rows} loading={list.isPending} columns={columns} rowKey={(r) => r.id}
            onRowClick={(r) => nav(`/store/receive/${r.grn_id}`)} empty="No material received yet." />
        )}
      </Card>
    </div>
  )
}

export default function ReceiveRegisterPage() {
  return <ReceiveList />
}
