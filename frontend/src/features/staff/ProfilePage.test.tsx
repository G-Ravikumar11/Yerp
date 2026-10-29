import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sent: { url: string; body: unknown }[] = []
let profile: Record<string, unknown> = {}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async () => profile),
  put: vi.fn(async (url: string, body: unknown) => { sent.push({ url, body }); return { message: 'Saved: emergency contact.', emergency_complete: true } }),
}))

import ProfilePage from './ProfilePage'

const base = {
  full_name: 'Asha Rao', first_name: 'Asha', last_name: 'Rao', email: 'a@example.com', phone: '', address: '', job_title: 'Engineer', level: '', employment_type: 'full_time',
  department: '', manager: '', start_date: '', work_location: '', employee_id_code: 'EMP-1', goals_count: 0, goal_progress: 0, team: [],
  emergency_contact: '', emergency_phone: '', emergency_complete: false, gender: '', aadhaar_no: '', pan_no: '', uan_no: '', esi_no: '', onboarding: true,
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><ProfilePage /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => { sent.length = 0; profile = { ...base } })

describe('My details', () => {
  it('asks for the emergency contact and holds the save until a name and a number are given', async () => {
    const user = userEvent.setup()
    mount()
    expect(await screen.findByText(/Please give an emergency contact to finish onboarding/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Save my details' }))
    expect(sent.length).toBe(0)
    expect(screen.getAllByText(/Required|Enter a phone number/).length).toBeGreaterThan(0)
    await user.type(screen.getByLabelText('Emergency contact name *'), 'Ravi Rao')
    await user.type(screen.getByLabelText('Emergency contact phone *'), '9876543210')
    await user.click(screen.getByRole('button', { name: 'Save my details' }))
    await waitFor(() => expect(sent.length).toBe(1))
    expect(sent[0].url).toBe('/api/employee/profile/details')
    expect(sent[0].body).toMatchObject({ emergency_contact: 'Ravi Rao', emergency_phone: '9876543210' })
  })

  it('saves without the Aadhaar, PAN or UAN numbers, and points to Documents for the files', async () => {
    const user = userEvent.setup()
    profile = { ...base, emergency_contact: 'Ravi', emergency_phone: '9876543210', emergency_complete: true }
    mount()
    await screen.findByLabelText('Aadhaar number')
    expect(screen.queryByText(/Please give an emergency contact/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save my details' }))        // numbers not filled in: still saves
    await waitFor(() => expect(sent.length).toBe(1))
    expect(screen.getByRole('link', { name: 'Documents' }).getAttribute('href')).toBe('/me/documents')
  })
})
