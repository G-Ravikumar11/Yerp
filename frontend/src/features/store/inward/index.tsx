import { Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Tabs } from '@/components/ui'
import { StoreShell } from '../StoreShell'
import { BASE, GrnForm, GrnList, GrnView } from './Grns'
import { GateRegister, PendingView, RatesAndSettings, ReturnList, ReturnView } from './Others'

type Part = 'grn' | 'gate' | 'pending' | 'returns' | 'rates'
const PARTS: { value: Part; label: string; path: string; info: string }[] = [
  { value: 'grn', label: 'GRNs', path: '/grn', info: 'Goods received against purchase orders, direct receipts and client-supplied material. Only accepted quantity goes into stock.' },
  { value: 'gate', label: 'Gate register', path: '/gate', info: 'Every vehicle that came in with material: challan, time and weighbridge weights. A GRN is made from an entry.' },
  { value: 'pending', label: 'Pending', path: '/pending', info: 'What approved purchase orders still have to deliver, by order or by vendor.' },
  { value: 'returns', label: 'Returns', path: '/returns', info: 'Material sent back to suppliers against a GRN, with the debit note.' },
  { value: 'rates', label: 'Rates & settings', path: '/rates', info: 'Agreed rates for client-supplied material, and whether input GST is recoverable.' },
]

/** Store > Inward. Sub-pages live under /store/hub/inward/*. */
export default function InwardIndex() {
  const { pathname } = useLocation()
  const nav = useNavigate()
  const part: Part = PARTS.find((p) => p.value !== 'grn' && pathname.startsWith(BASE + p.path))?.value ?? 'grn'
  return (
    <StoreShell slice="inward">
      <div className="mb-5">
        <Tabs label="Inward" value={part} onChange={(v) => nav(BASE + (PARTS.find((p) => p.value === v)?.path ?? ''))} items={PARTS} />
      </div>
      <Routes>
        <Route index element={<GrnList />} />
        <Route path="grn" element={<GrnList />} />
        <Route path="grn/new" element={<GrnForm />} />
        <Route path="grn/:id" element={<GrnView />} />
        <Route path="client-supply/:id" element={<GrnView />} />
        <Route path="gate" element={<GateRegister />} />
        <Route path="pending" element={<PendingView />} />
        <Route path="returns" element={<ReturnList />} />
        <Route path="returns/:id" element={<ReturnView />} />
        <Route path="rates" element={<RatesAndSettings />} />
        <Route path="*" element={<p className="text-sm text-muted-foreground">There is no such page in Inward.</p>} />
      </Routes>
    </StoreShell>
  )
}
