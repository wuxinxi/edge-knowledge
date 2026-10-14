// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '../../app/App.vue'
import ChatView from './ChatView.vue'
import { useLayoutStore } from '../../app/layout'
import { useChatStore } from './store'
import { memoryStorage } from '../../shared/preferences/test-storage'
import { api } from '../../shared/api/client'

vi.mock('../../app/store', () => ({
  useAppStore: () => ({ activeLibrary: 'default', libraries: [], health: {}, initialize: vi.fn() }),
}))
vi.mock('../../shared/api/client', () => ({
  api: {
    documents: vi.fn().mockResolvedValue([]),
    localQuery: vi.fn().mockResolvedValue({
      kind: 'retrieval',
      sources: [],
      content: '没有找到相关资料',
      notice: '本地检索',
    }),
    query: vi.fn(async function* () {
      yield { type: 'execution', location: 'local', generator: 'local' }
      yield { type: 'delta', delta: '本地模型回答' }
      yield { type: 'done' }
    }),
    loadChatState: vi
      .fn()
      .mockResolvedValue({ version: 1, initialized: false, revision: 0, sessions: [], active: {} }),
    saveChatState: vi.fn().mockResolvedValue({ revision: 1 }),
  },
}))
let cleanup = () => {}
beforeEach(() => {
  vi.clearAllMocks()
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: vi.fn() })
  Object.defineProperty(HTMLDialogElement.prototype, 'close', {
    configurable: true,
    value: vi.fn(),
  })
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal(
    'matchMedia',
    vi
      .fn()
      .mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})
async function mountShell(withChat = false) {
  const pinia = createPinia()
  const store = useChatStore(pinia)
  const layout = useLayoutStore(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: ['/', '/library', '/semantic', '/access', '/settings'].map((path) => ({
      path,
      component: withChat && path === '/' ? ChatView : { template: '<div class="test-page" />' },
    })),
  })
  await router.push('/')
  const root = document.createElement('div')
  document.body.append(root)
  const view = createApp(App).use(pinia).use(router)
  view.mount(root)
  cleanup = () => {
    view.unmount()
    root.remove()
  }
  await new Promise((resolve) => setTimeout(resolve, 0))
  return { root, store, layout, router }
}
it('creates a conversation after deleting the last one and prevents duplicate drafts from both entry points', async () => {
  const { root, store } = await mountShell()
  const session = store.create('default')
  store.remove(session.id)
  await nextTick()
  const button = root.querySelector<HTMLButtonElement>('.sidebar-new-chat')!
  const railButton = root.querySelector<HTMLButtonElement>('.rail-new-chat')!
  expect(button.disabled).toBe(false)
  expect(railButton.disabled).toBe(false)
  railButton.click()
  await nextTick()
  expect(store.list('default')).toHaveLength(1)
  expect(button.disabled).toBe(true)
  expect(railButton.disabled).toBe(true)
  button.click()
  railButton.click()
  expect(store.list('default')).toHaveLength(1)
})
it('keeps all route icons operable and highlights the current page while collapsed', async () => {
  const { root, layout, router } = await mountShell()
  root.querySelector<HTMLButtonElement>('.sidebar-toggle')!.click()
  await nextTick()
  expect(layout.sidebarCollapsed).toBe(true)
  expect(root.querySelector<HTMLElement>('#app-sidebar')!.style.display).toBe('none')
  for (const path of ['/library', '/semantic', '/access', '/settings', '/']) {
    const link = root.querySelector<HTMLAnchorElement>(`.app-rail a[href="${path}"]`)!
    expect(link.getAttribute('aria-label')).toBeTruthy()
    link.click()
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(router.currentRoute.value.path).toBe(path)
    expect(link.classList.contains('active')).toBe(true)
    expect(root.querySelectorAll('.app-rail a.active')).toHaveLength(1)
    expect(layout.sidebarCollapsed).toBe(true)
  }
})
it('reveals history or library controls with focus and remembers the collapsed state', async () => {
  const { root, layout } = await mountShell()
  const toggle = root.querySelector<HTMLButtonElement>('.sidebar-toggle')!
  toggle.click()
  await nextTick()
  expect(document.activeElement).toBe(toggle)
  expect(JSON.parse(localStorage.getItem('edge-assistant.layout.v1')!).sidebarCollapsed).toBe(true)
  root.querySelector<HTMLButtonElement>('.app-rail button[aria-label="最近对话"]')!.click()
  await nextTick()
  expect(layout.sidebarCollapsed).toBe(false)
  expect(document.activeElement).toBe(root.querySelector('.conversation-search'))
  toggle.click()
  await nextTick()
  root.querySelector<HTMLButtonElement>('.app-rail button[aria-label^="当前知识库"]')!.click()
  await nextTick()
  expect(document.activeElement).toBe(root.querySelector('#active-library'))
})
it('supports the collapse shortcut and dismisses the small-window navigation with Escape', async () => {
  const { root, layout } = await mountShell()
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', metaKey: true }))
  await nextTick()
  expect(layout.sidebarCollapsed).toBe(true)
  expect(document.activeElement).toBe(root.querySelector('.sidebar-toggle'))
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', metaKey: true }))
  await nextTick()
  expect(layout.sidebarCollapsed).toBe(false)
  vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await nextTick()
  expect(layout.sidebarCollapsed).toBe(true)
})
it('closes the narrow navigation after selecting a conversation even when already on the chat route', async () => {
  const { root, layout, store, router } = await mountShell()
  store.create('default')
  await nextTick()
  vi.mocked(window.matchMedia).mockReturnValue({ matches: true } as MediaQueryList)
  root.querySelector<HTMLButtonElement>('.conversation-select')!.click()
  await nextTick()
  expect(router.currentRoute.value.path).toBe('/')
  expect(layout.sidebarCollapsed).toBe(true)
})

