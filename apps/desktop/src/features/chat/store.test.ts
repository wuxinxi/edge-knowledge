import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../../shared/api/client'
import { useChatStore, boundedHistory } from './store'
import { memoryStorage } from '../../shared/preferences/test-storage'

vi.mock('../../shared/api/client', () => ({ api: { search: vi.fn(), query: vi.fn() } }))
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

it('local search shows evidence without calling cloud generation', async () => {
  vi.mocked(api.search).mockResolvedValue([
    {
      document_id: 'doc-1',
      filename: 'plan.md',
      text: '项目计划',
      section: '计划',
      index: 0,
      score: 0.9,
    },
  ])
  const store = useChatStore()
  await store.ask('library-one', '项目计划', 'search')
  expect(api.query).not.toHaveBeenCalled()
  expect(store.conversations['library-one']![1]!.sources[0]!.filename).toBe('plan.md')
  expect(store.conversations['library-one']![1]!.content).toContain('1 个相关片段')
  expect(store.conversations['library-two']).toBeUndefined()
  expect(store.busy).toBe(false)
})

it('empty local search explains the result without pretending to generate an answer', async () => {
  vi.mocked(api.search).mockResolvedValue([])
  const store = useChatStore()
  await store.ask('default', '没有的资料', 'search')
  expect(store.conversations.default![1]!.content).toContain('没有找到相关资料')
  expect(api.query).not.toHaveBeenCalled()
})

it('stopping a pending search cancels its transport and clears the busy state', async () => {
  vi.mocked(api.search).mockImplementation(
    (_library, _question, signal) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError')))
      }),
  )
  const store = useChatStore()
  const pending = store.ask('default', '项目计划', 'search')
  store.stop()
  await pending
  expect(store.busy).toBe(false)
  expect(store.conversations.default![1]!.error).toBe('已停止。')
})

it('does not authorize image upload by default and surfaces the backend evidence notice', async () => {
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'sources', sources: [] }
    yield { type: 'notice', message: '图片仅通过本地 OCR 处理' }
    yield { type: 'delta', delta: '文字答案' }
    yield { type: 'done' }
  })
  const store = useChatStore()
  await store.ask('default', '截图里的文字？', 'chat')
  expect(api.query).toHaveBeenCalledWith(
    'default',
    '截图里的文字？',
    expect.any(AbortSignal),
    false,
    { documentIds: [], history: [] },
  )
  expect(store.conversations.default![1]!.notice).toBe('图片仅通过本地 OCR 处理')
})

it('an explicit image authorization applies to that request only', async () => {
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'done' }
  })
  const store = useChatStore()
  await store.ask('default', '看这张图', 'chat', true)
  await store.ask('default', '下一个问题', 'chat')
  expect(vi.mocked(api.query).mock.calls.map((call) => call[3])).toEqual([true, false])
})

it('keeps separate chats, persists them, and restores the selected chat after restart', async () => {
  vi.mocked(api.search).mockResolvedValue([])
  const store = useChatStore()
  await store.ask('default', '第一段对话', 'search')
  const first = store.current('default')!.id
  store.create('default')
  await store.ask('default', '另一段对话', 'search')
  expect(store.list('default')).toHaveLength(2)
  store.select('default', first)
  expect(store.current('default')!.messages[0]!.content).toBe('第一段对话')
  store.rename(first, '架构讨论')
  setActivePinia(createPinia())
  const restored = useChatStore()
  expect(restored.current('default')!.title).toBe('架构讨论')
  expect(restored.current('default')!.messages).toHaveLength(2)
  expect(restored.list('another-library')).toHaveLength(0)
})

it('deletes and restores a conversation without changing its references or messages', async () => {
  vi.mocked(api.search).mockResolvedValue([])
  const store = useChatStore()
  const session = store.create('default')
  store.setReferences('default', [{ id: 'a'.repeat(64), filename: 'plan.md' }])
  await store.ask('default', 'plan', 'search')
  store.remove(session.id)
  expect(store.current('default')).toBeUndefined()
  expect(store.list('default')).toHaveLength(0)
  store.undoDelete()
  expect(store.current('default')!.messages[0]!.content).toBe('plan')
  expect(store.current('default')!.references[0]!.filename).toBe('plan.md')
})

it('sends only the current conversation history and selected file references', async () => {
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'delta', delta: '回答' }
    yield { type: 'done' }
  })
  const store = useChatStore()
  store.setReferences('default', [{ id: 'b'.repeat(64), filename: 'guide.md' }])
  await store.ask('default', '第一问', 'chat')
  await store.ask('default', '继续解释', 'chat')
  expect(vi.mocked(api.query).mock.calls[1]![4]).toEqual({
    documentIds: ['b'.repeat(64)],
    history: [
      { role: 'user', content: '第一问' },
      { role: 'assistant', content: '回答' },
    ],
  })
  store.create('default')
  await store.ask('default', '新话题', 'chat')
  expect(vi.mocked(api.query).mock.calls[2]![4]).toEqual({ documentIds: [], history: [] })
})

