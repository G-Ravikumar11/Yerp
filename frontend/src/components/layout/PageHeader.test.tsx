import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ShellTitle } from '@/lib/shellTitle'
import { PageHeader } from './PageHeader'

const header = <PageHeader eyebrow="Projects" title="Site Diary" description="Who turned up." actions={<button>Record a day</button>} />

describe('the page heading on the phone', () => {
  it('is whole on the website, which has no title bar', () => {
    render(header)
    expect(screen.getByRole('heading', { name: 'Site Diary' })).toBeInTheDocument()
    expect(screen.getByText('Projects')).toBeInTheDocument()
  })

  it('leaves out the eyebrow and heading the top bar already says, and keeps the rest', () => {
    render(<ShellTitle.Provider value="Site Diary">{header}</ShellTitle.Provider>)
    expect(screen.queryByRole('heading', { name: 'Site Diary' })).not.toBeInTheDocument()
    expect(screen.queryByText('Projects')).not.toBeInTheDocument()
    expect(screen.getByText('Who turned up.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Record a day' })).toBeInTheDocument()
  })

  it('keeps its heading when the top bar says something else', () => {
    render(<ShellTitle.Provider value="Details">{header}</ShellTitle.Provider>)
    expect(screen.getByRole('heading', { name: 'Site Diary' })).toBeInTheDocument()
  })
})
