import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({
  me: 'staff:ravi@site.test',
  files: new Map<string, unknown>(),
  api: vi.fn(),
  sendFile: vi.fn(),
  attachBillPhoto: vi.fn(),
}))

vi.mock('idb-keyval', () => ({
  createStore: () => undefined,
  get: async (k: string) => h.files.get(k),
  set: async (k: string, v: unknown) => void h.files.set(k, v),
  del: async (k: string) => void h.files.delete(k),
}))
vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), api: h.api }))
vi.mock('@/lib/query', () => ({ queryClient: { invalidateQueries: vi.fn(async () => undefined) } }))
vi.mock('@/lib/session', () => ({ personKey: () => h.me, personName: () => 'Ravi' }))
vi.mock('@/api/files', () => ({ sendFile: h.sendFile }))
vi.mock('@/api/sitecash', () => ({ attachBillPhoto: h.attachBillPhoto }))

import { ApiError } from '@/lib/api'
import { CONFLICT_TEXT, isMine, sendOrQueue, useOffline } from './offline'

// jsdom has no IndexedDB, so the store would keep files nowhere; the mock above stands in for it either way.
Object.defineProperty(globalThis, 'indexedDB', { value: {}, configurable: true })

const waiting = () => useOffline.getState().queue.map((q) => `${q.id}:${q.status}`)
const photo = (name = 'bill.jpg') => new File(['x'], name, { type: 'image/jpeg' })

beforeEach(() => {
  h.me = 'staff:ravi@site.test'
  h.files.clear()
  h.api.mockReset()
  h.sendFile.mockReset()
  h.attachBillPhoto.mockReset()
  useOffline.setState({ online: true, syncing: false, queue: [] })
})

function put(partial: Partial<import('./offline').QueuedRequest> & { id: string }) {
  useOffline.setState((s) => ({ queue: [...s.queue, { kind: 'request', method: 'POST', url: '/api/x', label: partial.id, createdAt: 1, status: 'waiting', ...partial }] }))
}

describe('whose change it is', () => {
  it('sends only the signed-in person\'s changes and leaves everybody else\'s where they are', async () => {
    put({ id: 'a1', by: 'staff:asha@site.test' })
    put({ id: 'r1', by: 'staff:ravi@site.test' })
    h.api.mockResolvedValue({})
    await useOffline.getState().flush()
    expect(h.api).toHaveBeenCalledTimes(1)
    expect(h.api.mock.calls[0][0]).toBe('/api/x')
    expect(waiting()).toEqual(['a1:waiting'])
  })

  it('sends them when their person signs in again', async () => {
    put({ id: 'a1', by: 'staff:asha@site.test' })
    h.api.mockResolvedValue({})
    await useOffline.getState().flush()
    expect(h.api).not.toHaveBeenCalled()
    h.me = 'staff:asha@site.test'
    await useOffline.getState().flush()
    expect(h.api).toHaveBeenCalledTimes(1)
    expect(waiting()).toEqual([])
  })

  it('sends nothing while nobody is signed in', async () => {
    h.me = ''
    put({ id: 'r1', by: 'staff:ravi@site.test' })
    await useOffline.getState().flush()
    expect(h.api).not.toHaveBeenCalled()
  })

  it('treats a change from before people were recorded as the current person\'s', () => {
    expect(isMine({ id: 'old' } as never, 'staff:anyone@site.test')).toBe(true)
    expect(isMine({ id: 'n', by: 'staff:asha@site.test' } as never, 'staff:ravi@site.test')).toBe(false)
  })

  it('does not hold a change that goes straight through to a version check: only one that was kept is', async () => {
    h.api.mockResolvedValue({ diary: { id: 1 } })
    await sendOrQueue({ method: 'PUT', url: '/api/diary/1', body: {}, label: 'Site diary' }, { base: '2026-11-01 09:00:00' })
    expect((h.api.mock.calls[0][1].headers as Record<string, string>)['X-Base-Version']).toBeUndefined()

    useOffline.setState({ online: false })
    await sendOrQueue({ method: 'PUT', url: '/api/diary/1', body: {}, label: 'Site diary' }, { base: '2026-11-01 09:00:00' })
    useOffline.setState({ online: true })
    await useOffline.getState().flush()
    expect((h.api.mock.calls[1][1].headers as Record<string, string>)['X-Base-Version']).toBe('2026-11-01 09:00:00')
  })

  it('records who made a change when it is kept', async () => {
    useOffline.setState({ online: false })
    await sendOrQueue({ method: 'POST', url: '/api/diary', body: {}, label: 'Site diary' })
    expect(useOffline.getState().queue[0]).toMatchObject({ by: 'staff:ravi@site.test', byName: 'Ravi', status: 'waiting' })
  })
})