it('bounds history and omits local search results from cloud context', () => {
  const messages = Array.from({ length: 20 }, (_, i) => ({
    id: String(i),
    role: i % 2 ? ('assistant' as const) : ('user' as const),
    content: 'x'.repeat(7000),
    sources: [],
    mode: 'chat' as const,
  }))
  const history = boundedHistory(messages)
  expect(history.reduce((n, item) => n + item.content.length, 0)).toBeLessThanOrEqual(24000)
  expect(history[0]!.role).toBe('user')
  expect(history.at(-1)!.role).toBe('assistant')
  expect(boundedHistory(messages.map((item) => ({ ...item, mode: 'search' })))).toEqual([])
})

it('surfaces storage errors while allowing an in-memory chat to continue', async () => {
  vi.mocked(api.search).mockResolvedValue([])
  vi.stubGlobal('localStorage', {
    getItem: () => null,
    setItem: () => {
      throw new Error('quota')
    },
  })
  const store = useChatStore()
  await store.ask('default', '保留内容', 'search')
  expect(store.current('default')!.messages[0]!.content).toBe('保留内容')
  expect(store.savingError).toContain('导出备份')
})

it('cancels a pending answer when opening a new conversation without moving its messages', async () => {
  vi.mocked(api.query).mockImplementation(async function* (_library, _question, signal) {
    await new Promise((_resolve, reject) =>
      signal.addEventListener('abort', () => reject(new DOMException('Cancelled', 'AbortError'))),
    )
    yield { type: 'done' }
  })
  const store = useChatStore()
  const pending = store.ask('default', '旧对话的问题', 'chat')
  const old = store.current('default')!
  store.create('default')
  await pending
  expect(store.current('default')!.messages).toEqual([])
  expect(old.messages[1]!.error).toBe('已停止。')
  expect(store.busy).toBe(false)
})

it('merges restored conversations and persists them without replacing originals', () => {
  const store = useChatStore()
  const original = store.create('default')
  const restored = {
    ...original,
    id: 'restored-chat',
    library: 'restored-library',
    title: 'Restored',
  }
  store.importConversations([restored])
  expect(store.list('default')).toHaveLength(1)
  expect(store.list('restored-library')).toHaveLength(1)
  setActivePinia(createPinia())
  expect(useChatStore().current('restored-library')!.id).toBe('restored-chat')
})
it('keeps existing conversations intact when restored chats exceed storage quota', () => {
  const store = useChatStore()
  const original = store.create('default')
  vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
    throw new Error('quota')
  })
  expect(() =>
    store.importConversations([{ ...original, id: 'restored-chat', library: 'restored-library' }]),
  ).toThrow('quota')
  expect(store.sessions).toHaveLength(1)
  expect(store.current('default')!.id).toBe(original.id)
  expect(store.current('restored-library')).toBeUndefined()
})

it('reuses the current unstarted conversation across repeated new-chat actions', () => {
  const store = useChatStore()
  const first = store.create('default')
  store.setReferences('default', [{ id: 'selected-document', filename: 'notes.md' }])
  for (let i = 0; i < 10; i++) expect(store.create('default').id).toBe(first.id)
  expect(store.list('default')).toHaveLength(1)
  expect(store.current('default')!.references).toEqual([
    { id: 'selected-document', filename: 'notes.md' },
  ])
})

it('regenerates only the latest answer with its original references and bounded prior history', async () => {
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'delta', delta: 'Answer' }
    yield { type: 'done' }
  })
  const store = useChatStore()
  await store.ask('default', 'First question', 'chat')
  const firstAnswer = store.current('default')!.messages[1]!.id
  store.setReferences('default', [{ id: 'c'.repeat(64), filename: 'notes.md' }])
  await store.ask('default', 'Latest question', 'chat', true)
  const answer = store.current('default')!.messages.at(-1)!
  const count = store.current('default')!.messages.length
  await store.retry('default', firstAnswer)
  expect(api.query).toHaveBeenCalledTimes(2)
  await store.retry('default', answer.id)
  expect(store.current('default')!.messages).toHaveLength(count)
  expect(vi.mocked(api.query).mock.calls.at(-1)![3]).toBe(false)
  expect(vi.mocked(api.query).mock.calls.at(-1)![4]).toEqual({
    documentIds: ['c'.repeat(64)],
    history: [
      { role: 'user', content: 'First question' },
      { role: 'assistant', content: 'Answer' },
    ],
  })
})

it('preserves the previous answer when regeneration fails', async () => {
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'delta', delta: 'Keep this answer' }
    yield { type: 'done' }
  })
  const store = useChatStore()
  await store.ask('default', 'Question', 'chat')
  const answer = store.current('default')!.messages.at(-1)!
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'error', message: 'Transport failure' }
  })
  await store.retry('default', answer.id)
  expect(answer.content).toBe('Keep this answer')
  expect(answer.notice).toContain('保留上次回答')
  expect(answer.error).toBe('Transport failure')
})
