import { useReducedMotion } from 'framer-motion'
import { useMinWidth } from '@/lib/hooks'
import { Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ProjectPnl } from '@/api/dashboard'
import { ageing, type MonthFlow } from '@/lib/cashflow'
import { compactINR, formatINR } from '@/lib/utils'

/* The charts read their colours from the design tokens, so they follow the theme. */
const RECEIVED = 'var(--chart-3)'
const PAID = 'var(--chart-2)'
const ACCENT = 'var(--chart-1)'
const GRID = 'var(--border)'
const TICK = { fill: 'var(--muted-foreground)', fontSize: 12 }

interface Row {
  name: string
  value: number
  color: string
  strong?: boolean
}

/** One tooltip for every chart: a heading and a row per figure. */
function Tip({ active, label, title, rows }: { active?: boolean; label?: string; title?: string; rows: Row[] }) {
  if (!active || !rows.length) return null
  return (
    <div className="min-w-44 rounded-lg border border-border bg-popover px-3 py-2.5 text-[13px] shadow-lift">
      <p className="mb-1.5 font-medium">{title ?? label}</p>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.name} className="flex items-center justify-between gap-6">
            <span className="flex items-center gap-2 text-muted-foreground">
              <span className="size-2 rounded-full" style={{ background: r.color }} />
              {r.name}
            </span>
            <span className={`tabular ${r.strong ? 'font-semibold' : ''}`} style={r.strong ? { color: r.color } : undefined}>
              {formatINR(r.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const legend = (value: string) => <span className="text-xs text-muted-foreground">{value}</span>

/** Revenue against cost for each project, the biggest first. Margin is in the tooltip - and red when it is a loss. */
export function ProfitChart({ projects }: { projects: ProjectPnl[] }) {
  const calm = useReducedMotion()
  const wide = useMinWidth(640)
  const data = projects
    .slice()
    .sort((a, b) => b.order_value - a.order_value)
    .slice(0, 8)
    .map((p) => ({ ...p, label: p.number || p.name }))

  return (
    <figure aria-label="Revenue and cost by project" className="m-0 h-full min-h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 0, bottom: 4 }} barCategoryGap="28%">
          <CartesianGrid horizontal={false} stroke={GRID} strokeDasharray="3 4" />
          <XAxis type="number" tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="label" width={92} tick={TICK} axisLine={false} tickLine={false} />
          <Tooltip
            cursor={{ fill: 'var(--accent)' }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as (ProjectPnl & { label: string }) | undefined
              if (!p) return null
              return (
                <Tip
                  active={active}
                  title={`${p.number} ${p.name}`}
                  rows={[
                    { name: 'Revenue earned', value: p.revenue, color: ACCENT },
                    { name: 'Cost incurred', value: p.incurred, color: PAID },
                    { name: `Margin (${p.margin_percent}%)`, value: p.margin, color: p.margin < 0 ? 'var(--danger)' : 'var(--success)', strong: true },
                  ]}
                />
              )
            }}
          />
          <Legend verticalAlign="top" align={wide ? 'right' : 'left'} iconType="circle" iconSize={8} formatter={legend} />
          <Bar name="Revenue" dataKey="revenue" fill={ACCENT} radius={[0, 6, 6, 0]} maxBarSize={22} isAnimationActive={!calm} />
          <Bar name="Cost" dataKey="incurred" fill={PAID} radius={[0, 6, 6, 0]} maxBarSize={22} isAnimationActive={!calm} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}

/** Money in and out by month, with the running balance drawn over it. */
export function CashFlowChart({ months }: { months: MonthFlow[] }) {
  const calm = useReducedMotion()
  const wide = useMinWidth(640)
  return (
    <figure aria-label="Cash flow by month" className="m-0 h-full min-h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={months} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={3}>
          <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="3 4" />
          <XAxis dataKey="label" tick={TICK} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          <YAxis tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} width={78} />
          <Tooltip
            cursor={{ fill: 'var(--accent)' }}
            content={({ active, payload }) => {
              const m = payload?.[0]?.payload as MonthFlow | undefined
              if (!m) return null
              return (
                <Tip
                  active={active}
                  title={m.label}
                  rows={[
                    { name: 'Received', value: m.received, color: RECEIVED },
                    { name: 'Paid out', value: m.paid, color: PAID },
                    { name: 'Net this month', value: m.net, color: m.net < 0 ? 'var(--danger)' : 'var(--success)', strong: true },
                    { name: 'Running balance', value: m.running, color: ACCENT },
                  ]}
                />
              )
            }}
          />
          <Legend verticalAlign="top" align={wide ? 'right' : 'left'} iconType="circle" iconSize={8} formatter={legend} />
          <Bar name="Received" dataKey="received" fill={RECEIVED} radius={[6, 6, 0, 0]} maxBarSize={26} isAnimationActive={!calm} />
          <Bar name="Paid out" dataKey="paid" fill={PAID} radius={[6, 6, 0, 0]} maxBarSize={26} isAnimationActive={!calm} />
          <Line name="Running balance" type="monotone" dataKey="running" stroke={ACCENT} strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} isAnimationActive={!calm} />
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  )
}

/** What is owed to us and what we owe, by how long it has been owing. */
export function AgeingChart({ receivable, payable }: { receivable: Record<string, number> | undefined; payable: Record<string, number> | undefined }) {
  const calm = useReducedMotion()
  const wide = useMinWidth(640)
  const rows = ageing(receivable, payable)
  return (
    <figure aria-label="Owed to us and owed by us, by age" className="m-0 h-full min-h-[260px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={3}>
          <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="3 4" />
          <XAxis dataKey="bucket" tick={TICK} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} width={78} />
          <Tooltip
            cursor={{ fill: 'var(--accent)' }}
            content={({ active, payload, label }) => (
              <Tip
                active={active}
                label={String(label)}
                rows={(payload ?? []).map((p) => ({ name: String(p.name), value: Number(p.value), color: String(p.color ?? p.fill) }))}
              />
            )}
          />
          <Legend verticalAlign="top" align={wide ? 'right' : 'left'} iconType="circle" iconSize={8} formatter={legend} />
          <Bar name="Owed to us" dataKey="receivable" fill={RECEIVED} radius={[6, 6, 0, 0]} maxBarSize={30} isAnimationActive={!calm} />
          <Bar name="We owe" dataKey="payable" fill={PAID} radius={[6, 6, 0, 0]} maxBarSize={30} isAnimationActive={!calm} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}
