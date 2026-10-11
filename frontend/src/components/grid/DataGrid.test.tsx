import { useState } from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DataGrid } from './DataGrid'
import type { ChangeInfo, Column } from './types'

type Line = { desc: string; uom: string; qty: number | null; rate: number | null; done: boolean }
const blank = (): Line => ({ desc: '', uom: 'sqm', qty: null, rate: null, done: false })
const line = (over: Partial<Line> = {}): Line => ({ ...blank(), ...over })

const columns: Column<Line>[] = [
  { id: 'desc', header: 'Description', required: true },
  { id: 'uom', header: 'UoM', type: 'select', options: ['sqm', 'cum', { value: 'MT', label: 'Tonne' }] },
  { id: 'qty', header: 'Qty', type: 'number', decimals: 2, validate: (v) => ((v as number) < 0 ? 'Cannot be negative' : null), summary: 'sum' },
  { id: 'rate', header: 'Rate', type: 'number' },
  { id: 'amount', header: 'Amount', type: 'number', readOnly: true, get: (r) => (r.qty ?? 0) * (r.rate ?? 0) || null },
  { id: 'done', header: 'Done', type: 'checkbox' },
]

let latest: Line[] = []
let changes: ChangeInfo[] = []

function Harness({ initial = [], readOnly = false, minRows = 0 }: { initial?: Line[]; readOnly?: boolean; minRows?: number }) {
  const [rows, setRows] = useState<Line[]>(initial)
  latest = rows
  return (
    <DataGrid
      aria-label="BOQ"
      columns={columns}
      rows={rows}
      onRowsChange={(next, info) => {
        latest = next
        changes.push(info)
        setRows(next)
      }}
      newRow={blank}
      readOnly={readOnly}
      minRows={minRows}
    />
  )
}

const grid = () => screen.getByRole('grid')
const dataRows = () => screen.getAllByRole('row').filter((r) => within(r).queryByRole('rowheader'))
const cell = (r: number, c: number) => within(dataRows()[r]).getAllByRole('gridcell')[c]
const active = () => /r(\d+)c(\d+)$/.exec(grid().getAttribute('aria-activedescendant') ?? '')!.slice(1).map(Number)

async function start(props: Parameters<typeof Harness>[0] = {}) {
  const user = userEvent.setup()
  render(<Harness {...props} />)
  await user.click(cell(0, 0))
  return user
}

beforeEach(() => {
  latest = []
  changes = []
})

describe('typing and moving', () => {
  it('replaces the cell with what is typed and Enter moves down', async () => {
    const user = await start({ initial: [line({ desc: 'old' })] })
    await user.keyboard('Slab{Enter}')
    expect(latest[0].desc).toBe('Slab')
    expect(active()).toEqual([1, 0])
  })

  it('Tab moves right and Shift+Tab back, carrying on to the next row at the end', async () => {
    const user = await start({ initial: [line(), line()] })
    await user.keyboard('{Tab}{Tab}')
    expect(active()).toEqual([0, 2])
    await user.keyboard('{Shift>}{Tab}{/Shift}')
    expect(active()).toEqual([0, 1])
    await user.keyboard('{End}{Tab}')
    expect(active()).toEqual([1, 0])
  })

  it('types a value and Tab commits it and moves right', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('Wall{Tab}')
    expect(latest[0].desc).toBe('Wall')
    expect(active()).toEqual([0, 1])
  })

  it('arrow keys walk the sheet and Ctrl+Home / End jump to the corners', async () => {
    const user = await start({ initial: [line({ desc: 'a' }), line({ desc: 'b' }), line({ desc: 'c' })] })
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowRight}')
    expect(active()).toEqual([2, 1])
    await user.keyboard('{Control>}{Home}{/Control}')
    expect(active()).toEqual([0, 0])
    await user.keyboard('{Control>}{End}{/Control}')
    expect(active()).toEqual([2, columns.length - 1])
  })

  it('always keeps one empty row waiting under the last', async () => {
    const user = await start({ initial: [] })
    expect(dataRows()).toHaveLength(1)
    await user.keyboard('First{Enter}')
    expect(dataRows()).toHaveLength(2)
    await user.keyboard('Second{Enter}')
    expect(dataRows()).toHaveLength(3)
    expect(latest.map((r) => r.desc)).toEqual(['First', 'Second'])
  })

  it('pads with blank rows up to minRows', () => {
    render(<Harness minRows={8} />)
    expect(dataRows()).toHaveLength(8)
  })
})

