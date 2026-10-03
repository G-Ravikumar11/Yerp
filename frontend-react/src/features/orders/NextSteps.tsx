import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, Circle, FileSignature, Receipt, Ruler } from 'lucide-react'
import { Badge, Button, Card, CardContent } from '@/components/ui'
import { useMeasurementBook } from '@/api/mb'
import { useSubBills } from '@/api/subbills'
import type { Order } from '@/api/orders'
import { compactINR, formatINR } from '@/lib/utils'
import { cn } from '@/lib/utils'

export type OrderTab = 'details' | 'schedule' | 'terms' | 'approval' | 'next'

const LABEL: Record<OrderTab, string> = { details: 'Details', schedule: 'Schedule', terms: 'Conditions', approval: 'Approval', next: 'After approval' }

/**
 * Back and Next under every section, so an order is worked through in order: details, schedule,
 * conditions, approval, and - once it is live - what comes after. On a draft with changes, Next
 * saves them first.
 */
export function StepNav({ steps, tab, onGo, dirty, saving, onSave }: { steps: OrderTab[]; tab: OrderTab; onGo: (t: OrderTab) => void; dirty: boolean; saving: boolean; onSave: () => Promise<unknown> }) {
  const at = steps.indexOf(tab)
  const prev = at > 0 ? steps[at - 1] : null
  const next = at >= 0 && at < steps.length - 1 ? steps[at + 1] : null
  if (!prev && !next) return null
  return (
    <div className="mt-8 flex items-center justify-between gap-3 border-t border-border pt-5" aria-label="Order steps">
      {prev ? (
        <Button variant="ghost" onClick={() => onGo(prev)}>
          <ArrowLeft /> Back: {LABEL[prev]}
        </Button>
      ) : (
        <span />
      )}
      {next && (
        <Button
          loading={saving}
          onClick={async () => {
            if (dirty) await onSave()
            onGo(next)
          }}
        >
          {dirty ? 'Save and continue: ' : 'Next: '}
          {LABEL[next]} <ArrowRight />
        </Button>
      )}
    </div>
  )
}

function Step({ done, title, children, action }: { done: boolean; title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <li className="flex items-start gap-3 py-4">
      <span className={cn('mt-0.5 grid size-6 shrink-0 place-items-center rounded-full', done ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground')}>{done ? <Check className="size-3.5" /> : <Circle className="size-3" />}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <div className="mt-0.5 text-[13px] text-muted-foreground">{children}</div>
      </div>
      {action}
    </li>
  )
}

/** Once the order is live: the work that follows from it, with where it stands and a way in. */
export function NextSteps({ order, canExecute, onExecute }: { order: Order; canExecute: boolean; onExecute: () => void }) {
  const book = useMeasurementBook(order.id)
  const bills = useSubBills(order.id)
  const s = book.data?.summary
  const live = order.status === 'APPROVED' || order.status === 'EXECUTED'
  const list = bills.data?.bills.filter((b) => b.status !== 'CANCELLED') ?? []
  const paid = list.filter((b) => b.status === 'PAID').length
  const measured = (s?.measured_value ?? 0) > 0
  const billedValue = bills.data?.summary.claimed ?? 0
  if (!live) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">This order is {order.status.toLowerCase()}. The steps after approval open once it is approved.</CardContent>
      </Card>
    )
  }
  return (
    <Card>
      <CardContent>
        <p className="mb-1 text-sm text-muted-foreground">
          {order.wo_number} is approved. This is what follows, in order.
        </p>
        <ol className="divide-y divide-border" aria-label="Steps after approval">
          <Step done title="Approved" action={<Badge tone="success">{order.approved_at ? 'Signed' : 'Live'}</Badge>}>
            {formatINR(order.net_order_value)} to {order.contractor || 'the gang'}.
          </Step>
          <Step
            done={order.status === 'EXECUTED'}
            title="Counter-signed copy back"
            action={
              order.status === 'APPROVED' && canExecute ? (
                <Button size="sm" variant="outline" onClick={onExecute}>
                  <FileSignature /> Mark as executed
                </Button>
              ) : undefined
            }
          >
            {order.status === 'EXECUTED' ? 'The gang has signed and returned it.' : 'When the gang returns the signed copy, mark it executed. Billing and measuring do not wait for it.'}
          </Step>
          <Step
            done={measured}
            title="Measure the work"
            action={
              <Button size="sm" asChild>
                <Link to={`/subcontractors/measurement-book?order=${order.id}`}>
                  <Ruler /> Open the book
                </Link>
              </Button>
            }
          >
            {measured ? (
              <>
                {compactINR(s?.measured_value)} measured of {compactINR(s?.ordered_value)}
                {!!s?.held_value && <> · {compactINR(s.held_value)} held back</>}
                {!!s?.unbilled_value && <> · {compactINR(s.unbilled_value)} ready to bill</>}
              </>
            ) : (
              'Nothing measured yet. Record the work line by line, or import the Excel book.'
            )}
          </Step>
          <Step
            done={list.length > 0}
            title="Bill what is measured"
            action={
              <Button size="sm" variant={measured ? 'primary' : 'outline'} asChild>
                <Link to={`/subcontractors/ra-bills?order=${order.id}`}>
                  <Receipt /> RA bills
                </Link>
              </Button>
            }
          >
            {list.length ? `${list.length} bill${list.length === 1 ? '' : 's'} · ${compactINR(billedValue)} claimed` : 'No RA bill yet. Draw one up once there is measured work.'}
          </Step>
          <Step done={list.length > 0 && paid === list.length} title="Certify and pay">
            {list.length ? `${paid} of ${list.length} paid.` : 'Bills climb the approval route, then are paid.'}
          </Step>
        </ol>
      </CardContent>
    </Card>
  )
}
