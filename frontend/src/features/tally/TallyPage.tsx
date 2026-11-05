import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Download, FileSpreadsheet } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { FilterBar, useListFilters } from '@/components/data/filters'
import { Badge, Button, Card, Field, Input, Modal, Skeleton } from '@/components/ui'
import { get, put } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface LeftOut { what: string; count: number; amount: number; why: string; where: string }
interface Summary { vouchers: { type: string; count: number; amount: number }[]; ledgers: number; cost_centres: number; warnings: string[]; left_out: LeftOut[] }
interface Voucher { date: string; type: string; number: string; narration: string; project: string; amount: number; cancelled: boolean; lines: { ledger: string; debit: number; credit: number }[] }
interface Settings { company: string; ledgers: { key: string; label: string; name: string; default: string; group: string }[] }

const keys = { all: ['tally'] as const }
/** 1 April of the financial year today is in. */
function yearStart() {
  const d = new Date()
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1
  return `${y}-04-01`
}

/**
 * Saved through a request rather than a link: the file is checked to be what it should be before it reaches the person's
 * disk, so anything else (signed out, a server error) is said on screen instead of being saved under a .xml name.
 */
async function saveFile(url: string, name: string, kind: 'xml' | 'sheet') {
  const res = await fetch(url, { credentials: 'include' })
  const type = res.headers.get('content-type') ?? ''
  const right = kind === 'xml' ? type.includes('xml') : type.includes('spreadsheet')
  if (!res.ok || !right) throw new Error(res.status === 401 ? 'You have been signed out. Sign in again, then download.' : 'The file could not be made. Try again.')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(await res.blob())
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000)
}

/**
 * The period's accounts, for the company's books in Tally: every voucher to read on the page, what was left out and why,
 * and the two files Tally Prime imports - the masters (ledgers, and the projects as cost centres), then the vouchers.
 */