describe('editing in place', () => {
  it('F2 opens the cell with its content, and the arrows then move the caret, not the cell', async () => {
    const user = await start({ initial: [line({ desc: 'Slab' })] })
    await user.keyboard('{F2}')
    const box = screen.getByRole('textbox', { name: 'Description' })
    expect(box).toHaveValue('Slab')
    await user.keyboard('{ArrowLeft}{ArrowLeft}X{Enter}')
    expect(latest[0].desc).toBe('SlXab')
  })

  it('a double click opens it too', async () => {
    const user = await start({ initial: [line({ desc: 'Beam' })] })
    await user.dblClick(cell(0, 0))
    expect(screen.getByRole('textbox', { name: 'Description' })).toHaveValue('Beam')
  })

  it('Escape puts it back as it was', async () => {
    const user = await start({ initial: [line({ desc: 'Keep' })] })
    await user.keyboard('Changed{Escape}')
    expect(latest[0].desc).toBe('Keep')
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('typing begins an edit whose arrow keys leave the cell, as in Excel', async () => {
    const user = await start({ initial: [line(), line()] })
    await user.keyboard('Slab{ArrowDown}')
    expect(latest[0].desc).toBe('Slab')
    expect(active()).toEqual([1, 0])
  })

  it('does not change a computed cell', async () => {
    const user = await start({ initial: [line({ qty: 2, rate: 5 })] })
    await user.keyboard('{Control>}{Home}{/Control}{ArrowRight}{ArrowRight}{ArrowRight}{ArrowRight}9{Enter}')
    expect(screen.queryByRole('textbox')).toBeNull()
    expect(latest[0]).toMatchObject({ qty: 2, rate: 5 })
  })
})

describe('numbers, choices and ticks', () => {
  it('works out arithmetic typed into a number cell', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{Tab}{Tab}12.5*8{Enter}')
    expect(latest[0].qty).toBe(100)
  })

  it('reads Indian grouping', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{Tab}{Tab}{Tab}1,20,000.50{Enter}')
    expect(latest[0].rate).toBe(120000.5)
  })

  it('will not keep text in a number cell: it says why and stays open', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{Tab}{Tab}abc{Enter}')
    expect(screen.getByRole('alert')).toHaveTextContent('Not a number')
    expect(latest[0].qty).toBeNull()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('a picker filters as you type and Enter takes the top match', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{Tab}to')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(screen.getAllByRole('option')).toHaveLength(1)
    await user.keyboard('{Enter}')
    expect(latest[0].uom).toBe('MT')
  })

  it('a picker moves through its list with the arrows', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{Tab}{F2}{ArrowDown}{Enter}')
    expect(latest[0].uom).toBe('cum')
  })

  it('a picker refuses something that is not a choice', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{Tab}zzz{Enter}')
    expect(screen.getByRole('alert')).toHaveTextContent('Not one of the choices')
    expect(latest[0].uom).toBe('sqm')
  })

  it('Space ticks a box', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{End} ')
    expect(latest[0].done).toBe(true)
    await user.keyboard(' ')
    expect(latest[0].done).toBe(false)
  })
})

