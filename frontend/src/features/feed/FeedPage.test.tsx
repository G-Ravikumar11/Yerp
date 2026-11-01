import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FEED_SEEN, type Announcement } from '@/api/feed'

vi.setConfig({ testTimeout: 20_000 })

const calls: { method: string; url: string; body?: unknown }[] = []
let canPost = true

const ann = (over: Partial<Announcement>): Announcement => ({
  id: 1, title: 'Site closed on Saturday', body: 'Heavy rain.\nBack on Monday.', category: 'site', pinned: false, expires_on: '', expired: false,
  posted_by: 'Priya Nair', created_at: '2026-10-30 10:00:00', updated_at: '', can_edit: canPost, media: [], ...over,
})
const celebrations = {
  today: [{ key: 'birthday:7:2026', kind: 'birthday', date: '2026-10-31', title: 'Meena Iyer\'s birthday', emoji: '🎂', message: '', job_title: 'Planning Engineer', reactions: [], wishes: [] }],
  upcoming: [{ key: 'festival:2026-11-08', kind: 'festival', date: '2026-11-08', title: 'Diwali', emoji: '🪔', message: '', days_away: 8 }],
  emojis: ['🎉', '👏'], can_manage: false,
}

vi.mock('@/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/lib/api')>()),
  get: vi.fn(async (url: string) => {
    if (url === '/api/celebrations') return celebrations
    return { announcements: [ann({ id: 2, title: 'Pay day moved', body: 'Salaries on the 3rd.', category: 'important', pinned: true }), ann({ media: [{ id: 5, kind: 'image', name: 'trench.jpg', content_type: 'image/jpeg', size: 10, url: '/api/announcements/media/5' }, { id: 6, kind: 'video', name: 'walk.mp4', content_type: 'video/mp4', size: 10, url: '/api/announcements/media/6' }] })], can_post: canPost, categories: ['general', 'site', 'holiday', 'important'] }
  }),
  post: vi.fn(async (url: string, body: unknown) => {
    calls.push({ method: 'POST', url, body: body instanceof FormData ? { file: (body.get('file') as File).name } : body })
    return url.endsWith('/media') ? { id: 9, kind: 'image', name: 'x', content_type: 'image/png', size: 1, url: '/m/9' } : { id: 77, message: 'ok', told: 12 }
  }),
  put: vi.fn(async (url: string, body: unknown) => { calls.push({ method: 'PUT', url, body }); return { message: 'ok' } }),
  del: vi.fn(async (url: string) => { calls.push({ method: 'DELETE', url }); return { message: 'ok' } }),
}))

import FeedPage from './FeedPage'
import { FeedFirst } from './FeedFirst'

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><MemoryRouter><FeedPage /></MemoryRouter></QueryClientProvider>)
}

beforeEach(() => { calls.length = 0; canPost = true; sessionStorage.clear() })

