import { useState } from 'react'
import { ChevronDown, ChevronRight, Copy } from 'lucide-react'
import { DataTable, type TableColumn } from '@/components/data/DataTable'
import { Badge, Input, Select, Stat, StatGrid } from '@/components/ui'
import { useErrorLog, type LoggedError } from '@/api/errorLog'
import { ERROR_CODES } from '@/lib/errorCodes'
import { toast } from '@/stores/toast'

const tone = (code: string) =>
  code.startsWith('YE-SRV') || code === 'YE-APP' ? 'danger' : code.startsWith('YE-BUSY') || code === 'YE-NET' ? 'warning' : code.startsWith('YE-AUTH') || code.startsWith('YE-ACCESS') ? 'info' : 'neutral'

/** Every error the app answered with in this company: who met it, where, and the ref that finds it in the server log. */
export default function ErrorLogTab() {
  const [area, setArea] = useState('')
  const [q, setQ] = useState('')
  const [days, setDays] = useState(30)
  const [open, setOpen] = useState<number | null>(null)
  const log = useErrorLog(area, q.trim(), days)
  const d = log.data
  const by = d?.summary.by_area ?? {}
  const copy = (e: LoggedError) => {
    void navigator.clipboard?.writeText(`${e.code} ref ${e.ref} - ${e.at} - ${e.method} ${e.path} - ${e.detail}`)
    toast.success(`Copied ${e.ref}`)
  }

  const columns: TableColumn<LoggedError>[] = [
    {
      id: 'more',
      header: '',
      width: '2.5rem',
      cell: (e) =>
        e.trace ? (
          <button type="button" aria-label={open === e.id ? 'Hide the details' : 'Show the details'} className="text-muted-foreground hover:text-foreground" onClick={() => setOpen(open === e.id ? null : e.id)}>
            {open === e.id ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        ) : null,
    },
    { id: 'at', header: 'When', sort: (e) => e.at, cell: (e) => <span className="tabular whitespace-nowrap text-[13px]">{e.at}</span> },
    {
      id: 'code',
      header: 'Code',
      cell: (e) => (
        <div>
          <Badge tone={tone(e.code)}>{e.code}</Badge>
          <div className="mt-0.5 text-xs text-muted-foreground">{e.title || ERROR_CODES[e.code]?.title}</div>
        </div>
      ),
    },
    {
      id: 'ref',
      header: 'Ref',
      cell: (e) => (
        <button type="button" title="Copy" onClick={() => copy(e)} className="inline-flex items-center gap-1 font-mono text-[13px] hover:text-primary">
          {e.ref} <Copy className="size-3" />
        </button>
      ),
    },
    {
      id: 'what',
      header: 'What happened',
      cell: (e) => (
        <div className="max-w-md">
          <div className="line-clamp-2 text-[13px]">{e.detail || '-'}</div>
          <div className="truncate font-mono text-[11px] text-muted-foreground">{e.method} {e.path}</div>
          {open === e.id && e.trace && <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-muted p-3 text-[11px] leading-snug">{e.trace}</pre>}
          {e.has_trace && !e.trace && <div className="mt-0.5 text-[11px] text-muted-foreground">Technical details are kept with the platform team: quote ref {e.ref}.</div>}
        </div>
      ),
    },
    { id: 'who', header: 'Who', hideBelow: 'md', cell: (e) => <span className="text-[13px]">{e.who}</span> },
  ]

  const areas = Object.entries(d?.areas ?? {})
  const faults = (by.SRV ?? 0) + (by.APP ?? 0)
  return (
    <div>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
        Every error the app answered with in your company, newest first. Each has a code, for the kind of problem, and a ref. Ask anyone who reports a problem
        for the ref, and search for it here. Everyday answers like a page not found or a signed-out session are left out.
      </p>
      <StatGrid className="lg:grid-cols-4 xl:grid-cols-4">
        <Stat label={`Errors in ${days} days`} value={d?.summary.total ?? 0} loading={log.isPending} />
        <Stat label="Server and screen faults" value={faults} tone={faults ? 'danger' : undefined} loading={log.isPending} />
        <Stat label="Sign-in problems" value={by.AUTH ?? 0} loading={log.isPending} />
        <Stat label="Server busy" value={by.BUSY ?? 0} tone={by.BUSY ? 'warning' : undefined} loading={log.isPending} />
      </StatGrid>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="w-52">
          <Select aria-label="Area" value={area} onChange={(e) => setArea(e.target.value)} options={[{ value: '', label: 'Every area' }, ...areas.map(([k, v]) => ({ value: k, label: `${v} (${by[k] ?? 0})` }))]} />
        </div>
        <div className="w-40">
          <Select aria-label="Period" value={String(days)} onChange={(e) => setDays(Number(e.target.value))} options={[{ value: '1', label: 'Today' }, { value: '7', label: 'Last 7 days' }, { value: '30', label: 'Last 30 days' }, { value: '90', label: 'Last 90 days' }]} />
        </div>
        <div className="min-w-56 flex-1">
          <Input aria-label="Search" placeholder="Search a ref, code, page or person" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <DataTable label="Error log" rows={d?.errors ?? []} columns={columns} rowKey={(e) => e.id} loading={log.isPending} empty={q || area ? 'No error matches.' : 'No errors in this period.'} />
    </div>
  )
}
