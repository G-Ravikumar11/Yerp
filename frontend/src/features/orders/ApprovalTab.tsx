import { CheckCircle2, Circle, Clock, MinusCircle, XCircle } from 'lucide-react'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui'
import type { Order, RouteStep } from '@/api/orders'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'
import { cn } from '@/lib/utils'

const stepIcon = (s: RouteStep['status']) => {
  if (s === 'approved') return <CheckCircle2 className="size-5 text-success" />
  if (s === 'waiting') return <Clock className="size-5 text-warning" />
  if (s === 'rejected' || s === 'cancelled') return <XCircle className="size-5 text-danger" />
  if (s === 'skipped') return <MinusCircle className="size-5 text-subtle" />
  return <Circle className="size-5 text-subtle" />
}

const stepWord: Record<string, string> = { approved: 'Signed', waiting: 'Waiting', pending: 'Later', skipped: 'Not needed', cancelled: 'Stopped', rejected: 'Sent back' }

/** Where the order is on its way to being signed, what it is worth after tax, and what has been done to it. */
export function ApprovalTab({ order }: { order: Order }) {
  const route = order.approval_route ?? []
  const history = order.history ?? []
  const schedule = order.billing_schedule?.rows ?? []

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Route</CardTitle>
          <CardDescription>
            {order.status === 'PROVISIONAL' && order.pending_with?.length ? `Waiting with ${order.pending_with.join(', ')}.` : 'Each person above the one who raised it signs in turn.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {route.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">Not sent for approval yet.</p>
          ) : (
            <ol className="relative space-y-4 border-l border-border pl-6">
              {route.map((r) => (
                <li key={r.step} className="relative">
                  <span className="absolute -left-[34px] top-0 grid size-6 place-items-center rounded-full bg-card">{stepIcon(r.status)}</span>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{r.name}</span>
                    <Badge tone={r.status === 'approved' ? 'success' : r.status === 'waiting' ? 'warning' : 'neutral'}>{stepWord[r.status] ?? r.status}</Badge>
                  </div>
                  {(r.decided_at || r.notes) && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {formatDate(r.decided_at)} {r.notes && `- ${r.notes}`}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
          {order.rejection_reason && order.status === 'DRAFT' && (
            <p className="mt-4 rounded-lg bg-danger-soft p-3 text-[13px] text-danger">Sent back: {order.rejection_reason}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>What it comes to</CardTitle>
          <CardDescription>The same heads appear on every RA bill against this order.</CardDescription>
        </CardHeader>
        <CardContent>
          <table className="w-full text-[13.5px]">
            <tbody>
              {schedule.map((h) => (
                <tr key={h.head} className={cn('border-b border-border last:border-0', (h.kind === 'net' || h.kind === 'total') && 'font-semibold', (h.kind === 'info' || h.kind === 'hold') && 'text-muted-foreground')}>
                  <td className="py-2">
                    {h.head}
                    {h.rate ? <span className="ml-1.5 text-xs text-muted-foreground">{h.rate}%</span> : null}
                    {h.note && <div className="text-xs font-normal text-subtle">{h.note}</div>}
                  </td>
                  <td className={cn('tabular py-2 text-right align-top', h.kind === 'less' && 'text-danger')}>
                    {h.kind === 'less' ? '-' : ''}
                    {formatINR(Math.abs(h.amount))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!!order.advance_paid && <p className="mt-3 text-xs text-muted-foreground">Mobilisation advance paid so far: {formatINR(order.advance_paid)}.</p>}
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>History</CardTitle>
        </CardHeader>
        <CardContent>
          {history.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">Nothing yet.</p>
          ) : (
            <ul className="divide-y divide-border">
              {history
                .slice()
                .reverse()
                .map((h, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2.5 text-[13.5px]">
                    <span className="w-24 shrink-0 font-medium">{h.action.charAt(0) + h.action.slice(1).toLowerCase()}</span>
                    <span className="text-muted-foreground">{h.actor}</span>
                    <span className="text-xs text-subtle">{formatDate(h.at)}</span>
                    {h.comments && <span className="w-full pl-24 text-[13px] text-muted-foreground">{h.comments}</span>}
                  </li>
                ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
