import { useEffect, useState } from 'react'
import { Check, ChevronDown, FolderOpen, HardHat, UserRound, Users, Wallet, Warehouse, type LucideIcon } from 'lucide-react'
import { Button, Field, Select, Skeleton } from '@/components/ui'
import { peopleKeys, setAccess, useHrCatalogue, type EmployeeDetail, type Portal } from '@/api/people'
import { useJobOptions } from '@/api/clientOrders'
import { useAction } from '@/lib/mutate'

const card = 'rounded-lg border border-border bg-card p-4'

function Toggle({ on, disabled, label, onChange }: { on: boolean; disabled?: boolean; label: string; onChange: (v: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} disabled={disabled} onClick={() => onChange(!on)}
      className={'relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40 ' + (on ? 'bg-[var(--primary)]' : 'bg-muted-foreground/30')}>
      <span className={'absolute top-0.5 size-4 rounded-full bg-white transition-all ' + (on ? 'left-[18px]' : 'left-0.5')} />
    </button>
  )
}

import { levelOf, withLevel, type Level } from './portals'

const LEVELS: { code: Level; label: string }[] = [{ code: 'none', label: 'No Access' }, { code: 'read', label: 'Read Only' }, { code: 'write', label: 'Read & Write' }]
const LEVEL_LABEL = Object.fromEntries(LEVELS.map((l) => [l.code, l.label])) as Record<Level, string>
const PORTAL_ICONS: Record<string, LucideIcon> = { projects: FolderOpen, clients: UserRound, subcontractors: HardHat, store: Warehouse, money: Wallet, people: Users }

/** A portal and the three settings it can have. Setting it sets only its own rights, so no other card moves. */
function PortalCard({ pt, level, roleLevel, readOnly, onChange }: { pt: Portal; level: Level; roleLevel: Level; readOnly: boolean; onChange: (l: Level) => void }) {
  const Icon = PORTAL_ICONS[pt.code] ?? FolderOpen
  const fixed = readOnly || !!pt.locked
  return (
    <div className="rounded-xl border border-border bg-card p-5 shadow-card">
      <div className="flex items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-foreground"><Icon className="size-5" /></span>
        <h4 className="text-lg font-semibold leading-tight">{pt.label}</h4>
      </div>
      <p className="mt-3 min-h-10 text-sm text-muted-foreground">{pt.blurb}</p>
      <div role="radiogroup" aria-label={`${pt.label} access`} className="mt-4 grid grid-cols-3 gap-1 rounded-full border border-border bg-card p-1 text-[13px]">
        {LEVELS.map((l) => (
          <button key={l.code} type="button" role="radio" aria-checked={level === l.code} disabled={fixed} onClick={() => onChange(l.code)}
            className={'rounded-md px-2 py-2 font-medium transition-colors disabled:cursor-default ' + (level === l.code ? 'bg-[var(--primary)] text-white shadow-sm' : 'text-foreground hover:bg-muted disabled:hover:bg-transparent') + (fixed && level !== l.code ? ' text-muted-foreground' : '')}>
            {l.label}
          </button>
        ))}
      </div>
      {pt.locked ? <p className="mt-2 text-[12px] text-muted-foreground">{pt.locked}: its screens open only for the Master's own login.</p>
        : !readOnly && level !== roleLevel ? <p className="mt-2 text-[12px] text-[var(--primary)]">Role default: {LEVEL_LABEL[roleLevel]}</p> : null}
    </div>
  )
}

/** Sites are listed only once the box is opened; the closed box says which are chosen. */
function SitePicker({ id, jobs, value, onChange }: { id: string; jobs: { id: number; number?: string; name: string }[]; value: number[]; onChange: (v: number[]) => void }) {
  const [open, setOpen] = useState(false)
  const chosen = jobs.filter((j) => value.includes(j.id))
  const summary = chosen.length === 0 ? 'Every site' : chosen.length <= 2 ? chosen.map((j) => `${j.number ?? ''} ${j.name}`.trim()).join(', ') : `${chosen.length} sites selected`
  return (
    <div className="relative" onKeyDown={(ev) => ev.key === 'Escape' && setOpen(false)}>
      <button id={id} type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex h-10 w-full items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 text-left text-sm">
        <span className="truncate">{summary}</span><ChevronDown className="size-4 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div role="listbox" aria-multiselectable className="absolute left-0 right-0 z-20 mt-1 max-h-64 overflow-y-auto rounded-lg border border-border bg-card py-1 shadow-card">
            {jobs.length === 0 && <p className="px-3 py-2 text-[13px] text-muted-foreground">No sites yet.</p>}
            {jobs.map((j) => {
              const on = value.includes(j.id)
              return (
                <button key={j.id} type="button" role="option" aria-selected={on} onClick={() => onChange(on ? value.filter((x) => x !== j.id) : [...value, j.id])}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted">
                  <span className="flex size-4 items-center justify-center rounded-md border border-border">{on && <Check className="size-3" />}</span>
                  {j.number} {j.name}
                </button>
              )
            })}
            {value.length > 0 && <button type="button" className="w-full border-t border-border px-3 py-2 text-left text-[13px] text-muted-foreground hover:bg-muted" onClick={() => onChange([])}>Clear (every site)</button>}
          </div>
        </>
      )}
    </div>
  )
}

