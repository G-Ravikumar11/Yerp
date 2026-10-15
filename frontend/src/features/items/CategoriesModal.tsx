import { useState } from 'react'
import { Button, Input, Modal } from '@/components/ui'
import { addCategory, masterKeys, patchCategory, useCategories } from '@/api/itemMaster'
import { useAction } from '@/lib/mutate'

/** The categories and subcategories items are filed under. The business keeps this list; nothing is fixed in code. */
export function CategoriesModal({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const cats = useCategories()
  const [name, setName] = useState('')
  const [sub, setSub] = useState<Record<number, string>>({})
  const add = useAction((v: { name: string; parent?: number }) => addCategory(v.name, v.parent), { invalidate: [masterKeys.categories] })
  const toggle = useAction((v: { id: number; on: boolean }) => patchCategory(v.id, { is_active: v.on }), { invalidate: [masterKeys.categories], success: false })

  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Item categories" description="Add the categories and subcategories your BOQ items are filed under." size="lg"
      footer={<Button variant="ghost" onClick={() => onOpenChange(false)}>Close</Button>}>
      <form className="mb-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) add.mutate({ name }, { onSuccess: () => setName('') }) }}>
        <Input aria-label="New category" placeholder="New category" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit" loading={add.isPending} disabled={!name.trim()}>Add</Button>
      </form>
      <ul className="max-h-[50vh] divide-y overflow-y-auto rounded-md border">
        {(cats.data ?? []).map((c) => (
          <li key={c.id} className="grid gap-2 px-3 py-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className={c.is_active ? 'font-medium' : 'font-medium text-muted-foreground line-through'}>{c.name}</span>
              <Button size="sm" variant="ghost" disabled={toggle.isPending} onClick={() => toggle.mutate({ id: c.id, on: !c.is_active })}>
                {c.is_active ? 'Switch off' : 'Switch on'}
              </Button>
            </div>
            {c.subcategories.length > 0 && <p className="text-xs text-muted-foreground">{c.subcategories.map((s) => s.name).join(' · ')}</p>}
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const v = (sub[c.id] ?? '').trim(); if (v) add.mutate({ name: v, parent: c.id }, { onSuccess: () => setSub((s) => ({ ...s, [c.id]: '' })) }) }}>
              <Input aria-label={`New subcategory of ${c.name}`} className="h-8" placeholder="Add a subcategory" value={sub[c.id] ?? ''} onChange={(e) => setSub((s) => ({ ...s, [c.id]: e.target.value }))} />
              <Button size="sm" variant="outline" type="submit" disabled={!(sub[c.id] ?? '').trim() || add.isPending}>Add</Button>
            </form>
          </li>
        ))}
      </ul>
    </Modal>
  )
}
