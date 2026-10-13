// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import QueryBuilder from './QueryBuilder.vue'
import { buildQuery, type QueryDraft } from './query-builder'
import { memoryStorage } from '../../shared/preferences/test-storage'

let root: HTMLDivElement, view: ReturnType<typeof createApp>
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value() {
      this.open = true
    },
  })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value() {
      this.open = false
    },
  })
})
afterEach(() => {
  view?.unmount()
  root?.remove()
  vi.unstubAllGlobals()
})

it('opens a centered native dialog and submits local count conditions without any API planning', async () => {
  const execute = vi.fn()
  root = document.createElement('div')
  document.body.append(root)
  view = createApp(QueryBuilder, { onExecute: execute }).use(createPinia())
  view.mount(root)
  root.querySelector<HTMLButtonElement>('.query-builder-trigger')!.click()
  await nextTick()
  expect(document.querySelector('dialog')!.open).toBe(true)
  document
    .querySelector('form')!
    .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await nextTick()
  expect(execute.mock.calls[0]![0]).toMatchObject({
    operation: 'aggregate',
    where: { all: [{ field: 'kind', op: 'eq', value: 'document' }] },
    metric: 'count',
  })
  expect(execute.mock.calls[0]![1]).toContain('统计资料数量')
  expect(document.querySelector('dialog')!.open).toBe(false)
  expect(document.body.textContent).toContain('不调用 API')
})

it('rejects incomplete or invalid numeric conditions instead of executing a broader query', () => {
  const draft: QueryDraft = {
    operation: 'aggregate',
    logic: 'all',
    filters: [{ field: 'size', op: 'gte', value: 'not a number', custom: '' }],
    metric: 'count',
    metricField: 'size',
    group: '',
    date: 'authored_date',
    order: 'title',
    descending: false,
    limit: 20,
    offset: 0,
  }
  expect(() => buildQuery(draft)).toThrow('数值')
  draft.filters[0]!.value = ''
  expect(() => buildQuery(draft)).toThrow('空条件')
  draft.filters[0] = { field: 'metadata', op: 'gt', value: '2.5', custom: 'hours' }
  expect(buildQuery(draft).where!.all![0]).toEqual({
    field: 'metadata.hours',
    op: 'gt',
    value: 2.5,
  })
})
