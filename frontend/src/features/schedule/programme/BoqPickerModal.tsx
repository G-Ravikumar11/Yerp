import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Plus, Scissors, Search, X } from 'lucide-react'
import { Button, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import { drawProgrammeFromBoq, programmeKeys, useProgramme, useProgrammeBoq, type BoqNode, type BoqPick } from '@/api/programme'
import { ApiError } from '@/lib/api'
import { formatINR } from '@/lib/utils'
import { toast } from '@/stores/toast'

interface Split { label: string; quantity: string }
const num = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(3).replace(/\.?0+$/, ''))
const LIMIT = 400

/**
 * Draw from BOQ: the client's sheet as a tree with boxes to tick. A line with no quantity is a heading and comes
 * along with the lines ticked under it; each line comes with its unit, quantity, rate and amount and its BOQ Ref.
 * The names are made short and can be changed here; the full description stays on the row. A line can be split
 * across units (slab concrete for A-16 and A-18), each with its share of the quantity.
 */
export function BoqPickerModal({ job, onClose, anchor = null, onDone }: { job: number; onClose: () => void; anchor?: number | null; onDone?: () => void }) {
  const qc = useQueryClient()
  const q = useProgrammeBoq(job, true)
  const prog = useProgramme(job)
  const nodes = useMemo(() => q.data?.items ?? [], [q.data])
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [names, setNames] = useState<Record<string, string>>({})
  const [splits, setSplits] = useState<Record<string, Split[]>>({})
  const [opened, setOpened] = useState<Set<string> | null>(null)
  const [find, setFind] = useState('')
  const [where, setWhere] = useState(anchor ? `after:${anchor}` : 'end')
  const [start, setStart] = useState('')
  const [busy, setBusy] = useState(false)

  const { kids, leaves, byId } = useMemo(() => {
    const kids = new Map<string | null, BoqNode[]>()
    const byId = new Map(nodes.map((n) => [n.id, n]))
    for (const n of nodes) kids.set(n.parent, [...(kids.get(n.parent) ?? []), n])
    const leaves = new Map<string, string[]>()
    const walk = (n: BoqNode): string[] => {
      const got = n.heading ? (kids.get(n.id) ?? []).flatMap(walk) : [n.id]
      leaves.set(n.id, got)
      return got
    }
    ;(kids.get(null) ?? []).forEach(walk)
    return { kids, leaves, byId }
  }, [nodes])
  // the parts and the first level are open to begin with
  const open = useMemo(() => opened ?? new Set(nodes.filter((n) => n.level === 0).map((n) => n.id)), [opened, nodes])

  const rows = useMemo(() => {
    const term = find.trim().toLowerCase()
    if (term) {
      const keep = new Set<string>()
      for (const n of nodes) {
        if (keep.size > LIMIT * 3) break
        if (`${n.ref} ${n.name} ${n.description}`.toLowerCase().includes(term)) {
          for (let x: BoqNode | undefined = n; x && !keep.has(x.id); x = x.parent ? byId.get(x.parent) : undefined) keep.add(x.id)
        }
      }
      return nodes.filter((n) => keep.has(n.id)).slice(0, LIMIT)
    }
    const out: BoqNode[] = []
    const walk = (parent: string | null) => {
      for (const n of kids.get(parent) ?? []) {
        out.push(n)
        if (n.heading && open.has(n.id)) walk(n.id)
      }
    }
    walk(null)
    return out
  }, [find, nodes, kids, open, byId])

  const toggle = (n: BoqNode) => setPicked((p) => {
    const next = new Set(p)
    const ids = leaves.get(n.id) ?? []
    const all = ids.every((id) => next.has(id))
    ids.forEach((id) => (all ? next.delete(id) : next.add(id)))
    return next
  })
  const expand = (id: string) => setOpened((o) => { const n = new Set(o ?? open); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const chosen = nodes.filter((n) => !n.heading && picked.has(n.id))
  const amount = chosen.reduce((s, n) => s + (n.amount || n.quantity * n.rate), 0)
  const splitTotal = (id: string) => (splits[id] ?? []).reduce((s, x) => s + (Number(x.quantity) || 0), 0)

  const places = useMemo(() => {
    const out = [{ value: 'end', label: 'At the end of the programme' }]
    for (const r of prog.data?.rows ?? []) {
      out.push({ value: `child:${r.id}`, label: `Under ${r.wbs} ${r.name}` })
      if (r.id === anchor) out.push({ value: `after:${r.id}`, label: `After ${r.wbs} ${r.name}` })
    }
    return out
  }, [prog.data, anchor])

  const draw = async () => {
    const picks: BoqPick[] = [
      ...chosen.map((n) => ({
        id: n.id,
        name: names[n.id]?.trim() || undefined,
        splits: (splits[n.id] ?? []).filter((s) => s.label.trim()).map((s) => ({ label: s.label.trim(), quantity: Number(s.quantity) || 0 })),
      })),
      ...nodes.filter((n) => n.heading && names[n.id]?.trim()).map((n) => ({ id: n.id, name: names[n.id].trim() })),
    ]
    const [kind, id] = where.split(':')
    setBusy(true)
    try {
      const view = await drawProgrammeFromBoq(job, { picks, anchor_id: id ? Number(id) : null, position: (kind === 'end' ? 'end' : kind) as 'after' | 'child' | 'end', start })
      qc.setQueryData(programmeKeys.one(job), view)
      void qc.invalidateQueries({ queryKey: ['schedule'], predicate: (x) => x.queryKey[1] !== 'programme' })
      if (view.warnings?.length) toast.info(view.message || 'Drawn from the BOQ')
      else toast.success(view.message || 'Drawn from the BOQ')
      onDone?.()
      onClose()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'Could not draw from the BOQ. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const head = q.data?.boq
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title="Draw from the BOQ"
      description={head ? `${head.number}${head.revision ? ` · ${head.revision}` : ''}. Tick the lines to put on the programme; the headings above them come too. Lines already on it are marked.` : 'The project’s BOQ, as a tree to pick from.'}
      footer={
        <div className="flex w-full flex-wrap items-end gap-3">
          <Field label="Put them" htmlFor="bp-where" className="min-w-64 flex-1"><Select id="bp-where" value={where} onChange={(e) => setWhere(e.target.value)} options={places} /></Field>
          <Field label="Start them on (optional)" htmlFor="bp-start"><Input id="bp-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="w-40" /></Field>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button loading={busy} disabled={!chosen.length} onClick={draw}>Put {chosen.length || ''} on the programme</Button>
          </div>
        </div>
      }>
      {q.isPending ? <Skeleton className="h-80 w-full" /> : !head ? (
        <p className="rounded-lg border border-border bg-muted/40 p-4 text-sm">This project has no BOQ yet. Make one under Projects, BOQ, then draw the programme from it. Rows not in the BOQ can be added on the programme with + Row.</p>
      ) : (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-60 flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input aria-label="Find in the BOQ" placeholder="Find: 2.1.1, excavation, M40 ..." value={find} onChange={(e) => setFind(e.target.value)} className="pl-8" />
            </div>
            <Button size="sm" variant="ghost" onClick={() => setOpened(new Set(nodes.filter((n) => n.heading).map((n) => n.id)))}>Open all</Button>
            <Button size="sm" variant="ghost" onClick={() => setOpened(new Set())}>Close all</Button>
            <span className="text-sm text-muted-foreground">{chosen.length} ticked · {formatINR(amount)}</span>
          </div>
          {!q.data?.numbered && <p className="text-xs text-muted-foreground">This BOQ was saved without its item numbers, so it is shown by section. Import the client&apos;s sheet again on the BOQ page to keep its numbering (2, 2.1, 2.1.1).</p>}
          <div role="tree" aria-label="BOQ" className="max-h-[52vh] overflow-auto rounded-lg border border-border">
            {rows.map((n) => {
              const ids = leaves.get(n.id) ?? []
              const on = ids.length > 0 && ids.every((id) => picked.has(id))
              const some = !on && ids.some((id) => picked.has(id))
              const sp = splits[n.id]
              const total = splitTotal(n.id)
              return (
                <div key={n.id} role="treeitem" aria-level={n.level + 1} aria-selected={on} aria-expanded={n.heading ? open.has(n.id) || !!find.trim() : undefined}
                  className={`border-b border-border/60 last:border-b-0 ${on ? 'bg-primary-soft/60' : ''}`}>
                  <div className="flex min-h-9 items-center gap-2 px-2 py-1 text-[13px]" style={{ paddingLeft: 8 + n.level * 18 }}>
                    {n.heading ? (
                      <button type="button" aria-label={open.has(n.id) ? `Close ${n.name}` : `Open ${n.name}`} onClick={() => expand(n.id)} className="grid size-5 place-items-center rounded-md text-muted-foreground hover:bg-accent">
                        {open.has(n.id) || find.trim() ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                      </button>
                    ) : <span className="w-5" />}
                    <input type="checkbox" aria-label={`Put ${n.ref} ${n.name} on the programme`} className="size-4 accent-primary" checked={on}
                      ref={(el) => { if (el) el.indeterminate = some }} onChange={() => toggle(n)} />
                    <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground">{n.ref}</span>
                    {on || (n.heading && some) ? (
                      <Input aria-label={`Name for ${n.ref}`} value={names[n.id] ?? n.name} onChange={(e) => setNames((x) => ({ ...x, [n.id]: e.target.value }))} title={n.description}
                        className={`h-7 min-w-0 flex-1 text-[13px] ${n.heading ? 'font-semibold' : ''}`} />
                    ) : (
                      <span className={`min-w-0 flex-1 truncate ${n.heading ? 'font-semibold' : ''}`} title={n.description}>{n.name}</span>
                    )}
                    {!n.heading && <>
                      <span className="w-28 shrink-0 text-right tabular-nums">{n.rate_only ? 'R/o' : `${num(n.quantity)} ${n.uom}`}</span>
                      <span className="w-28 shrink-0 text-right tabular-nums text-muted-foreground">{formatINR(n.amount || n.quantity * n.rate)}</span>
                      {n.drawn_rows > 0 ? (
                        <span className="w-28 shrink-0 text-right text-xs text-warning" title="Already on the programme">on it{n.drawn_rows > 1 ? ` ×${n.drawn_rows}` : ''}{n.quantity ? `: ${num(n.drawn_quantity)}` : ''}</span>
                      ) : <span className="w-28 shrink-0" />}
                      <Button size="icon-sm" variant="ghost" aria-label={`Split ${n.ref} across units`} title="Split across units"
                        onClick={() => { setPicked((p) => new Set(p).add(n.id)); setSplits((x) => ({ ...x, [n.id]: x[n.id] ?? [{ label: '', quantity: '' }, { label: '', quantity: '' }] })) }}>
                        <Scissors />
                      </Button>
                    </>}
                  </div>
                  {sp && on && (
                    <div className="grid gap-1.5 px-2 pb-2" style={{ paddingLeft: 8 + n.level * 18 + 56 }}>
                      {sp.map((s, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <Input aria-label="Unit or location" placeholder="Unit: A-16" value={s.label} className="h-7 w-40 text-[13px]"
                            onChange={(e) => setSplits((x) => ({ ...x, [n.id]: x[n.id].map((y, j) => (j === i ? { ...y, label: e.target.value } : y)) }))} />
                          <Input aria-label="Its quantity" inputMode="decimal" placeholder={n.uom || 'Qty'} value={s.quantity} className="h-7 w-28 text-right text-[13px]"
                            onChange={(e) => setSplits((x) => ({ ...x, [n.id]: x[n.id].map((y, j) => (j === i ? { ...y, quantity: e.target.value } : y)) }))} />
                          <Button size="icon-sm" variant="ghost" aria-label="Remove this unit" onClick={() => setSplits((x) => {
                            const left = x[n.id].filter((_, j) => j !== i)
                            const next = { ...x }
                            if (left.length) next[n.id] = left
                            else delete next[n.id]
                            return next
                          })}><X /></Button>
                        </div>
                      ))}
                      <div className="flex items-center gap-3 text-xs">
                        <Button size="sm" variant="ghost" onClick={() => setSplits((x) => ({ ...x, [n.id]: [...x[n.id], { label: '', quantity: '' }] }))}><Plus /> Unit</Button>
                        {n.quantity > 0 && (
                          Math.abs(total - n.quantity) < 1e-6
                            ? <span className="text-success">Adds up to the BOQ&apos;s {num(n.quantity)} {n.uom}.</span>
                            : <span role="status" className="text-warning">The units come to {num(total)} {n.uom}; the BOQ has {num(n.quantity)} ({total < n.quantity ? `${num(n.quantity - total)} left` : `${num(total - n.quantity)} over`}).</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
            {!rows.length && <p className="p-4 text-sm text-muted-foreground">{find.trim() ? 'Nothing in the BOQ matches that.' : 'The BOQ has no lines with a quantity yet.'}</p>}
            {find.trim() && rows.length >= LIMIT && <p className="p-3 text-xs text-muted-foreground">The first {LIMIT} matches are shown. Type more to narrow it.</p>}
          </div>
        </div>
      )}
    </Modal>
  )
}
