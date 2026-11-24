import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const sheets = vi.hoisted(() => ({ read: vi.fn(), names: vi.fn() }))
const pdf = vi.hoisted(() => ({ getDocument: vi.fn() }))
vi.mock('read-excel-file', () => ({ default: sheets.read, readSheetNames: sheets.names }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({ getDocument: pdf.getDocument, GlobalWorkerOptions: {} }))
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }))

import { FileViewer } from './FileViewer'
import { useFileSheet } from '@/stores/fileSheet'
import { toast } from '@/stores/toast'

const xlsx = (name = 'bill.xlsx') => ({ name, uri: 'file:///cache/' + name, data: 'QUJD' })

beforeEach(() => {
  sheets.read.mockReset()
  sheets.names.mockReset()
  pdf.getDocument.mockReset()
  vi.spyOn(toast, 'error').mockImplementation(() => undefined as never)
  useFileSheet.setState({ file: null, viewing: null })
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

/** read-excel-file is asked for the sheet names, then for one sheet's rows. */
function workbook(names: string[], rows: Record<number, unknown[][]>) {
  sheets.names.mockResolvedValue(names)
  sheets.read.mockImplementation(async (_blob: Blob, o: { sheet?: number }) => rows[o.sheet ?? 1])
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
    sheets.names.mockRejectedValue(new Error('not a workbook'))
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

  it('zooms with the + and - buttons, one step at a time, and Reset goes back to 100%', async () => {
    workbook(['S'], { 1: [['x']] })
    useFileSheet.getState().view(xlsx())
    render(<FileViewer />)
    await screen.findByText('x')
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('100%')
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('150%')
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('400%')
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Zoom out' }))
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('300%')
    await userEvent.click(screen.getByRole('button', { name: 'Reset zoom' }))
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('100%')
  })

  it('starts each file at 100%', async () => {
    workbook(['S'], { 1: [['x']] })
    useFileSheet.getState().view(xlsx('a.xlsx'))
    render(<FileViewer />)
    await screen.findByText('x')
    await userEvent.click(screen.getByRole('button', { name: 'Zoom in' }))
    useFileSheet.getState().view(xlsx('b.xlsx'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('100%'))
  })

  it('zooms when two fingers spread apart, and back out when they pinch in', async () => {
    workbook(['S'], { 1: [['x']] })
    useFileSheet.getState().view(xlsx())
    render(<FileViewer />)
    await screen.findByText('x')
    const box = document.querySelector('[data-viewer-scroll]') as HTMLElement
    const two = (gap: number) => [{ clientX: 100 - gap, clientY: 100 }, { clientX: 100 + gap, clientY: 100 }]
    fireEvent.touchStart(box, { touches: two(20) })
    fireEvent.touchMove(box, { touches: two(40) })
    fireEvent.touchEnd(box, { touches: [] })
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('200%')
    fireEvent.touchStart(box, { touches: two(40) })
    fireEvent.touchMove(box, { touches: two(20) })
    fireEvent.touchEnd(box, { touches: [] })
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('100%')
  })

  it('does not zoom past 400% or below 100% however far the fingers go', async () => {
    workbook(['S'], { 1: [['x']] })
    useFileSheet.getState().view(xlsx())
    render(<FileViewer />)
    await screen.findByText('x')
    const box = document.querySelector('[data-viewer-scroll]') as HTMLElement
    const two = (gap: number) => [{ clientX: 100 - gap, clientY: 100 }, { clientX: 100 + gap, clientY: 100 }]
    fireEvent.touchStart(box, { touches: two(5) })
    fireEvent.touchMove(box, { touches: two(300) })
    fireEvent.touchEnd(box, { touches: [] })
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('400%')
    fireEvent.touchStart(box, { touches: two(300) })
    fireEvent.touchMove(box, { touches: two(2) })
    fireEvent.touchEnd(box, { touches: [] })
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toHaveTextContent('100%')
  })
})
