import { useReducedMotion } from 'framer-motion'
import { useMinWidth } from '@/lib/hooks'
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, LabelList, Legend, Line, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ProjectPnl } from '@/api/dashboard'
import type { CostMix, CostRow } from '@/api/costs'
import { ageing, type MonthFlow } from '@/lib/cashflow'
import { compactINR, formatINR } from '@/lib/utils'

/* The charts read their colours from the design tokens, so they follow the theme. */
// Money coming in is always blue and money going out always cyan, on every chart, so they read at a glance.
// Profit and loss keep green and red: there the colour is the message.
const RECEIVED = 'var(--chart-1)'
const PAID = 'var(--chart-3)'
const BALANCE = 'var(--chart-4)'
const REVENUE = 'var(--chart-1)'
const COST = 'var(--chart-3)'
const PROFIT = 'var(--success)'
const LOSS = 'var(--danger)'
// Bars are lit from the top: the colour fades a little towards the axis.
const IN_FILL = 'url(#fill-in)'
const OUT_FILL = 'url(#fill-out)'
const FILLS = (
  <defs>
    <linearGradient id="fill-in" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor="var(--chart-2)" />
      <stop offset="100%" stopColor="var(--chart-1)" />
    </linearGradient>
    <linearGradient id="fill-out" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stopColor="var(--chart-3)" />
      <stop offset="100%" stopColor="var(--chart-3)" stopOpacity={0.6} />
    </linearGradient>
  </defs>
)
const GRID = 'var(--border)'
const TICK = { fill: 'var(--muted-foreground)', fontSize: 12 }
const short = (v: string, n = 14) => (v.length > n ? v.slice(0, n - 1) + '…' : v)
const label = (v: unknown) => (typeof v === 'number' && v ? compactINR(v).replace(/\s/g, ' ') : '')

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


const SLICES = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)']

type ProjectRow = ProjectPnl & { label: string }

const frame = (aria: string, h: number, chart: React.ReactElement) => (
  <figure aria-label={aria} className="chart-glow m-0 h-full" style={{ minHeight: h }}>
    <ResponsiveContainer width="100%" height="100%">
      {chart}
    </ResponsiveContainer>
  </figure>
)

/** A project's number with its name under it, so a bar can be read without hovering. */
function ProjectTick({ x = 0, y = 0, payload, names, narrow = false }: { x?: number; y?: number; payload?: { value: string }; names: Record<string, string>; narrow?: boolean }) {
  const key = payload?.value ?? ''
  // A phone has room for the number only; the name is in the tooltip a tap away.
  return (
    <g transform={`translate(${x},${y})`}>
      <text y={14} textAnchor="middle" fill="var(--foreground)" fontSize={narrow ? 11 : 12} fontWeight={500}>{short(key, narrow ? 9 : 10)}</text>
      {!narrow && names[key] && <text y={29} textAnchor="middle" fill="var(--muted-foreground)" fontSize={11}>{short(names[key], 12)}</text>}
    </g>
  )
}

