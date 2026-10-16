import { describe, expect, it } from 'vitest'
import { ApiError } from './api'
import { ERROR_CODES, codeFor, codeLine, newRef, showsCode } from './errorCodes'

describe('error codes', () => {
  it('a server failure shows its words, then its code and ref', () => {
    const e = new ApiError(500, 'An unexpected error occurred.', 'YE-SRV-01', '7F3A9C21')
    expect(e.message).toBe('An unexpected error occurred. (Error YE-SRV-01 · ref 7F3A9C21)')
    expect(e.detail).toBe('An unexpected error occurred.')
    expect(e.code).toBe('YE-SRV-01')
    expect(e.ref).toBe('7F3A9C21')
  })

  it('a wrong password and an account problem show their own codes', () => {
    expect(new ApiError(401, 'Invalid credentials', 'YE-AUTH-01', 'AB12CD34').message).toBe('Invalid credentials (Error YE-AUTH-01 · ref AB12CD34)')
    expect(new ApiError(429, 'Too many login attempts. Try again later.', 'YE-AUTH-03').message).toContain('YE-AUTH-03')
  })

  it('an input mistake shows only its words, but still carries its code', () => {
    const e = new ApiError(400, "The worker's name.", 'YE-DATA-04')
    expect(e.message).toBe("The worker's name.")
    expect(e.code).toBe('YE-DATA-04')
    expect(showsCode('YE-DATA-04')).toBe(false)
  })

  it('an answer without a code gets one from its status', () => {
    expect(new ApiError(404, 'Not found').message).toBe('Not found (Error YE-DATA-01)')
    expect(codeFor(503)).toBe('YE-BUSY-02')
    expect(codeFor(504)).toBe('YE-BUSY-03')
    expect(codeFor(500)).toBe('YE-SRV-01')
    expect(codeFor(0)).toBe('YE-NET')
    expect(codeLine('YE-NET')).toBe('Error YE-NET')
  })

  it('every code is explained, and refs look like the server\'s', () => {
    const server = ['YE-AUTH-01', 'YE-AUTH-02', 'YE-AUTH-03', 'YE-AUTH-04', 'YE-AUTH-05', 'YE-AUTH-06', 'YE-AUTH-07', 'YE-AUTH-08',
      'YE-ACCESS-01', 'YE-ACCESS-02', 'YE-DATA-01', 'YE-DATA-02', 'YE-DATA-03', 'YE-DATA-04', 'YE-FILE-01', 'YE-FILE-02', 'YE-FILE-03',
      'YE-BUSY-01', 'YE-BUSY-02', 'YE-BUSY-03', 'YE-SRV-01']
    for (const c of [...server, 'YE-NET', 'YE-APP']) expect(ERROR_CODES[c]?.title, c).toBeTruthy()
    expect(Object.keys(ERROR_CODES).length).toBe(server.length + 2)
    expect(newRef()).toMatch(/^[0-9A-F]{8}$/)
  })
})
