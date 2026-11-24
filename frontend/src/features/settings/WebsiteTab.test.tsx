import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BUILT_IN } from '@/features/site/siteContent'

// The server: every section as the site was built, with what is published and the draft the same until a test changes it.
const first: Record<string, unknown> = { company: BUILT_IN.COMPANY, ...BUILT_IN.SITE, projects: {} }
let drafts: Record<string, unknown>
let openings: { id: number; title: string; on_website: boolean; status: string; applications: number }[] = []
let published: Record<string, unknown>
const calls: { method: string; url: string; body?: unknown }[] = []
const versions = [{ id: 9, number: 2, note: '', published_at: '2026-11-24 10:00:00', published_by: 'Master' }, { id: 8, number: 1, note: '', published_at: '2026-11-20 10:00:00', published_by: 'Master' }]

vi.mock('@/lib/api', async (orig) => {
  const real = await orig<typeof import('@/lib/api')>()
  const answer = async (method: string, url: string, body?: unknown) => {
    calls.push({ method, url, body })
    if (url === '/api/website/sections') {
      return { sections: Object.keys(first).map((key) => ({ key, label: key, draft: drafts[key], published: published[key], unpublished_changes: JSON.stringify(drafts[key]) !== JSON.stringify(published[key]) })), latest: versions[0] }
    }
    if (url === '/api/website/versions') return { versions }
    if (url === '/api/website/projects') return { projects: [], most_photos: 6 }
    if (url === '/api/website/images') return { images: [] }
    const m = url.match(/^\/api\/website\/sections\/(\w+)$/)
    if (m && method === 'PUT') { drafts[m[1]] = (body as { draft: unknown }).draft; return { message: 'Draft saved.' } }
    if (url === '/api/website/publish') { published = { ...drafts }; return { message: 'Published. The website now shows version 3.', version: 3 } }
    if (url === '/api/website/careers' && method === 'GET') return { openings }
    if (url === '/api/website/careers' && method === 'POST') { openings.unshift({ id: 7, reference: 'JOB-0007', status: 'open', on_website: true, opened_at: '', closed_at: '', applications: 0, ...(body as object) } as never); return { message: 'Posted.' } }
    if (/\/api\/website\/careers\/\d+\/close$/.test(url)) { openings[0].on_website = false; openings[0].status = 'closed'; return { message: 'Closed.' } }
    if (url.endsWith('/restore')) return { message: 'Restored version 1. The website now shows version 3.', version: 3 }
    return {}
  }
  return {
    ...real,
    get: vi.fn((url: string) => answer('GET', url)),
    put: vi.fn((url: string, body?: unknown) => answer('PUT', url, body)),
    post: vi.fn((url: string, body?: unknown) => answer('POST', url, body)),
    del: vi.fn((url: string) => answer('DELETE', url)),
  }
})

import WebsiteTab from './WebsiteTab'

const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><WebsiteTab /></QueryClientProvider>)
const part = async (name: string) => userEvent.click(within(await screen.findByRole('navigation', { name: 'Parts of the website' })).getByRole('button', { name: new RegExp('^' + name) }))

beforeEach(() => {
  drafts = structuredClone(first)
  published = structuredClone(first)
  calls.length = 0
  openings = []
  window.history.replaceState(null, '', '/settings?tab=website')
})

