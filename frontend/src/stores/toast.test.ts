import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast, useToasts } from './toast'

beforeEach(() => { vi.useFakeTimers(); useToasts.setState({ toasts: [] }) })
afterEach(() => { vi.useRealTimers() })

describe('notifications', () => {
  it('stay on screen until they are closed, however long that is', () => {
    toast.success('Saved')
    toast.error('Could not save')
    vi.advanceTimersByTime(10 * 60_000)                       // ten minutes
    expect(useToasts.getState().toasts.map((t) => t.message)).toEqual(['Saved', 'Could not save'])
  })

  it('go when the person closes one, and only that one', () => {
    toast.success('First')
    toast.info('Second')
    const [first] = useToasts.getState().toasts
    useToasts.getState().dismiss(first.id)
    expect(useToasts.getState().toasts.map((t) => t.message)).toEqual(['Second'])
  })

  it('keep the newest five', () => {
    for (let i = 1; i <= 7; i++) toast.info(`Message ${i}`)
    expect(useToasts.getState().toasts.map((t) => t.message)).toEqual(['Message 3', 'Message 4', 'Message 5', 'Message 6', 'Message 7'])
  })
})
