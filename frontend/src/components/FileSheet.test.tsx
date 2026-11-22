import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const fs = vi.hoisted(() => ({ readdir: vi.fn(), writeFile: vi.fn() }))
const share = vi.hoisted(() => ({ share: vi.fn() }))
vi.mock('@capacitor/filesystem', () => ({ Filesystem: fs, Directory: { Documents: 'DOCUMENTS', Cache: 'CACHE' } }))
vi.mock('@capacitor/share', () => ({ Share: share }))
vi.mock('@capacitor/core', () => ({ Capacitor: { isNativePlatform: () => true } }))

import { FileSheet } from './FileSheet'
import { useFileSheet } from '@/stores/fileSheet'
import { toast } from '@/stores/toast'

const FILE = { name: 'registration.pdf', uri: 'file:///cache/registration.pdf', data: 'QUJD' }

beforeEach(() => {
  fs.readdir.mockReset().mockResolvedValue({ files: [] })
  fs.writeFile.mockReset().mockResolvedValue({ uri: 'x' })
  share.share.mockReset().mockResolvedValue({})
  vi.spyOn(toast, 'success').mockImplementation(() => undefined as never)
  vi.spyOn(toast, 'error').mockImplementation(() => undefined as never)
  useFileSheet.setState({ file: null })
})
afterEach(() => vi.restoreAllMocks())

describe('the "File ready" box', () => {
  it('draws nothing until a file is held', () => {
    const { container } = render(<FileSheet />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the file name with Save, Share and Close', () => {
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    expect(screen.getByText('registration.pdf')).toBeInTheDocument()
    for (const n of ['Save to phone', 'Share', 'Close']) expect(screen.getByRole('button', { name: n })).toBeEnabled()
  })

  it('saves into Documents/Y ERP with the file\'s data, says where, and closes', async () => {
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    await userEvent.click(screen.getByRole('button', { name: 'Save to phone' }))
    await waitFor(() => expect(useFileSheet.getState().file).toBeNull())
    expect(fs.writeFile).toHaveBeenCalledWith({ path: 'Y ERP/registration.pdf', data: 'QUJD', directory: 'DOCUMENTS', recursive: true })
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('Documents / Y ERP as registration.pdf'))
  })

  it('numbers the copy when the name is already taken', async () => {
    fs.readdir.mockResolvedValue({ files: [{ name: 'registration.pdf' }, { name: 'registration (2).pdf' }] })
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    await userEvent.click(screen.getByRole('button', { name: 'Save to phone' }))
    await waitFor(() => expect(fs.writeFile).toHaveBeenCalled())
    expect(fs.writeFile.mock.calls[0][0].path).toBe('Y ERP/registration (3).pdf')
  })

  it('still saves when the Y ERP folder does not exist yet', async () => {
    fs.readdir.mockRejectedValue(new Error('Folder does not exist'))
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    await userEvent.click(screen.getByRole('button', { name: 'Save to phone' }))
    await waitFor(() => expect(useFileSheet.getState().file).toBeNull())
    expect(fs.writeFile.mock.calls[0][0].path).toBe('Y ERP/registration.pdf')
  })

  it('stays open, with an error, when the phone refuses the save, so Share can still be used', async () => {
    fs.writeFile.mockRejectedValue(new Error('permission denied'))
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    await userEvent.click(screen.getByRole('button', { name: 'Save to phone' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalled())
    expect(useFileSheet.getState().file).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Share' })).toBeEnabled()
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('shares the cached copy and closes', async () => {
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    await userEvent.click(screen.getByRole('button', { name: 'Share' }))
    await waitFor(() => expect(useFileSheet.getState().file).toBeNull())
    expect(share.share).toHaveBeenCalledWith(expect.objectContaining({ url: 'file:///cache/registration.pdf', title: 'registration.pdf' }))
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('does not call dismissing the share list an error, but does report a real failure', async () => {
    share.share.mockRejectedValueOnce(new Error('Share canceled'))
    useFileSheet.getState().show(FILE)
    const { unmount } = render(<FileSheet />)
    await userEvent.click(screen.getByRole('button', { name: 'Share' }))
    await waitFor(() => expect(useFileSheet.getState().file).toBeNull())
    expect(toast.error).not.toHaveBeenCalled()
    unmount()

    share.share.mockRejectedValueOnce(new Error('no app can handle this'))
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    await userEvent.click(screen.getByRole('button', { name: 'Share' }))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('That file could not be shared.'))
  })

  it('closes with Close, with Escape, and by tapping outside, but not by tapping inside', async () => {
    for (const how of ['button', 'escape', 'outside'] as const) {
      useFileSheet.getState().show(FILE)
      const { unmount } = render(<FileSheet />)
      if (how === 'button') await userEvent.click(screen.getByRole('button', { name: 'Close' }))
      if (how === 'escape') await userEvent.keyboard('{Escape}')
      if (how === 'outside') await userEvent.click(screen.getByRole('dialog').parentElement as HTMLElement)
      expect(useFileSheet.getState().file, how).toBeNull()
      unmount()
    }
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    await userEvent.click(screen.getByRole('dialog'))
    expect(useFileSheet.getState().file).not.toBeNull()
  })

  it('shows a second file in place of the first, with the buttons usable again', async () => {
    useFileSheet.getState().show(FILE)
    render(<FileSheet />)
    useFileSheet.getState().show({ name: 'bill.xlsx', uri: 'file:///cache/bill.xlsx', data: 'WFla' })
    expect(await screen.findByText('bill.xlsx')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save to phone' })).toBeEnabled()
  })

  it('handles an odd file name: no extension, many dots, a very long name', async () => {
    const { savedName } = await import('@/lib/download')
    expect(savedName('archive.tar.gz', new Set(['archive.tar.gz']))).toBe('archive.tar (2).gz')
    expect(savedName('.hidden', new Set(['.hidden']))).toBe('.hidden (2)')
    const long = 'x'.repeat(300) + '.pdf'
    expect(savedName(long, new Set([long]))).toBe('x'.repeat(300) + ' (2).pdf')
  })
})
