import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button, Card, Field, Input, Skeleton } from '@/components/ui'
import { get, put } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

interface Summary { vouchers: { type: string; count: number; amount: number }[]; ledgers: number; cost_centres: number; warnings: string[] }
interface Settings { company: string; ledgers: { key: string; label: string; name: string; default: string; group: string }[] }

const keys = { all: ['tally'] as const }
/** 1 April of the financial year today is in. */
function yearStart() {
  const d = new Date()
  const y = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1
  return `${y}-04-01`
}

/**
 * The period's accounts, for the company's books in Tally: the masters (ledgers, and the projects as cost centres) and
 * the vouchers, as Tally Prime imports them. Receipts, payments, expenses, transfers, client and contractor RA bills
 * and supplier bills, with GST, TDS, retention and advances on their own ledgers.
 */
export default function TallyPage() {
  const [from, setFrom] = useState(yearStart())
  const [to, setTo] = useState(today())
  const q = useQuery({ queryKey: [...keys.all, 'summary', from, to], queryFn: () => get<Summary>(`/api/tally/summary?date_from=${from}&date_to=${to}`) })
  const s = q.data
  const file = (what: 'masters' | 'vouchers') => `/api/tally/${what}.xml?date_from=${from}&date_to=${to}`
  const total = (s?.vouchers ?? []).reduce((n, v) => n + v.count, 0)
  return (
    <>
      <PageHeader eyebrow="Accounts" title="Tally Export" description="The period's accounts for the books in Tally Prime: import the masters first, then the vouchers." />
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
              <div className="mt-1.5"><Button size="sm" variant="outline" asChild><a href={file('masters')}><Download /> Masters (XML)</a></Button></div></li>
            <li><span className="font-medium">2. The vouchers.</span> Gateway of Tally, Import, Transactions, and choose this file. Each voucher carries its own id, so the same one imported twice is not doubled.
              <div className="mt-1.5"><Button size="sm" asChild><a href={file('vouchers')}><Download /> Vouchers (XML){total ? ` - ${total}` : ''}</a></Button></div></li>
          </ol>
          <p className="mt-3 text-xs text-muted-foreground">Export each month once it is closed. The ledger names below are the ones the vouchers use; set them to the ledgers already in your Tally company.</p>
        </Card>
      </div>
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
    <Card className="mt-4 p-4">
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
