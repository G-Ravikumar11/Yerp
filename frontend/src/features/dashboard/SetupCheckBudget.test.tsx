import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const answer = {
  to_do: 1, total: 1,
  items: [{
    key: 'budgets', title: 'Every BOQ line is budgeted', detail: '2 of 4 BOQ lines on 1 live project are still to budget', count: 2, link: '/projects/budgeting', fix: 'Budget them', ok: false,
    budget: {
      totals: { lines: 4, budgeted: 2, partial: 1, unbudgeted: 1, approved_value: 1472800, budgeted_value: 1074000, remaining_value: 398800, completion_percent: 50, value_percent: 72.9 },
      projects: [{ job_id: 7, code: 'KOK', name: 'Kokapet Towers', lines: [
        { key: 'fwk', item_no: '1.3', description: 'Shuttering to raft edges', unit: 'sqm', status: 'Partially budgeted', quantity: 80, value: 32800 },
        { key: 'mas', item_no: '2.1', description: 'Brick masonry', unit: 'cum', status: 'Not budgeted', quantity: 60, value: 366000 },
      ] }],
    },
  }],
}
vi.mock('@/lib/session', () => ({ useSession: () => ({ isOwner: true }) }))
vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), get: vi.fn(async () => answer) }))

import { SetupCheck } from './SetupCheck'

describe('Setup check - the BOQ budget', () => {
  it('gives the counts and values and names each project with the lines still to budget', async () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><SetupCheck /></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText(/4 lines: 2 budgeted, 1 partly, 1 not at all \(50%\)/)).toBeInTheDocument()
    expect(screen.getByText(/₹3,98,800.00 to go/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'KOK Kokapet Towers' })).toHaveAttribute('href', '/projects/budgeting?job=7')
    expect(screen.getByText(/2 lines to budget: 1.3 Shuttering to raft edges; 2.1 Brick masonry/)).toBeInTheDocument()
  })
})
