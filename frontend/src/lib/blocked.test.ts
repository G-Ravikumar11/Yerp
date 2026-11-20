import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ platform: 'android', reachable: true }))
vi.mock('@capacitor/core', () => ({ Capacitor: { getPlatform: () => h.platform } }))
vi.mock('@/stores/offline', () => ({ serverReachable: async () => h.reachable }))

import { ApiError } from './api'
import { refusedNotOffline } from './blocked'

describe('a failure that looks like no connection', () => {
  beforeEach(() => { h.platform = 'android'; h.reachable = true })

  it('is a refusal when the server answers a plain call', async () => {
    expect(await refusedNotOffline(new TypeError('Failed to fetch'))).toBe(true)
  })
  it('is a lost connection when the server does not answer', async () => {
    h.reachable = false
    expect(await refusedNotOffline(new TypeError('Failed to fetch'))).toBe(false)
  })
  it('leaves an answer from the server as it is', async () => {
    expect(await refusedNotOffline(new ApiError(500, 'x'))).toBe(false)
  })
  it('changes nothing on the website or the iPhone app', async () => {
    h.platform = 'web'
    expect(await refusedNotOffline(new TypeError('Failed to fetch'))).toBe(false)
    h.platform = 'ios'
    expect(await refusedNotOffline(new TypeError('Failed to fetch'))).toBe(false)
  })
})
