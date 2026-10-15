import { useState } from 'react'
import { GitMerge, Pencil, Trash2 } from 'lucide-react'
import { Button, ConfirmDialog, Field, Input, Modal, Select } from '@/components/ui'
import { addCategory, deleteCategory, masterKeys, mergeCategory, patchCategory, useCategories } from '@/api/itemMaster'
import { itemKeys } from '@/api/items'
import { useAction } from '@/lib/mutate'

interface Node {
  id: number
  name: string
  items: number
  parentId: number | null
  siblings: { id: number; name: string }[]
}

/** The categories and subcategories items are filed under, with how many items each holds. The business keeps this list. */
export function CategoriesModal({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const cats = useCategories()
  const [name, setName] = useState('')
  const [sub, setSub] = useState<Record<number, string>>({})
  const [renaming, setRenaming] = useState<{ node: Node; to: string } | null>(null)
  const [merging, setMerging] = useState<{ node: Node; into: string } | null>(null)
  const [removing, setRemoving] = useState<Node | null>(null)
  const refresh = [masterKeys.all, itemKeys.all]

  const add = useAction((v: { name: string; parent?: number }) => addCategory(v.name, v.parent), { invalidate: [masterKeys.categories] })
  const rename = useAction((v: { id: number; to: string }) => patchCategory(v.id, { name: v.to }), { invalidate: refresh, onSuccess: () => setRenaming(null) })
  const merge = useAction((v: { id: number; into: number }) => mergeCategory(v.id, v.into), { invalidate: refresh, onSuccess: () => setMerging(null) })
  const remove = useAction((id: number) => deleteCategory(id), { invalidate: refresh, onSuccess: () => setRemoving(null), onError: () => setRemoving(null) })
  const toggle = useAction((v: { id: number; on: boolean }) => patchCategory(v.id, { is_active: v.on }), { invalidate: [masterKeys.categories], success: false })

  const all = cats.data ?? []
  const nodeOf = (id: number, name: string, items: number, parent: number | null): Node => ({
    id, name, items, parentId: parent,
    siblings: (parent === null ? all.map((c) => ({ id: c.id, name: c.name })) : (all.find((c) => c.id === parent)?.subcategories ?? []).map((s) => ({ id: s.id, name: s.name }))).filter((s) => s.id !== id),
  })

  const actions = (n: Node) => (
    <div className="flex shrink-0 gap-1">
      <Button size="icon-sm" variant="ghost" aria-label={`Rename ${n.name}`} onClick={() => setRenaming({ node: n, to: n.name })}><Pencil /></Button>
      <Button size="icon-sm" variant="ghost" aria-label={`Merge ${n.name} into another`} disabled={!n.siblings.length} onClick={() => setMerging({ node: n, into: '' })}><GitMerge /></Button>
      <Button size="icon-sm" variant="ghost" aria-label={`Delete ${n.name}`} onClick={() => setRemoving(n)}><Trash2 /></Button>
    </div>
  )

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Item categories" description="The groups your items are filed under. Rename one and its items follow; merge two to tidy up; delete only when nothing is filed under it." size="lg"
      footer={<Button variant="ghost" onClick={() => onOpenChange(false)}>Close</Button>}>
      <form className="mb-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate({ name }, { onSuccess: () => setName('') }) }}>
        <Input aria-label="New category" placeholder="New category, e.g. Glazing" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" loading={add.isPending} disabled={!name.trim()}>Add</Button>
      </form>
      <ul className="max-h-[50vh] divide-y overflow-y-auto rounded-md border" aria-label="Categories">
        {all.map((c) => (
          <li key={c.id} className="grid gap-2 px-3 py-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className={c.is_active ? 'font-medium' : 'font-medium text-muted-foreground line-through'}>
                {c.name} <span className="font-normal text-muted-foreground">({c.items} item{c.items === 1 ? '' : 's'})</span>
              </span>
              <div className="flex items-center gap-1">
                <Button size="sm" variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate({ id: c.id, on: !c.is_active })}>{c.is_active ? 'Hide' : 'Show'}</Button>
                {actions(nodeOf(c.id, c.name, c.items, null))}
              </div>
            </div>
            {c.subcategories.length > 0 && (
              <ul className="ml-4 grid gap-1 border-l pl-3">
                {c.subcategories.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-2">
                    <span>{s.name} <span className="text-muted-foreground">({s.items})</span></span>
                    {actions(nodeOf(s.id, s.name, s.items, c.id))}
                  </li>
                ))}
              </ul>
            )}
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const v = (sub[c.id] ?? '').trim(); if (v) add.mutate({ name: v, parent: c.id }, { onSuccess: () => setSub((s) => ({ ...s, [c.id]: '' })) }) }}>
              <Input aria-label={`New subcategory of ${c.name}`} className="h-8" placeholder="Add a subcategory" value={sub[c.id] ?? ''} onChange={(e) => setSub((s) => ({ ...s, [c.id]: e.target.value }))} />
              <Button size="sm" variant="outline" type="submit" disabled={!(sub[c.id] ?? '').trim() || add.isPending}>Add</Button>
            </form>
          </li>
        ))}
      </ul>

      <Modal open={!!renaming} onOpenChange={(o) => !o && setRenaming(null)} title={`Rename ${renaming?.node.name ?? ''}`} size="sm"
        footer={<><Button variant="ghost" onClick={() => setRenaming(null)}>Cancel</Button><Button loading={rename.isPending} disabled={!renaming?.to.trim()} onClick={() => renaming && rename.mutate({ id: renaming.node.id, to: renaming.to })}>Rename</Button></>}>
        <Field label="New name" htmlFor="cat-rename" hint="The items filed under it keep following it.">
          <Input id="cat-rename" value={renaming?.to ?? ''} onChange={(e) => setRenaming((r) => r && { ...r, to: e.target.value })} autoFocus />
        </Field>
      </Modal>

      <Modal open={!!merging} onOpenChange={(o) => !o && setMerging(null)} title={`Merge ${merging?.node.name ?? ''} into another`} size="sm"
        description={merging ? `Its ${merging.node.items} item${merging.node.items === 1 ? '' : 's'} move across, then ${merging.node.name} is removed.` : undefined}
        footer={<><Button variant="ghost" onClick={() => setMerging(null)}>Cancel</Button><Button variant="danger" loading={merge.isPending} disabled={!merging?.into} onClick={() => merging && merge.mutate({ id: merging.node.id, into: Number(merging.into) })}>Merge</Button></>}>
        <Field label="Merge into" htmlFor="cat-merge">
          <Select id="cat-merge" value={merging?.into ?? ''} placeholder="Choose where the items go" onChange={(e) => setMerging((m) => m && { ...m, into: e.target.value })}
            options={(merging?.node.siblings ?? []).map((s) => ({ value: s.id, label: s.name }))} />
        </Field>
      </Modal>

      <ConfirmDialog open={!!removing} onOpenChange={(o) => !o && setRemoving(null)} title={`Delete ${removing?.name ?? ''}?`}
        description={removing && removing.items > 0 ? `${removing.items} item${removing.items === 1 ? ' is' : 's are'} filed under it, so it cannot be deleted. Merge it into another first.` : 'Nothing is filed under it, so it can be removed.'}
        confirmLabel={removing && removing.items > 0 ? 'Try anyway' : 'Delete'} tone="danger" loading={remove.isPending}
        onConfirm={() => { if (removing) remove.mutate(removing.id) }} />
    </Modal>
  )
}
