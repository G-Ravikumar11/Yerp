import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FADE_MS, toast, useToasts } from './toast'

beforeEach(() => { vi.useFakeTimers(); useToasts.setState({ toasts: [] }) })
afterEach(() => { vi.useRealTimers() })

const shown = () => useToasts.getState().toasts.map((t) => t.message)

describe('notifications', () => {
  it('a success says so and then goes by itself', () => {
    toast.success('Saved')
    expect(shown()).toEqual(['Saved'])
    vi.advanceTimersByTime(FADE_MS - 1)
    expect(shown()).toEqual(['Saved'])
    vi.advanceTimersByTime(1)
    expect(shown()).toEqual([])
  })

  it('a failure, a warning and a notification stay until they are closed, however long that is', () => {
    toast.error('Could not save')
    toast.info('Two lines are not on the BOQ')
    toast.withAction('New approval waiting', 'Open', () => undefined)
    vi.advanceTimersByTime(10 * 60_000)                       // ten minutes
    expect(shown()).toEqual(['Could not save', 'Two lines are not on the BOQ', 'New approval waiting'])
  })

  it('a passing note goes by itself like a success', () => {
    toast.brief('Getting the file...')
    vi.advanceTimersByTime(FADE_MS)
    expect(shown()).toEqual([])
  })

  it('a success being read does not go until it is let go of', () => {
    toast.success('Saved')
    const [t] = useToasts.getState().toasts
    useToasts.getState().hold(t.id)
    vi.advanceTimersByTime(60_000)
    expect(shown()).toEqual(['Saved'])
    useToasts.getState().release(t.id)
    vi.advanceTimersByTime(FADE_MS)
    expect(shown()).toEqual([])
  })

  it('letting go of a failure does not start it fading', () => {
    toast.error('Could not save')
    const [t] = useToasts.getState().toasts
    useToasts.getState().hold(t.id)
    useToasts.getState().release(t.id)
    vi.advanceTimersByTime(60_000)
    expect(shown()).toEqual(['Could not save'])
  })

  it('go when the person closes one, and only that one', () => {
    toast.success('First')
    toast.info('Second')
    const [first] = useToasts.getState().toasts
    useToasts.getState().dismiss(first.id)
    expect(shown()).toEqual(['Second'])
  })

  it('keep the newest five', () => {
    for (let i = 1; i <= 7; i++) toast.info(`Message ${i}`)
    expect(shown()).toEqual(['Message 3', 'Message 4', 'Message 5', 'Message 6', 'Message 7'])
  })
})
