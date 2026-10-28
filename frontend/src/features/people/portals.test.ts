import { describe, expect, it } from 'vitest'
import type { Portal } from '@/api/people'
import { levelOf, withLevel } from './portals'

const store: Portal = { code: 'store', label: 'Store', blurb: '', read: ['store.view'], write: ['items.manage', 'purchase.manage'] }
const money: Portal = { code: 'money', label: 'Money', blurb: '', read: ['money.view', 'bills.view_all'], write: ['bills.pay'] }
const people: Portal = { code: 'people', label: 'People', blurb: '', read: ['people.manage'], write: ['payroll.manage', 'recruitment.manage', 'attendance.view_team', 'leave.approve'] }

describe('where a person stands on a portal', () => {
  it('is no access without the view right, whatever write rights are held', () => {
    expect(levelOf(store, new Set(['items.manage']))).toBe('none')
  })
  it('is read only with the view right alone', () => {
    expect(levelOf(store, new Set(['store.view']))).toBe('read')
  })
  it('is read and write once any write right is held', () => {
    expect(levelOf(store, new Set(['store.view', 'purchase.manage']))).toBe('write')
  })
  it('is no access on the People portal without people.manage', () => {
    expect(levelOf(people, new Set(['payroll.manage']))).toBe('none')
  })
  it('is read and write on the People portal once a write right is held', () => {
    expect(levelOf(people, new Set(['people.manage']))).toBe('read')
    expect(levelOf(people, new Set(['people.manage', 'payroll.manage']))).toBe('write')
  })
})

describe('setting a portal', () => {
  const held = ['self.service', 'bills.approve', 'store.view', 'items.manage', 'money.view', 'bills.view_all']
  it('to read only keeps the view right and drops the write rights', () => {
    expect(withLevel(held, store, 'read').sort()).toEqual(['bills.approve', 'bills.view_all', 'money.view', 'self.service', 'store.view'])
  })
  it('to read and write grants the view and every write right', () => {
    expect(withLevel(['self.service'], store, 'write').sort()).toEqual(['items.manage', 'purchase.manage', 'self.service', 'store.view'])
  })
  it('to no access takes all of the portal away and leaves everything else', () => {
    expect(withLevel(held, store, 'none').sort()).toEqual(['bills.approve', 'bills.view_all', 'money.view', 'self.service'])
  })
  it('never moves another portal', () => {
    const after = withLevel(held, store, 'write')
    expect(levelOf(money, new Set(after))).toBe(levelOf(money, new Set(held)))
  })
  it('does not grow the list when set to the level it already holds', () => {
    const once = withLevel(held, store, 'write')
    expect(withLevel(once, store, 'write').sort()).toEqual(once.sort())
  })
  it('sets the People portal on its own rights and leaves the rest', () => {
    const after = withLevel(held, people, 'write')
    expect(after.sort()).toEqual([...held, 'people.manage', 'payroll.manage', 'recruitment.manage', 'attendance.view_team', 'leave.approve'].sort())
    expect(withLevel(after, people, 'none').sort()).toEqual([...held].sort())
  })
})
