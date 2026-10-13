// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import QueryBuilder from './QueryBuilder.vue'
import {
  applyQueryPreset,
  buildQuery,
  defaultQueryDraft,
  monthRange,
  operatorLabel,
  queryLabel,
  type QueryDraft,
} from './query-builder'
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

async function mountBuilder() {
  const execute = vi.fn()
  root = document.createElement('div')
  document.body.append(root)
  view = createApp(QueryBuilder, { onExecute: execute, scopeLabel: '演示笔记库' }).use(
    createPinia(),
  )
  view.mount(root)
  root.querySelector<HTMLButtonElement>('.query-builder-trigger')!.click()
  await nextTick()
  return execute
}
it('compiles a selected calendar month and tag grouping from the quick start without planning', async () => {
  const execute = await mountBuilder()
  const button = [...document.querySelectorAll<HTMLButtonElement>('.qb-presets button')].find((b) =>
    b.textContent?.includes('按月份'),
  )!
  button.click()
  await nextTick()
  const month = document.querySelector<HTMLInputElement>('input[type="month"]')!
  month.value = '2026-09'
  month.dispatchEvent(new Event('input', { bubbles: true }))
  const group = [...document.querySelectorAll<HTMLSelectElement>('.qb-fields select')].find(
    (select) => select.closest('label')?.textContent?.includes('分别统计'),
  )!
  group.value = 'tags'
  group.dispatchEvent(new Event('change', { bubbles: true }))
  await nextTick()
  document
    .querySelector('form')!
    .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await nextTick()
  expect(execute.mock.calls[0]![0]).toMatchObject({
    operation: 'aggregate',
    group_by: 'tags',
    where: {
      all: [
        { all: [{ field: 'kind', op: 'eq', value: 'document' }] },
        { field: 'created_date', op: 'gte', value: '2026-09-01' },
        { field: 'created_date', op: 'lt', value: '2026-10-01' },
      ],
    },
  })
  expect(execute.mock.calls[0]![1]).toContain('2026-09')
  expect(document.body.textContent).toContain('演示笔记库')
})
it('never widens a month restriction when the additional filter relation changes to any', () => {
  const draft = defaultQueryDraft()
  applyQueryPreset(draft, 'month', '2026-12')
  draft.logic = 'any'
  const plan = buildQuery(draft)
  expect(plan.where!.all!.slice(1)).toEqual([
    { field: 'created_date', op: 'gte', value: '2026-12-01' },
    { field: 'created_date', op: 'lt', value: '2027-01-01' },
  ])
  expect(plan.where!.all![0]!.any).toHaveLength(1)
  expect(monthRange('0001-01')).toEqual(['0001-01-01', '0001-02-01'])
  expect(() => monthRange('2026-13')).toThrow('有效月份')
})
it('removes stale hidden aggregate fields on switching to file lookup and validates paging', () => {
  const draft = defaultQueryDraft()
  draft.metric = 'sum'
  draft.metricField = ''
  draft.group = 'tags'
  draft.order = 'value'
  expect(() => buildQuery(draft)).toThrow('字段名称')
  draft.operation = 'list'
  expect(buildQuery(draft)).toMatchObject({
    metric: 'count',
    metric_field: 'size',
    group_by: '',
    order_by: 'title',
  })
  draft.limit = 0
  expect(() => buildQuery(draft)).toThrow('展示数量')
  draft.limit = 20
  draft.offset = -1
  expect(() => buildQuery(draft)).toThrow('展示数量')
})
it('preserves comparisons, missing-property queries and explicit operator descriptions', () => {
  const draft = defaultQueryDraft()
  applyQueryPreset(draft, 'undated', '2026-09')
  expect(buildQuery(draft)).toMatchObject({
    operation: 'list',
    where: { all: expect.arrayContaining([{ field: 'created_date', op: 'missing' }]) },
  })
  expect(queryLabel(draft)).toContain('创建日期 未标注')
  expect(operatorLabel('created_date', 'lt')).toBe('早于')
  applyQueryPreset(draft, 'duplicates', '2026-09')
  expect(buildQuery(draft)).toMatchObject({ operation: 'duplicates', threshold: 0.9 })
  draft.threshold = 1.1
  expect(() => buildQuery(draft)).toThrow('相似度')
})

it('accepts typed numeric controls and keeps any-match grouping explicit in the preview', async () => {
  const execute = await mountBuilder()
  document.querySelector<HTMLButtonElement>('.qb-section-heading button')!.click()
  await nextTick()
  const rows = document.querySelectorAll('.qb-condition')
  const field = rows[1]!.querySelector<HTMLSelectElement>('select')!
  field.value = 'size'
  field.dispatchEvent(new Event('change', { bubbles: true }))
  await nextTick()
  const value = rows[1]!.querySelector<HTMLInputElement>('input')!
  expect(value.type).toBe('number')
  value.value = '2.5'
  value.dispatchEvent(new Event('input', { bubbles: true }))
  await nextTick()
  document
    .querySelector('form')!
    .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  await nextTick()
  expect(execute.mock.calls[0]![0].where.all[1]).toMatchObject({ field: 'size', value: 2.5 })
  const draft = defaultQueryDraft()
  applyQueryPreset(draft, 'month', '2026-09')
  draft.logic = 'any'
  draft.filters.push({ field: 'tags', op: 'eq', value: '工作', custom: '' })
  expect(queryLabel(draft)).toContain('2026-09 且 (资料类型 等于 文档 或 标签 等于 工作)')
})
