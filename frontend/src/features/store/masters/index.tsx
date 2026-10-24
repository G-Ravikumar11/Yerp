import { NavLink, Route, Routes } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { StoreShell } from '../StoreShell'
import ControlsPage from './ControlsPage'
import ItemSettingsPage from './ItemSettingsPage'
import StoresPage from './StoresPage'

const tab = ({ isActive }: { isActive: boolean }) =>
  cn('rounded-lg px-3.5 py-1.5 text-[13px] font-medium', isActive ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')

/** Store > Masters: the stores, and how each stock item is treated. Routes under /store/hub/masters/* land here. */
export default function MastersIndex() {
  return (
    <StoreShell slice="masters">
      <nav aria-label="Masters" className="mb-4 flex w-fit gap-1 rounded-xl bg-muted p-1">
        <NavLink to="/store/hub/masters" end className={tab}>Stores</NavLink>
        <NavLink to="/store/hub/masters/items" className={tab}>Item settings</NavLink>
        <NavLink to="/store/hub/masters/controls" className={tab}>Controls</NavLink>
      </nav>
      <Routes>
        <Route index element={<StoresPage />} />
        <Route path="items" element={<ItemSettingsPage />} />
        <Route path="controls" element={<ControlsPage />} />
      </Routes>
    </StoreShell>
  )
}