describe('pictures that wait with a change', () => {
  it('keeps them with a change made offline, and sends each to the record once it exists', async () => {
    useOffline.setState({ online: false })
    const sent = await sendOrQueue({ method: 'POST', url: '/api/diary', body: { day: 1 }, label: 'Site diary' }, { files: { items: [photo('a.jpg'), photo('b.jpg')], via: 'attached', type: 'diary', idFrom: 'diary.id' } })
    expect(sent).toEqual({ queued: true })
    expect(h.files.size).toBe(2)

    useOffline.setState({ online: true })
    h.api.mockResolvedValue({ diary: { id: 77 } })
    h.sendFile.mockResolvedValue(undefined)
    await useOffline.getState().flush()
    expect(h.sendFile).toHaveBeenCalledTimes(2)
    expect(h.sendFile.mock.calls.map((c) => [c[1], c[2]])).toEqual([['diary', 77], ['diary', 77]])
    expect(waiting()).toEqual([])
    expect(h.files.size).toBe(0)
  })

  it('attaches a bill to the expense it was entered with', async () => {
    useOffline.setState({ online: false })
    await sendOrQueue({ method: 'POST', url: '/api/site-cash/expenses', body: {}, label: 'Site cash' }, { files: { items: [photo()], via: 'bill', idFrom: 'expense.id' } })
    useOffline.setState({ online: true })
    h.api.mockResolvedValue({ expense: { id: 5 } })
    await useOffline.getState().flush()
    expect(h.attachBillPhoto.mock.calls[0][0]).toBe(5)
    expect(waiting()).toEqual([])
  })

  it('keeps a photo the server refused, marked, and does not let it hold up the next change', async () => {
    useOffline.setState({ online: false })
    await sendOrQueue({ method: 'POST', url: '/api/diary', body: {}, label: 'Site diary' }, { files: { items: [photo()], via: 'attached', type: 'diary', idFrom: 'diary.id' } })
    put({ id: 'later', by: 'staff:ravi@site.test' })
    useOffline.setState({ online: true })
    h.api.mockResolvedValue({ diary: { id: 9 } })
    h.sendFile.mockRejectedValue(new ApiError(413, 'That file is too large.'))
    await useOffline.getState().flush()
    const rest = useOffline.getState().queue
    expect(rest.find((q) => q.kind === 'upload')).toMatchObject({ status: 'failed', error: 'That file is too large.' })
    expect(rest.find((q) => q.id === 'later')).toBeUndefined()      // it went
    expect(h.files.size).toBe(1)                                    // the picture is still there to retry
  })

  it('stops, goes offline and keeps everything when the signal goes during a picture', async () => {
    useOffline.setState({ online: false })
    await sendOrQueue({ method: 'POST', url: '/api/diary', body: {}, label: 'Site diary' }, { files: { items: [photo()], via: 'attached', type: 'diary', idFrom: 'diary.id' } })
    put({ id: 'later', by: 'staff:ravi@site.test' })
    useOffline.setState({ online: true })
    h.api.mockResolvedValueOnce({ diary: { id: 9 } }).mockResolvedValue({})
    h.sendFile.mockRejectedValue(new TypeError('Failed to fetch'))
    await useOffline.getState().flush()
    expect(useOffline.getState().online).toBe(false)
    // The day and the later change went; the one picture is still waiting, with its file, for the signal to come back.
    expect(useOffline.getState().queue.map((q) => [q.kind, q.status])).toEqual([['upload', 'waiting']])
    expect(h.files.size).toBe(1)
  })

  it('removing a change also removes the pictures kept for it', async () => {
    useOffline.setState({ online: false })
    await sendOrQueue({ method: 'POST', url: '/api/diary', body: {}, label: 'Site diary' }, { files: { items: [photo()], via: 'attached', type: 'diary', idFrom: 'diary.id' } })
    useOffline.getState().discard(useOffline.getState().queue[0].id)
    await Promise.resolve()
    expect(h.files.size).toBe(0)
  })
})

describe('somebody else changed it meanwhile', () => {
  const edit = { id: 'e1', method: 'PUT' as const, url: '/api/diary/3', base: '2026-11-01 09:00:00', by: 'staff:ravi@site.test' }

  it('holds the edit for a choice instead of letting the last save win, and carries on with the rest', async () => {
    put(edit)
    put({ id: 'next', by: 'staff:ravi@site.test' })
    h.api.mockRejectedValueOnce(new ApiError(409, `The diary ${CONFLICT_TEXT} while you were away from signal.`)).mockResolvedValue({})
    await useOffline.getState().flush()
    expect(h.api.mock.calls[0][2]?.headers ?? h.api.mock.calls[0][1].headers).toMatchObject({ 'X-Base-Version': '2026-11-01 09:00:00' })
    expect(waiting()).toEqual(['e1:conflict'])
  })

  it('"keep mine" sends it again without the old version, so it replaces what is there', async () => {
    put({ ...edit, status: 'conflict' })
    h.api.mockResolvedValue({})
    useOffline.getState().keepMine('e1')
    await vi.waitFor(() => expect(h.api).toHaveBeenCalled())
    const headers = h.api.mock.calls[0][1].headers as Record<string, string>
    expect(headers['X-Base-Version']).toBeUndefined()
    await vi.waitFor(() => expect(waiting()).toEqual([]))
  })

  it('"take theirs" is removing the edit', () => {
    put({ ...edit, status: 'conflict' })
    useOffline.getState().discard('e1')
    expect(waiting()).toEqual([])
  })

  it('does not take any other refusal for a conflict', async () => {
    put(edit)
    h.api.mockRejectedValue(new ApiError(409, 'This day has been signed off.'))
    await useOffline.getState().flush()
    expect(waiting()).toEqual(['e1:failed'])
  })
})
