import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Link, Route, Routes, useNavigate } from 'react-router-dom'
import { Button, Card, Input, Select, SkeletonRows, Tabs } from '@/components/ui'
import { useSession } from '@/lib/session'
import { storeGet, storePerm, useStoreMeta, type DocStatus } from '@/api/store'
import { DocStatusBadge } from '../shared'
import { StoreShell } from '../StoreShell'
import { GrnView, ReturnView } from './DocView'
import { GrnForm } from './GrnForm'
import { ReturnForm } from './ReturnForm'
import { money, type Grn, type PurchaseReturn } from './types'

/** Store > Inward: goods received notes (with quality check) and purchase returns. */
export default function InwardIndex() {
  return (
    <StoreShell slice="inward">
      <Routes>
        <Route index element={<Lists />} />
        <Route path="grn/new" element={<GrnForm />} />
        <Route path="grn/:id/edit" element={<GrnForm />} />
        <Route path="grn/:id" element={<GrnView />} />
        <Route path="returns/new" element={<ReturnForm />} />
        <Route path="returns/:id" element={<ReturnView />} />
      </Routes>
    </StoreShell>
  )
}

function Lists() {
  const { can } = useSession()
  const nav = useNavigate()
  const meta = useStoreMeta()
  const [tab, setTab] = useState<'grn' | 'returns'>('grn')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const res = useQuery({
    queryKey: ['store', 'inward', 'list', tab, status, q],
    queryFn: () => storeGet<{ rows: (Grn | PurchaseReturn)[]; total: number }>('inward', `/${tab}?status=${status}&q=${encodeURIComponent(q)}`),
  })
  const rows = res.data?.rows ?? []
  const canCreate = can(storePerm('inward', 'create'))
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs label="Inward" value={tab} onChange={setTab} items={[{ value: 'grn', label: 'Goods received' }, { value: 'returns', label: 'Returns to supplier' }]} />
        {canCreate && <Button onClick={() => nav(tab === 'grn' ? 'grn/new' : 'returns/new')}><Plus /> {tab === 'grn' ? 'New GRN' : 'New return'}</Button>}
      </div>
      <div className="flex flex-wrap gap-3">
        <Input className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search number or supplier" />
        <Select className="w-44" value={status} placeholder="Any status" options={(meta.data?.doc_statuses ?? []).map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value as DocStatus)} />
      </div>
      {res.isLoading ? <SkeletonRows rows={6} cols={5} /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Number</th><th className="p-3">Date</th><th className="p-3">Supplier</th><th className="p-3 text-right">Lines</th><th className="p-3 text-right">Value</th><th className="p-3">Status</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0 hover:bg-accent/40">
                  <td className="p-3"><Link className="font-mono text-primary hover:underline" to={`${tab}/${r.id}`}>{r.number}</Link></td>
                  <td className="p-3">{'grn_date' in r ? r.grn_date : r.return_date}</td><td className="p-3">{r.supplier_name}</td>
                  <td className="p-3 text-right">{r.line_count}</td><td className="p-3 text-right">{money(r.total_value)}</td><td className="p-3"><DocStatusBadge status={r.status} /></td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={6} className="p-6 text-center text-muted-foreground">Nothing here yet.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
