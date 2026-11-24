import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EnquiryForm, LiveProjects } from './Live'

afterEach(() => vi.unstubAllGlobals())

describe('Company website', () => {
  it('sends an enquiry, with the planner brief, to the Tender Pipeline and thanks the visitor', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ message: 'Thank you, Ravi.' }) }))
    vi.stubGlobal('fetch', fetch)
    render(<EnquiryForm toast={() => undefined} brief={{ type: 'House or villa', scopes: [], city: 'Hyderabad', text: 'Brief' }} />)
    await userEvent.type(screen.getByLabelText('Your name'), 'Ravi')
    await userEvent.type(screen.getByLabelText('Phone'), '9800000000')
    await userEvent.click(screen.getByRole('button', { name: 'Send Enquiry' }))
    expect(await screen.findByText('Thank you, Ravi.')).toBeTruthy()
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/public/enquiry')
    expect(JSON.parse(String(init.body))).toMatchObject({ name: 'Ravi', phone: '9800000000', city: 'Hyderabad', project_type: 'House or villa', message: 'Brief' })
  })

  it('says what the server refused and keeps what was typed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ detail: 'Please give a phone number or an email so we can reply.' }) })))
    const toast = vi.fn()
    render(<EnquiryForm toast={toast} />)
    await userEvent.type(screen.getByLabelText('Your name'), 'Ravi')
    await userEvent.click(screen.getByRole('button', { name: 'Send Enquiry' }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Please give a phone number or an email so we can reply.'))
    expect((screen.getByLabelText('Your name') as HTMLInputElement).value).toBe('Ravi')
  })

  it('lists the projects ticked for the website and filters them by type of work', async () => {
    const p = (id: number, name: string, sector: string) => ({ id, name, sector, client: '', location: 'Hyderabad', scope: '', status: 'Ongoing' as const, year: '2026', photos: [] })
    render(<LiveProjects live={{ company_id: 1, numbers: { projects_delivered: 0, ongoing_sites: 2, safe_man_hours: 0 }, projects: [p(1, 'Vanya STP', 'Water'), p(2, 'Tower A', 'Residential')] }} />)
    expect(screen.getByText('Vanya STP')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Water' }))
    expect(screen.queryByText('Tower A')).toBeNull()
  })
})
