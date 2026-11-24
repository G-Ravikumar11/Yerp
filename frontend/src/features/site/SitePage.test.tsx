import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SitePage from './SitePage'
import { COMPANY, SITE } from './data/content'

// jsdom has no IntersectionObserver or matchMedia; the page only uses them for reveals and scroll spying.
beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }))
})
// The page is taken down while the stand-ins are still there: its counters start watching a moment after the data arrives, and on a
// slow runner that was after the stand-ins had gone ("IntersectionObserver is not defined").
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

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
    // Waited for longer than usual: with the whole suite running, the page's first draw can take more than a second.
    expect(await screen.findByText('Projects delivered', {}, { timeout: 4000 })).toBeTruthy()
    const text = document.body.textContent ?? ''
    for (const word of [/electrical/i, /33\s*kV/i, /\bpanels?\b/i, /Y\s*-?\s*ERP/i, /\bERP\b/i, /terms of service/i, /privacy/i]) expect(text).not.toMatch(word)
    // Nor anywhere hidden in the markup: picture descriptions, labels for screen readers, tooltips, link addresses.
    const html = document.body.innerHTML
    for (const word of [/electrical/i, /33\s*kV/i, /\bpanels?\b/i, /ERP/, /\by\s*-?\s*erp\b/i, /\bterms\b/i, /privacy/i]) expect(html).not.toMatch(word)
    expect(document.title).toMatch(/^Yalavarti Infra Projects/)
  })

  it('has no Terms of Service or Privacy Policy link: those live on the staff sign-in page', () => {
    stubFetch()
    render(<SitePage />)
    const links = screen.getAllByRole('link') as HTMLAnchorElement[]
    expect(links.filter((a) => /terms|privacy/i.test(a.textContent + ' ' + a.getAttribute('href')))).toEqual([])
  })

  it('signs staff in from one quiet footer link only, not from the menu', () => {
    stubFetch()
    render(<SitePage />)
    expect(within(screen.getByRole('banner')).queryByText(/login|sign in/i)).toBeNull()
    // The only way into the staff app is "Staff login", once, in the footer. (The careers link opens the public jobs page.)
    const links = screen.getAllByRole('link') as HTMLAnchorElement[]
    const staff = links.filter((a) => /login|sign.?in|staff/i.test(a.textContent + ' ' + a.getAttribute('href')))
    expect(staff.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([['Staff login', '/login']])
    expect(within(screen.getByRole('contentinfo')).getByRole('link', { name: 'Staff login' })).toBe(staff[0])
  })

  it('shows the words as last published from Settings -> Website, and its own copy until they arrive', async () => {
    const published = { hero: { title: 'Published title', sub: 'Published line' }, lead: 'Published lead', company: { ...COMPANY, phone: { show: '040 0000 0000', tel: '+914000000000' } } }
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...live, content: published }) })))
    render(<SitePage />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(SITE.hero.title)
    expect(await screen.findByRole('heading', { level: 1, name: 'Published title' })).toBeTruthy()
    expect(screen.getByText('Published lead')).toBeTruthy()
    expect(screen.getAllByText('040 0000 0000').length).toBeGreaterThan(0)
    expect(screen.getByText(SITE.steps[0].d)).toBeTruthy()           // a section not sent keeps the built-in copy
  })

  it('shows the sections in the published order, and leaves a hidden one (and its menu link) off the page', async () => {
    const layout = SITE.layout.filter((s) => s.id !== 'about').map((s) => ({ ...s, shown: s.id !== 'careers' }))
    layout.splice(1, 0, { id: 'about', shown: true })
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...live, content: { layout } }) })))
    const { container } = render(<SitePage />)
    await waitFor(() => expect(container.querySelector('#careers')).toBeNull())
    const order = [...container.querySelectorAll('main > section')].map((s) => s.id).filter(Boolean)
    expect(order.slice(0, 2)).toEqual(['top', 'about'])
    expect(within(screen.getByRole('navigation', { name: 'Primary' })).queryByRole('link', { name: 'Careers' })).toBeNull()
  })

  it('lists the open openings, each applying through its own form, and asks for a CV when there are none', async () => {
    const openings = [{ id: 4, title: 'Site Engineer (Civil)', location: 'Ongole', experience: '3-5 years', description: 'Runs a block.', apply_token: 'tok-4' }]
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...live, openings }) })))
    render(<SitePage />)
    const list = await screen.findByRole('list', { name: 'Openings' })
    expect(within(list).getByText('Ongole · 3-5 years experience')).toBeTruthy()
    expect(within(list).getByRole('link', { name: 'Apply for Site Engineer (Civil)' }).getAttribute('href')).toBe('/apply?token=tok-4')
  })

  it('shows only the credentials with a real value - never one "on request"', async () => {
    const credentials = [{ label: 'GSTIN', value: '36ABCDE1234F1Z5' }, { label: 'ISO certification', value: 'Certificates on request' }, { label: 'RERA registration', value: '' }]
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...live, content: { credentials } }) })))
    const { container } = render(<SitePage />)
    expect(await screen.findByText('36ABCDE1234F1Z5')).toBeTruthy()
    const creds = container.querySelector('#credentials') as HTMLElement
    expect(within(creds).queryByText('ISO certification')).toBeNull()
    expect(within(creds).queryByText('RERA registration')).toBeNull()
    expect(creds.textContent).not.toMatch(/on request/i)
  })

  it('leaves Credentials off the page while none has a value', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...live, content: { credentials: [{ label: 'GSTIN', value: '' }] } }) })))
    const { container } = render(<SitePage />)
    // The built-in list already has a value (the safety record); the published one, with none, takes the section away.
    expect(container.querySelector('#credentials')).not.toBeNull()
    await waitFor(() => expect(container.querySelector('#credentials')).toBeNull())
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
