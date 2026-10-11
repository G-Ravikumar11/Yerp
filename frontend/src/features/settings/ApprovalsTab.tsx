import { useEffect, useState } from 'react'
import { Badge, Button, Field, Input, NumField, Skeleton } from '@/components/ui'
import { useAction } from '@/lib/mutate'
import { saveApprovalRules, saveOrgDomain, settingsKeys, useApprovalRules, useOrgDomain, useWhoApproves } from '@/api/settings'
import { Section } from './Section'

function Rules() {
  const q = useApprovalRules()
  const [below, setBelow] = useState(0)
  const [above, setAbove] = useState(0)
  const [ownerSigns, setOwnerSigns] = useState(false)
  const [ownerSignsBills, setOwnerSignsBills] = useState(true)
  useEffect(() => {
    if (!q.data) return
    setBelow(q.data.auto_below)
    setAbove(q.data.finance_above)
    setOwnerSigns(q.data.owner_signs_work_orders)
    setOwnerSignsBills(q.data.owner_signs_sub_bills)
  }, [q.data])
  const save = useAction(() => saveApprovalRules({ auto_below: below, finance_above: above, owner_signs_work_orders: ownerSigns, owner_signs_sub_bills: ownerSignsBills }), { invalidate: [settingsKeys.all, ['approvals']], success: 'Approval rules saved.' })
  if (q.isPending) return <Skeleton className="h-40 w-full" />
  const cur = q.data?.currency ?? 'INR'
  return (
    <Section title="Approval rules" description="What needs a signature, and how high it climbs. Leave a limit at 0 for no rule.">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={`Sign-off limit (${cur})`} htmlFor="ar-below" hint="Costs below this need nobody to approve them."><NumField id="ar-below" value={below} onValue={setBelow} /></Field>
        <Field label={`Finance limit (${cur})`} htmlFor="ar-above" hint={q.data?.has_finance_approver ? `Above this, ${q.data.finance_approver} is added.` : 'Above this, someone who can approve bills is added - nobody holds that yet.'}><NumField id="ar-above" value={above} onValue={setAbove} /></Field>
      </div>
      <label className="mt-4 flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={ownerSigns} onChange={(e) => setOwnerSigns(e.target.checked)} /><span>The Master signs every work order last<span className="block text-xs text-muted-foreground">Even when the managers have all approved it, it waits for the Master.</span></span></label>
      <label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={ownerSignsBills} onChange={(e) => setOwnerSignsBills(e.target.checked)} /><span>The Master signs every RA bill last<span className="block text-xs text-muted-foreground">Even when the managers have all certified it, it waits for the Master. Bills already sent keep the route they were sent with.</span></span></label>
      <Button className="mt-4" loading={save.isPending} onClick={() => save.mutate()}>Save approval rules</Button>
    </Section>
  )
}

function Routes() {
  const q = useWhoApproves()
  return (
    <Section title="Who approves what" description="Where each kind of paper goes when the person who raised it has no manager set. Check it against how you want things run.">
      {q.isPending ? <Skeleton className="h-32 w-full" /> : (
        <ul className="divide-y divide-border">
          {q.data?.routes.map((r) => (
            <li key={r.right} className="py-3">
              <p className="text-sm font-medium">{r.what}</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {r.people.length ? r.people.map((p) => <Badge key={p.name} tone="neutral">{p.name}{p.department ? ` · ${p.department}` : ''}</Badge>) : <span className="text-xs text-warning">Nobody holds this right yet.</span>}
                <Badge tone="info">{q.data.owner} (Master, last)</Badge>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function Domain() {
  const q = useOrgDomain()
  const [d, setD] = useState('')
  useEffect(() => setD(q.data?.domain ?? ''), [q.data])
  const save = useAction(() => saveOrgDomain(d), { invalidate: [settingsKeys.all], success: 'Staff email domain saved.' })
  return (
    <Section title="Staff email domain" description="New staff accounts are issued on this domain, e.g. yprojects.co.in. People already added keep the address they have.">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Domain" htmlFor="org-domain" className="w-72"><Input id="org-domain" placeholder="yourcompany.com" value={d} onChange={(e) => setD(e.target.value)} /></Field>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save domain</Button>
      </div>
      {!!q.data?.employees_off_domain && <p className="mt-2 text-xs text-muted-foreground">{q.data.employees_off_domain} people sign in with an address outside this domain.</p>}
    </Section>
  )
}

/** Who signs what: the money limits, the route each paper takes, and the staff email domain. */
export default function ApprovalsTab() {
  return (
    <>
      <Rules />
      <Routes />
      <Domain />
    </>
  )
}
