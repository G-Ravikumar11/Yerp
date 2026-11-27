import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SitePage from './SitePage'
import { COMPANY, SITE } from './data/content'

// jsdom has no IntersectionObserver or matchMedia; the page only uses them for its fade-ins, the menu and the theme.
beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }))
  document.documentElement.removeAttribute('data-theme')
})
// The page is taken down while the stand-ins are still there: its counters start watching a moment after the data arrives, and on a
// slow runner that was after the stand-ins had gone ("IntersectionObserver is not defined").
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const live = { company_id: 7, numbers: { projects_delivered: 12, ongoing_sites: 3, safe_man_hours: 0 }, projects: [], openings: [] }
/** The server: the live figures (with `extra` mixed in), the enquiry's thanks, and "not an editor" for the edit bar. */
const stubFetch = (extra: Record<string, unknown> = {}) => {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (url.endsWith('/site') ? { ...live, ...extra } : url.endsWith('/editor') ? { can_edit: false } : { message: 'Thank you, Ravi.' }),
  }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('Company front page (Look B)', () => {
  it('reads as the civil company, with no electrical contractor or ERP wording, and nothing marked sample', async () => {
    stubFetch()
    render(<SitePage />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(`${SITE.hero.title} ${SITE.hero.accent}`)
    // Waited for longer than usual: with the whole suite running, the page's first draw can take more than a second.
    expect(await screen.findByText('Sites running now', {}, { timeout: 4000 })).toBeTruthy()
    const text = document.body.textContent ?? ''
    for (const word of [/electrical contractor/i, /33\s*kV/i, /\bpanels?\b/i, /Y\s*-?\s*ERP/i, /\bERP\b/i, /terms of service/i, /privacy/i,
      /\bsample\b/i, /owner to fill/i, /\bTBC\b/, /on request/i]) expect(text).not.toMatch(word)
    const html = document.body.innerHTML
    for (const word of [/33\s*kV/i, /ERP/, /\by\s*-?\s*erp\b/i, /\bterms\b/i, /privacy/i]) expect(html).not.toMatch(word)
    expect(document.title).toMatch(/^Yalavarti Infra Projects/)
  })

  it('draws the sections as drawing titles, numbered in the order shown', async () => {
    stubFetch()
    const { container } = render(<SitePage />)
    await screen.findByText('Sites running now', {}, { timeout: 4000 })
    const titles = [...container.querySelectorAll('.dtitle')].map((d) => [d.querySelector('.no span')?.textContent, d.querySelector('h2')?.textContent])
    expect(titles.slice(0, 3)).toEqual([['01', SITE.headings.about.title], ['02', SITE.headings.projects.title], ['03', SITE.headings.build.title]])
    expect(container.querySelector('#story')).toBeNull()                                     // no milestones yet
  })

  it('shows only figures we have - the live count when it is the larger - in the title block', async () => {
    stubFetch({ numbers: { projects_delivered: 0, ongoing_sites: 12, safe_man_hours: 0 } })
    render(<SitePage />)
    const block = await screen.findByRole('list', { name: 'At a glance' }).catch(() => screen.findByLabelText('At a glance'))
    await waitFor(() => expect(within(block as HTMLElement).getByText('12')).toBeTruthy())
    expect(within(block as HTMLElement).getByText('Live from site records')).toBeTruthy()
    expect(within(block as HTMLElement).queryByText('Years building')).toBeNull()          // founded is not set
  })

  it('signs staff in from one quiet footer link only, with no Terms or Privacy link', async () => {
    stubFetch()
    render(<SitePage />)
    await screen.findByText('Sites running now', {}, { timeout: 4000 })
    expect(within(screen.getByRole('banner')).queryByText(/login|sign in/i)).toBeNull()
    const links = screen.getAllByRole('link') as HTMLAnchorElement[]
    const staff = links.filter((a) => /login|sign.?in|staff/i.test(a.textContent + ' ' + a.getAttribute('href')))
    expect(staff.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([['Staff login', '/login']])
    expect(within(screen.getByRole('contentinfo')).getByRole('link', { name: 'Staff login' })).toBe(staff[0])
    expect(links.filter((a) => /terms|privacy/i.test(a.textContent + ' ' + a.getAttribute('href')))).toEqual([])
  })

  it('shows the words as last published, and its own copy until they arrive', async () => {
    const hero = { ...SITE.hero, title: 'Published title', accent: '' }
    stubFetch({ content: { hero, company: { ...COMPANY, phone: { show: '040 0000 0000', tel: '+914000000000' } } } })
    render(<SitePage />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(`${SITE.hero.title} ${SITE.hero.accent}`)
    expect(await screen.findByRole('heading', { level: 1, name: 'Published title' })).toBeTruthy()
    expect(screen.getAllByText('040 0000 0000').length).toBeGreaterThan(0)
    expect(screen.getByText(SITE.steps[0].d)).toBeTruthy()                                   // a section not sent keeps the built-in copy
  })

  it('shows the sections in the published order, and leaves a hidden one (and its menu link) off the page', async () => {
    const layout = SITE.layout.map((s) => ({ ...s, shown: s.id !== 'careers' }))
    stubFetch({ content: { layout: [layout[0], layout.find((s) => s.id === 'build')!, ...layout.filter((s) => s.id !== 'hero' && s.id !== 'build')] } })
    const { container } = render(<SitePage />)
    await waitFor(() => expect(container.querySelector('#careers')).toBeNull())
    const order = [...container.querySelectorAll('main > section')].map((s) => s.id).filter(Boolean)
    expect(order.slice(0, 2)).toEqual(['top', 'build'])
    expect(within(screen.getByRole('navigation', { name: 'Primary' })).queryByRole('link', { name: 'Careers' })).toBeNull()
  })

  it('lists the open openings, each applying through its own form, with a row for a CV', async () => {
    stubFetch({ openings: [{ id: 4, title: 'Site Engineer (Civil)', location: 'Ongole', experience: '3-5 years', description: 'Runs a block.', apply_token: 'tok-4' }] })
    render(<SitePage />)
    const list = await screen.findByRole('list', { name: 'Openings' })
    await waitFor(() => expect(within(list).getByText('Ongole · 3-5 years experience')).toBeTruthy())
    expect(within(list).getByRole('link', { name: 'Apply for Site Engineer (Civil)' }).getAttribute('href')).toBe('/apply?token=tok-4')
    expect(within(list).getByText('Not listed?')).toBeTruthy()
  })

  it('opens the enquiry from a "What we build" tile with its kind of work chosen, and sends it to the Tender Pipeline', async () => {
    const fetch = stubFetch()
    render(<SitePage />)
    await userEvent.click(screen.getAllByRole('link', { name: 'Enquire about this →' })[0])         // Gated townships & layouts
    expect(screen.getByRole('button', { name: 'Township or layout' }).getAttribute('aria-pressed')).toBe('true')
    await userEvent.type(screen.getByLabelText('Your name'), 'Ravi')
    await userEvent.type(screen.getByLabelText('Phone'), '9800000000')
    await userEvent.type(screen.getByLabelText('Site location'), 'Shadnagar')
    await userEvent.click(screen.getByRole('button', { name: /Send enquiry/ }))
    expect(await screen.findByText('Thank you, Ravi.')).toBeTruthy()
    const [url, init] = fetch.mock.calls.find(([u]) => String(u).endsWith('/enquiry')) as unknown as [string, RequestInit]
    expect(url).toBe('/api/public/enquiry')
    expect(JSON.parse(String(init.body))).toMatchObject({ name: 'Ravi', city: 'Shadnagar', project_type: 'Township or layout' })
  })

  it('switches between paper and blueprint, and remembers it', async () => {
    stubFetch()
    render(<SitePage />)
    await userEvent.click(screen.getByRole('button', { name: /blueprint \(dark\)/i }))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('yip-theme')).toBe('dark')
    expect(screen.getByRole('button', { name: /paper \(light\)/i })).toBeTruthy()
  })

  it('shows the WhatsApp button only once a number is set, and the edit bar only to an editor', async () => {
    const fetch = vi.fn(async (url: string) => ({
      ok: true,
      json: async () => (url.endsWith('/site') ? { ...live, content: { company: { ...COMPANY, whatsapp: '+91 98480 12345' } } } : url.endsWith('/editor') ? { can_edit: true, last_published: '2026-11-20 10:00:00' } : {}),
    }))
    vi.stubGlobal('fetch', fetch)
    render(<SitePage />)
    expect((await screen.findByRole('link', { name: 'WhatsApp us' })).getAttribute('href')).toBe('https://wa.me/919848012345')
    const bar = await screen.findByRole('region', { name: 'Edit the website' })
    expect(within(bar).getByRole('link', { name: 'Edit website' }).getAttribute('href')).toBe('/website')
    expect(bar.textContent).toMatch(/last published 20 Nov/)
  })
})
