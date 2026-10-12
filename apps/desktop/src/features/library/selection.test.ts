import { expect, it } from 'vitest'
import { toggleVisibleSelection } from './selection'
it('keeps hidden and previous-page selections when toggling filtered results', () => {
  const original = ['other-page']
  const selected = toggleVisibleSelection(original, ['first', 'second'])
  expect(original).toEqual(['other-page'])
  expect(new Set(selected)).toEqual(new Set(['other-page', 'first', 'second']))
  expect(toggleVisibleSelection(selected, ['first', 'second'])).toEqual(['other-page'])
  expect(toggleVisibleSelection(selected, [])).toEqual(selected)
})
