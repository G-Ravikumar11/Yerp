import { useRef, useState } from 'react'
import { Check, FileText, Upload, X } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Input, Select, Stat, StatGrid } from '@/components/ui'
import { ledgerKeys, useAccounts, useMoneyHeads } from '@/api/ledger'
import { bookLine, brsUrl, clearEntry, ignoreLine, matchLine, recoKeys, uploadStatement, useReco, type OpenEntry, type StatementLine } from '@/api/bankreco'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatDate, today } from '@/lib/format'
import { compactINR, formatINR } from '@/lib/utils'

/**
 * One bank account against the bank's own statement. Read the statement in (Excel or CSV, as the bank's site gives
 * it) and each line is matched to the entry it is; match the rest by hand, book what the bank booked on its own, and
 * what is left is the reconciliation - printed as the BRS for the auditor.
 */
export function ReconcileTab() {
  const { can } = useSession()
  const pay = can('bills.pay')
  const accounts = useAccounts()
  const banks = (accounts.data ?? []).filter((a) => a.kind !== 'Cash')
  const [picked, setPicked] = useState(0)
  const [asOf, setAsOf] = useState(today())
  const account = picked || banks[0]?.id || 0
  const q = useReco(account, asOf)
  const b = q.data?.brs
  const file = useRef<HTMLInputElement>(null)
  const done = { invalidate: [recoKeys.all, ledgerKeys.all] }
  const upload = useAction((f: File) => uploadStatement(account, f), done)

  if (accounts.data && !banks.length) {
    return <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">No bank account yet. Add one on the Bank book tab, then read its statement in here.</p>
  }
  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-72"><Select aria-label="Bank account" value={account} onChange={(e) => setPicked(Number(e.target.value))} options={banks.map((a) => ({ value: a.id, label: a.name }))} /></div>
        <label className="flex items-center gap-2 text-[13px] text-muted-foreground">As on<Input type="date" aria-label="As on" className="w-40" value={asOf} max={today()} onChange={(e) => e.target.value && setAsOf(e.target.value)} /></label>
        {pay && <>
          <input ref={file} type="file" hidden accept=".xlsx,.xls,.csv" aria-label="The bank's statement" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = '' }} />
          <Button size="sm" loading={upload.isPending} onClick={() => file.current?.click()}><Upload /> Read the bank&apos;s statement</Button>
        </>}
        {account > 0 && <Button size="sm" variant="ghost" asChild><a href={brsUrl(account, asOf)} target="_blank" rel="noreferrer"><FileText /> BRS (PDF)</a></Button>}
      </div>
      <StatGrid className="xl:grid-cols-5">
        <Stat label="As per the books" value={compactINR(b?.books)} loading={q.isPending} />
        <Stat label="Cheques not presented" value={compactINR(b?.not_presented_total)} sub="added back" loading={q.isPending} />
        <Stat label="Deposits not credited" value={compactINR(b?.not_credited_total)} sub="taken off" loading={q.isPending} />
        <Stat label="Bank should show" value={compactINR(b?.bank_should_show)} sub={b?.statement_balance != null ? `statement: ${formatINR(b.statement_balance)}` : 'no statement read in yet'} loading={q.isPending} />
        <Stat label="Difference" value={b?.difference == null ? '-' : formatINR(b.difference)} tone={b?.difference ? 'danger' : b?.difference === 0 ? 'success' : undefined} sub={q.data ? `${q.data.counts.unmatched} line${q.data.counts.unmatched === 1 ? '' : 's'} to match` : undefined} loading={q.isPending} />
      </StatGrid>
      {q.data && <Lines lines={q.data.lines} suggestions={q.data.suggestions} canAct={pay} />}
      {b && <Open title="Cheques issued, not yet presented" rows={b.not_presented} canAct={pay} />}
      {b && <Open title="Deposits made, not yet credited" rows={b.not_credited} canAct={pay} />}
    </>
  )
}

