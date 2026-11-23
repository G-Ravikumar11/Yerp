import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'

vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), get: vi.fn(async () => ({ rows: [], items: [], totals: {} })) }))
vi.mock('@/lib/session', () => ({ useSession: () => ({ can: () => true, user: { type: 'owner' }, isOwner: true }) }))

import ReportsIndex from './index'

const at = (path: string) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <TooltipProvider>
      <MemoryRouter initialEntries={[path]}><Routes><Route path="/store/hub/reports/*" element={<ReportsIndex />} /></Routes></MemoryRouter>
    </TooltipProvider>
  </QueryClientProvider>,
)

describe('Store reports without the old store', () => {
  it("answers the old store records' addresses with the 404 page, not with another report", () => {
    for (const path of ['/store/hub/reports/old-store', '/store/hub/reports/old-store/receipts', '/store/hub/reports/old-store/vouchers']) {
      const { unmount } = at(path)
      expect(screen.getByText('Page not found'), path).toBeTruthy()
      expect(screen.queryByRole('navigation', { name: 'Reports' }), path).toBeNull()
      unmount()
    }
  })

  it('offers no old store tab among the reports', () => {
    at('/store/hub/reports/budget-use')
    const tabs = screen.getByRole('navigation', { name: 'Reports' }).textContent ?? ''
    expect(tabs).toContain('Used vs budget')
    expect(tabs).not.toMatch(/old store/i)
  })
})