describe('selecting a block', () => {
  const rows = [line({ desc: 'a', qty: 10 }), line({ desc: 'b', qty: 20 }), line({ desc: 'c', qty: 30 })]

  it('Shift+arrows select a block and the status bar adds up the numbers in it', async () => {
    const user = await start({ initial: rows })
    await user.keyboard('{Tab}{Tab}{Shift>}{ArrowDown}{ArrowDown}{/Shift}')
    expect(screen.getByText('Sum 60')).toBeInTheDocument()
    expect(screen.getByText('Avg 20')).toBeInTheDocument()
    expect(screen.getByText('Count 3')).toBeInTheDocument()
  })

  it('Delete clears the whole block', async () => {
    const user = await start({ initial: rows })
    await user.keyboard('{Tab}{Tab}{Shift>}{ArrowDown}{/Shift}{Delete}')
    expect(latest.map((r) => r.qty)).toEqual([null, null, 30])
    expect(latest.map((r) => r.desc)).toEqual(['a', 'b', 'c'])
  })

  it('Ctrl+D fills down from the top of the block', async () => {
    const user = await start({ initial: rows })
    await user.keyboard('{Tab}{Tab}{Shift>}{ArrowDown}{ArrowDown}{/Shift}{Control>}d{/Control}')
    expect(latest.map((r) => r.qty)).toEqual([10, 10, 10])
  })

  it('Ctrl+A selects everything', async () => {
    const user = await start({ initial: rows })
    await user.keyboard('{Control>}a{/Control}{Delete}')
    expect(latest.every((r) => r.desc === '' && r.qty === null)).toBe(true)
  })

  it('clicking a row number selects the row', async () => {
    const user = await start({ initial: rows })
    await user.click(within(dataRows()[1]).getByRole('rowheader'))
    await user.keyboard('{Delete}')
    expect(latest.map((r) => r.desc)).toEqual(['a', '', 'c'])
  })
})

describe('the clipboard', () => {
  it('pastes a block from Excel, growing the sheet to fit', async () => {
    await start({ initial: [line()] })
    const text = 'Slab\tcum\t10\t500\nBeam\tsqm\t4\t650\nWall\tTonne\t\t\n'
    fireEvent.paste(grid(), { clipboardData: { getData: () => text } })
    expect(latest).toHaveLength(3)
    expect(latest[0]).toMatchObject({ desc: 'Slab', uom: 'cum', qty: 10, rate: 500 })
    expect(latest[2]).toMatchObject({ desc: 'Wall', uom: 'MT' })
    expect(screen.getByRole('status')).toHaveTextContent('2 rows added')
  })

  it('says what it left alone', async () => {
    await start({ initial: [line()] })
    fireEvent.paste(grid(), { clipboardData: { getData: () => 'Slab\tkg\tlots\t5\t99' } })
    expect(latest[0]).toMatchObject({ desc: 'Slab', uom: 'sqm', qty: null, rate: 5 })
    expect(screen.getByRole('status')).toHaveTextContent('left alone')
  })

  it('paints one pasted value over the selection', async () => {
    const user = await start({ initial: [line(), line(), line()] })
    await user.keyboard('{Tab}{Tab}{Shift>}{ArrowDown}{ArrowDown}{/Shift}')
    fireEvent.paste(grid(), { clipboardData: { getData: () => '7' } })
    expect(latest.map((r) => r.qty)).toEqual([7, 7, 7])
  })

  it('copies the selection as tab-separated text', async () => {
    const user = await start({ initial: [line({ desc: 'a', qty: 1234.5 }), line({ desc: 'b', qty: 2 })] })
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    await user.keyboard('{Shift>}{ArrowDown}{ArrowRight}{ArrowRight}{/Shift}{Control>}c{/Control}')
    expect(writeText).toHaveBeenCalledWith('a\tsqm\t1234.5\nb\tsqm\t2')
  })

  it('cut copies and then clears', async () => {
    const user = await start({ initial: [line({ desc: 'gone' })] })
    const writeText = vi.spyOn(navigator.clipboard, 'writeText')
    await user.keyboard('{Control>}x{/Control}')
    await vi.waitFor(() => expect(latest[0].desc).toBe(''))
    expect(writeText).toHaveBeenCalledWith('gone')
  })
})

