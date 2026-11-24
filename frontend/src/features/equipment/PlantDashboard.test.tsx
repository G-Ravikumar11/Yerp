import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'

// The dashboard as the server sends it: the total is the server's own (fuel + maintenance + rental + entered expenses);
// rental dues and labour from hours are shown beside it, never added in.
const cost_summary = {
  fuel: 40000, maintenance: 20000, rental: 25000, rental_outstanding: 5000,
  'Spare parts': 6000, 'Operator wages and overtime': 7000, 'Transportation and shifting': 2000, 'Insurance and permits': 0, Other: 0,
  labour_estimate: 9000, total: 100000,
}
const data = {
  date_from: '2026-11-01', date_to: '2026-11-30',
  cards: { total: 3, owned: 3, rented: 0, leased: 0, working: 1, idle: 2, maintenance: 0, breakdown: 0, operators: 1, working_hours: 10, fuel: 40000, maintenance_cost: 20000, operating_cost: 100000, upcoming: 0, service: { Overdue: 0, 'Service due': 0, 'Due soon': 0 } },
  status_distribution: [{ status: 'Available', count: 2 }, { status: 'Deployed', count: 1 }],
  cost_summary, maintenance_reminders: [], rental_returns: [], excess_idle: [],
  recent: [
    { at: '2026-11-20 10:15:00', who: 'Ravi', action: 'plant.fuel.recorded', what: 'FU-12', details: 'EX-01: 120 L Diesel at 92 = 11040' },
    { at: '2026-11-19 17:40:00', who: 'Owner', action: 'plant.settings.alerts', what: '', details: "{'idle_alert_share': 0.4, 'notify': True}" },
    { at: '2026-11-18 09:05:00', who: 'Sita', action: 'plant.machine.created', what: 'EX-01', details: 'Excavator' },
  ],
}
vi.mock('@/api/plant', async (orig) => ({
  ...(await orig<typeof import('@/api/plant')>()),
  useDashboard: () => ({ data, isPending: false, isError: false, refetch: vi.fn() }),
}))

import { PlantDashboard } from './PlantDashboard'

const card = () => {
  render(<TooltipProvider><PlantDashboard onGo={vi.fn()} /></TooltipProvider>)
  return screen.getByRole('heading', { name: 'Cost summary' }).parentElement as HTMLElement
}
const rowOf = (el: HTMLElement, label: string) => within(el).getByText(label).parentElement as HTMLElement
const bar = (row: HTMLElement) => row.querySelector('[aria-hidden] > span') as HTMLElement | null

describe('Cost summary', () => {
  it('keeps every category and the total exactly as the server worked them out', () => {
    const el = card()
    for (const label of ['Fuel and diesel', 'Maintenance and repairs', 'Rental charges', 'Rental dues outstanding', 'Spare parts', 'Operator wages and overtime',
      'Transportation and shifting', 'Insurance and permits', 'Other', 'Operator labour (from hours)', 'Total operating cost']) {
      expect(within(el).getByText(label)).toBeInTheDocument()
    }
    expect(rowOf(el, 'Total operating cost').textContent).toContain('1,00,000')
  })

  it('gives each part of the total a bar for its share, and none to what is only shown beside it', () => {
    const el = card()
    expect(bar(rowOf(el, 'Fuel and diesel'))!.style.width).toBe('40%')
    expect(bar(rowOf(el, 'Rental charges'))!.style.width).toBe('25%')
    expect(bar(rowOf(el, 'Insurance and permits'))!.style.width).toBe('0%')
    expect(bar(rowOf(el, 'Rental dues outstanding'))).toBeNull()
    expect(bar(rowOf(el, 'Operator labour (from hours)'))).toBeNull()
    expect(bar(rowOf(el, 'Total operating cost'))).toBeNull()
  })
})

describe('Recent activity', () => {
  const feed = () => {
    render(<TooltipProvider><PlantDashboard onGo={vi.fn()} /></TooltipProvider>)
    return screen.getByRole('heading', { name: 'Recent activity' }).parentElement as HTMLElement
  }

  it('spans both columns and splits its entries into two', () => {
    const el = feed()
    expect(el.className).toContain('lg:col-span-2')
    expect(el.querySelector('ul')!.className).toContain('md:columns-2')
  })

  it('names each kind of change, keeps the newest first, and shows when and who', () => {
    const items = within(feed()).getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toHaveLength(3)
    expect(items[0]).toContain('Fuel recorded FU-12')
    expect(items[0]).toContain('Ravi')
    expect(items[0]).toContain('10:15')
    expect(items[2]).toContain('Machine created EX-01')
  })

  it('never shows raw settings data as activity', () => {
    const el = feed()
    expect(within(el).getByText('Alert settings changed')).toBeInTheDocument()
    expect(el.textContent).not.toContain('idle_alert_share')
    expect(el.textContent).not.toContain('{')
  })
})
