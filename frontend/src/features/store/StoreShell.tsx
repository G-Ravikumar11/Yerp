import type { ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { LayoutGrid } from 'lucide-react'
import { Button } from '@/components/ui'
import { PageHeader } from '@/components/layout/PageHeader'
import { useSession } from '@/lib/session'
import { cn } from '@/lib/utils'
import { scanCode, storePerm, useScanning, type StoreSlice } from '@/api/store'
import { ApiError } from '@/lib/api'
import { toast } from '@/stores/toast'
import { ScanButton } from './shared/Scanner'

/** The six parts of the Store module, in menu order. */
export const SLICES: { slice: StoreSlice; label: string; blurb: string }[] = [
  { slice: 'masters', label: 'Settings', blurb: 'Stores, racks, who works in each store, and item units.' },
  { slice: 'enquiry', label: 'Stock', blurb: 'What is in each store, and every movement of each item.' },
  { slice: 'inward', label: 'Material In', blurb: 'Material received from suppliers, quality check, and returns to suppliers.' },
  { slice: 'outward', label: 'Material Out', blurb: 'Material requests, giving material to site and contractors, returns, gate passes, tools.' },
  { slice: 'control', label: 'Move & Count', blurb: 'Move stock between stores, count stock, damaged and scrap.' },
  { slice: 'reports', label: 'Reports', blurb: 'Stock, consumption and material cost reports.' },
]

/** The frame every Store screen sits in: the page title and a row of the parts this person may open. */
export function StoreShell({ slice, children }: { slice: StoreSlice | null; children: ReactNode }) {
  const { can } = useSession()
  const open = SLICES.filter((s) => can(storePerm(s.slice)))
  const here = SLICES.find((s) => s.slice === slice)
  const nav = useNavigate()
  const scanning = useScanning()
  // Anything scanned on the store floor opens what it is: an item's stock card, a bin's store, a document - a gate pass at the gate.
  const openScanned = async (code: string) => {
    try {
      const found = await scanCode(code)
      if (found.kind === 'item') nav(`/store/hub/enquiry/card?item=${found.item.id}`)
      else if (found.kind === 'bin') nav(`/store/hub/enquiry?store=${found.store.id}`)
      else nav(found.path)
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : 'The code could not be looked up.')
    }
  }
  return (
    <div>
      <PageHeader eyebrow="Store" title={here?.label ?? 'Store'} description={here?.blurb ?? 'Stock held at every store, and everything that moves it.'}
        actions={<>
          <Button variant="outline" asChild><Link to="/store"><LayoutGrid /> Store home</Link></Button>
          {scanning && <ScanButton label="Scan" title="Scan a code" hint="An item's rack label or maker's barcode opens its stock card, a bin tag its store, and a gate pass, issue or receipt the document - the gate checks a gate pass here." onCode={(c) => void openScanned(c)} />}
        </>} />
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
