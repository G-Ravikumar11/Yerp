import { useState } from 'react'
import { Button, Field, Input, Modal, NumField, Select, Skeleton } from '@/components/ui'
import { PAY_MODES, recordPayment, useBankAccounts, useOutstanding } from '@/api/money'
import { useAction } from '@/lib/mutate'
import { formatDate, today } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/**
 * Settle a bill, in whole or in part. Shows what it is worth, what has been
 * settled and what is left, and records the payment in the ledger and the bank
 * book - so what the bill says and what the books say cannot part company.
 */
export function PayModal({
  docType,
  docId,
  title,
  verb = 'Pay',
  open,
  onOpenChange,
  invalidate,
}: {
  docType: string
  docId: number
  title: string
  verb?: string
  open: boolean
  onOpenChange: (o: boolean) => void
  invalidate: readonly (readonly unknown[])[]
}) {
  const owed = useOutstanding(docType, docId, open)
  const accounts = useBankAccounts()
  return (
    <Modal open={open} onOpenChange={onOpenChange} title={`${verb} ${title}`} description="Recorded against the bill, in the ledger and the bank book." size="md">
      {owed.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-5 w-64" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : owed.data ? (
        <PayForm key={docId} docType={docType} docId={docId} owed={owed.data} accounts={accounts.data ?? []} onDone={() => onOpenChange(false)} invalidate={invalidate} verb={verb} />
      ) : (
        <p className="text-sm text-danger">Could not open that bill.</p>
      )}
    </Modal>
  )
}

function PayForm({
  docType,
  docId,
  owed,
  accounts,
  onDone,
  invalidate,
  verb,
}: {
  docType: string
  docId: number
  owed: NonNullable<ReturnType<typeof useOutstanding>['data']>
  accounts: { id: number; name: string; kind: string; balance: number }[]
  onDone: () => void
  invalidate: readonly (readonly unknown[])[]
  verb: string
}) {
  const [amount, setAmount] = useState(owed.outstanding)
  const [paidOn, setPaidOn] = useState(today())
  const [mode, setMode] = useState(PAY_MODES[0])
  const [ref, setRef] = useState('')
  const [account, setAccount] = useState(accounts.length === 1 ? String(accounts[0].id) : '')
  const [note, setNote] = useState('')

  const save = useAction(() => recordPayment({ doc_type: docType, doc_id: docId, amount, paid_on: paidOn, mode, reference: ref, note, account_id: account ? Number(account) : null }), {
    invalidate: [...invalidate.map((k) => [...k]), ['money']],
    onSuccess: onDone,
  })

  return (
    <div className="grid gap-4">
      <div className="rounded-lg bg-muted p-3 text-[13.5px]">
        Worth <strong>{formatINR(owed.worth)}</strong> · settled {formatINR(owed.settled)} · <strong>{formatINR(owed.outstanding)} left</strong>
        {owed.entries.length > 0 && (
          <ul className="mt-2 space-y-0.5 text-xs text-muted-foreground">
            {owed.entries.map((e) => (
              <li key={e.number} className={e.voided ? 'line-through opacity-60' : undefined}>
                {formatDate(e.paid_on)} · {e.number} · {formatINR(e.amount)} · {e.mode}
                {e.reference && ` ${e.reference}`}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Amount (₹)" htmlFor="pay-amount">
          <NumField id="pay-amount" value={amount} onValue={setAmount} autoFocus />
        </Field>
        <Field label="Date" htmlFor="pay-date">
          <Input id="pay-date" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        </Field>
        <Field label="Mode" htmlFor="pay-mode">
          <Select id="pay-mode" value={mode} onChange={(e) => setMode(e.target.value)} options={PAY_MODES.map((m) => ({ value: m, label: m }))} />
        </Field>
        <Field label="UTR / cheque no." htmlFor="pay-ref" hint="Needed for a cheque.">
          <Input id="pay-ref" value={ref} onChange={(e) => setRef(e.target.value)} />
        </Field>
      </div>
      <Field label="Through account" htmlFor="pay-account">
        <Select id="pay-account" value={account} onChange={(e) => setAccount(e.target.value)} placeholder="Not recorded against an account" options={accounts.map((a) => ({ value: a.id, label: `${a.name} (${a.kind}) - ${formatINR(a.balance)}` }))} />
      </Field>
      <Field label="Note" htmlFor="pay-note">
        <Input id="pay-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button loading={save.isPending} disabled={amount <= 0} onClick={() => save.mutate()}>
          {verb} {formatINR(amount)}
        </Button>
      </div>
    </div>
  )
}
