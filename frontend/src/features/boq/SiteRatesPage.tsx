import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, History, Link2, Lock, LockOpen, Save, Search, Wand2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, ConfirmDialog, Field, Input, Modal, NumField, Select, Skeleton, Stat } from '@/components/ui'
import { get } from '@/lib/api'
import {
  applyToBoq,
  bulkSave,
  createItemFromLine,
  finalizeRate,
  mapItem,
  priceKeys,
  reopenRate,
  usePriceAudit,
  useSitePrices,
  useSites,
  type PriceRow,
  type PriceStatus,
} from '@/api/siteRates'
import { masterKeys, useCategories, type MasterItem } from '@/api/itemMaster'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'
import { formatINR } from '@/lib/utils'

const TONE: Record<PriceStatus, 'neutral' | 'warning' | 'success' | 'info'> = { Pending: 'neutral', Draft: 'warning', Finalized: 'success', Changed: 'info' }
const LABEL: Record<PriceStatus, string> = { Pending: 'Pending', Draft: 'Draft', Finalized: 'Finalised', Changed: 'Changed' }

/** Pick a client, then a site: everything below is that site's alone and is rebuilt (`key`) when the site changes. */
export default function SiteRatesPage() {
  const sites = useSites()
  const [client, setClient] = useState('')
  const [siteId, setSiteId] = useState<number | null>(null)
  const all = sites.data ?? []
  const clients = [...new Set(all.map((s) => s.customer).filter(Boolean))].sort()
  const shown = all.filter((s) => !client || s.customer === client)

  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="Site item pricing"
        description="Choose a client and site to see its BOQ items matched to the item master, and finalise the rate for each at that site. The item is shared between sites; the rate is this site's alone."
      />
      <div className="mb-6 grid max-w-3xl gap-3 sm:grid-cols-2">
        <Select aria-label="Client" value={client} placeholder="All clients" options={clients.map((c) => ({ value: c, label: c }))}
          onChange={(e) => { setClient(e.target.value); setSiteId(null) }} />
        <Select aria-label="Project / site" value={siteId ?? ''} placeholder={sites.isPending ? 'Loading sites…' : 'Choose a project / site'}
          options={shown.map((s) => ({ value: s.id, label: `${s.site_code} ${s.site_name}`.trim() }))}
          onChange={(e) => setSiteId(e.target.value ? Number(e.target.value) : null)} />
      </div>
      {sites.isError && <p className="text-sm text-danger">The sites could not be loaded. You may not have access to site prices.</p>}
      {siteId === null ? (
        !sites.isPending && !sites.isError && <p className="text-sm text-muted-foreground">Choose a site to load its BOQ items and rates.</p>
      ) : (
        <SitePricing key={siteId} siteId={siteId} />
      )}
    </>
  )
}

