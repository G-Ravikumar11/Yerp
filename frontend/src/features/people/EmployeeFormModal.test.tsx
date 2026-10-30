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
vi.mock('@/lib/session', () => ({ useSession: () => ({ isOwner: owner, isHrOrMaster: owner, can: () => owner }) }))
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
    await user.selectOptions(screen.getByLabelText('Gender *'), 'Female')
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Ravi Rao')
    await user.type(screen.getByLabelText('Emergency contact phone *'), '9876543210')
    await user.selectOptions(screen.getByLabelText('Reporting role'), 'site_engineer')
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
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
    await user.selectOptions(screen.getByLabelText('Gender *'), 'Female')
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Ravi Rao')
    await user.type(screen.getByLabelText('Emergency contact phone *'), '9876543210')
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    await user.click(screen.getByRole('button', { name: 'Create the employee' }))
    await waitFor(() => expect(sent.length).toBe(1))
    expect(sent[0].body).toMatchObject({ permission_role: 'staff' })
    expect(sent[0].body).not.toHaveProperty('permissions')
  })

  it('will not create anybody without a gender and an emergency contact name and number', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.type(screen.getByLabelText('First name *'), 'Asha')
    await user.type(screen.getByLabelText('Last name *'), 'Rao')
    const create = screen.getByRole('button', { name: 'Save and continue' }) as HTMLButtonElement
    expect(create.disabled).toBe(true)
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Ravi Rao')
    expect(create.disabled).toBe(true)
    await user.type(screen.getByLabelText('Emergency contact phone *'), '12')
    expect(create.disabled).toBe(true)
    await user.type(screen.getByLabelText('Emergency contact phone *'), '34567890')
    expect(create.disabled).toBe(true)                                                       // still no gender
    expect((screen.getByLabelText('Gender *') as HTMLSelectElement).value).toBe('')
    await user.selectOptions(screen.getByLabelText('Gender *'), 'Female')
    expect(create.disabled).toBe(false)
    await user.click(create)
    await user.click(screen.getByRole('button', { name: 'Create the employee' }))
    await waitFor(() => expect(sent.length).toBe(1))
    expect(sent[0].body).toMatchObject({ emergency_contact: 'Ravi Rao', emergency_phone: '1234567890', gender: 'Female' })
  })
})

describe('Add an employee: the statutory numbers', () => {
  it('asks for the UAN, Aadhaar and ESI numbers, and sends what is typed', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.type(screen.getByLabelText('First name *'), 'Ravi')
    await user.type(screen.getByLabelText('Last name *'), 'Kumar')
    await user.selectOptions(screen.getByLabelText('Gender *'), 'Female')
    await user.type(screen.getByLabelText('UAN'), '101185316896')
    await user.type(screen.getByLabelText('Aadhaar number'), '801874264479')
    await user.type(screen.getByLabelText('ESI number'), '3100123456')
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Asha')
    await user.type(screen.getByLabelText('Emergency contact phone *'), '9876543210')
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    await user.click(screen.getByRole('button', { name: 'Create the employee' }))
    await waitFor(() => expect(sent.length).toBeGreaterThan(0))
    expect(sent[0]!.body).toMatchObject({ uan_no: '101185316896', aadhaar_no: '801874264479', esi_no: '3100123456' })
  })
})

describe('Add an employee: the PAN number, the cards, address and gender', () => {
  it('keeps the upload option out of the way until a number is clicked, then offers "Upload document"', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    expect(screen.getByLabelText('PAN number')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /upload document/i })).toBeNull()
    for (const [number, card] of [['Aadhaar number', 'Aadhaar card'], ['PAN number', 'PAN card'], ['ESI number', 'ESI card']] as const) {
      await user.click(screen.getByLabelText(number))
      const pick = screen.getByLabelText(`Attach ${card}`) as HTMLInputElement
      expect(pick.type).toBe('file')
      expect(pick.accept).toContain('.pdf')
      expect(pick.accept).toContain('.jpeg')
    }
    expect(screen.getAllByRole('button', { name: /upload document/i }).length).toBe(3)
  })

  it('shows the chosen file beside the option, and lets it be taken off again', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.click(screen.getByLabelText('Aadhaar number'))
    await user.upload(screen.getByLabelText('Attach Aadhaar card'), new File(['x'], 'aadhaar.jpeg', { type: 'image/jpeg' }))
    expect(screen.getByText('aadhaar.jpeg')).toBeTruthy()
    await user.click(screen.getByRole('button', { name: /remove the attached aadhaar card/i }))
    expect(screen.queryByText('aadhaar.jpeg')).toBeNull()
  })

  it('asks for an address and sends it, with the PAN number', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.type(screen.getByLabelText('First name *'), 'Ravi')
    await user.type(screen.getByLabelText('Last name *'), 'Kumar')
    await user.selectOptions(screen.getByLabelText('Gender *'), 'Male')
    await user.type(screen.getByLabelText('Address'), 'Plot 1, Kondapur')
    await user.type(screen.getByLabelText('PAN number'), 'abcde1234f')
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Asha')
    await user.type(screen.getByLabelText('Emergency contact phone *'), '9876543210')
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    await user.click(screen.getByRole('button', { name: 'Create the employee' }))
    await waitFor(() => expect(sent.length).toBeGreaterThan(0))
    expect(sent[0]!.body).toMatchObject({ pan_no: 'ABCDE1234F', address: 'Plot 1, Kondapur', gender: 'Male' })
  })

  it('will not go on to step 2 until a gender is chosen', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await user.type(screen.getByLabelText('First name *'), 'Ravi')
    await user.type(screen.getByLabelText('Last name *'), 'Kumar')
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Asha')
    await user.type(screen.getByLabelText('Emergency contact phone *'), '9876543210')
    const create = screen.getByRole('button', { name: /save and continue/i }) as HTMLButtonElement
    expect(create.disabled).toBe(true)
    await user.selectOptions(screen.getByLabelText('Gender *'), 'Prefer not to say')
    expect(create.disabled).toBe(false)
  })
})