export default function TallyPage() {
  const [from, setFrom] = useState(yearStart())
  const [to, setTo] = useState(today())
  const period = `date_from=${from}&date_to=${to}`
  const q = useQuery({ queryKey: [...keys.all, 'summary', from, to], queryFn: () => get<Summary>(`/api/tally/summary?${period}`) })
  const list = useQuery({ queryKey: [...keys.all, 'vouchers', from, to], queryFn: () => get<{ vouchers: Voucher[] }>(`/api/tally/vouchers?${period}`) })
  const s = q.data
  const [open, setOpen] = useState<Voucher | null>(null)
  const [saving, setSaving] = useState('')
  const total = (s?.vouchers ?? []).reduce((n, v) => n + v.count, 0)
  const download = async (what: 'masters' | 'vouchers' | 'sheet') => {
    setSaving(what)
    try {
      if (what === 'sheet') await saveFile(`/api/tally/vouchers.xlsx?${period}`, `yerp_vouchers_${from}_${to}.xlsx`, 'sheet')
      else await saveFile(`/api/tally/${what}.xml?${period}`, `yerp_${what}_${from}_${to}.xml`, 'xml')
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving('')
    }
  }
  const rows = useMemo(() => list.data?.vouchers ?? [], [list.data])
  const filters = useListFilters(rows, {
    search: (v) => [v.number, v.narration, v.project, ...v.lines.map((l) => l.ledger)].join(' '),
    status: (v) => v.type,
    date: (v) => v.date,
    facets: { project: { label: 'Project', get: (v) => v.project || 'Head office' } },
  })
  const columns: TableColumn<Voucher>[] = [
    { id: 'date', header: 'Date', sort: (v) => v.date, cell: (v) => formatDate(v.date) },
    { id: 'type', header: 'Voucher', sort: (v) => v.type, cell: (v) => (v.cancelled ? <Badge tone="danger">{v.type} cancelled</Badge> : <Badge tone="neutral">{v.type}</Badge>) },
    { id: 'no', header: 'Number', cell: (v) => <span className="font-mono text-[13px]">{v.number}</span> },
    { id: 'what', header: 'What it is', cell: (v) => <div className="max-w-md truncate" title={v.narration}>{v.narration}</div> },
    { id: 'project', header: 'Project', hideBelow: 'lg', cell: (v) => v.project || '-' },
    { id: 'amount', header: 'Amount', align: 'right', sort: (v) => v.amount, cell: (v) => formatINR(v.amount) },
  ]
  return (
    <>
      <PageHeader
        eyebrow="Accounts" title="Tally Export"
        description="Every voucher for the period, what was left out and why, and the two files for Tally Prime."
        actions={<Button variant="outline" loading={saving === 'sheet'} disabled={!total} onClick={() => download('sheet')}><FileSpreadsheet /> Excel to read</Button>}
      />
      <div className="mb-5 flex flex-wrap items-end gap-3">
        <Field label="From" htmlFor="tl-from"><Input id="tl-from" type="date" className="w-40" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} /></Field>
        <Field label="To" htmlFor="tl-to"><Input id="tl-to" type="date" className="w-40" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)} /></Field>
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Card className="p-4">
          <h2 className="mb-3 text-sm font-semibold">In this period</h2>
          {q.isPending ? <Skeleton className="h-32 w-full" /> : (
            <>
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="pb-2">Voucher</th><th className="pb-2 text-right">Count</th><th className="pb-2 text-right">Amount</th></tr></thead>
                <tbody>
                  {(s?.vouchers ?? []).map((v) => <tr key={v.type} className="border-t border-border"><td className="py-1.5">{v.type}</td><td className="text-right tabular-nums">{v.count}</td><td className="text-right tabular-nums">{formatINR(v.amount)}</td></tr>)}
                  {!total && <tr><td colSpan={3} className="py-3 text-muted-foreground">Nothing in this period.</td></tr>}
                </tbody>
              </table>
              <p className="mt-3 text-xs text-muted-foreground">{s?.ledgers ?? 0} ledgers and {s?.cost_centres ?? 0} projects (as cost centres) are named.</p>
              {s?.warnings.map((w) => <p key={w} role="alert" className="mt-2 text-xs text-danger">{w}</p>)}
            </>
          )}
        </Card>
        <Card className="p-4">
          <h2 className="mb-3 text-sm font-semibold">Into Tally Prime</h2>
          <ol className="grid gap-3 text-sm">
            <li><span className="font-medium">1. The masters.</span> Gateway of Tally, Import, Masters, and choose this file. Ledgers already there are left as they are.
              <div className="mt-1.5"><Button size="sm" variant="outline" loading={saving === 'masters'} onClick={() => download('masters')}><Download /> Masters (XML)</Button></div></li>
            <li><span className="font-medium">2. The vouchers.</span> Gateway of Tally, Import, Transactions, and choose this file. Each voucher carries its own id, so the same one imported twice is not doubled.
              <div className="mt-1.5"><Button size="sm" loading={saving === 'vouchers'} disabled={!total} onClick={() => download('vouchers')}><Download /> Vouchers (XML){total ? ` - ${total}` : ''}</Button></div></li>
          </ol>
          <p className="mt-3 text-xs text-muted-foreground">These two files are for Tally to import, not for reading: double-clicked, Windows opens them in a browser as a page of code. To read the vouchers, use the list below or Excel to read.</p>
        </Card>
      </div>

      {!!s?.left_out.length && (
        <Card className="mt-4 p-4">
          <h2 className="text-sm font-semibold">Not in this export</h2>
          <p className="mb-3 text-xs text-muted-foreground">Recorded in the period, but not a voucher yet. Each goes across once the step named is done.</p>
          <ul className="divide-y divide-border text-sm">
            {s.left_out.map((l) => (
              <li key={l.what} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2">
                <div className="min-w-0"><span className="font-medium">{l.count} {l.what}</span><span className="block text-xs text-muted-foreground">{l.why}</span></div>
                <div className="flex items-center gap-3"><span className="tabular-nums">{formatINR(l.amount)}</span><Link to={l.where} className="text-[13px] text-primary underline underline-offset-4">Open</Link></div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <h2 className="mb-2 mt-6 text-base font-semibold">Vouchers in this export</h2>
      <FilterBar filters={filters} placeholder="Search by number, ledger, project or what it is..." />
      <DataTable
        label="Vouchers" rows={filters.filtered} columns={columns} rowKey={(v) => `${v.type}-${v.number}-${v.date}`} loading={list.isPending} onRowClick={setOpen}
        empty={filters.active ? 'Nothing matches those filters.' : 'No vouchers in this period.'}
      />
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open ? `${open.type} ${open.number}` : ''} description={open ? `${formatDate(open.date)}. ${open.narration}` : undefined}>
        {open && (
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground"><tr><th className="pb-2">Ledger</th><th className="pb-2 text-right">Debit</th><th className="pb-2 text-right">Credit</th></tr></thead>
            <tbody>
              {open.lines.map((l, i) => <tr key={i} className="border-t border-border"><td className="py-1.5">{l.ledger}</td><td className="text-right tabular-nums">{l.debit ? formatINR(l.debit) : ''}</td><td className="text-right tabular-nums">{l.credit ? formatINR(l.credit) : ''}</td></tr>)}
            </tbody>
          </table>
        )}
      </Modal>
      <LedgerNames />
    </>
  )
}

/** The company's own Tally ledger names, so what is imported lands on ledgers it already keeps. */
function LedgerNames() {
  const { can } = useSession()
  const q = useQuery({ queryKey: [...keys.all, 'settings'], queryFn: () => get<Settings>('/api/tally/settings') })
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [company, setCompany] = useState<string | null>(null)
  const save = useAction(() => put<{ message: string }>('/api/tally/settings', { ledgers: Object.fromEntries((q.data?.ledgers ?? []).map((l) => [l.key, edits[l.key] ?? l.name])), company: company ?? q.data?.company ?? '' }), {
    invalidate: [[...keys.all]], onSuccess: () => { setEdits({}); setCompany(null) },
  })
  const editable = can('accounts.manage')
  if (!q.data) return null
  return (
    <Card className="mt-6 p-4">
      <h2 className="text-sm font-semibold">Ledger names in Tally</h2>
      <p className="mb-3 text-xs text-muted-foreground">Parties, bank accounts, cash boxes and expense heads go across under their own names. These are the rest.</p>
      <Field label="Company name in Tally" htmlFor="tl-company" hint="Optional: the company the import goes into, if more than one is open" className="mb-4 max-w-md">
        <Input id="tl-company" value={company ?? q.data.company} disabled={!editable} onChange={(e) => setCompany(e.target.value)} />
      </Field>
      <div className="grid gap-x-6 gap-y-2 md:grid-cols-2">
        {q.data.ledgers.map((l) => (
          <label key={l.key} className="grid grid-cols-[1fr_1.2fr] items-center gap-3 text-sm">
            <span className="text-muted-foreground">{l.label}<span className="block text-[11px]">{l.group}</span></span>
            <Input aria-label={l.label} value={edits[l.key] ?? l.name} placeholder={l.default} disabled={!editable} onChange={(e) => setEdits((x) => ({ ...x, [l.key]: e.target.value }))} />
          </label>
        ))}
      </div>
      {editable && (
        <div className="mt-4 flex items-center gap-3">
          <Button size="sm" loading={save.isPending} disabled={!Object.keys(edits).length && company === null} onClick={() => save.mutate()}>Save ledger names</Button>
          {save.error && <p role="alert" className="text-[13px] text-danger">{save.error.message}</p>}
        </div>
      )}
    </Card>
  )
}