describe('The Feed', () => {
  it('opens on the announcements, with what each one is', async () => {
    mount()
    const pinned = (await screen.findByText('Pay day moved')).closest('article')!
    expect(within(pinned).getByText('Important')).toBeTruthy()
    expect(within(pinned).getByText('Pinned')).toBeTruthy()
    const site = screen.getByText('Site closed on Saturday').closest('article')!
    expect(within(site).getByText('Site')).toBeTruthy()
    expect(site.textContent).toContain('Priya Nair')
    expect(screen.getByText(/Heavy rain\./)).toBeTruthy()
    expect(screen.queryByText('Diwali')).toBeNull()                       // the celebrations are their own tab
  })

  it('keeps the celebrations on a tab of their own, with their reactions and what is coming', async () => {
    const user = userEvent.setup()
    mount()
    await screen.findByText('Pay day moved')
    await user.click(screen.getByRole('tab', { name: /celebrations/i }))
    expect(screen.getByText("Meena Iyer's birthday")).toBeTruthy()
    expect(screen.getByRole('button', { name: 'React with 🎉' })).toBeTruthy()
    expect(screen.getByText('Diwali')).toBeTruthy()
    expect(screen.queryByText('Pay day moved')).toBeNull()
    expect(screen.queryByRole('button', { name: /post an announcement/i })).toBeNull()   // posting belongs to the announcements
    await user.click(screen.getByRole('tab', { name: /announcements/i }))
    expect(screen.getByText('Pay day moved')).toBeTruthy()
  })

  it('summarises the Feed at the top', async () => {
    mount()
    await screen.findByText('Pay day moved')
    for (const label of ['Announcements', 'Pinned', 'Celebrating today', 'Coming up in 30 days']) expect(screen.getAllByText(label).length).toBeGreaterThan(0)
  })

  it('lets HR post, and nobody else', async () => {
    mount()
    expect(await screen.findByRole('button', { name: /post an announcement/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Edit Pay day moved' })).toBeTruthy()
  })

  it('gives everybody else the Feed to read and nothing to change', async () => {
    canPost = false
    mount()
    await screen.findByText('Pay day moved')
    expect(screen.queryByRole('button', { name: /post an announcement/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Edit / })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Remove Pay day/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Pin / })).toBeNull()
  })

  it('posts what was written, and will not post without a title', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: /post an announcement/i }))
    const post = screen.getByRole('button', { name: /^Post$/ })
    expect((post as HTMLButtonElement).disabled).toBe(true)
    await user.type(screen.getByLabelText('Title'), 'Diwali holidays')
    await user.type(screen.getByLabelText('Message'), 'Office closed 8 to 10 November.')
    await user.selectOptions(screen.getByLabelText('Kind'), 'holiday')
    await user.click(screen.getByLabelText(/keep at the top/i))
    await user.click(post)
    await waitFor(() => expect(calls).toEqual([{ method: 'POST', url: '/api/announcements', body: {
      title: 'Diwali holidays', body: 'Office closed 8 to 10 November.', category: 'holiday', pinned: true, expires_on: '', notify: true } }]))
  })

  it('shows the photos and videos on a post', async () => {
    mount()
    const site = (await screen.findByText('Site closed on Saturday')).closest('article')!
    expect(within(site).getByAltText('trench.jpg').getAttribute('src')).toBe('/api/announcements/media/5')
    expect(site.querySelector('video')?.getAttribute('src')).toBe('/api/announcements/media/6')
  })

  it('posts with a photo and a video, and refuses what is too big or not a picture', async () => {
    const user = userEvent.setup({ applyAccept: false })
    mount()
    await user.click(await screen.findByRole('button', { name: /post an announcement/i }))
    await user.type(screen.getByLabelText('Title'), 'Site visit')
    const pick = screen.getByLabelText('Add photos or videos')
    await user.upload(pick, new File(['x'], 'notes.txt', { type: 'text/plain' }))
    expect((await screen.findByRole('alert')).textContent).toContain('notes.txt')
    await user.upload(pick, [new File(['x'], 'a.png', { type: 'image/png' }), new File(['y'], 'b.mp4', { type: 'video/mp4' })])
    await user.click(screen.getByRole('button', { name: /^Post$/ }))
    await waitFor(() => expect(calls.map((c) => c.url)).toEqual(['/api/announcements', '/api/announcements/77/media', '/api/announcements/77/media']))
    expect(calls.slice(1).map((c) => c.body)).toEqual([{ file: 'a.png' }, { file: 'b.mp4' }])
  })

  it('asks before taking one down', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Remove Pay day moved' }))
    expect(calls).toEqual([])
    await user.click(screen.getByRole('button', { name: 'Remove it' }))
    await waitFor(() => expect(calls).toEqual([{ method: 'DELETE', url: '/api/announcements/2' }]))
  })

  it('pins and unpins', async () => {
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Unpin Pay day moved' }))
    await waitFor(() => expect(calls).toEqual([{ method: 'POST', url: '/api/announcements/2/pin', body: { pinned: false } }]))
  })

  it('marks itself seen for the session', async () => {
    mount()
    await screen.findByText('Pay day moved')
    expect(sessionStorage.getItem(FEED_SEEN)).toBe('1')
  })
})

describe('Opening the app', () => {
  const landing = () => render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<FeedFirst Home={() => <p>The front page</p>} />} />
        <Route path="/feed" element={<p>The Feed</p>} />
      </Routes>
    </MemoryRouter>)

  it('goes to the Feed the first time in a session', () => {
    landing()
    expect(screen.getByText('The Feed')).toBeTruthy()
  })

  it('shows the front page once the Feed has been seen', () => {
    sessionStorage.setItem(FEED_SEEN, '1')
    landing()
    expect(screen.getByText('The front page')).toBeTruthy()
  })
})