function SitePricing({ siteId }: { siteId: number }) {
  const { can } = useSession()
  const canEdit = can('siteprices.edit')
  const canFinalize = can('siteprices.finalize')
  const canMap = can('items.manage|workorders.manage')
  const q = useSitePrices(siteId)
  const [drafts, setDrafts] = useState<Record<number, number | null>>({})
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<PriceStatus | 'Unmapped' | ''>('')
  const [finalizing, setFinalizing] = useState<PriceRow | null>(null)
  const [reopening, setReopening] = useState<PriceRow | null>(null)
  const [mapping, setMapping] = useState<PriceRow | null>(null)
  const [reasoning, setReasoning] = useState(false)
  const [applying, setApplying] = useState(false)
  const [history, setHistory] = useState(false)
  const invalidate = [priceKeys.rows(siteId), priceKeys.audit(siteId), masterKeys.all]

  const data = q.data
  const rows = useMemo(() => data?.rows ?? [], [data])
  const view = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return rows.filter((r) => {
      if (status === 'Unmapped' ? r.mapped : status && (!r.mapped || r.status !== status)) return false
      return !needle || `${r.item_code} ${r.item_name} ${r.description} ${r.section} ${r.specification}`.toLowerCase().includes(needle)
    })
  }, [rows, search, status])

  const draftOf = (r: PriceRow) => (r.item_id !== null && r.item_id in drafts ? drafts[r.item_id] : r.site_rate)
  const changed = rows.filter((r) => r.item_id !== null && r.status !== 'Finalized' && r.item_id in drafts && drafts[r.item_id] !== r.site_rate)
  const needsReason = changed.some((r) => r.site_rate !== null)
  const drop = (ids: number[]) => setDrafts((d) => Object.fromEntries(Object.entries(d).filter(([k]) => !ids.includes(Number(k)))))

  const saveAll = useAction(
    (reason: string) => bulkSave(siteId, changed.map((r) => ({ item_id: r.item_id!, rate: draftOf(r) ?? null, version: r.version })), reason),
    { invalidate, onSuccess: () => { drop(changed.map((r) => r.item_id!)); setReasoning(false) } },
  )
  const finalize = useAction((r: PriceRow) => finalizeRate(siteId, r.item_id!, r.version), { invalidate, onSuccess: () => setFinalizing(null) })
  const reopen = useAction((v: { r: PriceRow; why: string }) => reopenRate(siteId, v.r.item_id!, v.why), { invalidate, onSuccess: () => setReopening(null) })
  const apply = useAction(() => applyToBoq(siteId), { invalidate: [...invalidate, ['boq']], onSuccess: () => setApplying(false) })
  const busy = saveAll.isPending || finalize.isPending || reopen.isPending || apply.isPending

  if (q.isPending) return <Skeleton className="h-64 w-full" />
  if (q.isError || !data) return <p className="text-sm text-danger">This site's BOQ items could not be loaded. Check your connection or your access, then try again.</p>
  const s = data.summary
  const finalisedToApply = rows.some((r) => r.status === 'Finalized' || r.status === 'Changed')

  return (
    <div className="grid gap-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Priced BOQ lines" value={s.lines} sub={data.boq ? `${data.boq.number} · ${data.boq.revision}` : undefined} />
        <Stat label="Unmapped" value={s.unmapped} tone={s.unmapped ? 'danger' : undefined} onClick={() => setStatus(status === 'Unmapped' ? '' : 'Unmapped')} active={status === 'Unmapped'} />
        <Stat label="Pending" value={s.pending} tone={s.pending ? 'warning' : undefined} onClick={() => setStatus(status === 'Pending' ? '' : 'Pending')} active={status === 'Pending'} />
        <Stat label="Draft" value={s.draft} onClick={() => setStatus(status === 'Draft' ? '' : 'Draft')} active={status === 'Draft'} />
        <Stat label="Finalised" value={s.finalized + s.changed} tone="success" sub={s.changed ? `${s.changed} master default changed` : undefined} onClick={() => setStatus(status === 'Finalized' ? '' : 'Finalized')} active={status === 'Finalized'} />
        <Stat label="Amount at site rates" value={formatINR(s.amount)} sub={s.rate_only ? `${s.rate_only} rate-only, not counted` : undefined} />
      </div>

      {!data.boq ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">This site has no BOQ yet.</p>
          <p className="mt-1 text-sm text-muted-foreground">Open its BOQ and import the client's sheet; its items will appear here to be priced.</p>
          <Button className="mt-4" asChild><Link to="/projects/boq">Create or import the BOQ</Link></Button>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-52 flex-1 sm:max-w-sm">
              <Input aria-label="Search BOQ items" placeholder="Search code, item, description, section" value={search} onChange={(e) => setSearch(e.target.value)} leading={<Search />} />
            </div>
            <div className="ml-auto flex flex-wrap gap-2">
              {canEdit && (
                <Button variant="outline" disabled={!changed.length || busy} loading={saveAll.isPending}
                  onClick={() => (needsReason ? setReasoning(true) : saveAll.mutate(''))}>
                  <Save /> Save {changed.length || ''} change{changed.length === 1 ? '' : 's'}
                </Button>
              )}
              {canFinalize && data.boq.editable && (
                <Button variant="outline" disabled={!finalisedToApply || busy} onClick={() => setApplying(true)}>
                  <Wand2 /> Apply finalised rates to BOQ
                </Button>
              )}
              <Button variant="ghost" onClick={() => setHistory(true)}><History /> History</Button>
            </div>
          </div>

          {view.length === 0 ? (
            <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              {rows.length === 0 ? 'This BOQ has no priced items yet.' : 'Nothing matches that search.'}
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full min-w-[78rem] text-sm">
                <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2">BOQ section</th>
                    <th className="px-3 py-2">BOQ line</th>
                    <th className="px-3 py-2">Item code</th>
                    <th className="px-3 py-2">Master item</th>
                    <th className="px-3 py-2">Specification</th>
                    <th className="px-3 py-2">UOM</th>
                    <th className="px-3 py-2 text-right">BOQ qty</th>
                    <th className="px-3 py-2 text-right">Default rate</th>
                    <th className="px-3 py-2">Site rate</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {view.map((r) => {
                    const locked = r.status === 'Finalized' || r.status === 'Changed'
                    const dirty = r.item_id !== null && r.item_id in drafts && drafts[r.item_id] !== r.site_rate
                    return (
                      <tr key={r.line_key} className="align-top">
                        <td className="max-w-40 px-3 py-2 text-muted-foreground"><div className="truncate">{r.section || '-'}</div></td>
                        <td className="max-w-xs px-3 py-2"><div className="line-clamp-2">{r.description}</div>{r.rate_only && <Badge tone="info" className="mt-1">Rate only</Badge>}</td>
                        <td className="px-3 py-2 font-mono text-[13px]">{r.item_code || <span className="inline-flex items-center gap-1 text-danger"><AlertTriangle className="size-3.5" /> Unmapped</span>}</td>
                        <td className="max-w-48 px-3 py-2"><div className="truncate">{r.item_name || '-'}</div>{r.mapped && !r.item_active && <span className="text-xs text-warning">Deactivated</span>}</td>
                        <td className="px-3 py-2">{r.specification || '-'}</td>
                        <td className="px-3 py-2">{r.uom}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{r.quantity}</td>
                        <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">{r.default_rate ? formatINR(r.default_rate) : '-'}</td>
                        <td className="w-40 px-3 py-2">
                          {r.mapped ? (
                            <NumField aria-label={`Site rate for ${r.item_code}`} value={draftOf(r)} placeholder="Pending"
                              disabled={!canEdit || locked || busy}
                              onValue={(n) => setDrafts((d) => ({ ...d, [r.item_id!]: n }))} />
                          ) : <span className="text-xs text-muted-foreground">Map the item first</span>}
                        </td>
                        <td className="px-3 py-2 text-right font-medium tabular-nums">{r.rate_only || r.site_rate === null ? '-' : formatINR(r.amount)}</td>
                        <td className="px-3 py-2">
                          {r.mapped && <Badge tone={TONE[r.status]}>{LABEL[r.status]}</Badge>}
                          {r.status === 'Changed' && <div className="mt-1 text-xs text-muted-foreground">Default is now {r.default_rate ? formatINR(r.default_rate) : 'blank'}</div>}
                          {locked && r.finalized_by && <div className="mt-1 text-xs text-muted-foreground">{r.finalized_by}</div>}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex justify-end gap-1.5">
                            {!r.mapped && canMap && data.boq?.editable && <Button size="sm" variant="outline" disabled={busy} onClick={() => setMapping(r)}><Link2 /> Map</Button>}
                            {r.mapped && canFinalize && !locked && r.site_rate !== null && !dirty && <Button size="sm" disabled={busy} onClick={() => setFinalizing(r)}><Lock /> Finalise</Button>}
                            {r.mapped && canFinalize && locked && <Button size="sm" variant="outline" disabled={busy} onClick={() => setReopening(r)}><LockOpen /> Reopen</Button>}
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      <ConfirmDialog open={reasoning} onOpenChange={setReasoning} title="Why are these rates changing?" description="Some rows already had a rate. The reason is kept with each change."
        confirmLabel="Save changes" reason={{ label: 'Reason', placeholder: 'e.g. Supplier revised quote', required: true }} loading={saveAll.isPending}
        onConfirm={(why) => { saveAll.mutate(why) }} />
      <ConfirmDialog open={!!finalizing} onOpenChange={(o) => !o && setFinalizing(null)} title={`Finalise ${finalizing?.item_code ?? ''}?`}
        description={finalizing ? `${formatINR(finalizing.site_rate)} per ${finalizing.uom} becomes this site's agreed rate. It cannot be changed afterwards unless it is reopened with a reason.` : ''}
        confirmLabel="Finalise rate" loading={finalize.isPending}
        onConfirm={() => { if (finalizing) finalize.mutate(finalizing) }} />
      <ConfirmDialog open={!!reopening} onOpenChange={(o) => !o && setReopening(null)} title={`Reopen ${reopening?.item_code ?? ''}?`}
        description="The rate goes back to draft so it can be changed. Who reopened it, and why, is kept." confirmLabel="Reopen rate" tone="danger"
        reason={{ label: 'Reason', placeholder: 'Why is this rate being reopened?', required: true }} loading={reopen.isPending}
        onConfirm={(why) => { if (reopening) reopen.mutate({ r: reopening, why }) }} />
      <ConfirmDialog open={applying} onOpenChange={setApplying} title="Apply finalised rates to the BOQ?"
        description="The open BOQ revision's line rates and amounts are set to this site's finalised rates and its totals recalculated. Issued revisions and work orders already drawn are not changed."
        confirmLabel="Apply to BOQ" loading={apply.isPending} onConfirm={() => apply.mutate()} />
      {mapping && <MapDialog siteId={siteId} row={mapping} onClose={() => setMapping(null)} invalidate={invalidate} />}
      {history && <HistoryDialog siteId={siteId} onClose={() => setHistory(false)} />}
    </div>
  )
}

/** Tie an unmapped BOQ line to an item already in the master, or make a new item from the line. */
function MapDialog({ siteId, row, onClose, invalidate }: { siteId: number; row: PriceRow; onClose: () => void; invalidate: readonly (readonly unknown[])[] }) {
  const [text, setText] = useState('')
  const [mode, setMode] = useState<'pick' | 'new'>('pick')
  const [code, setCode] = useState('')
  const [category, setCategory] = useState('')
  const cats = useCategories()
  const found = useQuery({ queryKey: ['item-master', 'pick', text], enabled: text.trim().length > 1, queryFn: async () => (await get<{ items: MasterItem[] }>(`/api/items?kind=FG&status=active&page_size=20&q=${encodeURIComponent(text)}`)).items })
  const done = { invalidate: invalidate as never, onSuccess: onClose }
  const map = useAction((id: number) => mapItem(siteId, row.line_key, id), done)
  const create = useAction(() => createItemFromLine(siteId, row.line_key, { item_code: code, item_category: category }), done)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Map BOQ line to an item" description={row.description.slice(0, 160)} size="lg"
      footer={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      <div className="mb-4 flex gap-2">
        <Button size="sm" variant={mode === 'pick' ? 'primary' : 'outline'} onClick={() => setMode('pick')}>Use an existing item</Button>
        <Button size="sm" variant={mode === 'new' ? 'primary' : 'outline'} onClick={() => setMode('new')}>Create a new item</Button>
      </div>
      {mode === 'pick' ? (
        <div className="grid gap-3">
          <Input aria-label="Search the item master" placeholder="Item code or name" value={text} onChange={(e) => setText(e.target.value)} autoFocus leading={<Search />} />
          <ul className="max-h-60 divide-y overflow-y-auto rounded-md border">
            {(found.data ?? []).map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                <span className="min-w-0"><span className="font-mono font-semibold">{i.item_code}</span> <span className="truncate">{i.item_name}</span> <span className="text-muted-foreground">{i.units_of_measure}</span></span>
                <Button size="sm" disabled={map.isPending} onClick={() => map.mutate(i.id)}>Use</Button>
              </li>
            ))}
            {text.trim().length > 1 && found.data?.length === 0 && <li className="px-3 py-3 text-sm text-muted-foreground">No active finished-goods item matches.</li>}
          </ul>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <p className="text-sm text-muted-foreground sm:col-span-2">The item takes this line's description and unit. Leave the code blank to be issued one.</p>
          <Field label="Item code" htmlFor="mp-code"><Input id="mp-code" className="font-mono uppercase" value={code} onChange={(e) => setCode(e.target.value)} maxLength={30} placeholder="Automatic" /></Field>
          <Field label="Category" htmlFor="mp-cat"><Select id="mp-cat" value={category} placeholder="No category" onChange={(e) => setCategory(e.target.value)} options={(cats.data ?? []).map((c) => ({ value: c.name, label: c.name }))} /></Field>
          <div className="sm:col-span-2"><Button loading={create.isPending} onClick={() => create.mutate()}>Create and map</Button></div>
        </div>
      )}
    </Modal>
  )
}

function HistoryDialog({ siteId, onClose }: { siteId: number; onClose: () => void }) {
  const audit = usePriceAudit(siteId, true)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title="Rate history" description="Every change to this site's rates, newest first." footer={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      {audit.isPending ? <Skeleton className="h-32 w-full" /> : (audit.data ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">No rate has been saved at this site yet.</p>
      ) : (
        <ul className="max-h-96 divide-y overflow-y-auto text-sm">
          {audit.data!.map((a) => (
            <li key={a.id} className="py-2">
              <div><span className="font-mono font-semibold">{a.item_code}</span> {a.action}: {a.previous_rate === null ? '-' : formatINR(a.previous_rate)} → {a.new_rate === null ? '-' : formatINR(a.new_rate)} ({a.new_status})</div>
              <div className="text-xs text-muted-foreground">{a.changed_by} · {a.changed_at}{a.reason ? ` · ${a.reason}` : ''}</div>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}
