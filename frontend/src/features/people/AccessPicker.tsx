import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Button, Field, Select } from '@/components/ui'
import type { HrCatalogue } from '@/api/people'

/**
 * What somebody can do in the portal: a role to start from, with every right it carries ticked.
 * Changing the role starts again from that role's rights; anything ticked or unticked after is theirs alone.
 * The rights themselves stay folded away until they are asked for: the access level is usually all that is chosen.
 */
export function AccessPicker({ catalogue, role, granted, onRole, onGranted }: { catalogue: HrCatalogue; role: string; granted: string[]; onRole: (code: string, rights: string[]) => void; onGranted: (rights: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const current = catalogue.permission_roles.find((r) => r.code === role)
  const groups = new Map<string, HrCatalogue['permissions']>()
  for (const p of catalogue.permissions) groups.set(p.group || 'Other', [...(groups.get(p.group || 'Other') ?? []), p])
  const fromRole = new Set(current?.permissions ?? [])
  return (
    <div>
      <Field label="Access level" htmlFor="ac-role" hint={current?.description}>
        <Select id="ac-role" value={role} onChange={(e) => onRole(e.target.value, catalogue.permission_roles.find((r) => r.code === e.target.value)?.permissions ?? [])} options={catalogue.permission_roles.filter((r) => !r.retired || r.code === role).map((r) => ({ value: r.code, label: r.label + (r.retired ? ' (older access level)' : '') }))} />
      </Field>
      <div className="mt-3 flex items-center gap-3">
        <Button type="button" size="sm" variant="outline" aria-expanded={open} aria-controls="ac-permissions" onClick={() => setOpen((o) => !o)}>
          {open ? <ChevronUp /> : <ChevronDown />} {open ? 'Hide permissions' : 'Show permissions'}
        </Button>
        <span className="text-xs text-muted-foreground">{catalogue.permissions.filter((p) => granted.includes(p.key)).length} ticked</span>
      </div>
      {open && <fieldset id="ac-permissions" className="mt-3 rounded-lg border border-border p-3">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">What they can do</legend>
        <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {[...groups.entries()].map(([group, items]) => (
            <div key={group}>
              <p className="mb-1 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{group}</p>
              {items.map((p) => {
                // Opening vendor codes, work orders and BOQs goes with being HO QS (or Master) - it is not ticked on for anybody else.
                const reserved = !!p.only_role && p.only_role !== role && role !== 'owner'
                const holder = catalogue.permission_roles.find((r) => r.code === p.only_role)?.label ?? p.only_role
                return (
                  <label key={p.key} className={'flex items-start gap-2 py-0.5 text-[13px]' + (reserved ? ' opacity-60' : '')}>
                    <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" disabled={reserved} checked={!reserved && granted.includes(p.key)} onChange={(e) => onGranted(e.target.checked ? [...granted, p.key] : granted.filter((k) => k !== p.key))} />
                    <span>{p.label}{reserved ? <span className="text-muted-foreground"> · {holder} only</span> : !fromRole.has(p.key) && <span className="text-muted-foreground"> · not in this level</span>}</span>
                  </label>
                )
              })}
            </div>
          ))}
        </div>
      </fieldset>}
    </div>
  )
}
