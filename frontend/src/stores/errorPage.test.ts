import { describe, expect, it } from 'vitest'
import { ApiError } from '@/lib/api'
import { pageFor } from './errorPage'

describe('which failures get the whole error page', () => {
  it('real failures get a page, with their code and ref', () => {
    expect(pageFor(new ApiError(500, 'An unexpected error occurred.', 'YE-SRV-01', '7F3A9C21'))).toMatchObject({ kind: 'server', code: 'YE-SRV-01', ref: '7F3A9C21' })
    expect(pageFor(new ApiError(503, 'Restarting', 'YE-BUSY-02'))?.kind).toBe('busy')
    expect(pageFor(new ApiError(403, 'Not allowed', 'YE-ACCESS-01'))?.kind).toBe('forbidden')
    expect(pageFor(new ApiError(404, 'Drawing not found', 'YE-DATA-01'))?.kind).toBe('gone')
    expect(pageFor(new TypeError('Failed to fetch'))).toMatchObject({ kind: 'offline', code: 'YE-NET' })
  })

  it('a mistake in the form keeps its short message, so nothing typed is lost', () => {
    expect(pageFor(new ApiError(400, "The worker's name.", 'YE-DATA-04'))).toBeNull()
    expect(pageFor(new ApiError(409, 'That record conflicts with one that already exists.', 'YE-DATA-02'))).toBeNull()
    expect(pageFor(new ApiError(413, 'That file is over 15 MB.', 'YE-FILE-01'))).toBeNull()
    expect(pageFor(new ApiError(401, 'Invalid credentials', 'YE-AUTH-01'))).toBeNull()
  })
})