/** Money earned against cost incurred for each project: the busiest first, and only projects with money moving. */
export function ProfitChart({ projects }: { projects: ProjectPnl[] }) {
  const calm = useReducedMotion()
  const wide = useMinWidth(640)
  const activity = (p: ProjectPnl) => p.revenue + p.incurred
  const live = projects.filter((p) => activity(p) > 0)
  const data: ProjectRow[] = (live.length ? live : projects)
    .slice()
    .sort((a, b) => activity(b) - activity(a) || b.order_value - a.order_value)
    .slice(0, wide ? 8 : 4)
    .map((p) => ({ ...p, label: p.number || p.name }))
  const names = Object.fromEntries(data.map((p) => [p.label, p.number ? p.name : '']))
  return frame(
    'Money earned and spent by project',
    240,
    <BarChart data={data} margin={{ top: 22, right: 12, left: 0, bottom: 4 }} barGap={6} barCategoryGap="22%">
      {FILLS}
      <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="2 6" strokeOpacity={0.7} />
      <XAxis dataKey="label" interval={0} height={wide ? 40 : 24} tick={<ProjectTick names={names} narrow={!wide} />} axisLine={false} tickLine={false} />
      <YAxis tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} width={wide ? 64 : 78} tickCount={5} />
      <Tooltip
        cursor={{ fill: 'var(--accent)', fillOpacity: 0.5, radius: 8 }}
        content={({ active, payload }) => {
          const p = payload?.[0]?.payload as ProjectRow | undefined
          if (!p) return null
          return (
            <Tip
              active={active}
              title={`${p.number} ${p.name}`}
              rows={[
                { name: 'Money earned', value: p.revenue, color: REVENUE },
                { name: 'Money spent', value: p.incurred, color: COST },
                { name: `Profit (${p.margin_percent}%)`, value: p.margin, color: p.margin < 0 ? LOSS : PROFIT, strong: true },
              ]}
            />
          )
        }}
      />
      <Legend verticalAlign={wide ? 'top' : 'bottom'} align={wide ? 'right' : 'left'} iconType="circle" iconSize={8} formatter={legend} wrapperStyle={wide ? undefined : { paddingTop: 8 }} />
      <Bar name="Money earned" dataKey="revenue" fill={IN_FILL} radius={[8, 8, 2, 2]} maxBarSize={36} isAnimationActive={!calm}>
        {wide && <LabelList dataKey="revenue" position="top" formatter={label} style={{ fill: 'var(--muted-foreground)', fontSize: 11 }} />}
      </Bar>
      <Bar name="Money spent" dataKey="incurred" fill={OUT_FILL} radius={[8, 8, 2, 2]} maxBarSize={36} isAnimationActive={!calm}>
        {wide && <LabelList dataKey="incurred" position="top" formatter={label} style={{ fill: 'var(--muted-foreground)', fontSize: 11 }} />}
      </Bar>
    </BarChart>,
  )
}

/** How many incidents were reported, by kind, the most frequent first. */
export function IncidentsChart({ kinds }: { kinds: { kind: string; count: number }[] }) {
  const calm = useReducedMotion()
  const data = kinds.slice().sort((a, b) => b.count - a.count).slice(0, 10)
  return frame(
    'Safety incidents by kind',
    210,
    <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, left: 0, bottom: 4 }} barCategoryGap="28%">
      <CartesianGrid horizontal={false} stroke={GRID} strokeDasharray="2 6" strokeOpacity={0.7} />
      <XAxis type="number" allowDecimals={false} tick={TICK} axisLine={false} tickLine={false} />
      <YAxis type="category" dataKey="kind" width={150} tick={TICK} axisLine={false} tickLine={false} tickFormatter={(v: string) => short(v, 24)} />
      <Tooltip
        cursor={{ fill: 'var(--accent)', fillOpacity: 0.5, radius: 8 }}
        content={({ active, payload }) => {
          const d = payload?.[0]?.payload as { kind: string; count: number } | undefined
          if (!active || !d) return null
          return (
            <div className="rounded-lg border border-border bg-popover px-3 py-2.5 text-[13px] shadow-lift">
              <p className="font-medium">{d.kind}</p>
              <p className="tabular text-muted-foreground">{d.count} reported</p>
            </div>
          )
        }}
      />
      <Bar dataKey="count" fill={LOSS} radius={[2, 8, 8, 2]} maxBarSize={26} isAnimationActive={!calm}>
        <LabelList dataKey="count" position="right" style={{ fill: 'var(--muted-foreground)', fontSize: 11 }} />
      </Bar>
    </BarChart>,
  )
}

/** Profit or loss per project; green to the right of zero, red to the left. */
export function MarginChart({ projects }: { projects: ProjectPnl[] }) {
  const calm = useReducedMotion()
  const data: ProjectRow[] = projects
    .slice()
    .sort((a, b) => b.margin - a.margin)
    .slice(0, 10)
    .map((p) => ({ ...p, label: p.number || p.name }))
  return frame(
    'Profit or loss by project',
    210,
    <BarChart data={data} layout="vertical" margin={{ top: 4, right: 56, left: 0, bottom: 4 }} barCategoryGap="28%">
      <CartesianGrid horizontal={false} stroke={GRID} strokeDasharray="2 6" strokeOpacity={0.7} />
      <ReferenceLine x={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
      <XAxis type="number" tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} />
      <YAxis type="category" dataKey="label" width={104} tick={TICK} axisLine={false} tickLine={false} tickFormatter={(v: string) => short(v, 16)} />
      <Tooltip
        cursor={{ fill: 'var(--accent)', fillOpacity: 0.5, radius: 8 }}
        content={({ active, payload }) => {
          const p = payload?.[0]?.payload as ProjectRow | undefined
          if (!p) return null
          return <Tip active={active} title={`${p.number} ${p.name}`} rows={[{ name: `Profit (${p.margin_percent}%)`, value: p.margin, color: p.margin < 0 ? LOSS : PROFIT, strong: true }]} />
        }}
      />
      <Bar name="Profit or loss" dataKey="margin" radius={[0, 8, 8, 0]} maxBarSize={14} isAnimationActive={!calm}>
        {data.map((p) => (
          <Cell key={p.job_id} fill={p.margin < 0 ? LOSS : PROFIT} />
        ))}
        <LabelList dataKey="margin" position="right" formatter={label} fill="currentColor" fontSize={11} className="text-muted-foreground" />
      </Bar>
    </BarChart>,
  )
}

