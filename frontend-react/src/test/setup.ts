import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// jsdom has no layout, so every box is 0x0 and a virtualised list would draw
// nothing. Give elements a fixed size instead.
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 480 })
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 1000 })
Element.prototype.getBoundingClientRect = function () {
  return { x: 0, y: 0, top: 0, left: 0, right: 1000, bottom: 480, width: 1000, height: 480, toJSON() {} } as DOMRect
}
Element.prototype.scrollIntoView = function () {}
Element.prototype.scrollTo = function () {}
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
