import { expect, it } from 'vitest'
import { followsLatest } from './scroll'
it('does not pull a reader back when they scroll within a long local result', () => {
  expect(followsLatest(700, -300)).toBe(false)
  expect(followsLatest(600, 200)).toBe(false)
  expect(followsLatest(400, 16)).toBe(true)
  expect(followsLatest(40)).toBe(true)
  expect(followsLatest(200)).toBe(false)
})
