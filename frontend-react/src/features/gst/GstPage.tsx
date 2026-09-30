import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Field, Input, Stat, StatGrid, Tabs } from '@/components/ui'
import { gstExport, saveGstin, useGstSettings, useInward, useOutward, type InwardSupply, type OutwardSupply } from '@/api/gst'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

type Tab = 'outward' | 'inward'

/** The first and last day of the financial year we are in, as yyyy-mm-dd. */
function thisYear() {
  const d = new Date()
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1
  return { from: `${y}-04-01`, to: `${y + 1}-03-31` }
}

export default function GstPage() {
  const { can } = useSession()
  const [tab, setTab] = useState<Tab>('outward')
  const fy = thisYear()
  const [from, setFrom] = useState(fy.from)
  const [to, setTo] = useState(fy.to)
  const settings = useGstSettings()
  const [gstin, setGstin] = useState('')
  useEffect(() => { if (settings.data) setGstin(settings.data.gstin) }, [settings.data])
  const out = useOutward(from, to)
  const inw = useInward(from, to)
  const save = useAction(() => saveGstin(gstin.trim().toUpperCase()), { invalidate: [['gst']], success: (r) => `Registered in ${r.state || 'no state'}` })
  const states = settings.data?.states ?? {}
  const os = out.data?.summary
  const is = inw.data?.summary

  const outCols: TableColumn<OutwardSupply>[] = [
    { id: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    { id: 'no', header: 'Bill', cell: (r) => <span className="font-mono text-[13px]">{r.number}</span> },
    { id: 'party', header: 'Party', cell: (r) => <div>{r.party || '-'}<div className="text-xs text-muted-foreground">{r.project}</div></div> },
    { id: 'pos', header: 'Place of supply', hideBelow: 'md', cell: (r) => (r.place_of_supply ? states[r.place_of_supply] || r.place_of_supply : <span className="text-warning">not set</span>) },
    { id: 'rate', header: 'Rate', hideBelow: 'md', align: 'right', cell: (r) => `${r.rate}%` },
    { id: 'taxable', header: 'Taxable', align: 'right', cell: (r) => formatINR(r.taxable) },
    { id: 'tax', header: 'Tax', hideBelow: 'lg', align: 'right', cell: (r) => (r.igst ? <>{formatINR(r.igst)} <span className="text-[11px] text-muted-foreground">IGST</span></> : `${formatINR(r.cgst)} + ${formatINR(r.sgst)}`) },
    { id: 'total', header: 'Total', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.total)}</span> },
  ]

  const inCols: TableColumn<InwardSupply>[] = [
    { id: 'date', header: 'Date', cell: (r) => formatDate(r.date) },
    { id: 'no', header: 'Bill', cell: (r) => <div><span className="font-mono text-[13px]">{r.number}</span><div className="text-[11px] text-muted-foreground">{r.kind}</div></div> },
    { id: 'party', header: 'Supplier', cell: (r) => <div>{r.party || '-'}{r.party_gstin ? <div className="font-mono text-[11px] text-muted-foreground">{r.party_gstin}</div> : <div className="text-[11px] text-warning">no GSTIN - credit at risk</div>}</div> },
    { id: 'rate', header: 'Rate', hideBelow: 'md', align: 'right', cell: (r) => (r.rate ? `${r.rate}%` : '-') },
    { id: 'taxable', header: 'Taxable', align: 'right', cell: (r) => formatINR(r.taxable) },
    { id: 'tax', header: 'Input credit', align: 'right', cell: (r) => <span className="font-semibold">{formatINR(r.tax)}</span> },
  ]

  const monthCols: TableColumn<NonNullable<typeof out.data>['by_month'][number]>[] = [
    { id: 'm', header: 'Month', cell: (m) => <span className="font-semibold">{m.month}</span> },
    { id: 'b', header: 'Bills', align: 'right', cell: (m) => m.bills },
    { id: 't', header: 'Taxable', align: 'right', cell: (m) => formatINR(m.taxable) },
    { id: 'c', header: 'CGST', hideBelow: 'md', align: 'right', cell: (m) => formatINR(m.cgst) },
    { id: 's', header: 'SGST', hideBelow: 'md', align: 'right', cell: (m) => formatINR(m.sgst) },
    { id: 'i', header: 'IGST', hideBelow: 'md', align: 'right', cell: (m) => formatINR(m.igst) },
    { id: 'tax', header: 'Tax', align: 'right', cell: (m) => <span className="font-semibold">{formatINR(m.tax)}</span> },
  ]

  return (
    <>
      <PageHeader eyebrow="Money" title="GST" description="The outward and inward supplies a return is filed from, grouped by month and by rate. Bills with no place of supply are called out, because a return cannot be filed against a blank." />
      <div className="mb-6 flex flex-wrap items-end gap-4 rounded-xl border border-border bg-card p-4">
        <Field label="Our GSTIN" htmlFor="gst-gstin" hint={settings.data ? (settings.data.state ? `${settings.data.state} (${settings.data.state_code})` : 'Not set - every bill will carry IGST until it is.') : undefined}>
          <Input id="gst-gstin" className="w-64 font-mono uppercase" value={gstin} onChange={(e) => setGstin(e.target.value)} />
        </Field>
        {can('accounts.manage') && <Button variant="outline" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>}
        <div className="ml-auto flex flex-wrap items-end gap-3">
          <Field label="From" htmlFor="gst-from"><Input id="gst-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="To" htmlFor="gst-to"><Input id="gst-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        </div>
      </div>

      <div className="mb-5">
        <Tabs label="Supplies" value={tab} onChange={setTab} items={[{ value: 'outward', label: 'Outward (we charge)' }, { value: 'inward', label: 'Inward (we are charged)' }]} />
      </div>

      {tab === 'outward' && (
        <>
          <StatGrid>
            <Stat label="Taxable value" value={compactINR(os?.taxable)} loading={out.isPending} />
            <Stat label="CGST" value={compactINR(os?.cgst)} loading={out.isPending} />
            <Stat label="SGST" value={compactINR(os?.sgst)} loading={out.isPending} />
            <Stat label="IGST" value={compactINR(os?.igst)} loading={out.isPending} />
            <Stat label="Total tax" value={compactINR(os?.tax)} loading={out.isPending} />
          </StatGrid>
          {!!os?.missing_place_of_supply && (
            <div role="status" className="mb-5 rounded-lg border-l-4 border-warning bg-warning-soft px-4 py-3 text-sm">
              <strong>{os.missing_place_of_supply} bill{os.missing_place_of_supply === 1 ? '' : 's'} with no place of supply.</strong> Set the state on each project under Projects, then the split is recalculated the next time the bill is drawn. Until then they carry IGST.
            </div>
          )}
          <h2 className="mb-3 text-lg font-semibold">By month</h2>
          <DataTable label="Outward supplies by month" rows={out.data?.by_month ?? []} columns={monthCols} rowKey={(m) => m.month} loading={out.isPending} empty="Nothing certified in this period." className="mb-8" />
          <div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-semibold">Every bill</h2><Button variant="outline" size="sm" asChild><a href={gstExport('outward', from, to)}><Download /> Excel</a></Button></div>
          <DataTable label="Outward supplies" rows={out.data?.supplies ?? []} columns={outCols} rowKey={(r) => `${r.number}-${r.rate}`} loading={out.isPending} empty="No certified bills in this period." />
        </>
      )}
      {tab === 'inward' && (
        <>
          <StatGrid className="xl:grid-cols-4">
            <Stat label="Taxable value" value={compactINR(is?.taxable)} loading={inw.isPending} />
            <Stat label="Input credit" value={compactINR(is?.tax)} loading={inw.isPending} />
            <Stat label="Bills" value={is?.bills ?? 0} loading={inw.isPending} />
            <Stat label="Missing supplier GSTIN" value={is?.missing_party_gstin ?? 0} tone={is?.missing_party_gstin ? 'warning' : undefined} loading={inw.isPending} />
          </StatGrid>
          <div className="mb-3 flex items-center justify-end"><Button variant="outline" size="sm" asChild><a href={gstExport('inward', from, to)}><Download /> Excel</a></Button></div>
          <DataTable label="Inward supplies" rows={inw.data?.supplies ?? []} columns={inCols} rowKey={(r) => `${r.number}-${r.rate}-${r.taxable}`} loading={inw.isPending} empty="Nothing charged to us in this period." />
        </>
      )}
    </>
  )
}
