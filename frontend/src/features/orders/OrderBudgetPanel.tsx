import { Link } from 'react-router-dom'
import type { OrderBudgetCheck } from '@/api/budgetControl'
import { formatINR } from '@/lib/utils'

const qty = (n: number, unit: string) => `${n.toLocaleString('en-IN', { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ''}`

/**
 * The HO QS budget against this order, before it is sent - the server's own check (GET /api/wo/orders/:id/budget-check),
 * which it makes again when the order is sent and approved:
 *   - lines of the project still to budget stop it altogether;
 *   - lines past the BOQ quantity left need the Master's override at approval;
 *   - lines past the contractor budget left need a reason to send, and the Master signs.
 */
export function OrderBudgetPanel({ check }: { check: OrderBudgetCheck }) {
  if (!check.applies) return null
  const { project, missing, over_quantity: overQty, over_value: overValue } = check
  if (!missing.length && !overQty.length && !overValue.length) {
    return <p role="status" className="mb-5 rounded-xl border border-success/30 bg-success-soft p-3 text-[13.5px] text-success">HO QS budget: the project is fully budgeted and every line of this order is within what is left.</p>
  }
  const where = project ? [project.code, project.name].filter(Boolean).join(' ') : 'This project'
  return (
    <div className="mb-5 space-y-3">
      {missing.length > 0 && (
        <div role="alert" className="rounded-xl border border-danger/30 bg-danger-soft p-3.5 text-[13.5px] text-danger">
          <p className="font-semibold">{where}: the HO QS budget is not complete - {missing.length} BOQ line{missing.length === 1 ? '' : 's'} still to budget. This order cannot be sent until every line is.</p>
          <ul className="mt-1 list-disc pl-5">
            {missing.slice(0, 8).map((m) => <li key={m.key}>{m.item} - {m.status.toLowerCase()}{m.value != null && `, ${formatINR(m.value)}`}</li>)}
            {missing.length > 8 && <li>and {missing.length - 8} more</li>}
          </ul>
          {project && <Link className="mt-1 inline-block font-medium underline" to={`/projects/budgeting?job=${project.job_id}`}>Budget them on the Budgeting tab</Link>}
        </div>
      )}
      {overQty.length > 0 && (
        <div role="status" className="rounded-xl border border-warning/30 bg-warning-soft p-3.5 text-[13.5px] text-warning">
          <p className="font-semibold">More than the BOQ quantity left - the Master overrides this at approval, with a reason:</p>
          <ul className="mt-1 list-disc pl-5">{overQty.map((x) => <li key={x.key}>{x.item}: {qty(x.this_order_qty, x.unit)} on this order, {qty(x.available_qty, x.unit)} left ({qty(x.short_qty ?? 0, x.unit)} short)</li>)}</ul>
        </div>
      )}
      {overValue.length > 0 && (
        <div role="status" className="rounded-xl border border-warning/30 bg-warning-soft p-3.5 text-[13.5px] text-warning">
          <p className="font-semibold">More than the contractor budget left - send it with the reason, and the Master signs it:</p>
          <ul className="mt-1 list-disc pl-5">{overValue.map((x) => <li key={x.key}>{x.item}: {formatINR(x.this_order_value)} on this order, {formatINR(x.available_value)} left ({formatINR(x.short_value ?? 0)} more)</li>)}</ul>
        </div>
      )}
    </div>
  )
}
