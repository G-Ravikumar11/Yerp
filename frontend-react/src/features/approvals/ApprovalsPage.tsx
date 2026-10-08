import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowUpRight, CheckCheck, FileText } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, ConfirmDialog, Skeleton, Tabs } from '@/components/ui'
import { approvalKeys, decide, hrefFor, useInbox, type ApprovalItem } from '@/api/approvals'
import { useAction } from '@/lib/mutate'
import { formatDate } from '@/lib/format'
import { formatINR } from '@/lib/utils'

/**
 * Everything waiting on this person to decide - work orders, bills, vendors,
 * variations, leave - in one list, each decided through the same rules as on
 * its own screen. The account holder also sees what waits on others.
 */
export default function ApprovalsPage() {
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

  return (
    <>
      <PageHeader
        eyebrow="Approvals"
        title="Waiting on you"
        description={owner ? 'Everything waiting on anybody, with whose desk it is on. Yours come first.' : 'Everything waiting for your decision. Decide here, or open the document to read it first.'}
      />

      {inbox.isPending ? (
        <div className="space-y-3" role="status" aria-label="Loading">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      ) : (
        <>
          <div className="mb-5 flex flex-wrap items-center gap-3">
            <Tabs
              label="Kind"
              value={kind}
              onChange={setKind}
              items={[{ value: '', label: 'All', count: inbox.data?.items.length }, ...kinds.map(([k, n]) => ({ value: k, label: k, count: n }))]}
            />
            {owner && (
              <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
                <input type="checkbox" checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} className="size-4 accent-[var(--primary)]" />
                Only what is waiting on me
              </label>
            )}
          </div>

          {items.length === 0 ? (
            <Card className="grid place-items-center gap-3 py-20 text-center">
              <span className="grid size-14 place-items-center rounded-2xl bg-success-soft text-success">
                <CheckCheck className="size-6" />
              </span>
              <p className="text-lg font-semibold">Nothing is waiting</p>
              <p className="text-sm text-muted-foreground">Everything that needed a decision has had one.</p>
            </Card>
          ) : (
            <ul className="space-y-3">
              {items.map((i, n) => {
                const firstOthers = !!owner && !i.mine && n === items.findIndex((x) => !x.mine)
                const link = hrefFor(i)
                return (
                  <li key={i.key}>
                    {firstOthers && <h2 className="mb-2 mt-4 text-sm font-semibold">With your team <span className="font-normal text-muted-foreground">- waiting on somebody else; stepping in is your call</span></h2>}
                    <Card className="p-4 sm:p-5">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone="ember">{i.kind_label}</Badge>
                            <span className="font-mono text-[15px] font-semibold">{i.number}</span>
                            {!i.mine && <Badge tone="neutral">With {i.waiting_on}</Badge>}
                            {!i.mine && owner && <span className="text-xs text-muted-foreground">You can decide it yourself if it is stuck</span>}
                          </div>
                          <p className="mt-2 text-[15px]">
                            {i.party}
                            {i.project && <span className="text-muted-foreground"> · {i.project}</span>}
                          </p>
                          {i.what && <p className="mt-1 text-[13.5px] text-muted-foreground">{i.what}</p>}
                          <p className="mt-2 text-xs text-muted-foreground">
                            {i.raised_by && `Raised by ${i.raised_by}`}
                            {i.since && ` · ${formatDate(i.since)}`}
                          </p>
                          {i.warnings.map((w) => (
                            <p key={w} className="mt-2 flex items-start gap-1.5 text-[13px] text-warning">
                              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {w}
                            </p>
                          ))}
                        </div>
                        <div className="flex flex-col items-end gap-3">
                          {i.amount > 0 && <span className="tabular font-display text-xl font-semibold">{formatINR(i.amount)}</span>}
                          <div className="flex flex-wrap justify-end gap-2">
                            {link.external ? (
                              <Button size="sm" variant="ghost" asChild>
                                <a href={link.to}>
                                  Open <ArrowUpRight />
                                </a>
                              </Button>
                            ) : (
                              <Button size="sm" variant="ghost" asChild>
                                <Link to={link.to}>
                                  Open <ArrowUpRight />
                                </Link>
                              </Button>
                            )}
                            {i.pdf && (
                              <Button size="sm" variant="ghost" asChild>
                                <a href={i.pdf} target="_blank" rel="noopener">
                                  <FileText /> PDF
                                </a>
                              </Button>
                            )}
                            {i.scan && (
                              <Button size="sm" variant="ghost" asChild>
                                <a href={i.scan} target="_blank" rel="noopener">
                                  <FileText /> Hard copy
                                </a>
                              </Button>
                            )}
                            {(i.mine || owner) && (
                              <>
                                <Button size="sm" variant="outline" onClick={() => setPending({ item: i, mode: 'reject' })}>
                                  {i.reject_label}
                                </Button>
                                <Button size="sm" onClick={() => setPending({ item: i, mode: 'approve' })}>
                                  {i.approve_label}
                                </Button>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    </Card>
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
            : { label: item?.overrun && override ? 'Why is the allocation being exceeded?' : 'Note (optional)', required: !!item?.overrun && override }
        }
        loading={send.isPending}
        onConfirm={(note) => item && pending && send.mutate({ kind: item.kind, id: item.id, decision: pending.mode, note, override })}
      >
        {pending?.mode === 'approve' && item?.overrun && (
          <label className="flex items-start gap-2.5 rounded-lg bg-warning-soft p-3 text-[13px] text-warning">
            <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} className="mt-0.5 size-4 accent-[var(--warning)]" />
            <span>This overruns the project allocation. Approve it anyway - the reason is kept beside the figures.</span>
          </label>
        )}
      </ConfirmDialog>
    </>
  )
}
