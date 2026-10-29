import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { HrCatalogue } from '@/api/people'
import { AccessPicker } from './AccessPicker'

const catalogue = {
  portals: [], levels: [], roles: [],
  permission_roles: [
    { code: 'staff', label: 'Staff', rank: 1, description: 'Their own work.', permissions: ['self.service'] },
    { code: 'accounts', label: 'Accounts', rank: 2, description: 'The money.', permissions: ['self.service', 'bills.pay'] },
  ],
  permissions: [
    { key: 'self.service', group: 'Everyone', label: 'My timesheet, payslips and leave' },
    { key: 'bills.pay', group: 'Costs', label: 'Pay bills' },
  ],
} as unknown as HrCatalogue

function mount(onGranted = vi.fn()) {
  render(<AccessPicker catalogue={catalogue} role="accounts" granted={['self.service', 'bills.pay']} onRole={() => {}} onGranted={onGranted} />)
  return onGranted
}

describe('The access level and its permissions', () => {
  it('shows the access level and keeps the permissions folded away until asked for', () => {
    mount()
    expect(screen.getByLabelText('Access level')).toBeTruthy()
    expect(screen.queryByText('Pay bills')).toBeNull()
    expect(screen.getByText('2 ticked')).toBeTruthy()
    expect((screen.getByRole('button', { name: 'Show permissions' })).getAttribute('aria-expanded')).toBe('false')
  })

  it('opens the permissions on request, lets them be changed, and folds them away again', async () => {
    const user = userEvent.setup()
    const onGranted = mount()
    await user.click(screen.getByRole('button', { name: 'Show permissions' }))
    expect(screen.getByText('Pay bills')).toBeTruthy()
    await user.click(screen.getByLabelText('Pay bills'))
    expect(onGranted).toHaveBeenCalledWith(['self.service'])
    await user.click(screen.getByRole('button', { name: 'Hide permissions' }))
    expect(screen.queryByText('Pay bills')).toBeNull()
  })
})
