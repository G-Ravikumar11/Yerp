import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@/components/ui'
import { StatusDonut } from './StatusDonut'

const draw = (distribution: { status: string; count: number }[]) => {
  const onPick = vi.fn()
  const view = render(<TooltipProvider><StatusDonut distribution={distribution} onPick={onPick} /></TooltipProvider>)
  return { onPick, ...view }
}
const row = (name: RegExp) => screen.getByRole('button', { name })

describe('Equipment status donut', () => {
  it('shows each status with its count and share of the total, and the total in the middle', () => {
    draw([{ status: 'Available', count: 3 }, { status: 'Deployed', count: 5 }, { status: 'Under repair', count: 1 }, { status: 'Breakdown', count: 1 }])
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(row(/^Available \/ idle: 3 machines \(30%\)/)).toBeInTheDocument()
    expect(row(/^Working: 5 machines \(50%\)/)).toBeInTheDocument()
    expect(row(/^Under maintenance: 1 machine \(10%\)/)).toBeInTheDocument()
    expect(row(/^Breakdown: 1 machine \(10%\)/)).toBeInTheDocument()
    // Returned is listed only when there are some.
    expect(screen.queryByText('Returned')).toBeNull()
  })

  it('keeps a status at zero in the legend, and lists Returned when there is one', () => {
    draw([{ status: 'Deployed', count: 2 }, { status: 'Returned', count: 2 }])
    expect(row(/^Breakdown: 0 machines \(0%\)/)).toBeInTheDocument()
    expect(row(/^Returned: 2 machines \(50%\)/)).toBeInTheDocument()
    expect(screen.getByText('4')).toBeInTheDocument()
  })

  it('the legend adds up to the total, a status it does not know included', () => {
    draw([{ status: 'Available', count: 1 }, { status: 'Hired out', count: 2 }])
    const legend = screen.getByRole('list', { name: 'Equipment by status' })
    const counts = within(legend).getAllByRole('button').map((b) => Number(b.getAttribute('aria-label')!.match(/: (\d+) machine/)![1]))
    expect(counts.reduce((a, b) => a + b, 0)).toBe(3)
    expect(row(/^Hired out: 2 machines/)).toBeInTheDocument()
  })

  it('copes with no data at all', () => {
    draw([])
    expect(screen.getByText('machines').previousElementSibling?.textContent).toBe('0')
    expect(row(/^Working: 0 machines \(0%\)/)).toBeInTheDocument()
  })

  it('a legend item opens the register with that status', async () => {
    const { onPick } = draw([{ status: 'Breakdown', count: 2 }, { status: 'Deployed', count: 1 }])
    await userEvent.click(row(/^Breakdown:/))
    expect(onPick).toHaveBeenCalledWith('Breakdown')
  })

  it('a slice of the ring opens the register with that status too', async () => {
    const { onPick, container } = draw([{ status: 'Under repair', count: 4 }])
    const slices = container.querySelectorAll('svg circle.cursor-pointer')
    expect(slices).toHaveLength(1)
    await userEvent.click(slices[0])
    expect(onPick).toHaveBeenCalledWith('Under repair')
  })
})
