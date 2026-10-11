import { Download } from 'lucide-react'
import { Button, Card, Skeleton } from '@/components/ui'
import { useStatement } from '@/api/clientBook'
import { cn, formatINR } from '@/lib/utils'

function Row({ label, value, strong, rule, tone }: { label: string; value?: string; strong?: boolean; rule?: boolean; tone?: 'warning' }) {
  return (
    <div className={cn('flex justify-between gap-3 py-1.5', rule && 'mt-1 border-t border-border pt-2.5')}>
      <span className={cn('text-[13px]', strong ? 'font-semibold text-foreground' : 'text-muted-foreground')}>{label}</span>
      <span className={cn('tabular text-sm', strong ? 'font-bold' : 'font-semibold', tone === 'warning' && 'text-warning')}>{value}</span>
    </div>
  )
}

/** One panel that answers "where are we on this order": every figure already existed, now in a column so the subtraction shows. */
export function Statement({ workOrderId }: { workOrderId: number }) {
  const q = useStatement(workOrderId)
  const s = q.data
  const pc = Math.max(0, Math.min(100, s?.progress.percent_complete ?? 0))
  return (
    <Card className="mb-6">
      <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
        <h2 className="text-base font-semibold">Where this order stands</h2>
        <Button variant="outline" size="sm" asChild>
          <a href={`/api/erp/work-orders/${workOrderId}/statement.xlsx`}>
            <Download /> Download the statement
          </a>
        </Button>
      </div>
      {!s ? (
        <div className="p-5">
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="grid gap-x-8 gap-y-4 p-5 sm:grid-cols-2 xl:grid-cols-4">
          <div>
            <Row label="Original order" value={formatINR(s.order.original_value)} />
            <Row label="Variations agreed" value={formatINR(s.order.variations_agreed)} />
            <Row label="Revised order" value={formatINR(s.order.revised_value)} strong rule />
            {s.order.variations_pending > 0 && <Row label="Asked for, not agreed" value={formatINR(s.order.variations_pending)} tone="warning" />}
          </div>
          <div>
            <Row label="Measured to date" value={formatINR(s.progress.measured_value)} />
            <div className="my-1 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(pc)} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-full rounded-full bg-primary" style={{ width: `${pc}%` }} />
            </div>
            <Row label="Left to build" value={formatINR(s.progress.left_to_build)} />
            {s.progress.over_run_not_yet_varied > 0 && <Row label="Built past the order" value={formatINR(s.progress.over_run_not_yet_varied)} tone="warning" />}
            <Row label={`${pc}% complete`} strong rule />
          </div>
          <div>
            <Row label="Claimed on bills" value={formatINR(s.money.claimed)} />
            <Row label="Certified" value={formatINR(s.money.certified)} />
            <Row label="Paid" value={formatINR(s.money.paid)} strong />
            <Row label="Awaiting payment" value={formatINR(s.money.awaiting_payment)} tone={s.money.awaiting_payment ? 'warning' : undefined} />
          </div>
          <div>
            <Row label="Measured, not billed" value={formatINR(s.money.measured_not_billed)} strong tone={s.money.measured_not_billed ? 'warning' : undefined} />
            <Row label="Retention held" value={formatINR(s.money.retention_held)} rule />
            <Row label="TDS deducted" value={formatINR(s.money.tds_deducted)} />
          </div>
        </div>
      )}
    </Card>
  )
}
