import { Download, Printer } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Skeleton } from '@/components/ui'
import { useBudgetReport } from '@/api/budgetReport'
import { formatINR } from '@/lib/utils'

const qty = (n: number) => n.toLocaleString('en-IN', { maximumFractionDigits: 3 })
const rate = (n: number) => n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
const first = (s: string) => (s || '').split('\n')[0]

/** The budget read back under the lines it was allocated against, as it prints. Lines with nothing budgeted are shown, not skipped. */
export default function BudgetReportPage() {
  const id = Number(useParams().id)
  const q = useBudgetReport(id)
  const r = q.data
  const t = r?.totals
  return (
    <>
      <div className="print:hidden">
        <PageHeader
          eyebrow="Client work orders"
          title="Budget Entry Report"
          description="The allocation, read back under the lines it was allocated against."
          actions={
            <>
              <Button variant="outline" asChild><Link to="/clients/work-orders">Back</Link></Button>
              <Button variant="outline" asChild><a href={`/api/erp/work-orders/${id}/budget-report.xlsx`} title="As a workbook"><Download /> Download</a></Button>
              <Button onClick={() => window.print()}><Printer /> Print</Button>
            </>
          }
        />
      </div>
      {q.isPending ? (
        <Skeleton className="h-96 w-full" />
      ) : q.isError || !r || !t ? (
        <p className="py-10 text-center text-muted-foreground">Could not load the report.</p>
      ) : (
        <div className="rounded-xl border border-border bg-card p-5 print:border-0 print:p-0">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2 border-b border-border pb-3">
            <h2 className="text-xl font-semibold">{r.title}</h2>
            <strong>{r.company}</strong>
          </div>
          <div className="mb-4 flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-muted-foreground">
            <span>Print Out Date: {r.printed_at}</span>
            <span>Fiscal Year: {r.fiscal_year}</span>
            <span>Sale order No: {r.sale_order_no}</span>
            <span>Project: {r.project}</span>
          </div>
          <div className="overflow-x-auto">
            <table aria-label="Budget report" className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Ordered Items</th><th className="pr-3 font-medium">RM code - Description</th>
                  <th className="pr-3 text-right font-medium">Quantity</th><th className="pr-3 font-medium">Units</th>
                  <th className="pr-3 text-right font-medium">Price</th><th className="pr-3 text-right font-medium">WO Qty</th><th className="text-right font-medium">Total Amount</th>
                </tr>
              </thead>
              <tbody>
                {r.groups.map((g) => (
                  <GroupRows key={g.fg_code} g={g} />
                ))}
                {!r.groups.length && <tr><td colSpan={7} className="py-8 text-center text-muted-foreground">Nothing on this order yet.</td></tr>}
              </tbody>
              <tfoot>
                <tr className="border-t border-border font-semibold">
                  <td colSpan={5} className="py-2">{t.ordered_lines} ordered line(s), {t.material_lines} material line(s){t.unbudgeted_lines ? <span className="text-warning">, {t.unbudgeted_lines} not budgeted</span> : null}</td>
                  <td className="tabular text-right">{formatINR(t.value)}</td><td className="tabular text-right">{formatINR(t.cost)}</td>
                </tr>
                <tr><td colSpan={6} className="py-1 text-right text-muted-foreground">Margin</td><td className="tabular text-right font-semibold">{formatINR(t.margin)} ({t.margin_percent}%)</td></tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

function GroupRows({ g }: { g: import('@/api/budgetReport').BudgetGroup }) {
  return (
    <>
      <tr className="bg-muted/50 font-medium">
        <td className="py-2 pr-3"><code>{g.fg_code}</code></td>
        <td colSpan={4} className="pr-3">{first(g.item_name)}</td>
        <td className="tabular pr-3 text-right">{formatINR(g.value)}</td>
        <td className="tabular text-right">{g.budgeted ? formatINR(g.cost) : <Badge tone="warning">Not budgeted</Badge>}</td>
      </tr>
      {g.lines.map((m, i) => (
        <tr key={i} className="border-b border-border/60">
          <td />
          <td className="py-1.5 pr-3">{first(m.description)}</td>
          <td className="tabular pr-3 text-right">{qty(m.qty)}</td>
          <td className="pr-3">{m.uom}</td>
          <td className="tabular pr-3 text-right">{rate(m.rate)}</td>
          <td className="tabular pr-3 text-right">{qty(m.wo_qty)}</td>
          <td className="tabular text-right">{formatINR(m.amount)}</td>
        </tr>
      ))}
    </>
  )
}
