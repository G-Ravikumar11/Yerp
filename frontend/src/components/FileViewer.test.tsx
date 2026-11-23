import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const sheets = vi.hoisted(() => ({ read: vi.fn() }))
const pdf = vi.hoisted(() => ({ getDocument: vi.fn() }))
vi.mock('read-excel-file', () => ({ default: sheets.read }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: {} }))
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }))

import { FileViewer } from './FileViewer'
import { useFileSheet } from '@/stores/fileSheet'
import { toast } from '@/stores/toast'

const xlsx = (name = 'bill.xlsx') => ({ name, uri: 'file:///cache/' + name, data: 'QUJD' })

beforeEach(() => {
  sheets.read.mockReset()
  pdf.getDocument.mockReset()
  vi.spyOn(toast, 'error').mockImplementation(() => undefined as never)
  useFileSheet.setState({ file: null, viewing: null })
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

/** read-excel-file is asked twice: for the sheet names, then for one sheet's rows. */
function workbook(names: string[], rows: Record<number, unknown[][]>) {
  sheets.read.mockImplementation(async (_blob: Blob, o: { getSheets?: boolean; sheet?: number }) => (o.getSheets ? names.map((name) => ({ name })) : rows[o.sheet ?? 1]))
}

describe('the file viewer', () => {
  it('draws nothing when no file is being looked at', () => {
    const { container } = render(<FileViewer />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows an Excel sheet as a table, with dates written day first and no time-zone slip', async () => {
    workbook(['Bill'], { 1: [['Item', 'Date', 'Amount'], ['Cement', new Date(Date.UTC(2026, 10, 1)), 1250.5], ['Sand', null, 0]] })
    useFileSheet.getState().view(xlsx())
    render(<FileViewer />)
    expect(await screen.findByText('Cement')).toBeInTheDocument()
    expect(screen.getByText('01/11/2026')).toBeInTheDocument()
    expect(screen.getByText('1250.5')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  it('offers each sheet of a workbook as a tab and reads the one chosen', async () => {
    workbook(['Summary', 'తెలుగు'], { 1: [['A'], ['one']], 2: [['పేరు'], ['సిమెంట్']] })
    useFileSheet.getState().view(xlsx('multi.xlsx'))
    render(<FileViewer />)
    expect(await screen.findByText('one')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'తెలుగు' }))
    expect(await screen.findByText('సిమెంట్')).toBeInTheDocument()
  })

  it('says so when a sheet is empty, and shows only the first 2000 rows of a long one', async () => {
    workbook(['Empty', 'Long'], { 1: [], 2: Array.from({ length: 2500 }, (_, i) => [`row ${i}`]) })
    useFileSheet.getState().view(xlsx())
    render(<FileViewer />)
    expect(await screen.findByText('This sheet is empty.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Long' }))
    expect(await screen.findByText(/Showing the first 2000 of 2500 rows/)).toBeInTheDocument()
    expect(screen.queryByText('row 2400')).not.toBeInTheDocument()
  })

  it('sends a workbook it cannot read to the Save / Share box instead, with a message', async () => {
    sheets.read.mockRejectedValue(new Error('not a workbook'))
    useFileSheet.getState().view(xlsx('broken.xlsx'))
    render(<FileViewer />)
    await waitFor(() => expect(useFileSheet.getState().file?.name).toBe('broken.xlsx'))
    expect(useFileSheet.getState().viewing).toBeNull()
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/could not be shown here/i))
  })

  it('does the same for a PDF it cannot open', async () => {
    pdf.getDocument.mockReturnValue({ promise: Promise.reject(new Error('Invalid PDF')) })
    useFileSheet.getState().view(xlsx('broken.pdf'))
    render(<FileViewer />)
    await waitFor(() => expect(useFileSheet.getState().file?.name).toBe('broken.pdf'))
    expect(useFileSheet.getState().viewing).toBeNull()
  })

  it('has Save / Share, which opens the box over the file, and a Close that ends the look', async () => {
    workbook(['S'], { 1: [['x']] })
    useFileSheet.getState().view(xlsx())
    render(<FileViewer />)
    await screen.findByText('x')
    await userEvent.click(screen.getByRole('button', { name: /Save \/ Share/ }))
    expect(useFileSheet.getState().file?.name).toBe('bill.xlsx')
    expect(useFileSheet.getState().viewing?.name).toBe('bill.xlsx') // still there underneath
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(useFileSheet.getState().viewing).toBeNull()
  })

  it('closes on Escape', async () => {
    workbook(['S'], { 1: [['x']] })
    useFileSheet.getState().view(xlsx())
    render(<FileViewer />)
    await screen.findByText('x')
    await userEvent.keyboard('{Escape}')
    expect(useFileSheet.getState().viewing).toBeNull()
  })
})
