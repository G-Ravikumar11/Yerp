import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SitePage from './SitePage'

// jsdom has no IntersectionObserver or matchMedia; the page only uses them for reveals and scroll spying.
beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }))
})
afterEach(() => vi.unstubAllGlobals())

const live = { company_id: 7, numbers: { projects_delivered: 12, ongoing_sites: 3, safe_man_hours: 0 }, projects: [] }
const stubFetch = () => {
  const fetch = vi.fn(async (url: string) => ({ ok: true, json: async () => (url.endsWith('/site') ? live : { message: 'Thank you, Ravi.' }) }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('Company front page', () => {
  it('reads as the civil company, with no electrical contractor or ERP wording', async () => {
    stubFetch()
    render(<SitePage />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toMatch(/homes, townships/i)
    expect(await screen.findByText('Projects delivered')).toBeTruthy()
    const text = document.body.textContent ?? ''
    for (const word of [/electrical/i, /33\s*kV/i, /\bpanels?\b/i, /YERP/, /\bERP\b/]) expect(text).not.toMatch(word)
    // Nor in the alt text of any picture.
    for (const img of document.querySelectorAll('img')) expect(img.alt).not.toMatch(/electrical|33\s*kV|panel|YERP/i)
    expect(document.title).toMatch(/^Yalavarti Infra Projects/)
  })

  it('signs staff in from the footer only, not from the menu', () => {
    stubFetch()
    render(<SitePage />)
    expect(within(screen.getByRole('banner')).queryByText(/login/i)).toBeNull()
    expect(within(screen.getByRole('contentinfo')).getByRole('link', { name: 'Staff login' })).toBeTruthy()
  })

  it('sends a civil enquiry from a "What we build" card into the Tender Pipeline', async () => {
    const fetch = stubFetch()
    render(<SitePage />)
    await userEvent.click(screen.getAllByRole('link', { name: 'Enquire About This →' })[2])     // Gated townships & layouts
    expect((screen.getByRole('radio', { name: /Township or layout/ }) as HTMLInputElement).checked).toBe(true)
    await userEvent.type(screen.getByLabelText('Site location'), 'Shadnagar')
    await userEvent.type(screen.getByLabelText('Area'), '12')
    await userEvent.selectOptions(screen.getByLabelText('Unit'), 'acres')
    const brief = screen.getByRole('complementary', { name: 'Your brief' })
    await userEvent.type(within(brief).getByLabelText('Your name'), 'Ravi')
    await userEvent.type(within(brief).getByLabelText('Phone'), '9800000000')
    await userEvent.click(within(brief).getByRole('button', { name: 'Send This Brief' }))
    expect(await screen.findByText('Thank you, Ravi.')).toBeTruthy()
    const [url, init] = fetch.mock.calls.find(([u]) => String(u).endsWith('/enquiry')) as unknown as [string, RequestInit]
    expect(url).toBe('/api/public/enquiry')
    const body = JSON.parse(String(init.body))
    expect(body).toMatchObject({ name: 'Ravi', city: 'Shadnagar', project_type: 'Township or layout' })
    expect(body.message).toContain('Plot or built-up area: 12 acres')
  })
})
