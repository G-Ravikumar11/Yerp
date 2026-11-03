import { lazy, Suspense } from 'react'
import { Download } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Stat, StatGrid } from '@/components/ui'
import { useCashFlow, usePayables, useReceivables } from '@/api/dashboard'
import type { MonthFlow } from '@/lib/cashflow'
import { compactINR, downloadCsv, formatINR } from '@/lib/utils'

const CashFlowChart = lazy(() => import('@/features/dashboard/Charts').then((m) => ({ default: m.CashFlowChart })))
const AgeingChart = lazy(() => import('@/features/dashboard/Charts').then((m) => ({ default: m.AgeingChart })))

/** Money in and money out, month by month, over the whole company's ledger - the trend behind the Finance Dashboard's
 * single Cash Flow Trend tile, with the figures laid out month by month underneath it. */
export default function CashFlowPage() {
  const cash = useCashFlow(true)
  const receivables = useReceivables(true)
  const payables = usePayables(true)
  const months = cash.data ?? []
  const hasData = months.some((m) => m.received || m.paid)
  const last = months[months.length - 1]
  const totalIn = months.reduce((n, m) => n + m.received, 0)
  const totalOut = months.reduce((n, m) => n + m.paid, 0)

  const columns: TableColumn<MonthFlow>[] = [
    { id: 'm', header: 'Month', cell: (m) => m.label },
    { id: 'in', header: 'Money in', align: 'right', cell: (m) => <span className="tabular">{formatINR(m.received)}</span> },
    { id: 'out', header: 'Money out', align: 'right', cell: (m) => <span className="tabular">{formatINR(m.paid)}</span> },
    { id: 'net', header: 'Net', align: 'right', cell: (m) => <span className={`tabular font-medium ${m.net < 0 ? 'text-danger' : 'text-success'}`}>{formatINR(m.net)}</span> },
    { id: 'bal', header: 'Balance', align: 'right', cell: (m) => <span className="tabular">{formatINR(m.running)}</span> },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Accounts" title="Cash Flow" description="Money received and money paid out each month, across every bank account and cash box, and the balance left."
        actions={<Button variant="outline" disabled={!months.length} onClick={() => downloadCsv('cash-flow', ['Month', 'Money in', 'Money out', 'Net', 'Balance'], months.map((m) => [m.label, m.received, m.paid, m.net, m.running]))}><Download /> Export</Button>}
      />

      <StatGrid>
        <Stat label="Money in (12 months)" value={compactINR(totalIn)} loading={cash.isPending} />
        <Stat label="Money out (12 months)" value={compactINR(totalOut)} loading={cash.isPending} />
        <Stat label="Net (12 months)" value={compactINR(totalIn - totalOut)} tone={totalIn - totalOut < 0 ? 'danger' : 'success'} loading={cash.isPending} />
        <Stat label="Balance today" value={compactINR(last?.running)} loading={cash.isPending} />
      </StatGrid>

      <Card className="mb-5">
        <CardHeader>
          <CardTitle>Cash Flow Trend</CardTitle>
          <CardDescription>Monthly inflow against outflow, with the running balance.</CardDescription>
        </CardHeader>
        <CardContent>
          {cash.isPending ? (
            <Skeleton className="h-[260px] w-full" />
          ) : cash.isError ? (
            <p className="grid h-40 place-items-center text-sm text-muted-foreground">Could not load the ledger.</p>
          ) : !hasData ? (
            <p className="grid h-40 place-items-center text-sm text-muted-foreground">Nothing received or paid in the last twelve months.</p>
          ) : (
            <Suspense fallback={<Skeleton className="h-[260px] w-full" />}>
              <CashFlowChart months={months} />
            </Suspense>
          )}
        </CardContent>
      </Card>

      <Card className="mb-5">
        <CardHeader>
          <CardTitle>Unpaid money, by how old</CardTitle>
          <CardDescription>What is still owed to us and what we still owe, grouped by how long it has been pending.</CardDescription>
        </CardHeader>
        <CardContent>
          {receivables.isPending || payables.isPending ? (
            <Skeleton className="h-[220px] w-full" />
          ) : (
            <Suspense fallback={<Skeleton className="h-[220px] w-full" />}>
              <AgeingChart receivable={receivables.data?.buckets} payable={payables.data?.buckets} />
            </Suspense>
          )}
        </CardContent>
      </Card>

      <DataTable label="Cash flow by month" rows={months.slice().reverse()} columns={columns} rowKey={(m) => m.month} loading={cash.isPending} empty="Nothing received or paid in the last twelve months." />
    </>
  )
}