/** What each project was sold for, what it is forecast to cost, and what is already spent. */
export function BudgetChart({ projects }: { projects: CostRow[] }) {
  const calm = useReducedMotion()
  const wide = useMinWidth(640)
  const data = projects
    .slice()
    .sort((a, b) => b.contract_value - a.contract_value)
    .slice(0, 8)
    .map((p) => ({ ...p, label: p.number || p.name }))
  return frame(
    'Budget against spend by project',
    210,
    <BarChart data={data} margin={{ top: 12, right: 16, left: 0, bottom: 0 }} barGap={4} barCategoryGap="30%">
      {FILLS}
      <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="2 6" strokeOpacity={0.7} />
      <XAxis dataKey="label" tick={TICK} axisLine={false} tickLine={false} tickFormatter={(v: string) => short(v, 10)} />
      <YAxis tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} width={78} />
      <Tooltip
        cursor={{ fill: 'var(--accent)', fillOpacity: 0.5, radius: 8 }}
        content={({ active, payload }) => {
          const p = payload?.[0]?.payload as (CostRow & { label: string }) | undefined
          if (!p) return null
          return (
            <Tip
              active={active}
              title={`${p.number} ${p.name}`}
              rows={[
                { name: 'Contract amount', value: p.contract_value, color: REVENUE },
                { name: 'Expected cost', value: p.forecast_cost, color: 'var(--chart-4)' },
                { name: 'Spent so far', value: p.incurred, color: COST },
                { name: 'Promised, bill not yet received', value: p.commitment, color: 'var(--chart-5)' },
              ]}
            />
          )
        }}
      />
      <Legend verticalAlign="top" align={wide ? 'right' : 'left'} iconType="circle" iconSize={8} formatter={legend} />
      <Bar name="Contract amount" dataKey="contract_value" fill={IN_FILL} radius={[8, 8, 2, 2]} maxBarSize={18} isAnimationActive={!calm} />
      <Bar name="Expected cost" dataKey="forecast_cost" fill={'var(--chart-4)'} radius={[8, 8, 2, 2]} maxBarSize={18} isAnimationActive={!calm} />
      <Bar name="Spent so far" dataKey="incurred" fill={OUT_FILL} radius={[8, 8, 2, 2]} maxBarSize={18} isAnimationActive={!calm} />
    </BarChart>,
  )
}

/** Where the money has gone: materials, labour, subcontractors and the rest, across every project. */
export function CostMixChart({ categories }: { categories: CostMix[] }) {
  const calm = useReducedMotion()
  const data = categories.filter((c) => c.amount > 0)
  const total = data.reduce((n, c) => n + c.amount, 0)
  return frame(
    'Cost by category',
    210,
    <PieChart>
      <Tooltip
        content={({ active, payload }) => {
          const c = payload?.[0]?.payload as CostMix | undefined
          if (!c) return null
          return <Tip active={active} title={c.label} rows={[{ name: `${Math.round((c.amount / total) * 100)}% of all spending`, value: c.amount, color: 'var(--chart-1)', strong: true }]} />
        }}
      />
      <Legend verticalAlign="bottom" iconType="circle" iconSize={8} formatter={legend} />
      <Pie data={data} dataKey="amount" nameKey="label" innerRadius="52%" outerRadius="80%" paddingAngle={2} stroke="var(--card)" strokeWidth={2} isAnimationActive={!calm}>
        {data.map((c, i) => (
          <Cell key={c.key} fill={SLICES[i % SLICES.length]} />
        ))}
      </Pie>
    </PieChart>,
  )
}

