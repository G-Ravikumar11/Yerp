import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Link, Route, Routes, useNavigate } from 'react-router-dom'
import { Badge, Button, Card, Input, Select, SkeletonRows, Tabs } from '@/components/ui'
import { useSession } from '@/lib/session'
import { storeGet, storePerm, useStoreMeta } from '@/api/store'
import { DocStatusBadge } from '../shared'
import { StoreShell } from '../StoreShell'
import { IssueForm } from './IssueForm'
import { RequisitionForm } from './RequisitionForm'
import { ReturnForm } from './ReturnForm'
import { IssueView, RequisitionView, ReturnView } from './Views'
import { money, num } from './types'

/** Store > Outward: requisitions, issues to site and subcontractors, returns, outstanding returnables and write-off requests. */
export default function OutwardIndex() {
  return (
    <StoreShell slice="outward">
      <Routes>
        <Route index element={<Lists />} />
        <Route path="requisitions/new" element={<RequisitionForm />} />
        <Route path="requisitions/:id/edit" element={<RequisitionForm />} />
        <Route path="requisitions/:id" element={<RequisitionView />} />
        <Route path="issues/new" element={<IssueForm />} />
        <Route path="issues/:id/edit" element={<IssueForm />} />
        <Route path="issues/:id" element={<IssueView />} />
        <Route path="returns/new" element={<ReturnForm />} />
        <Route path="returns/:id" element={<ReturnView />} />
      </Routes>
    </StoreShell>
  )
}

type Tab = 'issues' | 'requisitions' | 'returns' | 'outstanding' | 'writeoffs'
interface DocRow { id: number; number: string; status: never; store_code: string; line_count: number; total_value?: string; issue_date?: string; req_date?: string; return_date?: string; purpose?: string; subcontractor_name?: string; issue_type?: string; direct?: boolean; issue_number?: string }

function Lists() {
  const { can } = useSession()
  const nav = useNavigate()
  const [tab, setTab] = useState<Tab>('issues')
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs label="Outward" value={tab} onChange={setTab} items={[{ value: 'issues', label: 'Issues' }, { value: 'requisitions', label: 'Requisitions' }, { value: 'returns', label: 'Returns' }, { value: 'outstanding', label: 'Outstanding returnables' }, { value: 'writeoffs', label: 'Write-off requests' }]} />
        {can(storePerm('outward', 'create')) && (tab === 'issues' || tab === 'requisitions') && <Button onClick={() => nav(`${tab}/new`)}><Plus /> {tab === 'issues' ? 'New issue' : 'New requisition'}</Button>}
      </div>
      {tab === 'outstanding' ? <Outstanding /> : tab === 'writeoffs' ? <Writeoffs /> : <Docs kind={tab} />}
    </div>
  )
}

function Docs({ kind }: { kind: 'issues' | 'requisitions' | 'returns' }) {
  const meta = useStoreMeta()
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const res = useQuery({ queryKey: ['store', 'outward', 'list', kind, status, q], queryFn: () => storeGet<{ rows: DocRow[]; total: number }>('outward', `/${kind}?status=${status}&q=${encodeURIComponent(q)}`) })
  const rows = res.data?.rows ?? []
  return (
    <>
      <div className="flex flex-wrap gap-3">
        <Input className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search number" />
        <Select className="w-44" value={status} placeholder="Any status" options={(meta.data?.doc_statuses ?? []).map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
      </div>
      {res.isLoading ? <SkeletonRows rows={6} cols={5} /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Number</th><th className="p-3">Date</th><th className="p-3">{kind === 'issues' ? 'Issued to' : kind === 'returns' ? 'Against' : 'Purpose'}</th><th className="p-3 text-right">Lines</th>{kind !== 'requisitions' && <th className="p-3 text-right">Value</th>}<th className="p-3">Status</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0 hover:bg-accent/40">
                  <td className="p-3"><Link className="font-mono text-primary hover:underline" to={`${kind}/${r.id}`}>{r.number}</Link></td>
                  <td className="p-3">{r.issue_date ?? r.req_date ?? r.return_date}</td>
                  <td className="p-3">{kind === 'issues' ? <>{r.issue_type === 'SUBCONTRACTOR' ? r.subcontractor_name : 'Site use'} {r.direct && <Badge tone="warning">Direct</Badge>}</> : kind === 'returns' ? r.issue_number : r.purpose}</td>
                  <td className="p-3 text-right">{r.line_count}</td>{kind !== 'requisitions' && <td className="p-3 text-right">{money(r.total_value ?? '0')}</td>}<td className="p-3"><DocStatusBadge status={r.status} /></td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={6} className="p-6 text-center text-muted-foreground">Nothing here yet.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}
    </>
  )
}

function Outstanding() {
  const res = useQuery({ queryKey: ['store', 'outward', 'outstanding'], queryFn: () => storeGet<{ rows: { issue_line_id: number; issue_id: number; issue_number: string; store_code: string; item_code: string; item_name: string; holder_name: string; qty_outstanding: string; expected_return_date: string | null; overdue_days: number }[] }>('outward', '/outstanding') })
  const rows = res.data?.rows ?? []
  return res.isLoading ? <SkeletonRows rows={5} cols={5} /> : (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Item</th><th className="p-3">Held by</th><th className="p-3 text-right">Still out</th><th className="p-3">Due</th><th className="p-3">Issue</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.issue_line_id} className="border-b border-border last:border-0">
              <td className="p-3"><span className="font-mono text-xs text-muted-foreground">{r.item_code}</span> {r.item_name}</td><td className="p-3">{r.holder_name}</td><td className="p-3 text-right">{num(r.qty_outstanding)}</td>
              <td className="p-3">{r.expected_return_date ?? '—'} {r.overdue_days > 0 && <Badge tone="danger">{r.overdue_days} days late</Badge>}</td>
              <td className="p-3"><Link className="font-mono text-primary hover:underline" to={`issues/${r.issue_id}`}>{r.issue_number}</Link></td>
            </tr>
          ))}
          {rows.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">Everything issued has come back.</td></tr>}
        </tbody>
      </table>
    </Card>
  )
}

function Writeoffs() {
  const res = useQuery({ queryKey: ['store', 'outward', 'writeoffs'], queryFn: () => storeGet<{ rows: { id: number; store_code: string; item_code: string; item_name: string; qty: string; reason: string; status: string }[] }>('outward', '/writeoffs?status=') })
  const rows = res.data?.rows ?? []
  return res.isLoading ? <SkeletonRows rows={5} cols={4} /> : (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Store</th><th className="p-3">Item</th><th className="p-3 text-right">Quantity</th><th className="p-3">Reason</th><th className="p-3">Status</th></tr></thead>
        <tbody>
          {rows.map((r) => <tr key={r.id} className="border-b border-border last:border-0"><td className="p-3 font-mono">{r.store_code}</td><td className="p-3">{r.item_name}</td><td className="p-3 text-right">{num(r.qty)}</td><td className="p-3">{r.reason}</td><td className="p-3"><Badge tone={r.status === 'OPEN' ? 'warning' : 'neutral'}>{r.status}</Badge></td></tr>)}
          {rows.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">No write-off requests. Material declared lost on a return appears here until Control writes it off.</td></tr>}
        </tbody>
      </table>
    </Card>
  )
}
