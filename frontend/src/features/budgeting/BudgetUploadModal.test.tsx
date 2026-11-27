import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'
import type { BudgetUploadPlan } from '@/api/budgeting'

const unit = { MATERIAL: 0, LABOUR: 0, OTHER: 0 }
const plan: BudgetUploadPlan = {
  lines: 4, budgeted_before: 1,
  counts: { add: 1, kept: 1, empty: 1, error: 1 },
  rows: [
    { row: 7, item: '1.1 Excavation in soil', key: 'a', status: 'add', message: 'Will be added: labour 180 per cum', unit: { ...unit, LABOUR: 180 } },
    { row: 8, item: '1.2 RCC M25 raft', key: 'b', status: 'kept', message: 'Already budgeted in the app - left as it is. The sheet has other figures for it; change it on the page if they are right.', unit },
    { row: 9, item: '1.3 Shuttering', key: 'c', status: 'empty', message: 'No cost filled - left for later.', unit },
    { row: 10, item: '2.1 Brickwork', key: 'd', status: 'error', message: 'A cost is not a number. Type figures only, like 1250.50.', unit },
  ],
}
const calls: string[] = []
vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  api: vi.fn(async (url: string) => { calls.push(url); return url.endsWith('/preview') ? plan : { ...plan, added: 1, budget: {} } }),
}))

import { BudgetUploadModal } from './BudgetUploadModal'

describe('Uploading a budget filled in Excel', () => {
  it('checks the sheet first, shows what it will do, and adds only on the button', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<QueryClientProvider client={new QueryClient()}><BudgetUploadModal job={8} onClose={onClose} /></QueryClientProvider>)
    expect(screen.getByRole('button', { name: /Nothing to add/ })).toBeDisabled()

    await user.upload(screen.getByLabelText('The filled budget sheet'), new File(['x'], 'budget.xlsx'))
    expect(await screen.findByText('Row 7: 1.1 Excavation in soil')).toBeInTheDocument()
    expect(calls).toEqual(['/api/jobs/8/budget/upload/preview'])                    // only checked so far
    expect(screen.getByText('Row 10: 2.1 Brickwork')).toBeInTheDocument()           // the problem, shown
    expect(screen.getByText('Row 8: 1.2 RCC M25 raft')).toBeInTheDocument()         // budgeted here, sheet differs: shown, not changed
    expect(screen.queryByText(/Row 9/)).not.toBeInTheDocument()                     // empty rows are only counted

    await user.click(screen.getByRole('button', { name: /Add 1 line to the budget/ }))
    expect(calls).toEqual(['/api/jobs/8/budget/upload/preview', '/api/jobs/8/budget/upload'])
    expect(onClose).toHaveBeenCalled()
  })
})
