import { useMemo, useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { ledgerKeys, saveOpening, useParties, useSuppliers, type Opening, type OpeningSide } from '@/api/ledger'
import { bookKeys } from '@/api/books'
import { projectLabel, useProjects } from '@/api/projects'
import { useAction } from '@/lib/mutate'
import { financialYearStart, formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

const TYPES = [{ value: 'client', label: 'Client' }, { value: 'supplier', label: 'Supplier' }, { value: 'contractor', label: 'Subcontractor' }]

/** The words for each side, as the party's own type says them: a client owes us; a supplier is owed by us. */
const sides = (type: string): { value: OpeningSide; label: string }[] =>
  type === 'client'
    ? [{ value: 'owed', label: 'They owe us' }, { value: 'advance', label: 'They paid us in advance' }]
    : [{ value: 'owed', label: 'We owe them' }, { value: 'advance', label: 'We paid them in advance' }]

/** What a party owed - or was owed - on the day the books begin, for the ones with no bill here to show it. */
export function OpeningModal({ target, onClose }: { target: Opening | 'new' | null; onClose: () => void }) {
  const editing = target && target !== 'new' ? target : null
  return (
    <Modal open={!!target} onOpenChange={(o) => !o && onClose()} size="lg" title={editing ? `Opening balance ${editing.number}` : 'Opening balance'}
      description="What a client, supplier or contractor owed - or was owed - on the day your books here begin. It starts their ledger and goes to Tally as an opening journal.">
      {target && <Form key={editing?.id ?? 'new'} opening={editing} onClose={onClose} />}
    </Modal>
  )
}

function Form({ opening, onClose }: { opening: Opening | null; onClose: () => void }) {
  const projects = useProjects()
  const [type, setType] = useState<string>(opening?.party_type ?? 'supplier')
  const [name, setName] = useState(opening?.party ?? '')
  const [side, setSide] = useState<OpeningSide>(opening?.side ?? 'owed')
  const [amount, setAmount] = useState(opening?.amount ?? 0)
  const [on, setOn] = useState(opening?.as_on ?? financialYearStart())
  const [job, setJob] = useState(opening?.job_id ? String(opening.job_id) : '')
  const [note, setNote] = useState(opening?.note ?? '')
  // The names already in this party's books, so one is picked rather than typed a second way.
  const parties = useParties(type)
  const suppliers = useSuppliers()
  const known = useMemo(() => [...new Set([...(parties.data?.parties ?? []).map((p) => p.party), ...(type === 'supplier' ? (suppliers.data?.suppliers ?? []).map((s) => s.name) : [])].filter(Boolean))].sort(), [parties.data, suppliers.data, type])
  const save = useAction(
    () => saveOpening(opening?.id ?? null, { party_type: type, party_name: name.trim(), side, amount, as_on: on, job_id: Number(job) || null, note }),
    { invalidate: [ledgerKeys.all, bookKeys.all, ['dashboard']], onSuccess: onClose },
  )
  const words = sides(type)
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Party type" htmlFor="ob-type">
          <Select id="ob-type" value={type} onChange={(e) => { setType(e.target.value); setSide('owed') }} options={TYPES} />
        </Field>
        <Field label="Name" htmlFor="ob-name" hint="As it is on their bills, so the two join up.">
          <Input id="ob-name" list="ob-known" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          <datalist id="ob-known">{known.map((n) => <option key={n} value={n} />)}</datalist>
        </Field>
        <Field label="Which way it runs" htmlFor="ob-side"><Select id="ob-side" value={side} onChange={(e) => setSide(e.target.value as OpeningSide)} options={words} /></Field>
        <Field label="Amount" htmlFor="ob-amount"><NumField id="ob-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="As on" htmlFor="ob-on" hint="The day the balance stood at - usually 1 April."><Input id="ob-on" type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Project" htmlFor="ob-job" hint="Leave blank for the head office."><Select id="ob-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder="Head office" options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Note" htmlFor="ob-note" className="sm:col-span-2"><Input id="ob-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Where the figure comes from: their statement of 31 March, the old books..." /></Field>
      </div>
      {amount > 0 && name.trim() && (
        <p className="mt-4 rounded-lg bg-muted/50 p-3 text-sm">
          On {formatDate(on)}, <strong>{name.trim()}</strong>: {words.find((w) => w.value === side)?.label.toLowerCase()} <strong>{formatINR(amount)}</strong>.
        </p>
      )}
      <div className="mt-5 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!name.trim() || amount <= 0 || !on} onClick={() => save.mutate()}>{opening ? 'Save' : 'Add the opening balance'}</Button>
      </div>
    </div>
  )
}