describe('Add an employee: the two sections', () => {
  it('heads the personal details first and the company details after them', async () => {
    mount()
    await waitFor(() => screen.getByTestId('access'))
    const personal = screen.getByRole('heading', { name: 'Personal details' })
    const company = screen.getByRole('heading', { name: 'Company details' })
    expect(personal.compareDocumentPosition(screen.getByLabelText('First name *')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(personal.compareDocumentPosition(company) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(company.compareDocumentPosition(screen.getByLabelText('Employee ID')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // Phone and address are personal; the job title and salary are the company's.
    expect(company.compareDocumentPosition(screen.getByLabelText('Phone')) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
    expect(company.compareDocumentPosition(screen.getByLabelText('Job title')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})

describe('Add an employee: two steps', () => {
  const fill = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.type(screen.getByLabelText('First name *'), 'Ravi')
    await user.type(screen.getByLabelText('Last name *'), 'Kumar')
    await user.selectOptions(screen.getByLabelText('Gender *'), 'Male')
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Asha')
    await user.type(screen.getByLabelText('Emergency contact phone *'), '9876543210')
  }

  it('starts on the details, with the sites and access held back for the second step', async () => {
    mount()
    await waitFor(() => screen.getByTestId('access'))
    expect(screen.getByRole('listitem', { current: 'step' }).textContent).toContain('Details')
    expect(screen.getByRole('button', { name: 'Save and continue' })).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Create the employee' })).toBeNull()
    expect(screen.getByText('Sites').closest('[hidden]')).not.toBeNull()      // out of sight until step 2
  })

  it('goes on to the sites and access once the details are complete, and nothing is sent yet', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    expect((screen.getByRole('button', { name: 'Save and continue' }) as HTMLButtonElement).disabled).toBe(true)
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    expect(screen.getByRole('listitem', { current: 'step' }).textContent).toContain('Sites and access')
    expect(screen.getByText('Sites').closest('[hidden]')).toBeNull()
    expect(screen.getByLabelText('First name *').closest('[hidden]')).not.toBeNull()      // the details are put away
    expect(screen.getByRole('button', { name: 'Create the employee' })).toBeTruthy()
    expect(sent.length).toBe(0)
  })

  it('lists the sites one under another', async () => {
    mount()
    await waitFor(() => screen.getByTestId('access'))
    const list = screen.getByText('Sites').closest('div')!.parentElement!.querySelector('#ef-sites')!
    expect(list.className).toContain('flex-col')
    expect(list.className).not.toContain('flex-wrap')
  })

  it('goes back with everything typed still there, then creates the employee at the end', async () => {
    const user = userEvent.setup()
    mount()
    await waitFor(() => screen.getByTestId('access'))
    await fill(user)
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect((screen.getByLabelText('First name *') as HTMLInputElement).value).toBe('Ravi')
    expect((screen.getByLabelText('Gender *') as HTMLSelectElement).value).toBe('Male')
    await user.click(screen.getByRole('button', { name: 'Save and continue' }))
    await user.click(screen.getByRole('button', { name: 'Create the employee' }))
    await waitFor(() => expect(sent.length).toBe(1))
    expect(sent[0]!.body).toMatchObject({ first_name: 'Ravi', last_name: 'Kumar', gender: 'Male', emergency_contact: 'Asha' })
  })
})

describe('Add an employee: the ID numbers are for HR and the Master', () => {
  it('shows the UAN, Aadhaar, PAN and ESI inputs to HR and the Master, and to nobody else', async () => {
    mount()
    await waitFor(() => screen.getByTestId('access'))
    for (const label of ['UAN', 'Aadhaar number', 'PAN number', 'ESI number']) expect(screen.getByLabelText(label)).toBeTruthy()
  })

  it('leaves them out for anybody else', async () => {
    owner = false
    mount()
    await screen.findByRole('option', { name: 'Site Engineer' })
    for (const label of ['UAN', 'Aadhaar number', 'PAN number', 'ESI number']) expect(screen.queryByLabelText(label)).toBeNull()
    expect(screen.getByLabelText('Address')).toBeTruthy()                        // the rest of the form is theirs as before
  })
})
