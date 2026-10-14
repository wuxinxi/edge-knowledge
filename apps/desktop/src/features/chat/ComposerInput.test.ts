// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick, reactive } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ComposerInput from './ComposerInput.vue'
import { api } from '../../shared/api/client'
import type { ReferenceChoice, ReferenceChoices } from '../../shared/types/api'
import type { Reference } from './store'
import { memoryStorage } from '../../shared/preferences/test-storage'

vi.mock('../../shared/api/client', () => ({ api: { referenceChoices: vi.fn() } }))
let root: HTMLDivElement, view: ReturnType<typeof createApp>
const choice = (id: string, title: string, path: string): ReferenceChoice => ({
  document_id: id,
  title,
  path,
  filename: 'index.md',
  kind: 'document',
})
const page = (items: ReferenceChoice[], total = items.length, offset = 0): ReferenceChoices => ({
  items,
  total,
  offset,
  limit: 20,
})
const deploy = choice('a', '项目部署手册', '项目/部署/index.md')
const shopping = choice('b', '本周采购清单', '生活/采购/index.md')
beforeEach(() => {
  vi.useFakeTimers()
  vi.resetAllMocks()
  vi.stubGlobal('localStorage', memoryStorage())
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(),
  })
  vi.mocked(api.referenceChoices).mockResolvedValue(page([deploy, shopping]))
})
afterEach(() => {
  view?.unmount()
  root?.remove()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
async function mount(references: Reference[] = []) {
  const state = reactive({
    modelValue: '  待发送的追问  ',
    library: 'default',
    references,
    mode: 'search' as const,
    disabled: false,
    busy: false,
    canCreateConversation: true,
  })
  const send = vi.fn()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  await router.push('/')
  root = document.createElement('div')
  document.body.append(root)
  view = createApp({
    components: { ComposerInput },
    setup: () => ({ state, send }),
    template:
      '<form @submit.prevent="send"><ComposerInput v-bind="state" @update:model-value="state.modelValue = $event" @references="state.references = $event" @send="send" /></form>',
  })
    .use(createPinia())
    .use(router)
  view.mount(root)
  await nextTick()
  return { state, send }
}
async function settle() {
  await vi.advanceTimersByTimeAsync(180)
  await nextTick()
}
async function open() {
  root.querySelector<HTMLButtonElement>('.composer-reference-toolbar button')!.click()
  await nextTick()
  await settle()
}
async function search(value: string) {
  const input = root.querySelector<HTMLInputElement>('.reference-picker-search input')!
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
  await nextTick()
  return input
}
it('loads only on opening and distinguishes equal filenames by title and path without changing a draft', async () => {
  const { state } = await mount()
  expect(api.referenceChoices).not.toHaveBeenCalled()
  await open()
  expect(document.activeElement).toBe(root.querySelector('.reference-picker-search input'))
  expect(root.textContent).toContain('项目部署手册')
  expect(root.textContent).toContain('生活/采购/index.md')
  root.querySelector<HTMLButtonElement>('#composer-option-1')!.click()
  await nextTick()
  expect(state.references).toEqual([
    { id: 'b', filename: 'index.md', title: shopping.title, path: shopping.path },
  ])
  expect(state.modelValue).toBe('  待发送的追问  ')
  expect(root.querySelector('.reference-chip')?.textContent).toContain(shopping.title)
  expect(root.querySelector('.reference-chip')?.getAttribute('title')).toContain(shopping.path)
  expect(document.activeElement).toBe(root.querySelector('textarea'))
})
it('debounces local title/path searches and appends the next page with its actual offset', async () => {
  await mount()
  vi.mocked(api.referenceChoices).mockResolvedValueOnce(page([deploy], 2))
  await open()
  vi.mocked(api.referenceChoices).mockResolvedValueOnce(page([shopping], 2, 1))
  root.querySelector<HTMLButtonElement>('.reference-load-more')!.click()
  await nextTick()
  await settle()
  expect(api.referenceChoices).toHaveBeenLastCalledWith('default', '', 1, expect.any(AbortSignal))
  expect(root.querySelectorAll('[role="option"]')).toHaveLength(2)
  expect(root.querySelector('.reference-load-more')).toBeNull()
  await search('部')
  await search('部署')
  vi.mocked(api.referenceChoices).mockResolvedValueOnce(page([deploy]))
  await settle()
  expect(api.referenceChoices).toHaveBeenCalledTimes(3)
  expect(api.referenceChoices).toHaveBeenLastCalledWith(
    'default',
    '部署',
    0,
    expect.any(AbortSignal),
  )
})
it('discards late results after a search or library switch and aborts the earlier request', async () => {
  const { state } = await mount()
  let resolveOld!: (value: ReferenceChoices) => void
  vi.mocked(api.referenceChoices).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveOld = resolve
      }),
  )
  await open()
  const oldSignal = vi.mocked(api.referenceChoices).mock.calls[0]![3]
  await search('采购')
  expect(oldSignal.aborted).toBe(true)
  vi.mocked(api.referenceChoices).mockResolvedValueOnce(page([shopping]))
  await settle()
  resolveOld(page([deploy]))
  await settle()
  expect(root.textContent).not.toContain(deploy.title)
  expect(root.textContent).toContain(shopping.title)
  state.library = 'other'
  await nextTick()
  expect(root.querySelector('.composer-picker')).toBeNull()
  await open()
  expect(api.referenceChoices).toHaveBeenLastCalledWith('other', '', 0, expect.any(AbortSignal))
})
it('retries a failed page and never sends a question by pressing Enter in an empty reference search', async () => {
  const { send } = await mount()
  vi.mocked(api.referenceChoices).mockRejectedValueOnce(new Error('本地目录读取失败'))
  await open()
  expect(root.querySelector('[role="alert"]')?.textContent).toContain('本地目录读取失败')
  root.querySelector<HTMLButtonElement>('.reference-picker-error button')!.click()
  await settle()
  expect(root.querySelectorAll('[role="option"]')).toHaveLength(2)
  const input = await search('不存在')
  vi.mocked(api.referenceChoices).mockResolvedValueOnce(page([]))
  await settle()
  const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
  input.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
  expect(send).not.toHaveBeenCalled()
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  await nextTick()
  expect(document.activeElement).toBe(root.querySelector('textarea'))
})
it('uses keyboard selection without adding an already selected file and clears scope without changing the draft', async () => {
  const { state } = await mount([
    { id: 'a', filename: 'index.md', title: deploy.title, path: deploy.path },
  ])
  await open()
  expect(root.querySelector<HTMLButtonElement>('#composer-option-0')!.disabled).toBe(true)
  const input = root.querySelector<HTMLInputElement>('.reference-picker-search input')!
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  input.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }),
  )
  await nextTick()
  expect(state.references.map((item) => item.id)).toEqual(['a', 'b'])
  root.querySelector<HTMLButtonElement>('.reference-scope-heading button')!.click()
  await nextTick()
  expect(state.references).toEqual([])
  expect(state.modelValue).toBe('  待发送的追问  ')
})
