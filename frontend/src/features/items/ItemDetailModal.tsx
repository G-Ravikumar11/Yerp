import { Link } from 'react-router-dom'
import { Copy, ExternalLink, Pencil, Power } from 'lucide-react'
import { Badge, Button, Modal, Skeleton } from '@/components/ui'
import { useItemSites, useWhereUsed, type MasterItem, type UsageGroup } from '@/api/itemMaster'
import { formatINR } from '@/lib/utils'
import { purchaseRateOf, stockLabel } from './itemLogic'

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
    <dt className="w-44 shrink-0 text-xs text-muted-foreground sm:pt-0.5">{label}</dt>
    <dd className="min-w-0 text-sm">{children || <span className="text-muted-foreground">-</span>}</dd>
  </div>
)

/** The places an item is used, kept short: how many of each, and the first few to click through to. */
export function UsageList({ groups }: { groups: UsageGroup[] }) {
  return (
    <ul className="grid gap-3">
      {groups.map((g) => (
        <li key={g.key}>
          <p className="text-sm font-medium">{g.label} <span className="text-muted-foreground">({g.count})</span></p>
          {g.rows.length > 0 && (
            <ul className="mt-1 divide-y rounded-md border text-sm">
              {g.rows.map((r, i) => (
                <li key={i} className="flex flex-wrap items-center justify-between gap-2 px-3 py-1.5">
                  <Link className="text-primary hover:underline" to={r.path}>{r.label}</Link>
                  <span className="text-xs text-muted-foreground">{r.detail}</span>
                </li>
              ))}
              {g.more > 0 && <li className="px-3 py-1.5 text-xs text-muted-foreground">and {g.more} more</li>}
            </ul>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Everything about one item in one place: its details, stock, what each site pays, where it is used, and who last changed it. */
export function ItemDetailModal({ item, manage, onClose, onEdit, onCopy, onToggle }: {
  item: MasterItem | null
  manage: boolean
  onClose: () => void
  onEdit: (i: MasterItem) => void
  onCopy: (i: MasterItem) => void
  onToggle: (i: MasterItem) => void
}) {
  const id = item?.id ?? null
  const usage = useWhereUsed(id)
  const sites = useItemSites(id)
  const i = usage.data?.item ?? item
  return (
    <Modal open={!!item} onOpenChange={(o) => !o && onClose()} title={item?.item_name ?? 'Item'} description={item ? `Code ${item.item_code}` : undefined} size="lg"
      footer={
        <>
          {item && manage && (
            <div className="mr-auto flex gap-2">
              <Button variant="outline" size="sm" onClick={() => onEdit(item)}><Pencil /> Edit</Button>
              <Button variant="outline" size="sm" onClick={() => onCopy(item)}><Copy /> Copy as new item</Button>
              <Button variant="outline" size="sm" onClick={() => onToggle(item)}><Power /> {item.is_active ? 'Deactivate' : 'Activate'}</Button>
            </div>
          )}
          <Button variant="ghost" onClick={onClose}>Close</Button>
        </>
      }
    >
      {i && (
        <div className="grid gap-6">
          <section aria-labelledby="d-details">
            <h3 id="d-details" className="mb-2 flex items-center gap-2 border-b pb-1 text-sm font-semibold">
              Details <Badge tone={i.is_active ? 'success' : 'neutral'}>{i.is_active ? 'Active' : 'Inactive'}</Badge>
            </h3>
            <dl className="grid gap-2">
              <Row label="What it is">{i.kind === 'RM' ? 'Material (kept in stock)' : 'Work item (used in BOQs)'}</Row>
              <Row label="Category">{[i.item_category, i.item_subcategory].filter(Boolean).join(' › ') || 'Not set yet. Edit the item to file it.'}</Row>
              <Row label="Unit">{i.units_of_measure}</Row>
              <Row label="Grade or specification">{i.specification}</Row>
              <Row label="Description">{i.description !== i.item_name ? i.description : ''}</Row>
              <Row label="Usual purchase rate">{(() => { const r = purchaseRateOf(i); return r ? `${formatINR(r.value)}${r.lastUsed ? ' (the last rate it was bought or sold at)' : ''}` : '' })()}</Row>
              <Row label="Usual selling rate">{i.selling_rate ? formatINR(i.selling_rate) : ''}</Row>
              <Row label="GST (tax) rate">{i.item_tax_type}</Row>
              <Row label="HSN / SAC code">{i.hsn_code}</Row>
              <Row label="Usual supplier">{i.preferred_supplier}</Row>
              <Row label="Remarks">{i.remarks}</Row>
            </dl>
          </section>

          <section aria-labelledby="d-stock">
            <h3 id="d-stock" className="mb-2 border-b pb-1 text-sm font-semibold">In stock</h3>
            {i.kind === 'RM' || i.stock !== null ? (
              <p className="text-sm"><strong>{stockLabel(i.kind, i.stock, i.units_of_measure)}</strong> <span className="text-muted-foreground">in the store in total{i.reorder_level ? ` · warn below ${i.reorder_level} ${i.units_of_measure}` : ''}</span></p>
            ) : (
              <p className="text-sm text-muted-foreground">A work item is not kept in stock.</p>
            )}
          </section>

          <section aria-labelledby="d-sites">
            <h3 id="d-sites" className="mb-2 flex items-center justify-between border-b pb-1 text-sm font-semibold">
              <span>Rates by site</span>
              <Link className="inline-flex items-center gap-1 text-xs font-normal text-primary hover:underline" to="/projects/boq/rates">Site Item Pricing <ExternalLink className="size-3" /></Link>
            </h3>
            {sites.isPending ? <Skeleton className="h-10 w-full" /> : sites.data?.sites.length ? (
              <ul className="divide-y rounded-md border text-sm">
                {sites.data.sites.map((s) => (
                  <li key={s.site_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                    <Link className="text-primary hover:underline" to={`/projects/boq/rates?site=${s.site_id}`}>{s.site_code} {s.site_name}</Link>
                    <span className="text-muted-foreground">quantity {s.quantity} · {s.site_rate === null ? 'rate not set yet' : `${formatINR(s.site_rate)} (${s.status})`}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-muted-foreground">No site's BOQ uses this item yet.</p>}
          </section>

          <section aria-labelledby="d-used">
            <h3 id="d-used" className="mb-2 border-b pb-1 text-sm font-semibold">Where it is used</h3>
            {usage.isPending ? <Skeleton className="h-16 w-full" /> : usage.data && usage.data.groups.length ? <UsageList groups={usage.data.groups} /> : <p className="text-sm text-muted-foreground">Not used on any BOQ, order or store record yet.</p>}
          </section>

          <p className="text-xs text-muted-foreground">Added by {i.created_by || '-'} on {i.created_at || '-'} · last changed by {i.updated_by || '-'} on {i.updated_at || '-'}</p>
        </div>
      )}
    </Modal>
  )
}
