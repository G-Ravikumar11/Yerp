import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui'
import { putBackChargesOnBill, takeBackChargeOffBill } from '@/api/compliance'
import { billKeys, type SubBill } from '@/api/subbills'
import { useAction } from '@/lib/mutate'
import { formatINR } from '@/lib/utils'

/** What would make paying this contractor unsafe, and the charges that can come off this bill. Only a draft can change them. */
export function BackCharges({ bill, canEdit, onChanged }: { bill: SubBill; canEdit: boolean; onChanged: () => void }) {
  const draft = bill.status === 'DRAFT'
  const applied = bill.applied_back_charges ?? []
  const open = bill.open_back_charges ?? []
  const warnings = bill.compliance_warnings ?? []
  const on = useAction((id: number) => putBackChargesOnBill(bill.id, [id]), { invalidate: [billKeys.all], onSuccess: onChanged })
  const off = useAction((id: number) => takeBackChargeOffBill(bill.id, id), { invalidate: [billKeys.all], onSuccess: onChanged })
  if (!warnings.length && !applied.length && !(draft && open.length)) return null
  return (
    <Card className={warnings.some((w) => /not on record|ran out/.test(w)) ? 'border-warning/50' : undefined}>
      <CardHeader>
        <CardTitle>Papers and back-charges</CardTitle>
        <CardDescription>Papers the contractor must hold, and what has been charged back to them.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 text-[13.5px]">
        {warnings.length > 0 && (
          <ul aria-label="Contractor papers" className="grid gap-1">
            {warnings.map((w) => <li key={w} className="flex items-start gap-2"><Badge tone={/not on record|ran out/.test(w) ? 'danger' : 'warning'}>papers</Badge><span>{w}</span></li>)}
          </ul>
        )}
        {applied.length > 0 && (
          <div>
            <p className="mb-1 font-medium">Taken off this bill: {formatINR(bill.back_charges ?? 0)}</p>
            {applied.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-border py-1.5">
                <span><span className="font-mono text-xs">{c.number}</span> {c.kind} - {c.reason}</span>
                <span className="flex items-center gap-2 tabular">{formatINR(c.amount)}{draft && canEdit && <Button size="sm" variant="ghost" loading={off.isPending} onClick={() => off.mutate(c.id)}>Take off</Button>}</span>
              </div>
            ))}
          </div>
        )}
        {draft && canEdit && open.length > 0 && (
          <div>
            <p className="mb-1 font-medium">Open back-charges for this contractor</p>
            {open.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-border py-1.5">
                <span><span className="font-mono text-xs">{c.number}</span> {c.kind} - {c.reason}</span>
                <span className="flex items-center gap-2 tabular">{formatINR(c.amount)}<Button size="sm" variant="outline" loading={on.isPending} onClick={() => on.mutate(c.id)}>Take off this bill</Button></span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
