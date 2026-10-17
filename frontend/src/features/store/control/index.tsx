import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { Link, Route, Routes, useNavigate } from 'react-router-dom'
import { Badge, Button, Card, Input, Select, SkeletonRows, Tabs } from '@/components/ui'
import { useSession } from '@/lib/session'
import { storeGet, storePerm, useStoreMeta } from '@/api/store'
import { DocStatusBadge } from '../shared'
import { StoreShell } from '../StoreShell'
import { AdjustmentForm, CountStart, ScrapForm, TransferForm } from './Forms'
import { AdjustmentView, CountView, ScrapView, TransferView } from './Views'
import { money, type Transfer } from './types'

/** Store > Control: transfers (with stock in transit), stock counts, adjustments and scrap. */
export default function ControlIndex() {
  return (
    <StoreShell slice="control">
      <Routes>
        <Route index element={<Lists />} />
        <Route path="transfers/new" element={<TransferForm />} />
        <Route path="transfers/:id/edit" element={<TransferForm />} />
        <Route path="transfers/:id" element={<TransferView />} />
        <Route path="counts/new" element={<CountStart />} />
        <Route path="counts/:id" element={<CountView />} />
        <Route path="adjustments/new" element={<AdjustmentForm />} />
        <Route path="adjustments/:id/edit" element={<AdjustmentForm />} />
        <Route path="adjustments/:id" element={<AdjustmentView />} />
        <Route path="scrap/new" element={<ScrapForm />} />
        <Route path="scrap/:id/edit" element={<ScrapForm />} />
        <Route path="scrap/:id" element={<ScrapView />} />
      </Routes>
    </StoreShell>
  )
}

type Tab = 'transfers' | 'transit' | 'counts' | 'adjustments' | 'scrap'
const LABEL: Record<string, string> = { transfers: 'New transfer', counts: 'Start a count', adjustments: 'New adjustment', scrap: 'New scrap note' }
interface Row { id: number; number: string; status: never; store_code: string; to_store_code?: string; trf_date?: string; count_date?: string; adj_date?: string; scrap_date?: string; kind?: string; reason?: string; transit?: string; total_value?: string; book_value?: string; realised_value?: string; variance_value?: string | null; counted_count?: number; line_count: number; inter_project?: boolean }

function Lists() {
  const { can } = useSession()
  const nav = useNavigate()
  const [tab, setTab] = useState<Tab>('transfers')
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs label="Control" value={tab} onChange={setTab} items={[{ value: 'transfers', label: 'Transfers' }, { value: 'transit', label: 'In transit' }, { value: 'counts', label: 'Stock counts' }, { value: 'adjustments', label: 'Adjustments' }, { value: 'scrap', label: 'Scrap' }]} />
        {can(storePerm('control', 'create')) && tab !== 'transit' && <Button onClick={() => nav(`${tab}/new`)}><Plus /> {LABEL[tab]}</Button>}
      </div>
      {tab === 'transit' ? <Transit /> : <Docs kind={tab} />}
    </div>
  )
}

function Docs({ kind }: { kind: 'transfers' | 'counts' | 'adjustments' | 'scrap' }) {
  const meta = useStoreMeta()
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const res = useQuery({ queryKey: ['store', 'control', 'list', kind, status, q], queryFn: () => storeGet<{ rows: Row[] }>('control', `/${kind}?status=${status}&q=${encodeURIComponent(q)}`) })
  const rows = res.data?.rows ?? []
  const date = (r: Row) => r.trf_date ?? r.count_date ?? r.adj_date ?? r.scrap_date
  const detail = (r: Row) => kind === 'transfers' ? <>{r.store_code} → {r.to_store_code} {r.inter_project && <Badge tone="warning">Inter-project</Badge>} {r.transit === 'IN_TRANSIT' && <Badge tone="info">In transit</Badge>}</>
    : kind === 'counts' ? `${r.store_code} · ${r.counted_count} of ${r.line_count} counted` : kind === 'adjustments' ? `${r.store_code} · ${r.kind?.toLowerCase()} · ${r.reason}` : `${r.store_code} · ${r.reason}`
  const value = (r: Row) => kind === 'counts' ? (r.variance_value == null ? '—' : money(r.variance_value)) : kind === 'scrap' ? money(r.realised_value ?? '0') : money(r.total_value ?? '0')
  return (
    <>
      <div className="flex flex-wrap gap-3">
        <Input className="max-w-xs" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search number" />
        <Select className="w-44" value={status} placeholder="Any status" options={(meta.data?.doc_statuses ?? []).map((s) => ({ value: s, label: s }))} onChange={(e) => setStatus(e.target.value)} />
      </div>
      {res.isLoading ? <SkeletonRows rows={6} cols={5} /> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Number</th><th className="p-3">Date</th><th className="p-3">Details</th><th className="p-3 text-right">{kind === 'counts' ? 'Net difference' : kind === 'scrap' ? 'Realised' : 'Value'}</th><th className="p-3">Status</th></tr></thead>
            <tbody>
              {rows.map((r) => <tr key={r.id} className="border-b border-border last:border-0 hover:bg-accent/40"><td className="p-3"><Link className="font-mono text-primary hover:underline" to={`${kind}/${r.id}`}>{r.number}</Link></td><td className="p-3">{date(r)}</td><td className="p-3">{detail(r)}</td><td className="p-3 text-right">{value(r)}</td><td className="p-3"><DocStatusBadge status={r.status} /></td></tr>)}
              {rows.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">Nothing here yet.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}
    </>
  )
}

function Transit() {
  const res = useQuery({ queryKey: ['store', 'control', 'in-transit'], queryFn: () => storeGet<{ rows: Transfer[] }>('control', '/in-transit') })
  const rows = res.data?.rows ?? []
  return res.isLoading ? <SkeletonRows rows={4} cols={5} /> : (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-border text-left text-xs uppercase text-muted-foreground"><th className="p-3">Transfer</th><th className="p-3">Route</th><th className="p-3">Sent</th><th className="p-3 text-right">Lines</th><th className="p-3 text-right">Value</th></tr></thead>
        <tbody>
          {rows.map((t) => <tr key={t.id} className="border-b border-border last:border-0"><td className="p-3"><Link className="font-mono text-primary hover:underline" to={`transfers/${t.id}`}>{t.number}</Link></td><td className="p-3">{t.store_code} → {t.to_store_code} {t.inter_project && <Badge tone="warning">Inter-project</Badge>}</td><td className="p-3">{t.trf_date}</td><td className="p-3 text-right">{t.line_count}</td><td className="p-3 text-right">{money(t.total_value)}</td></tr>)}
          {rows.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">Nothing is on the road.</td></tr>}
        </tbody>
      </table>
    </Card>
  )
}
