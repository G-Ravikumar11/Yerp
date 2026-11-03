import { Search } from 'lucide-react'
import { Input } from '@/components/ui'
import { PageHeader } from '@/components/layout/PageHeader'
import { StorePicker } from '../shared'

/** The heading of a register page. Left out where a register sits inside the Store Hub, which has its own. */
export function RegisterHeader({ title, description, actions, embedded }: { title: string; description: string; actions?: React.ReactNode; embedded?: boolean }) {
  if (embedded) return actions ? <div className="mb-4 flex justify-end gap-2">{actions}</div> : null
  return <PageHeader eyebrow="Store" title={title} description={description} actions={actions} />
}

/** The search box and store choice over a register's table. */
export function RegisterFilters({ q, onQ, storeId, onStore, placeholder = 'Search materials...', children }: {
  q: string; onQ: (q: string) => void; storeId: number; onStore?: (id: number) => void; placeholder?: string; children?: React.ReactNode
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <div className="w-full sm:w-80"><Input aria-label="Search" placeholder={placeholder} leading={<Search />} value={q} onChange={(e) => onQ(e.target.value)} /></div>
      {onStore && <div className="w-full sm:w-56"><StorePicker id="reg-store" value={storeId || null} placeholder="All my stores" onChange={(id) => onStore(id ?? 0)} /></div>}
      {children}
    </div>
  )
}
