import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, FileSpreadsheet, GitMerge, Search } from 'lucide-react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Badge, Button, Card, Field, Input, Modal, Select, Skeleton } from '@/components/ui'
import { apiUrl, get, post } from '@/lib/api'
import { useAction } from '@/lib/mutate'
import { useSession } from '@/lib/session'

interface DupItem { id: number; item_code: string; item_name: string; kind: string; item_category: string; units_of_measure: string; stock: number; is_active: boolean }
interface DupGroup { type: 'exact' | 'possible'; reason: string; name: string; items: DupItem[] }
interface DupReport { groups: DupGroup[]; total: number; page: number; per_page: number; exact: number; possible: number }
interface MergeCard { id: number; item_code: string; item_name: string; kind: string; units_of_measure: string; item_category: string; specification: string; make: string; hsn_code: string; is_active: boolean; is_primary: boolean; stock: number; linked_total: number; linked: { label: string; count: number }[] }
interface Preview { items: MergeCard[]; problems: string[] }

const KEY = ['item-master', 'duplicates'] as const
const th = 'px-3 py-2 text-left text-xs font-medium text-muted-foreground'

/** Items that may have been entered twice, exact and possible apart, and folding them into one. Nothing here merges by itself. */
export default function DuplicatesPage() {
  const { can } = useSession()
  const [type, setType] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [merging, setMerging] = useState<DupItem[] | null>(null)
  const report = useQuery({ queryKey: [...KEY, type, q, page], queryFn: () => get<DupReport>(`/api/items/duplicates?type=${type}&q=${encodeURIComponent(q)}&page=${page}`) })
  const d = report.data
  const pages = d ? Math.max(1, Math.ceil(d.total / d.per_page)) : 1
  return (
    <>
      <PageHeader eyebrow="Store" title="Duplicate Items" description="Items that may have been entered twice. Exact matches and possible ones are kept apart, and nothing is merged until someone says so."
        actions={<><Button variant="outline" asChild><Link to="/store/items"><ArrowLeft /> Item Master</Link></Button><Button variant="outline" asChild><a href={apiUrl(`/api/items/duplicates.xlsx?type=${type}&q=${encodeURIComponent(q)}`)}><FileSpreadsheet /> Download</a></Button></>} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="w-44"><Select aria-label="Match" value={type} placeholder="Every match" onChange={(e) => { setType(e.target.value); setPage(1) }} options={[{ value: 'exact', label: 'Exact' }, { value: 'possible', label: 'Possible' }]} /></div>
        <div className="w-full sm:w-72"><Input aria-label="Search duplicates" placeholder="Search by name or code" leading={<Search />} value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></div>
        {d && <span className="text-[13px] text-muted-foreground">{d.exact} exact, {d.possible} possible</span>}
      </div>
      {report.isPending ? <Skeleton className="h-40 w-full" /> : report.isError ? <p role="alert" className="text-sm text-danger">{report.error.message}</p> : !d?.groups.length ? <Card className="p-6 text-center text-sm text-muted-foreground">No duplicate items found.</Card> : (
        <div className="grid gap-3">
          {d.groups.map((g) => (
            <Card key={`${g.type}-${g.items[0].id}`} className="overflow-hidden">
              <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
                <Badge tone={g.type === 'exact' ? 'danger' : 'warning'} dot>{g.type === 'exact' ? 'Exact' : 'Possible'}</Badge>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{g.name}</span>
                <span className="text-xs text-muted-foreground">{g.reason}</span>
                {can('items.manage') && <Button size="sm" variant="outline" onClick={() => setMerging(g.items)}><GitMerge /> Merge</Button>}
              </div>
              <div className="overflow-x-auto">
                <table aria-label={`Duplicates of ${g.name}`} className="w-full min-w-[34rem] text-[13px]">
                  <thead className="bg-surface"><tr><th className={th}>Code</th><th className={th}>Name</th><th className={th}>Category</th><th className={th}>Unit</th><th className={`${th} text-right`}>Stock</th><th className={th}>Status</th></tr></thead>
                  <tbody>{g.items.map((i) => (
                    <tr key={i.id} className="border-t border-border">
                      <td className="px-3 py-2 font-mono">{i.item_code}</td><td className="px-3 py-2">{i.item_name}</td><td className="px-3 py-2">{i.item_category || '-'}</td>
                      <td className="px-3 py-2">{i.units_of_measure}</td><td className="px-3 py-2 text-right tabular">{i.stock}</td><td className="px-3 py-2">{i.is_active ? 'Active' : 'Inactive'}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </Card>
          ))}
          {pages > 1 && <nav aria-label="Pages" className="flex items-center justify-end gap-2 text-xs text-muted-foreground"><Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>Page {page} of {pages}<Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button></nav>}
        </div>
      )}
      {merging && <MergeModal items={merging} onClose={() => setMerging(null)} />}
    </>
  )
}

function MergeModal({ items, onClose }: { items: DupItem[]; onClose: () => void }) {
  const [primary, setPrimary] = useState(items[0].id)
  const [picked, setPicked] = useState<number[]>(items.map((i) => i.id))
  const [sure, setSure] = useState(false)
  const [reason, setReason] = useState('')
  const others = picked.filter((i) => i !== primary)
  const preview = useQuery({ queryKey: [...KEY, 'preview', primary, picked], enabled: others.length > 0, staleTime: 0, queryFn: () => post<Preview>('/api/items/merge/preview', { primary_id: primary, item_ids: others }) })
  const run = useAction(() => post<{ message: string }>('/api/items/merge', { primary_id: primary, item_ids: others, reason }), { invalidate: [KEY, ['item-master']], success: (r) => r.message, onSuccess: onClose })
  const p = preview.data
  const blocked = !p || p.problems.length > 0 || others.length === 0
  const keep = p?.items.find((i) => i.id === primary)
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="xl" title="Merge items" description="Choose the item to keep. Everything linked to the others moves onto it. The others are switched off and kept, never deleted."
      footer={sure
        ? <><Button variant="ghost" onClick={() => setSure(false)}>Back</Button><Button loading={run.isPending} disabled={run.isPending} onClick={() => run.mutate()}><GitMerge /> Yes, merge {others.length} into {keep?.item_code}</Button></>
        : <><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={blocked} onClick={() => setSure(true)}>Continue</Button></>}>
      <div className="mb-3 flex flex-wrap gap-3">
        {items.map((i) => <label key={i.id} className="flex items-center gap-1.5 text-[13px]"><input type="checkbox" disabled={i.id === primary} checked={picked.includes(i.id)} onChange={(e) => setPicked((x) => (e.target.checked ? [...x, i.id] : x.filter((v) => v !== i.id)))} /> {i.item_code}</label>)}
      </div>
      {preview.isPending && others.length > 0 ? <Skeleton className="h-32 w-full" /> : preview.isError ? <p role="alert" className="text-sm text-danger">{preview.error.message}</p> : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {p?.items.map((c) => (
            <section key={c.id} aria-label={c.item_code} className={`rounded-lg border p-3 text-[13px] ${c.id === primary ? 'border-primary' : 'border-border'}`}>
              <label className="mb-2 flex items-center gap-2 font-medium"><input type="radio" name="merge-primary" checked={c.id === primary} onChange={() => setPrimary(c.id)} /> {c.id === primary ? 'Keep this one' : 'Keep this instead'}</label>
              <p className="font-mono font-semibold">{c.item_code}</p>
              <p>{c.item_name}</p>
              <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-0.5 text-xs">
                <dt className="text-muted-foreground">Unit</dt><dd>{c.units_of_measure || '-'}</dd>
                <dt className="text-muted-foreground">Category</dt><dd>{c.item_category || '-'}</dd>
                <dt className="text-muted-foreground">Stock</dt><dd>{c.stock}</dd>
                <dt className="text-muted-foreground">Linked records</dt><dd>{c.linked_total}</dd>
              </dl>
              {c.linked.length > 0 && <ul className="mt-2 text-xs text-muted-foreground">{c.linked.map((l) => <li key={l.label}>{l.count} {l.label}</li>)}</ul>}
            </section>
          ))}
        </div>
      )}
      {(p?.problems.length ?? 0) > 0 && <ul role="alert" className="mt-3 list-disc rounded-lg border border-danger/40 p-3 pl-6 text-[13px] text-danger">{p?.problems.map((x) => <li key={x}>{x}</li>)}</ul>}
      {sure && (
        <div className="mt-4 rounded-lg border border-warning/40 p-3">
          <p className="mb-2 text-[13px] font-medium">This cannot be undone. {others.length} item{others.length === 1 ? '' : 's'} will be merged into {keep?.item_code} {keep?.item_name}.</p>
          <Field label="Reason (kept on the record)" htmlFor="mg-why"><Input id="mg-why" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></Field>
        </div>
      )}
    </Modal>
  )
}