/** One person's access: role, sites, and a setting for each portal. Read-only until Edit is pressed. The individual rights behind the portals stay below, folded away. */
export function EmployeeAccess({ e }: { e: EmployeeDetail }) {
  const cat = useHrCatalogue()
  const jobs = useJobOptions(false)
  const [role, setRole] = useState(e.permission_role)
  const [granted, setGranted] = useState(e.permissions)
  const [sites, setSites] = useState(e.all_sites ? [] : e.site_ids)
  useEffect(() => { setRole(e.permission_role); setGranted(e.permissions); setSites(e.all_sites ? [] : e.site_ids) }, [e.permission_role, e.permissions, e.site_ids, e.all_sites])
  const [editing, setEditing] = useState(false)
  const save = useAction(() => setAccess(e.id, { permission_role: role, permissions: granted, site_ids: sites }), { invalidate: [peopleKeys.all], success: 'Access updated', onSuccess: () => setEditing(false) })
  if (!cat.data) return <Skeleton className="h-40 w-full" />

  const current = cat.data.permission_roles.find((r) => r.code === role)
  const fromRole = new Set(current?.permissions ?? [])
  const perms = cat.data.permissions
  // A right tied to one role (HO QS) cannot be switched on for anybody else.
  const reserved = (p: (typeof perms)[number]) => !!p.only_role && p.only_role !== role && role !== 'owner'
  const isOn = (key: string) => granted.includes(key)
  const dirty = role !== e.permission_role || [...granted].sort().join() !== [...e.permissions].sort().join() || [...sites].sort().join() !== [...(e.all_sites ? [] : e.site_ids)].sort().join()
  const changed = perms.filter((p) => !reserved(p) && isOn(p.key) !== fromRole.has(p.key)).length

  const reset = () => { setRole(e.permission_role); setGranted(e.permissions); setSites(e.all_sites ? [] : e.site_ids) }
  const roleLabel = cat.data.permission_roles.find((r) => r.code === e.permission_role)?.label ?? e.permission_role
  const siteLabel = e.all_sites || e.site_names.length === 0 ? 'Every site' : e.site_names.join(', ')
  const held = perms.filter((p) => isOn(p.key) && !reserved(p))
  const portals = cat.data.portals ?? []
  const heldSet = new Set(granted)
  const setLevel = (pt: Portal, level: Level) => setGranted((g) => withLevel(g, pt, level))
  const portalCards = (readOnly: boolean) => (
    <div className="grid gap-4 sm:grid-cols-2">
      {portals.map((pt) => <PortalCard key={pt.code} pt={pt} readOnly={readOnly} level={levelOf(pt, heldSet)} roleLevel={levelOf(pt, fromRole)} onChange={(l) => setLevel(pt, l)} />)}
    </div>
  )
  const portalsDiffer = portals.filter((pt) => !pt.locked && levelOf(pt, heldSet) !== levelOf(pt, fromRole)).length
  const wasAssigned = (p: (typeof perms)[number]) => e.permissions.includes(p.key) && !reserved(p)
  const assigned = perms.filter(wasAssigned)
  const unassigned = perms.filter((p) => !wasAssigned(p))
  const groupsOf = (list: typeof perms) => {
    const m = new Map<string, typeof perms>()
    for (const p of list) m.set(p.group || 'Other', [...(m.get(p.group || 'Other') ?? []), p])
    return [...m.entries()]
  }

  if (!editing) {
    return (
      <div className="space-y-6">
        <div className="flex justify-end"><Button variant="outline" onClick={() => setEditing(true)}>Edit</Button></div>
        <section>
          <h3 className="mb-2 text-base font-semibold">Role &amp; assignment</h3>
          <dl className={card + ' grid gap-4 sm:grid-cols-2'}>
            <div><dt className="text-[13px] text-muted-foreground">Base role</dt><dd className="mt-0.5 text-sm">{roleLabel}</dd></div>
            <div><dt className="text-[13px] text-muted-foreground">Assigned sites</dt><dd className="mt-0.5 text-sm">{siteLabel}</dd></div>
          </dl>
        </section>
        <section>
          <h3 className="mb-2 text-base font-semibold">Portal access</h3>
          {portalCards(true)}
        </section>
        <details>
          <summary className="cursor-pointer text-sm font-medium text-muted-foreground hover:text-foreground">Individual rights ({held.length})</summary>
          <div className="mt-3">
            {held.length === 0 ? <p className="text-[13px] text-muted-foreground">No permissions.</p> : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {groupsOf(held).map(([group, items]) => (
                  <div key={group} className={card}>
                    <p className="mb-1 text-sm font-semibold">{group}</p>
                    <ul className="space-y-0.5 text-[13px] text-muted-foreground">{items.map((p) => <li key={p.key}>{p.label}</li>)}</ul>
                  </div>
                ))}
              </div>
            )}
          </div>
        </details>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <section>
        <h3 className="mb-2 text-base font-semibold">Role &amp; assignment</h3>
        <div className={card + ' grid gap-4 sm:grid-cols-2'}>
          <Field label="Base role" htmlFor="ea-role" hint={current?.description}>
            <Select id="ea-role" value={role} onChange={(ev) => { const r = cat.data!.permission_roles.find((x) => x.code === ev.target.value); setRole(ev.target.value); setGranted(r?.permissions ?? []) }}
              options={cat.data.permission_roles.filter((r) => !r.retired || r.code === role).map((r) => ({ value: r.code, label: r.label + (r.retired ? ' (older access level)' : '') }))} />
          </Field>
          <Field label="Assigned sites" htmlFor="ea-sites" hint={sites.length === 0 ? 'None ticked means every site.' : undefined}>
            <SitePicker id="ea-sites" jobs={jobs.data ?? []} value={sites} onChange={setSites} />
          </Field>
        </div>
      </section>

      <section>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold">Portal access</h3>
            <p className="text-[13px] text-muted-foreground">Choose what this person can do in each portal. The base role sets where they start.</p>
          </div>
          <span className="shrink-0 text-[13px] text-muted-foreground">{portalsDiffer === 0 ? 'Same as the role' : `${portalsDiffer} different from the role`}</span>
        </div>
        {portalCards(false)}
      </section>

      <details>
        <summary className="cursor-pointer text-sm font-medium text-muted-foreground hover:text-foreground">Individual rights{changed > 0 ? ` (${changed} different from the role)` : ''}</summary>
        <div className="mt-3">
        {/* Ordered by what is saved for them, not by the switches as they are flipped, so a card does not jump away from under the cursor. */}
        {[{ title: 'Assigned to them', list: assigned }, { title: 'Not assigned', list: unassigned }].map(({ title, list }) => list.length > 0 && (
          <div key={title} className="mb-4 last:mb-0">
            <p className="mb-2 text-[13px] font-medium text-muted-foreground">{title} ({list.length})</p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((p) => {
                const locked = reserved(p)
                const diff = !locked && isOn(p.key) !== fromRole.has(p.key)
                return (
                  <div key={p.key} className={card + ' flex items-center justify-between gap-3 !py-3' + (diff ? ' border-[var(--primary)]' : '')}>
                    <div className="min-w-0">
                      <p className="text-[13px] leading-snug">{p.label}</p>
                      <p className="text-[11px] text-muted-foreground">{locked ? `${cat.data!.permission_roles.find((r) => r.code === p.only_role)?.label ?? p.only_role} only` : diff ? (isOn(p.key) ? 'Added for them' : 'Removed for them') : p.group}</p>
                    </div>
                    <Toggle on={!locked && isOn(p.key)} disabled={locked} label={p.label} onChange={(v) => setGranted((g) => v ? [...g, p.key] : g.filter((k) => k !== p.key))} />
                  </div>
                )
              })}
            </div>
          </div>
        ))}
        </div>
      </details>

      <div className="flex items-center justify-end gap-2 border-t border-border pt-4">
        {save.error && <p role="alert" className="mr-auto text-[13px] text-danger">{save.error.message}</p>}
        <Button variant="outline" onClick={() => { reset(); setEditing(false) }}>Cancel</Button>
        <Button loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>Save access</Button>
      </div>
    </div>
  )
}