/** Money in and out by month, with the running balance drawn over it. */
export function CashFlowChart({ months }: { months: MonthFlow[] }) {
  const calm = useReducedMotion()
  const wide = useMinWidth(640)
  return (
    <figure aria-label="Cash flow by month" className="chart-glow m-0 h-full min-h-[210px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={months} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={4} barCategoryGap="30%">
          {FILLS}
          <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="2 6" strokeOpacity={0.7} />
          <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
          <XAxis dataKey="label" tick={TICK} axisLine={false} tickLine={false} interval="preserveStartEnd" />
          <YAxis tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} width={78} />
          <Tooltip
            cursor={{ fill: 'var(--accent)', fillOpacity: 0.5, radius: 8 }}
            content={({ active, payload }) => {
              const m = payload?.[0]?.payload as MonthFlow | undefined
              if (!m) return null
              return (
                <Tip
                  active={active}
                  title={m.label}
                  rows={[
                    { name: 'Money in', value: m.received, color: RECEIVED },
                    { name: 'Money out', value: m.paid, color: PAID },
                    { name: 'Left over this month', value: m.net, color: m.net < 0 ? LOSS : PROFIT, strong: true },
                    { name: 'Balance', value: m.running, color: BALANCE },
                  ]}
                />
              )
            }}
          />
          <Legend verticalAlign="top" align={wide ? 'right' : 'left'} iconType="circle" iconSize={8} formatter={legend} />
          <Bar name="Money in" dataKey="received" fill={IN_FILL} radius={[8, 8, 2, 2]} maxBarSize={16} isAnimationActive={!calm} />
          <Bar name="Money out" dataKey="paid" fill={OUT_FILL} radius={[8, 8, 2, 2]} maxBarSize={16} isAnimationActive={!calm} />
          <Area name="Balance" type="monotone" dataKey="running" stroke="none" fill={BALANCE} fillOpacity={0.12} legendType="none" isAnimationActive={!calm} />
          <Line name="Balance" type="monotone" dataKey="running" stroke={BALANCE} strokeWidth={2.5} dot={{ r: 3, strokeWidth: 2, fill: 'var(--card)' }} activeDot={{ r: 5 }} isAnimationActive={!calm} />
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  )
}

/** Money to receive and money to pay, by how long it has been pending. */
export function AgeingChart({ receivable, payable }: { receivable: Record<string, number> | undefined; payable: Record<string, number> | undefined }) {
  const calm = useReducedMotion()
  const wide = useMinWidth(640)
  const rows = ageing(receivable, payable)
  return (
    <figure aria-label="Money to receive and money to pay, by age" className="chart-glow m-0 h-full min-h-[210px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 20, right: 8, left: 0, bottom: 0 }} barGap={3}>
          {FILLS}
          <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="2 6" strokeOpacity={0.7} />
          <XAxis dataKey="bucket" tick={TICK} axisLine={false} tickLine={false} />
          <YAxis tickFormatter={compactINR} tick={TICK} axisLine={false} tickLine={false} width={78} />
          <Tooltip
            cursor={{ fill: 'var(--accent)', fillOpacity: 0.5, radius: 8 }}
            content={({ active, payload, label }) => (
              <Tip
                active={active}
                label={String(label)}
                rows={(payload ?? []).map((p) => ({ name: String(p.name), value: Number(p.value), color: p.dataKey === 'payable' ? PAID : RECEIVED }))}
              />
            )}
          />
          <Legend verticalAlign="top" align={wide ? 'right' : 'left'} iconType="circle" iconSize={8} formatter={legend} />
          <Bar name="Money to receive" dataKey="receivable" fill={IN_FILL} radius={[8, 8, 2, 2]} maxBarSize={22} isAnimationActive={!calm}>
            <LabelList dataKey="receivable" position="top" formatter={label} fill="currentColor" fontSize={11} className="text-muted-foreground" />
          </Bar>
          <Bar name="Money to pay" dataKey="payable" fill={OUT_FILL} radius={[8, 8, 2, 2]} maxBarSize={22} isAnimationActive={!calm}>
            <LabelList dataKey="payable" position="top" formatter={label} fill="currentColor" fontSize={11} className="text-muted-foreground" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}