it('shows a single new-chat entry and reserves the expanded sidebar for library and conversations', async () => {
  const { root, layout } = await mountShell()
  expect(root.querySelector('#app-sidebar .navigation')).toBeNull()
  expect(root.querySelector('.conversation-heading button')).toBeNull()
  const rail = root.querySelector<HTMLElement>('.rail-new-chat')!
  expect(rail.style.display).toBe('none')
  layout.sidebarCollapsed = true
  await nextTick()
  expect(rail.style.display).not.toBe('none')
  expect(root.querySelector<HTMLElement>('#app-sidebar')!.style.display).toBe('none')
})

it('keeps the first request running when sending directly from a home page with no saved conversation', async () => {
  const { root, store } = await mountShell(true)
  expect(store.current('default')).toBeUndefined()
  const input = root.querySelector<HTMLTextAreaElement>('.composer textarea')!
  input.value = '查询本地资料'
  input.dispatchEvent(new Event('input'))
  await nextTick()
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(store.current('default')!.messages.at(-1)?.status).toBe('complete')
  expect(store.activeTask?.state).toBe('success')
})

it('restores unfinished questions and their modes after switching chats and leaving the page', async () => {
  const { root, store, router } = await mountShell(true)
  await store.ask('default', '第一段对话', 'search')
  const first = store.current('default')!
  let input = root.querySelector<HTMLTextAreaElement>('.composer textarea')!
  const write = async (value: string) => {
    input.value = value
    input.dispatchEvent(new Event('input'))
    await nextTick()
  }
  root.querySelector<HTMLButtonElement>('.mode-selector button')!.click()
  await write('  继续查找\n还没写完  ')
  expect(root.querySelector('.conversation-draft')?.textContent).toBe('草稿')
  const second = store.create('default')
  await nextTick()
  expect(input.value).toBe('')
  await write('第二个未发送问题')
  store.select('default', first.id)
  await nextTick()
  expect(input.value).toBe('  继续查找\n还没写完  ')
  expect(root.querySelector('.mode-selector button')?.getAttribute('aria-pressed')).toBe('true')
  await router.push('/library')
  await nextTick()
  await router.push('/')
  await nextTick()
  input = root.querySelector<HTMLTextAreaElement>('.composer textarea')!
  expect(input.value).toBe('  继续查找\n还没写完  ')
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(input.value).toBe('')
  expect(first.messages.at(-2)?.content).toBe('  继续查找\n还没写完  ')
  expect(second.draft?.content).toBe('第二个未发送问题')
  await write('/new')
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(store.current('default')!.id).toBe(second.id)
  expect(input.value).toBe('第二个未发送问题')
  expect(first.draft).toBeUndefined()
})

it('puts an empty-result question back in the composer without sending or overwriting a draft', async () => {
  const { root, store } = await mountShell(true)
  const original = '  查找会议笔记\n保留原始换行  '
  await store.ask('default', original, 'search')
  await nextTick()
  const edit = root.querySelector<HTMLButtonElement>('.empty-search-actions button')!
  expect(edit.disabled).toBe(false)
  edit.click()
  await nextTick()
  const input = root.querySelector<HTMLTextAreaElement>('.composer textarea')!
  expect(input.value).toBe(original)
  expect(document.activeElement).toBe(input)
  expect(root.querySelector('.mode-selector button')?.getAttribute('aria-pressed')).toBe('true')
  expect(api.localQuery).toHaveBeenCalledOnce()
  expect(api.query).not.toHaveBeenCalled()
  input.value = '我正在写的另一份问题'
  input.dispatchEvent(new Event('input'))
  await nextTick()
  expect(edit.disabled).toBe(true)
  edit.click()
  expect(input.value).toBe('我正在写的另一份问题')
  expect(store.current('default')!.messages).toHaveLength(2)
})

it('retains the chosen lookup mode after the first draft is sent and restored after navigation', async () => {
  const { root, router } = await mountShell(true)
  root.querySelector<HTMLButtonElement>('.mode-selector button')!.click()
  const input = root.querySelector<HTMLTextAreaElement>('.composer textarea')!
  input.value = '查找会议笔记'
  input.dispatchEvent(new Event('input'))
  // Sending before the next render also exercises first-draft navigation.
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(input.value).toBe('')
  expect(root.querySelector('.mode-selector button')?.getAttribute('aria-pressed')).toBe('true')
  expect(api.localQuery).toHaveBeenCalledOnce()
  expect(api.query).not.toHaveBeenCalled()
  await router.push('/library')
  await router.push('/')
  await nextTick()
  expect(root.querySelector('.mode-selector button')?.getAttribute('aria-pressed')).toBe('true')
})
