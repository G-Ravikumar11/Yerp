import { Field, Select } from '@/components/ui'
import type { HrCatalogue } from '@/api/people'

/**
 * What somebody can do in the portal: a role to start from, with every right it carries ticked.
 * Changing the role starts again from that role's rights; anything ticked or unticked after is theirs alone.
 */
export function AccessPicker({ catalogue, role, granted, onRole, onGranted }: { catalogue: HrCatalogue; role: string; granted: string[]; onRole: (code: string, rights: string[]) => void; onGranted: (rights: string[]) => void }) {
  const current = catalogue.permission_roles.find((r) => r.code === role)
  const groups = new Map<string, HrCatalogue['permissions']>()
  for (const p of catalogue.permissions) groups.set(p.group || 'Other', [...(groups.get(p.group || 'Other') ?? []), p])
  const fromRole = new Set(current?.permissions ?? [])
  return (
    <div>
      <Field label="Access level" htmlFor="ac-role" hint={current?.description}>
        <Select id="ac-role" value={role} onChange={(e) => onRole(e.target.value, catalogue.permission_roles.find((r) => r.code === e.target.value)?.permissions ?? [])} options={catalogue.permission_roles.filter((r) => !r.retired || r.code === role).map((r) => ({ value: r.code, label: r.label + (r.retired ? ' (older access level)' : '') }))} />
      </Field>
      <fieldset className="mt-4 rounded-lg border border-border p-3">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">What they can do</legend>
        <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
          {[...groups.entries()].map(([group, items]) => (
            <div key={group}>
              <p className="mb-1 text-[11px] font-bold uppercase tracking-wide text-muted-foreground">{group}</p>
              {items.map((p) => (
                <label key={p.key} className="flex items-start gap-2 py-0.5 text-[13px]">
                  <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={granted.includes(p.key)} onChange={(e) => onGranted(e.target.checked ? [...granted, p.key] : granted.filter((k) => k !== p.key))} />
                  <span>{p.label}{!fromRole.has(p.key) && <span className="text-muted-foreground"> · not in this level</span>}</span>
                </label>
              ))}
            </div>
          ))}
        </div>
      </fieldset>
    </div>
  )
}
