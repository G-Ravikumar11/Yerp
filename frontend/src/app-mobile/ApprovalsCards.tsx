import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowUpRight, CheckCheck, FileText } from 'lucide-react'
import { approvalKeys, decide, hrefFor, useInbox, type ApprovalItem } from '@/api/approvals'
import { ConfirmDialog, Skeleton } from '@/components/ui'
import { formatDate } from '@/lib/format'
import { useAction } from '@/lib/mutate'
import { cn, formatINR } from '@/lib/utils'
import { LargeTitle, Pill, Sheet } from './ui'

/**
 * Everything waiting on this person, as cards you can decide from. The same list, the same rules and the same
 * confirmation as the website's Approvals screen (features/approvals): only the way it is laid out is the phone's.
 */
export default function ApprovalsCards() {
  const inbox = useInbox()
  const [kind, setKind] = useState('')
  const [mineOnly, setMineOnly] = useState(false)
  const [pending, setPending] = useState<{ item: ApprovalItem; mode: 'approve' | 'reject' } | null>(null)
  const [override, setOverride] = useState(false)

  // Yours first; what waits on somebody else follows, apart.
  const items = useMemo(() => (inbox.data?.items ?? []).filter((i) => (!mineOnly || i.mine) && (!kind || i.kind_label === kind)).sort((a, b) => Number(b.mine) - Number(a.mine)), [inbox.data, kind, mineOnly])
  const kinds = useMemo(() => {
    const counts = new Map<string, number>()
    for (const i of inbox.data?.items ?? []) counts.set(i.kind_label, (counts.get(i.kind_label) ?? 0) + 1)
    return [...counts.entries()].sort()
  }, [inbox.data])

  const send = useAction((d: Parameters<typeof decide>[0]) => decide(d), {
    invalidate: [approvalKeys.inbox, ['orders'], ['subbills'], ['vendors']],
    onSuccess: () => {
      setPending(null)
      setOverride(false)
    },
  })

  const owner = inbox.data?.owner
  const item = pending?.item
  const total = inbox.data?.items.length ?? 0
  const chip = (on: boolean) => cn('h-9 shrink-0 rounded-full border px-4 text-sm font-semibold', on ? 'border-transparent bg-primary text-primary-foreground' : 'border-border bg-card')

  return (
    <div className="pb-4">
      <LargeTitle title="Approvals" sub={inbox.data ? (inbox.data.mine ? `${inbox.data.mine} waiting on you` : 'Nothing waiting on you') : undefined} />

      {inbox.isPending ? (
        <div className="space-y-3" role="status" aria-label="Loading">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 w-full rounded-2xl" />)}
        </div>
      ) : inbox.isError ? (
        <Sheet><p className="py-2 text-center text-sm text-muted-foreground">Could not load the approvals. Check the connection and try again.</p></Sheet>
      ) : (
        <>
          <div role="tablist" aria-label="Kind" className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <button role="tab" aria-selected={kind === ''} type="button" onClick={() => setKind('')} className={chip(kind === '')}>All <span className="opacity-70">{total}</span></button>
            {kinds.map(([k, n]) => <button key={k} role="tab" aria-selected={kind === k} type="button" onClick={() => setKind(k)} className={chip(kind === k)}>{k} <span className="opacity-70">{n}</span></button>)}
          </div>
          {owner && (
            <label className="mt-3 flex items-center gap-2.5 px-1 text-[13px] text-muted-foreground">
              <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} className="size-4 accent-[var(--primary)]" />
              Only what is waiting on me
            </label>
          )}

          {items.length === 0 ? (
            <Sheet className="mt-4 grid place-items-center gap-2 py-14 text-center">
              <span className="grid size-14 place-items-center rounded-full bg-success/15 text-success"><CheckCheck className="size-6" /></span>
              <p className="text-lg font-bold tracking-tight">Nothing is waiting</p>
              <p className="text-sm text-muted-foreground">Everything that needed a decision has had one.</p>
            </Sheet>
          ) : (
            <ul className="mt-4 space-y-3">
              {items.map((i, n) => {
                const firstOthers = !!owner && !i.mine && n === items.findIndex((x) => !x.mine)
                const link = hrefFor(i)
                return (
                  <li key={i.key}>
                    {firstOthers && <h2 className="mb-2 mt-5 px-1 text-[15px] font-bold tracking-tight">With your team <span className="font-normal text-muted-foreground">- waiting on somebody else</span></h2>}
                    <Sheet>
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Pill tone="info">{i.kind_label}</Pill>
                            {!i.mine && <Pill>With {i.waiting_on}</Pill>}
                          </div>
                          <div className="mt-2 break-all font-mono text-[13px] font-semibold text-muted-foreground">{i.number}</div>
                        </div>
                        {i.amount > 0 && <span className="shrink-0 text-xl font-extrabold tracking-tight">{formatINR(i.amount)}</span>}
                      </div>
                      <p className="mt-1.5 text-[15px] font-semibold leading-snug">{i.party}{i.project && <span className="font-normal text-muted-foreground"> · {i.project}</span>}</p>
                      {i.what && <p className="mt-1 text-[13.5px] leading-snug text-muted-foreground">{i.what}</p>}
                      <p className="mt-2 text-xs text-muted-foreground">{i.raised_by && `Raised by ${i.raised_by}`}{i.since && ` · ${formatDate(i.since)}`}</p>
                      {!i.mine && owner && <p className="mt-1 text-xs text-muted-foreground">You can decide it yourself if it is stuck.</p>}
                      {i.warnings.map((w) => <p key={w} className="mt-2 flex items-start gap-1.5 rounded-xl bg-warning/10 p-2.5 text-[13px] text-warning"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {w}</p>)}

                      <div className="mt-3.5 flex flex-wrap items-center gap-2">
                        <Link to={link.to} className="inline-flex h-10 items-center gap-1 rounded-full px-3 text-sm font-semibold text-primary active:opacity-70">Open <ArrowUpRight className="size-4" /></Link>
                        {i.pdf && <a href={i.pdf} target="_blank" rel="noopener" className="inline-flex h-10 items-center gap-1 rounded-full px-3 text-sm font-semibold text-primary active:opacity-70"><FileText className="size-4" /> PDF</a>}
                        {i.scan && <a href={i.scan} target="_blank" rel="noopener" className="inline-flex h-10 items-center gap-1 rounded-full px-3 text-sm font-semibold text-primary active:opacity-70"><FileText className="size-4" /> Hard copy</a>}
                        {(i.mine || owner) && (
                          <div className="ml-auto flex gap-2">
                            <button type="button" onClick={() => setPending({ item: i, mode: 'reject' })} className="h-10 rounded-full border border-border px-4 text-sm font-semibold active:opacity-70">{i.reject_label}</button>
                            <button type="button" onClick={() => setPending({ item: i, mode: 'approve' })} className="h-10 rounded-full bg-[image:var(--app-grad)] px-5 text-sm font-semibold text-white active:opacity-90">{i.approve_label}</button>
                          </div>
                        )}
                      </div>
                    </Sheet>
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}

      <ConfirmDialog
        open={!!pending}
        onOpenChange={(o) => {
          if (!o) {
            setPending(null)
            setOverride(false)
          }
        }}
        title={pending?.mode === 'reject' ? `${item?.reject_label}: ${item?.number}` : `${item?.approve_label}: ${item?.number}`}
        description={item ? `${item.kind_label}${item.party ? ` - ${item.party}` : ''}${item.amount ? ` - ${formatINR(item.amount)}` : ''}` : undefined}
        confirmLabel={pending?.mode === 'reject' ? (item?.reject_label ?? 'Send back') : (item?.approve_label ?? 'Approve')}
        reason={
          pending?.mode === 'reject'
            ? { label: 'What needs putting right?', required: true }
            : { label: item?.overrun && override ? 'Why is it being approved past the budget or the BOQ?' : 'Note (optional)', required: !!item?.overrun && override }
        }
        loading={send.isPending}
        onConfirm={(note) => item && pending && send.mutate({ kind: item.kind, id: item.id, decision: pending.mode, note, override })}
      >
        {pending?.mode === 'approve' && item?.overrun && (
          <label className="flex items-start gap-2.5 rounded-lg bg-warning-soft p-3 text-[13px] text-warning">
            <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="mt-0.5 size-4 accent-[var(--warning)]" />
            <span>This goes past the project allocation or the client&apos;s BOQ (see the notes above). Approve it anyway - the reason is kept beside the figures.</span>
          </label>
        )}
      </ConfirmDialog>
    </div>
  )
}
