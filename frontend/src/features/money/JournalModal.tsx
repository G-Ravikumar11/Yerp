import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { JOURNAL_INVALIDATE, raiseJournal, type JournalLine, type LineKind } from '@/api/journals'
import { PARTY_LABEL, useAccounts, useMoneyHeads } from '@/api/ledger'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const blank = (kind: LineKind, job: number): JournalLine => ({ kind, party_type: 'supplier', party_name: '', head: '', account_id: null, ledger_key: '', job_id: job || null, debit: 0, credit: 0, note: '' })

/** A journal voucher: lines of debit and credit, raised for the Master to approve. One that is out is still kept: Tally gets the difference in Suspense A/c. */
export function JournalModal({ ledgers, defaultJob, onClose }: { ledgers: { key: string; label: string }[]; defaultJob: number; onClose: () => void }) {
  const [on, setOn] = useState(today())
  const [narration, setNarration] = useState('')
  const [lines, setLines] = useState<JournalLine[]>([blank('party', defaultJob), blank('head', defaultJob)])
  const heads = useMoneyHeads()
  const accounts = useAccounts()
  const projects = useProjects()
  const sites = (projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))
  const headOptions = [...(heads.data?.expense ?? []), ...(heads.data?.income ?? [])].map((h) => ({ value: h, label: h }))
  const dr = lines.reduce((s, l) => s + (l.debit || 0), 0)
  const cr = lines.reduce((s, l) => s + (l.credit || 0), 0)
  const off = Math.round((dr - cr) * 100) / 100
  const save = useAction(() => raiseJournal({ voucher_date: on, narration, lines }), { invalidate: JOURNAL_INVALIDATE, success: (j) => `${j.number} raised; it waits for the Master`, onSuccess: onClose })
  const set = (i: number, patch: Partial<JournalLine>) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, ...patch } : l)))

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="New journal voucher" size="xl"
      description="Debits on one side, credits on the other. If they are not equal the voucher is still saved, and in Tally the difference is posted to Suspense A/c. Put the project on each line it concerns."
      footer={<>
        <span className={`mr-auto text-sm tabular-nums ${off ? 'text-warning' : 'text-muted-foreground'}`} role="status">Debit {formatINR(dr)} / Credit {formatINR(cr)}{off ? ` - out by ${formatINR(Math.abs(off))}: saved as it is, and in Tally the difference goes to Suspense A/c` : ''}</span>
        <Button variant="ghost" onClick={onClose}>Not now</Button>
        <Button loading={save.isPending} disabled={(dr <= 0 && cr <= 0) || narration.trim().length < 3} onClick={() => save.mutate()}>Send to the Master</Button>
      </>}>
      <div className="mb-4 grid gap-3 sm:grid-cols-[10rem_1fr]">
        <Field label="Date"><Input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Narration"><Input value={narration} onChange={(e) => setNarration(e.target.value)} placeholder="What it is for - this goes in the books" /></Field>
      </div>
      <div className="space-y-2">
        {lines.map((l, i) => (
          <div key={i} className="grid items-end gap-2 rounded-lg border border-border p-2 md:grid-cols-[8rem_1fr_12rem_8rem_8rem_auto]">
            <Field label="Line"><Select aria-label="Line kind" value={l.kind} onChange={(e) => set(i, { kind: e.target.value as LineKind })}
              options={[{ value: 'party', label: 'Party' }, { value: 'head', label: 'Expense / income' }, { value: 'account', label: 'Bank / cash' }, { value: 'ledger', label: 'Books ledger' }]} /></Field>
            {l.kind === 'party' ? (
              <div className="grid grid-cols-[8rem_1fr] gap-2">
                <Field label="Type"><Select aria-label="Party type" value={l.party_type} onChange={(e) => set(i, { party_type: e.target.value })}
                  options={['supplier', 'contractor', 'client', 'staff', 'other'].map((t) => ({ value: t, label: PARTY_LABEL[t] ?? t }))} /></Field>
                <Field label="Name"><Input aria-label="Party name" value={l.party_name} onChange={(e) => set(i, { party_name: e.target.value })} /></Field>
              </div>
            ) : l.kind === 'head' ? (
              <Field label="Head"><Select aria-label="Head" value={l.head} onChange={(e) => set(i, { head: e.target.value })} placeholder="Choose a head" options={headOptions} /></Field>
            ) : l.kind === 'account' ? (
              <Field label="Account"><Select aria-label="Account" value={l.account_id ?? ''} onChange={(e) => set(i, { account_id: Number(e.target.value) || null })} placeholder="Choose an account"
                options={(accounts.data ?? []).map((a) => ({ value: a.id, label: a.name }))} /></Field>
            ) : (
              <Field label="Ledger"><Select aria-label="Ledger" value={l.ledger_key} onChange={(e) => set(i, { ledger_key: e.target.value })} placeholder="Choose a ledger"
                options={ledgers.map((x) => ({ value: x.key, label: x.label }))} /></Field>
            )}
            <Field label="Project"><Select aria-label="Project" value={l.job_id ?? ''} onChange={(e) => set(i, { job_id: Number(e.target.value) || null })} placeholder="Head office" options={sites} /></Field>
            <Field label="Debit"><NumField aria-label="Debit" value={l.debit} onValue={(n) => set(i, { debit: n, credit: n ? 0 : l.credit })} /></Field>
            <Field label="Credit"><NumField aria-label="Credit" value={l.credit} onValue={(n) => set(i, { credit: n, debit: n ? 0 : l.debit })} /></Field>
            <Button size="icon-sm" variant="ghost" aria-label="Remove line" disabled={lines.length <= 2} onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))}><Trash2 /></Button>
          </div>
        ))}
      </div>
      <Button className="mt-3" variant="outline" size="sm" onClick={() => setLines((ls) => [...ls, blank('head', defaultJob)])}><Plus /> Add a line</Button>
    </Modal>
  )
}
