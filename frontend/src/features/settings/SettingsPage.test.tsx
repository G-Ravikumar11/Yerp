import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

// The Master's tabs are not what is being tested here; each stands in as its name.
for (const [file, name] of [['./CompanyTab', 'Company tab'], ['./DocumentsTab', 'Documents tab'], ['./ApprovalsTab', 'Approvals tab'], ['./AccessTab', 'Access tab'], ['./DataTab', 'Data tab'], ['./ErrorLogTab', 'Errors tab']]) {
  vi.doMock(file, () => ({ default: () => <p>{name}</p> }))
}

import SettingsPage from './SettingsPage'

const Where = () => { const l = useLocation(); return <p data-testid="where">{l.pathname + l.search}</p> }
const mount = (url: string) => {
  window.history.replaceState(null, '', url)
  return render(
    <MemoryRouter initialEntries={[url]}><QueryClientProvider client={new QueryClient()}>
      <Routes><Route path="/settings" element={<SettingsPage />} /><Route path="/website" element={<Where />} /></Routes>
    </QueryClientProvider></MemoryRouter>,
  )
}

describe('Settings', () => {
  it('is the Master’s, with no Website tab: the website has a page of its own', () => {
    mount('/settings')
    expect(screen.getByRole('tab', { name: 'Company' })).toBeTruthy()
    expect(screen.queryByRole('tab', { name: 'Website' })).toBeNull()
  })

  it('sends an old link to its Website tab to the Website page, with what it asked for', async () => {
    mount('/settings?tab=website&part=projects&project=4')
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/website?part=projects&project=4'))
  })
})