/** The statement's lines not yet matched: match one to the entry it is, book it, or set it aside. */
function Lines({ lines, suggestions, canAct }: { lines: StatementLine[]; suggestions: Record<string, { id: number; number: string; paid_on: string; party: string; reference: string }[]>; canAct: boolean }) {
  const heads = useMoneyHeads()
  const [pick, setPick] = useState<Record<number, string>>({})
  const done = { invalidate: [recoKeys.all, ledgerKeys.all] }
  const match = useAction((a: { line: number; entry: number }) => matchLine(a.line, a.entry), done)
  const book = useAction((a: { line: number; head: string }) => bookLine(a.line, a.head), done)
  const ignore = useAction((line: number) => ignoreLine(line), done)
  const columns: TableColumn<StatementLine>[] = [
    { id: 'date', header: 'Date', cell: (l) => formatDate(l.txn_date) },
    { id: 'narr', header: 'On the statement', cell: (l) => <div className="max-w-80"><div className="truncate" title={l.narration}>{l.narration}</div>{l.reference && <div className="text-xs text-muted-foreground">{l.reference}</div>}</div> },
    { id: 'out', header: 'Out', align: 'right', cell: (l) => (l.debit ? formatINR(l.debit) : '') },
    { id: 'in', header: 'In', align: 'right', cell: (l) => (l.credit ? formatINR(l.credit) : '') },
    {
      id: 'act', header: '', align: 'right', cell: (l) => {
        if (!canAct) return null
        const fits = suggestions[String(l.id)] ?? []
        const list = (l.debit ? heads.data?.expense : heads.data?.income) ?? []
        const choice = pick[l.id] ?? (fits[0] ? `e:${fits[0].id}` : `h:${l.debit ? 'Bank charges' : 'Interest received'}`)
        return (
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <div className="w-64"><Select aria-label="Match or book" value={choice} onChange={(e) => setPick((p) => ({ ...p, [l.id]: e.target.value }))}
              options={[...fits.map((f) => ({ value: `e:${f.id}`, label: `Is ${f.number} · ${f.party} · ${formatDate(f.paid_on)}` })),
                ...list.map((h) => ({ value: `h:${h}`, label: `Book as ${h}` }))]} /></div>
            <Button size="sm" loading={match.isPending || book.isPending} onClick={() => (choice.startsWith('e:') ? match.mutate({ line: l.id, entry: Number(choice.slice(2)) }) : book.mutate({ line: l.id, head: choice.slice(2) }))}><Check /> Do it</Button>
            <Button size="icon-sm" variant="ghost" aria-label="Set this line aside" title="Nothing for the books (a reversal and its correction)" onClick={() => ignore.mutate(l.id)}><X /></Button>
          </div>
        )
      },
    },
  ]
  return (
    <section className="mt-6">
      <h3 className="mb-2 text-sm font-semibold">On the bank&apos;s statement, not matched yet</h3>
      <DataTable label="Statement lines to match" rows={lines} columns={columns} rowKey={(l) => l.id}
        empty="Every line read in is matched. Read in the next statement when it comes." />
    </section>
  )
}

/** Entries the bank has not moved yet: cleared by hand when the passbook shows them, without a statement. */
function Open({ title, rows, canAct }: { title: string; rows: OpenEntry[]; canAct: boolean }) {
  const [on, setOn] = useState<Record<number, string>>({})
  const clear = useAction((a: { id: number; on: string }) => clearEntry(a.id, a.on), { invalidate: [recoKeys.all, ledgerKeys.all] })
  const columns: TableColumn<OpenEntry>[] = [
    { id: 'date', header: 'Date', cell: (r) => formatDate(r.paid_on) },
    { id: 'no', header: 'No.', cell: (r) => <span className="font-mono text-[13px]">{r.number}</span> },
    { id: 'party', header: 'Party', cell: (r) => r.party },
    { id: 'ref', header: 'Cheque / ref', hideBelow: 'md', cell: (r) => `${r.mode} ${r.reference}`.trim() },
    { id: 'amount', header: 'Amount', align: 'right', cell: (r) => formatINR(r.amount) },
    {
      id: 'act', header: '', align: 'right', cell: (r) => canAct && (
        <div className="flex items-center justify-end gap-1.5">
          <Input type="date" aria-label={`Cleared on, ${r.number}`} className="h-8 w-36" min={r.paid_on} max={today()} value={on[r.id] ?? ''} onChange={(e) => setOn((x) => ({ ...x, [r.id]: e.target.value }))} />
          <Button size="sm" variant="outline" disabled={!on[r.id]} loading={clear.isPending && clear.variables?.id === r.id} onClick={() => clear.mutate({ id: r.id, on: on[r.id] })}>Cleared</Button>
        </div>
      ),
    },
  ]
  return (
    <section className="mt-6">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <DataTable label={title} rows={rows} columns={columns} rowKey={(r) => r.id} empty="None." />
    </section>
  )
}
