import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { PrivacyPage, TermsPage } from './LegalPage'

describe('legal pages', () => {
  it('shows the Terms of Service with its date line and sections', () => {
    render(<MemoryRouter><TermsPage /></MemoryRouter>)
    expect(screen.getByRole('heading', { level: 1, name: 'Terms of Service' })).toBeInTheDocument()
    expect(screen.getAllByText(/Last updated:/).length).toBeGreaterThan(0)
    expect(screen.getByRole('heading', { name: /Acceptance of these terms/ })).toBeInTheDocument()
  })

  it('shows the Privacy Policy and links to the terms', () => {
    render(<MemoryRouter><PrivacyPage /></MemoryRouter>)
    expect(screen.getByRole('heading', { level: 1, name: 'Privacy Policy' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Terms of Service' })).toHaveAttribute('href', expect.stringContaining('terms'))
  })
})
