import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select } from '@/components/ui'
import { ledgerKeys, PARTY_LABEL, recordOnAccount, useAccounts } from '@/api/ledger'
import { PAY_MODES } from '@/api/money'
import { advanceKeys, useAdvanceStaff } from '@/api/advances'
import { projectLabel, useProjects } from '@/api/projects'
import { mustAsk, paymentKeys, raisePaymentRequest, usePaymentRules } from '@/api/payments'
import { useAction } from '@/lib/mutate'
import { today } from '@/lib/format'

/** Money that has moved against no bill yet: it sits in the party's ledger and the bank book until a bill arrives. */
export function OnAccountModal({ direction, onClose, partyType, jobId }: { direction: 'IN' | 'OUT' | null; onClose: () => void; partyType?: string; jobId?: number }) {
  return (
    <Modal open={!!direction} onOpenChange={(o) => !o && onClose()} title={direction === 'IN' ? 'Money received on account' : 'Advance or payment on account'} description="Against no bill yet. It is set against a bill when one arrives - or, for staff, against what they spend or what is taken from their salary (record that as received, mode Adjustment).">
      {direction && <Form direction={direction} onClose={onClose} partyType={partyType} jobId={jobId} />}
    </Modal>
  )
}

function Form({ direction, onClose, partyType, jobId }: { direction: 'IN' | 'OUT'; onClose: () => void; partyType?: string; jobId?: number }) {
  const accounts = useAccounts()
  const [type, setType] = useState(partyType ?? (direction === 'IN' ? 'client' : 'supplier'))
  // Every advance belongs to a site, so Advances and the project's money can be read site by site.
  const [job, setJob] = useState(jobId ? String(jobId) : '')
  const projects = useProjects()
  const staff = useAdvanceStaff(type === 'staff')
  const [party, setParty] = useState('')
  const [amount, setAmount] = useState(0)
  const [on, setOn] = useState(today())
  const [mode, setMode] = useState('Bank transfer')
  const [ref, setRef] = useState('')
  const [note, setNote] = useState('')
  const [account, setAccount] = useState('')
  const only = accounts.data?.length === 1 ? String(accounts.data[0].id) : ''
  const rules = usePaymentRules()
  // An advance paid out, where the company approves payments first: sent for approval, paid once approved.
  const ask = direction === 'OUT' && mustAsk(rules.data, amount)
  const save = useAction(() => (ask
    ? raisePaymentRequest({ doc_type: 'on_account', party_type: type, party_name: party.trim(), amount, mode, note, account_id: Number(account || only) || null, job_id: Number(job) || null })
    : recordOnAccount({ direction, party_type: type, party_name: party.trim(), amount, paid_on: on, mode, reference: ref, note, account_id: Number(account || only) || null, job_id: Number(job) || null })), { invalidate: [ledgerKeys.all, ['owed'], paymentKeys.all, advanceKeys.all], onSuccess: onClose })
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Party type" htmlFor="oa-type"><Select id="oa-type" value={type} onChange={(e) => setType(e.target.value)} options={Object.entries(PARTY_LABEL).map(([v, l]) => ({ value: v, label: l }))} /></Field>
        <Field label={direction === 'IN' ? 'Received from' : 'Paid to'} htmlFor="oa-party">
          {type === 'staff'
            ? <Select id="oa-party" value={party} onChange={(e) => setParty(e.target.value)} placeholder="Choose the member of staff" options={(staff.data?.staff ?? []).map((e) => ({ value: e.name, label: e.name }))} />
            : <Input id="oa-party" value={party} onChange={(e) => setParty(e.target.value)} autoFocus />}
        </Field>
        <Field label="Project" htmlFor="oa-job" className="sm:col-span-2"><Select id="oa-job" value={job} onChange={(e) => setJob(e.target.value)} placeholder="Head office" options={(projects.data ?? []).map((p) => ({ value: p.id, label: projectLabel(p) }))} /></Field>
        <Field label="Amount" htmlFor="oa-amount"><NumField id="oa-amount" value={amount} onValue={setAmount} /></Field>
        <Field label="Date" htmlFor="oa-date"><Input id="oa-date" type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Mode" htmlFor="oa-mode"><Select id="oa-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={PAY_MODES.map((m) => ({ value: m, label: m }))} /></Field>
        <Field label="Reference" htmlFor="oa-ref"><Input id="oa-ref" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="UTR or cheque no." /></Field>
        <Field label="Account" htmlFor="oa-account" className="sm:col-span-2"><Select id="oa-account" value={account || only} onChange={(e) => setAccount(e.target.value)} placeholder="Not recorded against an account" options={(accounts.data ?? []).map((a) => ({ value: a.id, label: `${a.name} (${a.kind})` }))} /></Field>
        <Field label="Note" htmlFor="oa-note" className="sm:col-span-2"><Input id="oa-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
      <div className="mt-5 flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button loading={save.isPending} disabled={!party.trim() || amount <= 0} onClick={() => save.mutate()}>{direction === 'IN' ? 'Record the receipt' : ask ? 'Send for approval' : 'Record the payment'}</Button>
      </div>
    </div>
  )
}