describe('undo', () => {
  it('Ctrl+Z takes back an edit and Ctrl+Y brings it back', async () => {
    const user = await start({ initial: [line({ desc: 'one' })] })
    await user.keyboard('two{Enter}')
    expect(latest[0].desc).toBe('two')
    await user.keyboard('{Control>}z{/Control}')
    expect(latest[0].desc).toBe('one')
    await user.keyboard('{Control>}y{/Control}')
    expect(latest[0].desc).toBe('two')
  })

  it('takes back a whole paste in one step', async () => {
    const user = await start({ initial: [line({ desc: 'keep' })] })
    fireEvent.paste(grid(), { clipboardData: { getData: () => 'a\nb\nc' } })
    expect(latest).toHaveLength(3)
    await user.keyboard('{Control>}z{/Control}')
    expect(latest).toHaveLength(1)
    expect(latest[0].desc).toBe('keep')
  })

  it('says so when there is nothing to undo', async () => {
    const user = await start({ initial: [line()] })
    await user.keyboard('{Control>}z{/Control}')
    expect(screen.getByRole('status')).toHaveTextContent('Nothing to undo')
  })
})

describe('rows', () => {
  it('Ctrl+- removes the selected rows and Ctrl+Shift++ inserts above', async () => {
    const user = await start({ initial: [line({ desc: 'a' }), line({ desc: 'b' }), line({ desc: 'c' })] })
    await user.keyboard('{ArrowDown}{Control>}-{/Control}')
    expect(latest.map((r) => r.desc)).toEqual(['a', 'c'])
    await user.keyboard('{Control>}{Shift>}+{/Shift}{/Control}')
    expect(latest).toHaveLength(3)
    expect(latest[1].desc).toBe('')
  })
})

describe('problems', () => {
  it('flags a bad value, counts it, and jumps to it', async () => {
    const user = await start({ initial: [line({ desc: 'ok', qty: 1 }), line({ desc: 'bad', qty: -3 })] })
    const issues = screen.getByRole('button', { name: /1 to fix/ })
    await user.click(issues)
    expect(active()).toEqual([1, 2])
    expect(cell(1, 2)).toHaveAttribute('aria-invalid', 'true')
  })

  it('asks for what a started row is missing', async () => {
    await start({ initial: [line({ qty: 4 })] })
    expect(cell(0, 0)).toHaveAttribute('aria-invalid', 'true')
    expect(cell(0, 0)).toHaveAttribute('title', 'Required')
  })
})

describe('read only', () => {
  it('lets you look and copy but not change', async () => {
    const user = await start({ initial: [line({ desc: 'fixed' })], readOnly: true })
    await user.keyboard('X{Enter}{Delete}')
    fireEvent.paste(grid(), { clipboardData: { getData: () => 'pasted' } })
    expect(latest[0].desc).toBe('fixed')
    expect(changes).toHaveLength(0)
  })
})

describe('totals', () => {
  it('sums a column over the rows that have data', () => {
    render(<Harness initial={[line({ desc: 'a', qty: 10 }), line({ desc: 'b', qty: 2.5 })]} />)
    const total = screen.getAllByRole('row').at(-1)!
    expect(total).toHaveTextContent('12.50')
  })
})

describe('big sheets', () => {
  it('draws only the rows in view', () => {
    const many = Array.from({ length: 3000 }, (_, i) => line({ desc: `Item ${i}`, qty: i }))
    render(<Harness initial={many} />)
    expect(dataRows().length).toBeLessThan(60)
    expect(grid()).toHaveAttribute('aria-rowcount', '3002')
  })

  it('Ctrl+End reaches the last row of 3000', async () => {
    const many = Array.from({ length: 3000 }, (_, i) => line({ desc: `Item ${i}`, qty: i }))
    const user = await start({ initial: many })
    await user.keyboard('{Control>}{End}{/Control}')
    expect(active()).toEqual([2999, columns.length - 1])
  })
})
