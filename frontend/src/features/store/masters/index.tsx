import { Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Tabs } from '@/components/ui'
import { StoreShell } from '../StoreShell'
import { ItemsTab } from './ItemsTab'
import { BASE, OpeningForm, OpeningImport, OpeningList, OpeningView } from './Opening'
import { StoresTab } from './StoresTab'

type Part = 'stores' | 'items' | 'opening'
const PARTS: { value: Part; label: string; path: string; info: string }[] = [
  { value: 'stores', label: 'Stores', path: '', info: 'Central, site and yard stores, their bins, and the people who work in each. Only assigned people (and store administrators) can work in a store.' },
  { value: 'items', label: 'Items & units', path: '/items', info: 'What the store keeps for each stock item: its category, the base unit stock is counted in, reorder levels, and the other units it can be entered in.' },
  { value: 'opening', label: 'Opening stock', path: '/opening', info: 'What each store held on the day it started on the Store module, typed or imported from a sheet, posted as opening stock.' },
]

/** Store > Masters. Sub-pages live under /store/hub/masters/*. */
export default function MastersIndex() {
  const { pathname } = useLocation()
  const nav = useNavigate()
  const part: Part = pathname.startsWith(`${BASE}/opening`) ? 'opening' : pathname.startsWith(`${BASE}/items`) ? 'items' : 'stores'
  return (
    <StoreShell slice="masters">
      <div className="mb-5">
        <Tabs label="Masters" value={part} onChange={(v) => nav(BASE + (PARTS.find((p) => p.value === v)?.path ?? ''))} items={PARTS} />
      </div>
      <Routes>
        <Route index element={<StoresTab />} />
        <Route path="items" element={<ItemsTab />} />
        <Route path="opening" element={<OpeningList />} />
        <Route path="opening/new" element={<OpeningForm />} />
        <Route path="opening/import" element={<OpeningImport />} />
        <Route path="opening/:id" element={<OpeningView />} />
        <Route path="opening/:id/edit" element={<OpeningForm />} />
        <Route path="*" element={<p className="text-sm text-muted-foreground">There is no such page in Masters.</p>} />
      </Routes>
    </StoreShell>
  )
}
