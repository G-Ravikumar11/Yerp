import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './confirm'
import { Modal } from './modal'

describe('ConfirmDialog', () => {
  const open = (extra: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) => {
    const onConfirm = vi.fn()
    const onOpenChange = vi.fn()
    render(<ConfirmDialog open onOpenChange={onOpenChange} title="Delete bathroom flooring?" description="Anything that followed it will follow what it followed." confirmLabel="Delete" tone="danger" onConfirm={onConfirm} {...extra} />)
    return { onConfirm, onOpenChange, dialog: screen.getByRole('dialog') }
  }

  it('is the title, the warning and the buttons - with no empty body between them', () => {
    const { dialog } = open()
    expect(screen.getByText('Delete bathroom flooring?')).toBeTruthy()
    expect(screen.getByText(/Anything that followed it/)).toBeTruthy()
    // The body box that used to sit empty between the words and the buttons is not drawn.
    expect(dialog.querySelector('.overflow-y-auto')).toBeNull()
    // Header, then footer: nothing in between.
    expect([...dialog.children].map((c) => c.tagName)).toEqual(['HEADER', 'FOOTER'])
  })

  it('keeps the close icon, Not now and the Delete button, and Delete still confirms', async () => {
    const { onConfirm, onOpenChange } = open()
    expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Not now' }))
    expect(onOpenChange).toHaveBeenCalledWith(false)
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
  })

  it('still draws its body when it asks for a reason, and holds the confirmation until it is given', async () => {
    const { onConfirm, dialog } = open({ reason: { label: 'Why', required: true } })
    expect(dialog.querySelector('.overflow-y-auto')).not.toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).not.toHaveBeenCalled()
    await userEvent.type(screen.getByLabelText('Why'), 'Wrong room')
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    expect(onConfirm).toHaveBeenCalledWith('Wrong room')
  })
})

describe('Modal', () => {
  it('a form dialog keeps its body and its header rule', () => {
    render(<Modal open onOpenChange={() => {}} title="New thing"><p>content</p></Modal>)
    const dialog = screen.getByRole('dialog')
    expect(dialog.querySelector('.overflow-y-auto')?.textContent).toBe('content')
    expect(dialog.querySelector('header')?.className).toContain('border-b')
  })
})
