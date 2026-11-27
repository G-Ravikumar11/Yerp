import { useState } from 'react'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { Projects, Quality, Quote, registerRows } from './Live'
import { BUILT_IN, ContentProvider, contentFrom } from './siteContent'
import type { Live } from './siteApi'

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} })
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const p = (id: number, name: string, extra: Partial<Live['projects'][number]> = {}) => ({ id, name, sector: 'Residential', client: 'Vision', location: 'Hyderabad', scope: '', status: 'Ongoing' as const, year: '2026', photos: [], ...extra })
const live = (projects: Live['projects'], numbers: Partial<Live['numbers']> = {}): Live => ({ company_id: 1, numbers: { projects_delivered: 0, ongoing_sites: 0, safe_man_hours: 0, ...numbers }, projects })
const withContent = (published: Record<string, unknown>, ui: React.ReactNode) => <ContentProvider value={contentFrom(published)}>{ui}</ContentProvider>

describe('The projects register', () => {
  it('is the sites listed, plus the live projects on the website that are not one of them already', () => {
    const rows = registerRows(BUILT_IN.SITE.sites, live([p(1, 'Vision Arusha', { progress: 40 }), p(2, 'Kokapet Villas')]))
    expect(rows.map((r) => r.site)).toEqual([...BUILT_IN.SITE.sites.map((s) => s.site), 'Kokapet Villas'])
    expect(rows.find((r) => r.site === 'Vision Arusha')!.progress).toBe(40)                  // the live project lends its progress
  })

  it('filters by state, and shows "% done" only when the company has chosen to', async () => {
    const data = live([p(1, 'Vision Arusha', { progress: 40 })])
    const { unmount } = render(withContent({}, <Projects no={2} live={data} />))
    expect(screen.queryByRole('columnheader', { name: 'Progress' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Telangana · 3/ }))
    const body = screen.getAllByRole('rowgroup')[1]
    expect(within(body).getAllByRole('row')).toHaveLength(3)
    unmount()
    render(withContent({ options: { safeHoursFrom: 100000, showProgress: true } }, <Projects no={2} live={data} />))
    expect(screen.getByRole('columnheader', { name: 'Progress' })).toBeTruthy()
    expect(screen.getByLabelText('40% done')).toBeTruthy()
  })
})

describe('Quality, safety and credentials', () => {
  it('shows a credential only with a real value, and the safe man-hours only past the level set', () => {
    const credentials = [{ label: 'GSTIN', value: '36ABCDE1234F1Z5' }, { label: 'ISO certification', value: 'owner to fill' }, { label: 'RERA', value: '' }]
    const { container, unmount } = render(withContent({ credentials }, <Quality no={5} live={live([], { safe_man_hours: 50000 })} />))
    expect(within(container).getByText('36ABCDE1234F1Z5')).toBeTruthy()
    expect(within(container).queryByText('ISO certification')).toBeNull()
    expect(container.textContent).not.toMatch(/owner to fill|on request|sample/i)
    expect(within(container).queryByText(/Safe man-hours/i)).toBeNull()                       // 50,000 is under 1,00,000
    unmount()
    render(withContent({ credentials }, <Quality no={5} live={live([], { safe_man_hours: 241600 })} />))
    expect(screen.getByText('2,41,600')).toBeTruthy()
  })
})

describe('Start a project', () => {
  it('sends the one form, with the kind of work, to the Tender Pipeline and thanks the visitor', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ message: 'Thank you, Ravi.' }) }))
    vi.stubGlobal('fetch', fetch)
    const Form = () => {
      const [type, setType] = useState('')
      return <Quote no={6} type={type} setType={setType} toast={() => undefined} />
    }
    render(withContent({}, <Form />))
    await userEvent.click(screen.getByRole('button', { name: 'Township or layout' }))
    await userEvent.type(screen.getByLabelText('Your name'), 'Ravi')
    await userEvent.type(screen.getByLabelText('Phone'), '9800000000')
    await userEvent.type(screen.getByLabelText('Site location'), 'Shadnagar')
    await userEvent.type(screen.getByLabelText('Plot or built-up area'), '12 acres')
    await userEvent.selectOptions(screen.getByLabelText('Expected start'), '3 to 6 months')
    await userEvent.click(screen.getByRole('button', { name: /Send enquiry/ }))
    expect(await screen.findByText('Thank you, Ravi.')).toBeTruthy()
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/public/enquiry')
    const body = JSON.parse(String(init.body))
    expect(body).toMatchObject({ name: 'Ravi', phone: '9800000000', city: 'Shadnagar', project_type: 'Township or layout', website: '' })
    expect(body.message).toContain('Plot or built-up area: 12 acres')
    expect(body.message).toContain('Expected start: 3 to 6 months')
  })

  it('says what the server refused and keeps what was typed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ detail: 'Please give a phone number or an email so we can reply.' }) })))
    const toast = vi.fn()
    render(withContent({}, <Quote no={6} type="" setType={() => undefined} toast={toast} />))
    await userEvent.type(screen.getByLabelText('Your name'), 'Ravi')
    await userEvent.click(screen.getByRole('button', { name: /Send enquiry/ }))
    await waitFor(() => expect(toast).toHaveBeenCalledWith('Please give a phone number or an email so we can reply.'))
    expect((screen.getByLabelText('Your name') as HTMLInputElement).value).toBe('Ravi')
  })

  it('offers WhatsApp beside the form only once the number is set', () => {
    const { unmount } = render(withContent({}, <Quote no={6} type="" setType={() => undefined} toast={() => undefined} />))
    expect(screen.queryByText('WhatsApp')).toBeNull()
    unmount()
    render(withContent({ company: { ...BUILT_IN.COMPANY, whatsapp: '+91 98480 12345' } }, <Quote no={6} type="" setType={() => undefined} toast={() => undefined} />))
    expect(screen.getByText('WhatsApp').closest('a')!.getAttribute('href')).toBe('https://wa.me/919848012345')
  })
})
