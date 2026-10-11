import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Field, Input, Modal, Stat, StatGrid } from '@/components/ui'
import { createEstimate, estimateKeys, useEstimates, type Estimate } from '@/api/estimates'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

export const ESTIMATE_TONE = { DRAFT: 'neutral', SUBMITTED: 'warning', WON: 'success', LOST: 'danger', WITHDRAWN: 'danger' } as const

export default function EstimatesPage() {
  const nav = useNavigate()
  const { can } = useSession()
  const list = useEstimates()
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [client, setClient] = useState('')
  const create = useAction(() => createEstimate({ title: title.trim(), customer_name: client.trim() }), {
    invalidate: [estimateKeys.all],
    onSuccess: (r) => { setCreating(false); nav(`/clients/estimates/${r.estimate.id}`) },
  })

  const rows = list.data?.estimates ?? []
  const s = list.data?.summary
  const filters = useListFilters(rows, { search: (e) => [e.number, e.title, e.customer_name, e.tender_reference, e.work_order].join(' '), status: (e) => e.status, date: (e) => e.due_on })

  const columns: TableColumn<Estimate>[] = [
    { id: 'no', header: 'Tender', width: '7rem', sort: (e) => e.number, cell: (e) => <span className="font-mono text-[13px] font-semibold">{e.number}</span> },
    {
      id: 'title',
      header: 'Title',
      sort: (e) => e.title,
      cell: (e) => (
        <div className="max-w-sm">
          <div className="truncate">{e.title}</div>
          <div className="truncate text-xs text-muted-foreground">{[e.customer_name, e.tender_reference].filter(Boolean).join(' · ')}</div>
        </div>
      ),
    },
    { id: 'due', header: 'Due', hideBelow: 'md', sort: (e) => e.due_on, cell: (e) => formatDate(e.due_on) || '-' },
    { id: 'items', header: 'Items', hideBelow: 'lg', align: 'right', cell: (e) => e.item_count },
    { id: 'cost', header: 'Cost', hideBelow: 'lg', align: 'right', cell: (e) => formatINR(e.cost_total) },
    {
      id: 'quoted',
      header: 'We ask',
      align: 'right',
      sort: (e) => e.quoted_total,
      cell: (e) => (
        <div>
          <span className="font-bold">{formatINR(e.quoted_total)}</span>
          <div className="text-xs font-normal text-muted-foreground">{e.margin_percent}% margin</div>
        </div>
      ),
    },
    {
      id: 'status',
      header: 'Status',
      cell: (e) => (
        <div>
          <Badge tone={ESTIMATE_TONE[e.status] ?? 'neutral'}>{e.status.charAt(0) + e.status.slice(1).toLowerCase()}</Badge>
          {e.work_order && <div className="mt-1 text-xs text-muted-foreground">→ {e.work_order}</div>}
        </div>
      ),
    },
    {
      id: 'act',
      header: '',
      align: 'right',
      cell: (e) => (
        <div className="flex justify-end gap-1.5" onClick={(ev) => ev.stopPropagation()}>
          <Button size="sm" onClick={() => nav(`/clients/estimates/${e.id}`)}>Open</Button>
          <Button size="sm" variant="outline" asChild>
            <a href={`/api/estimates/${e.id}/export.xlsx`} title="As a workbook"><Download /> Excel</a>
          </Button>
        </div>
      ),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Clients"
        title="Tenders & Estimates"
        description="Tenders priced rate by rate, and the work order a won one becomes. Pricing the job is where the business starts."
        actions={can('billing.manage') && <Button onClick={() => setCreating(true)}><Plus /> New estimate</Button>}
      />
      <StatGrid className="xl:grid-cols-4">
        <Stat label="Open tenders" value={s?.open ?? 0} loading={list.isPending} />
        <Stat label="Out for decision" value={compactINR(s?.out_for_decision)} loading={list.isPending} />
        <Stat label="Won" value={compactINR(s?.won_value)} loading={list.isPending} />
        <Stat label="Strike rate" value={`${s?.strike_rate ?? 0}%`} loading={list.isPending} />
      </StatGrid>
      <FilterBar filters={filters} placeholder="Search by number, title, client or reference..." />
      <DataTable label="Estimates" rows={filters.filtered} columns={columns} rowKey={(e) => e.id} loading={list.isPending} onRowClick={(e) => nav(`/clients/estimates/${e.id}`)} empty={filters.active ? 'Nothing matches those filters.' : 'No tenders yet. Pricing the job is where the business starts.'} />

      <Modal open={creating} onOpenChange={setCreating} title="New estimate" description="Open a tender to price. Overhead and profit start at 10% and 8%, and can be changed on the estimate.">
        <div className="grid gap-4">
          <Field label="What is the tender for?" htmlFor="es-title"><Input id="es-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="295 KLD STP, Vizag" autoFocus /></Field>
          <Field label="Client (who issued the tender)" htmlFor="es-client"><Input id="es-client" value={client} onChange={(e) => setClient(e.target.value)} /></Field>
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            {create.error && <p role="alert" className="mr-auto text-[13px] text-danger">{create.error.message}</p>}
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button loading={create.isPending} disabled={!title.trim()} onClick={() => create.mutate()}>Open it</Button>
          </div>
        </div>
      </Modal>
    </>
  )
}
