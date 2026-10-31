import { Route, Routes } from 'react-router-dom'
import { StoreShell } from '../StoreShell'
import BatchesPage from './BatchesPage'
import StockCardPage from './StockCardPage'
import StockPositionPage from './StockPositionPage'

/** Store > Stock enquiry: the position, and an item's stock card. Routes under /store/hub/enquiry/* land here. */
export default function EnquiryIndex() {
  return (
    <StoreShell slice="enquiry">
      <Routes>
        <Route index element={<StockPositionPage />} />
        <Route path="card" element={<StockCardPage />} />
        <Route path="batches" element={<BatchesPage />} />
      </Routes>
    </StoreShell>
  )
}
