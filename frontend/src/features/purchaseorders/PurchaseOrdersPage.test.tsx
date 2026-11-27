import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'
import type { PurchaseOrder } from '@/api/purchaseOrders'

const order = (over: Partial<PurchaseOrder>): PurchaseOrder => ({
  id: 1, number: 'PO-0001', supplier_name: 'Sri Cements', job_id: null, job_name: '', issue_date: '2026-11-01', needed_by: '', amount: 100, tax_amount: 0, total: 100,
  status: 'Approved', approval_status: 'approved', rejection_reason: '', notes: '', billed_total: 0, billed_count: 0, line_items: [], ...over,
})
const orders = [
  order({ receipt_status: 'Partially received', line_items: [{ id: 1, item_code: 'CEM-1', description: 'Cement OPC', uom: 'kg', qty: 5000, price: 1, tax_rate: '0%', received_qty: 3000, pending_qty: 2000 }] }),
  order({ id: 2, number: 'PO-0002', receipt_status: 'Fully received' }),
  order({ id: 3, number: 'PO-0003', status: 'Draft', approval_status: 'none', receipt_status: 'Not received' }),
]
vi.mock('@/api/purchaseOrders', async (orig) => ({ ...(await orig<typeof import('@/api/purchaseOrders')>()), usePurchaseOrders: () => ({ data: orders, isPending: false, isError: false }) }))
vi.mock('@/api/ledger', async (orig) => ({ ...(await orig<typeof import('@/api/ledger')>()), useSuppliers: () => ({ data: { suppliers: [] } }) }))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true, user: { type: 'owner' }, isOwner: true }) }))
vi.mock('./PurchaseSettings', () => ({ PurchaseSettingsButton: () => null }))
vi.mock('@/features/deleteorder/MasterDelete', () => ({ MasterDelete: () => null }))

import PurchaseOrdersPage from './PurchaseOrdersPage'

describe('Purchase orders - what has been received', () => {
  it('shows the receipt status beside the approval, with what is still pending, and none on an order not yet approved', () => {
    render(<QueryClientProvider client={new QueryClient()}><TooltipProvider><MemoryRouter><PurchaseOrdersPage /></MemoryRouter></TooltipProvider></QueryClientProvider>)
    const one = screen.getByText('PO-0001').closest('tr') as HTMLElement
    expect(within(one).getByText('Approved')).toBeInTheDocument()                    // approval stays: further receipts are still made against it
    expect(within(one).getByText('Partially received')).toHaveAttribute('title', 'Cement OPC: 2000 kg pending')
    expect(within(screen.getByText('PO-0002').closest('tr') as HTMLElement).getByText('Fully received')).toBeInTheDocument()
    expect(within(screen.getByText('PO-0003').closest('tr') as HTMLElement).queryByText('Not received')).toBeNull()
  })
})
