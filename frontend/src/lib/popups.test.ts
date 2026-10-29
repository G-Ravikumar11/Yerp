import { describe, expect, it } from 'vitest'
import { MOST_AT_ONCE, freshOnes, newestId, popupText, type Popup } from './popups'

const p = (id: number, over: Partial<Popup> = {}): Popup => ({ id, title: `T${id}`, body: '', tone: 'info', read: false, ...over })

describe('pop-ups for notifications', () => {
  it('show only what is newer than the last one shown, oldest first', () => {
    expect(freshOnes([p(9), p(7), p(8), p(5)], 7).map((x) => x.id)).toEqual([8, 9])
  })
  it('skip what has been read already', () => {
    expect(freshOnes([p(8, { read: true }), p(9)], 5).map((x) => x.id)).toEqual([9])
  })
  it('show nothing the first time a person is seen on a device, so old unread ones do not pour in', () => {
    expect(freshOnes([p(1), p(2)], null)).toEqual([])
  })
  it('know the newest id, and join the title with what it says', () => {
    expect(newestId([p(3), p(12), p(7)])).toBe(12)
    expect(newestId([])).toBe(0)
    expect(popupText(p(1, { title: 'Low stock', body: '12 bags left' }))).toBe('Low stock - 12 bags left')
    expect(popupText(p(1))).toBe('T1')
  })
  it('cap how many appear at once', () => { expect(MOST_AT_ONCE).toBe(3) })
})