describe('Settings -> Website', () => {
  it('edits the opening banner as a draft, and sends nothing until it is saved', async () => {
    mount()
    const headline = await screen.findByLabelText('Headline')
    expect((headline as HTMLTextAreaElement).value).toBe(BUILT_IN.SITE.hero.title)
    await userEvent.clear(headline)
    await userEvent.type(headline, 'Homes that last')
    expect(screen.getByText('Changes not saved yet')).toBeTruthy()
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: /Save draft/ }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.url).toBe('/api/website/sections/hero'))
    expect((calls.find((c) => c.method === 'PUT')!.body as { draft: { title: string } }).draft.title).toBe('Homes that last')
    expect(await screen.findByText(/Draft ready: 1 section changed/)).toBeTruthy()
  })

  it('publishes the draft, saving what is typed first, with a note for the history', async () => {
    mount()
    await part('Footer')
    const tagline = screen.getByLabelText('Line after the company name')
    await userEvent.clear(tagline)
    await userEvent.type(tagline, 'Civil works since 2012')
    await userEvent.click(screen.getByRole('button', { name: /^Publish$/ }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByRole('textbox'), 'New footer')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Publish' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/website/publish')).toBe(true))
    const order = calls.filter((c) => c.method !== 'GET').map((c) => c.url)
    expect(order).toEqual(['/api/website/sections/footer', '/api/website/publish'])
    expect(calls.find((c) => c.url === '/api/website/publish')!.body).toEqual({ note: 'New footer' })
    expect(published.footer).toEqual({ tagline: 'Civil works since 2012', showGroupLink: true })
  })

  it('hides and reorders the sections of the page', async () => {
    mount()
    await part('Page layout')
    const list = screen.getByRole('list', { name: 'Sections of the page' })
    await userEvent.click(within(list).getByRole('checkbox', { name: 'Careers' }))
    await userEvent.click(within(list).getByRole('button', { name: 'Move About up' }))
    await userEvent.click(screen.getByRole('button', { name: /Save draft/ }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/website/sections/layout')).toBe(true))
    const layout = drafts.layout as { id: string; shown: boolean }[]
    expect(layout.slice(0, 3).map((s) => s.id)).toEqual(['hero', 'about', 'proof'])
    expect(layout.find((s) => s.id === 'careers')!.shown).toBe(false)
  })

  it('adds, edits and removes the items of a list', async () => {
    mount()
    await part('How we build')
    const n = BUILT_IN.SITE.steps.length
    await userEvent.click(screen.getByRole('button', { name: /Add stage/ }))
    const added = screen.getAllByLabelText('Stage').at(-1)!
    await userEvent.type(added, 'Maintenance')
    await userEvent.click(screen.getByRole('button', { name: `Remove ${BUILT_IN.SITE.steps[0].t}` }))
    await userEvent.click(screen.getByRole('button', { name: /Save draft/ }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/website/sections/steps')).toBe(true))
    const steps = drafts.steps as { t: string }[]
    expect(steps).toHaveLength(n)
    expect(steps[0].t).toBe(BUILT_IN.SITE.steps[1].t)
    expect(steps.at(-1)!.t).toBe('Maintenance')
  })

  it('lists every published version and puts an earlier one back', async () => {
    mount()
    await part('History')
    expect(await screen.findByText('On the website now')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: /Restore this version/ }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Restore this version' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/website/versions/8/restore')).toBe(true))
  })

  it('shows the draft in a desktop and a phone preview of the site itself, as it is typed', { timeout: 20000 }, async () => {
    mount()
    // Waited for longer than usual: with the whole suite running, the panel's first draw can take more than a second.
    const desk = (await screen.findByTitle('Preview of the draft on a desktop screen', {}, { timeout: 5000 })) as HTMLIFrameElement
    const phone = screen.getByTitle('Preview of the draft on a phone') as HTMLIFrameElement
    expect(desk.getAttribute('src')).toMatch(/\?preview=1$/)
    expect(phone.getAttribute('src')).toBe(desk.getAttribute('src'))
    const sent = vi.fn()
    Object.defineProperty(desk, 'contentWindow', { value: { postMessage: sent } })
    await userEvent.type(await screen.findByLabelText('Line under the headline', {}, { timeout: 5000 }), '!')
    await waitFor(() => expect(sent).toHaveBeenCalled(), { timeout: 5000 })
    const [message, origin] = sent.mock.calls.at(-1)!
    expect(origin).toBe(location.origin)
    expect(message.type).toBe('website-preview')
    expect(message.content.hero.sub).toBe(BUILT_IN.SITE.hero.sub + '!')
    expect(message.content.projects).toBeUndefined()                  // the project cards are not the site's to read
  })

  it('posts an opening for the Careers section and closes it again', async () => {
    mount()
    await part('Careers')
    await userEvent.click(await screen.findByRole('button', { name: /Post an opening/ }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Title'), 'Site Engineer')
    await userEvent.type(within(dialog).getByLabelText('Site or location'), 'Ongole')
    await userEvent.type(within(dialog).getByLabelText('Experience'), '3-5 years')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Post on the website' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'POST' && c.url === '/api/website/careers')?.body).toEqual({ title: 'Site Engineer', location: 'Ongole', experience: '3-5 years', description: '' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Close Site Engineer' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Close the opening' }))
    await waitFor(() => expect(calls.some((c) => c.url === '/api/website/careers/7/close')).toBe(true))
  })
})
