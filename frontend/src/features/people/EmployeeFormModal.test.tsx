import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sent: { url: string; body: unknown }[] = []
let owner = true

const catalogue = {
  portals: [],
  levels: [{ code: 'L5', label: 'L5 - Site Director / Sr. Engineer', rank: 3 }, { code: 'L6', label: 'L6 - Site Engineer', rank: 2 }, { code: 'L4', label: 'L4 - Project Manager', rank: 4 }],
  roles: [
    { code: 'site_director', label: 'Site Director', level: 'L5', reports_to: null, department: 'Site', access: 'construction' },
    { code: 'sr_engineer', label: 'Sr. Engineer', level: 'L5', reports_to: null, department: 'Site', access: 'construction' },
    { code: 'store_executive', label: 'Store Executive', level: 'L6', reports_to: null, department: 'Store', access: 'stores' },
    { code: 'site_engineer', label: 'Site Engineer', level: 'L6', reports_to: null, department: 'Site', access: 'construction' },
    { code: 'tpt', label: 'TPT', level: 'L4', reports_to: null, department: 'Transport', access: 'staff' },
    { code: 'project_manager', label: 'Project Manager', level: 'L4', reports_to: null, department: 'Projects', access: 'project_manager' },
  ],
  permission_roles: [
    { code: 'staff', label: 'Staff', rank: 1, description: '', permissions: ['self.service'] },
    { code: 'construction', label: 'Construction', rank: 2, description: '', permissions: ['self.service', 'site.record'] },
    { code: 'stores', label: 'Stores', rank: 2, description: '', permissions: ['self.service', 'store.view'] },
    { code: 'project_manager', label: 'Project Manager', rank: 3, description: '', permissions: ['self.service', 'site.record', 'projects.view'] },
  ],
  permissions: [],
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url.startsWith('/api/hr/levels')) return catalogue
    if (url.startsWith('/api/employees')) return []
    if (url.startsWith('/api/departments')) return []
    if (url.startsWith('/api/jobs')) return { jobs: [] }
    return {}
  }),
  post: vi.fn(async (url: string, body: unknown) => { sent.push({ url, body }); return { id: 1, employee_id: 'EMP-1', message: 'ok', site_names: [] } }),
}))
vi.mock('@/lib/session', () => ({ useSession: () => ({ isOwner: owner, can: () => owner }) }))
vi.mock('@/features/people/AccessPicker', () => ({
  AccessPicker: ({ role, granted }: { role: string; granted: string[] }) => <div data-testid="access">{role}|{[...granted].sort().join(',')}</div>,
}))

import { EmployeeFormModal } from './EmployeeFormModal'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><EmployeeFormModal open onClose={() => {}} /></MemoryRouter></QueryClientProvider>)
}

const access = () => screen.getByTestId('access').textContent

beforeEach(() => { sent.length = 0; owner = true })

describe('Add an employee: access follows the role and the level', () => {
  it('gives the access level a role carries, with its rights, as soon as the role is chosen', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => expect(access()).toBe('staff|self.service'))
    await user.selectOptions(screen.getByLabelText('Reporting role'), 'store_executive')
    expect(access()).toBe('stores|self.service,store.view')
    expect((screen.getByLabelText('Level') as HTMLSelectElement).value).toBe('L6')
    await user.selectOptions(screen.getByLabelText('Reporting role'), 'site_engineer')
    expect(access()).toBe('construction|self.service,site.record')
  })

  it('gives the access of a level on its own', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.selectOptions(screen.getByLabelText('Level'), 'L5')
    expect(access()).toBe('construction|self.service,site.record')
    expect(screen.getAllByRole('option', { name: 'Site Director' }).length).toBe(1)
    expect(screen.queryByRole('option', { name: 'Store Executive' })).toBeNull()
  })

  it('uses the access of the role a level is named for, and the role refines it', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.selectOptions(screen.getByLabelText('Level'), 'L4')
    expect(access()).toBe('project_manager|projects.view,self.service,site.record')
    await user.selectOptions(screen.getByLabelText('Reporting role'), 'tpt')
    expect(access()).toBe('staff|self.service')
    await user.selectOptions(screen.getByLabelText('Level'), 'L6')
    expect(access()).toBe('construction|self.service,site.record')
    await user.selectOptions(screen.getByLabelText('Reporting role'), 'store_executive')
    expect(access()).toBe('stores|self.service,store.view')
  })

  it('sends the access with the new employee, in the one request', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.type(screen.getByLabelText('First name *'), 'Asha')
    await user.type(screen.getByLabelText('Last name *'), 'Rao')
    await user.selectOptions(screen.getByLabelText('Reporting role'), 'site_engineer')
    await user.click(screen.getByRole('button', { name: 'Create the employee' }))
    await waitFor(() => expect(sent.length).toBe(1))
    expect(sent[0].url).toBe('/api/employees')
    expect(sent[0].body).toMatchObject({ role: 'site_engineer', level: 'L6', permission_role: 'construction', permissions: ['self.service', 'site.record'] })
  })

  it('does not touch access for anybody but the Master', async () => {
    owner = false
    const user = userEvent.setup()
    mount()
    await screen.findByRole('option', { name: 'Site Engineer' })
    await user.selectOptions(screen.getByLabelText('Reporting role'), 'site_engineer')
    expect(screen.queryByTestId('access')).toBeNull()
    await user.type(screen.getByLabelText('First name *'), 'Asha')
    await user.type(screen.getByLabelText('Last name *'), 'Rao')
    await user.click(screen.getByRole('button', { name: 'Create the employee' }))
    await waitFor(() => expect(sent.length).toBe(1))
    expect(sent[0].body).toMatchObject({ permission_role: 'staff' })
    expect(sent[0].body).not.toHaveProperty('permissions')
  })
})
