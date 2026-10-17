import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { PageHeader } from '@/components/layout/PageHeader'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { storePerm, type StoreSlice } from '@/api/store'

/** The six parts of the Store module, in menu order. */
export const SLICES: { slice: StoreSlice; label: string; blurb: string }[] = [
  { slice: 'masters', label: 'Masters', blurb: 'Stores, bins, who works where, item settings and unit conversions.' },
  { slice: 'enquiry', label: 'Stock enquiry', blurb: 'What is held, where, and every movement behind it.' },
  { slice: 'inward', label: 'Inward', blurb: 'Goods received against purchase orders, quality checks and returns to suppliers.' },
  { slice: 'outward', label: 'Outward', blurb: 'Issues to site and to subcontractors, returnables and write-offs.' },
  { slice: 'control', label: 'Control', blurb: 'Transfers, stock counts, adjustments and scrap.' },
  { slice: 'reports', label: 'Reports', blurb: 'Stock, consumption and material cost reports.' },
]

/** The frame every Store screen sits in: the page title and a row of the parts this person may open. */
export function StoreShell({ slice, children }: { slice: StoreSlice | null; children: ReactNode }) {
  const { can } = useSession()
  const open = SLICES.filter((s) => can(storePerm(s.slice)))
  const here = SLICES.find((s) => s.slice === slice)
  return (
    <div>
      <PageHeader eyebrow="Store" title={here?.label ?? 'Store'} description={here?.blurb ?? 'Stock held at every store, and everything that moves it.'} />
      <nav aria-label="Store sections" className="mb-6 flex gap-1 overflow-x-auto border-b border-border">
        <NavLink to="/store/hub" end className={({ isActive }) => cn('whitespace-nowrap px-3 py-2 text-sm', isActive ? 'border-b-2 border-primary font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}>
          Overview
        </NavLink>
        {open.map((s) => (
          <NavLink key={s.slice} to={`/store/hub/${s.slice}`} className={({ isActive }) => cn('whitespace-nowrap px-3 py-2 text-sm', isActive ? 'border-b-2 border-primary font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}>
            {s.label}
          </NavLink>
        ))}
      </nav>
      {children}
    </div>
  )
}
