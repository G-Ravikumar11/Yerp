import { describe, expect, it } from 'vitest'
import { fileNameFor, isDownloadLink } from './download'

const BASE = 'https://localhost/projects/drawings' // where the phone app's pages live

describe('which links the phone app must fetch itself', () => {
  it('takes the server\'s PDF, Excel and document addresses', () => {
    for (const href of ['/api/ra-bills/3/export.xlsx', '/api/ra-bills/3/document.pdf', '/api/gst/outward.xlsx?month=2026-09',
      '/api/money/receivables.pdf', '/api/wo/orders.csv', 'https://localhost/api/qc/cubes.pdf']) {
      expect(isDownloadLink(href, null, BASE), href).toBe(true)
    }
  })

  it('takes any /api address marked as a download, and a file the page made in memory', () => {
    expect(isDownloadLink('/api/ledger/statement', '', BASE)).toBe(true)          // a download attribute, even an empty one
    expect(isDownloadLink('/api/files/12?download=1', null, BASE)).toBe(true)
    expect(isDownloadLink('blob:https://localhost/3f2a', 'report.xlsx', BASE)).toBe(true)
  })

  it('leaves everything else alone', () => {
    expect(isDownloadLink('/projects/drawings', null, BASE)).toBe(false)           // a page of the app
    expect(isDownloadLink('/api/jobs/3/schedule', null, BASE)).toBe(false)         // data, not a file
    expect(isDownloadLink('https://example.com/x.pdf', null, BASE)).toBe(false)    // somebody else's website
    expect(isDownloadLink('blob:https://localhost/3f2a', null, BASE)).toBe(false)  // a blob that is not a download
    expect(isDownloadLink('#top', null, BASE)).toBe(false)
    expect(isDownloadLink('', null, BASE)).toBe(false)
    expect(isDownloadLink(null, null, BASE)).toBe(false)
  })
})

describe('what the saved file is called', () => {
  it('prefers the name the page asked for, then the server\'s, then the address', () => {
    expect(fileNameFor('RA bill 3.pdf', 'attachment; filename="x.pdf"', '/api/a/b.pdf')).toBe('RA bill 3.pdf')
    expect(fileNameFor(null, 'attachment; filename="RA-3.xlsx"', '/api/a/export.xlsx')).toBe('RA-3.xlsx')
    expect(fileNameFor(null, "attachment; filename*=UTF-8''Bill%20no%203.pdf", '/api/a/document.pdf')).toBe('Bill no 3.pdf')
    expect(fileNameFor(null, null, '/api/gst/outward.xlsx?month=9')).toBe('outward.xlsx')
    expect(fileNameFor('', null, '/api/')).toBe('download')
  })

  it('never lets a path or odd character into the name', () => {
    expect(fileNameFor('../../secret/x:y.pdf', null, '/api/x.pdf')).not.toMatch(/[\/:]/)
  })
})
