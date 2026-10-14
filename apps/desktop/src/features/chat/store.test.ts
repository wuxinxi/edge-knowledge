import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '../../shared/api/client'
import { useChatStore, boundedHistory } from './store'
import { memoryStorage } from '../../shared/preferences/test-storage'

vi.mock('../../shared/api/client', () => ({
  api: { localQuery: vi.fn(), query: vi.fn(), loadChatState: vi.fn(), saveChatState: vi.fn() },
}))
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

it('local search shows evidence without calling cloud generation', async () => {
  vi.mocked(api.localQuery).mockResolvedValue({
    content: '找到 1 份相关资料，结果如下。',
    notice: '本地检索',
    sources: [
      {
        document_id: 'doc-1',
        filename: 'plan.md',
        text: '项目计划',
        section: '计划',
        index: 0,
        score: 0.9,
      },
    ],
  })
  const store = useChatStore()
  await store.ask('library-one', '项目计划', 'search')
  expect(api.query).not.toHaveBeenCalled()
  expect(store.conversations['library-one']![1]!.sources[0]!.filename).toBe('plan.md')
  expect(store.conversations['library-one']![1]!.content).toContain('1 份相关资料')
  expect(store.conversations['library-two']).toBeUndefined()
  expect(store.busy).toBe(false)
})

it('keeps exact drafts and modes isolated by conversation and library after reopening', async () => {
  vi.mocked(api.localQuery).mockResolvedValue({ content: '结果', sources: [], notice: '' })
  const store = useChatStore()
  await store.ask('default', '已发送的问题')
  const first = store.current('default')!
  const content = '  未发送的追问\n\n保留空白  '
  store.setDraft('default', content, 'search')
  const second = store.create('default')
  store.setDraft('default', '另一个话题', 'chat')
  store.setDraft('other-library', '另一资料库', 'search')
  store.select('default', first.id)
  expect(store.current('default')!.draft).toEqual({ content, mode: 'search' })
  expect(second.draft).toEqual({ content: '另一个话题', mode: 'chat' })
  setActivePinia(createPinia())
  const restored = useChatStore()
  expect(restored.current('default')!.draft).toEqual({ content, mode: 'search' })
  expect(restored.current('other-library')!.draft?.content).toBe('另一资料库')
  restored.remove(first.id)
  restored.undoDelete()
  expect(restored.current('default')!.draft?.content).toBe(content)
  expect(api.localQuery).toHaveBeenCalledTimes(1)
  expect(api.query).not.toHaveBeenCalled()
})

it('clears only the submitted draft and preserves drafts when local tools run', async () => {
  vi.mocked(api.localQuery).mockResolvedValue({ content: '结果', sources: [], notice: '' })
  const store = useChatStore()
  store.setDraft('default', '  写一半的问题\n', 'chat')
  await store.ask('default', '检查重复', 'search', false, { operation: 'duplicates' })
  expect(store.current('default')!.draft?.content).toBe('  写一半的问题\n')
  await store.ask('default', '  写一半的问题\n', 'search')
  expect(store.current('default')!.draft).toBeUndefined()
  expect(store.current('default')!.messages.at(-2)!.content).toBe('  写一半的问题\n')
  expect(vi.mocked(api.localQuery).mock.calls.at(-1)![1]).toBe('写一半的问题')
  setActivePinia(createPinia())
  expect(useChatStore().current('default')!.draft).toBeUndefined()
})

it('stores drafts in the durable snapshot and restores them without browser cache', async () => {
  vi.mocked(api.loadChatState).mockResolvedValue({
    version: 1,
    initialized: false,
    revision: 0,
    sessions: [],
    active: {},
  })
  let revision = 0
  vi.mocked(api.saveChatState).mockImplementation(async () => ({ revision: ++revision }))
  const store = useChatStore()
  await store.initialize()
  store.setDraft('default', '本地未发送草稿', 'search')
  await store.flush()
  const saved = vi.mocked(api.saveChatState).mock.calls.at(-1)![0]
  vi.mocked(api.loadChatState).mockResolvedValue({ ...saved, revision, initialized: true })
  localStorage.clear()
  setActivePinia(createPinia())
  const restored = useChatStore()
  await restored.initialize()
  expect(restored.current('default')!.draft).toEqual({ content: '本地未发送草稿', mode: 'search' })
  expect(restored.current('default')!.messages).toEqual([])
})

it('persists the full local statistics answer rather than replacing it with the preview count', async () => {
  const content = '2026 年 9 月匹配 **23 篇**。仅预览前 20 份依据。'
  vi.mocked(api.localQuery).mockResolvedValue({ content, sources: [], notice: '不调用 DeepSeek' })
  const store = useChatStore()
  await store.ask('default', '2026 年 9 月写了多少篇笔记')
  expect(store.current('default')!.messages[1]!.content).toBe(content)
  expect(store.current('default')!.messages[1]!.status).toBe('complete')
  expect(api.query).not.toHaveBeenCalled()
  setActivePinia(createPinia())
  expect(useChatStore().current('default')!.messages[1]!.content).toBe(content)
})

it('preserves structured query conditions across saving and retrying without switching on AI', async () => {
  vi.mocked(api.localQuery).mockResolvedValue({
    content: '匹配 2 篇',
    sources: [],
    notice: '本机统计',
  })
  const store = useChatStore()
  const plan = {
    operation: 'aggregate' as const,
    where: { field: 'tags', op: 'eq' as const, value: 'work' },
  }
  await store.ask('default', '按 work 标签统计', 'search', false, plan)
  const session = store.current('default')!
  expect(session.messages[0]!.queryPlan).toEqual(plan)
  await store.retry('default', session.messages[1]!.id)
  expect(api.localQuery).toHaveBeenLastCalledWith(
    'default',
    '按 work 标签统计',
    expect.any(AbortSignal),
    [],
    plan,
  )
  expect(api.query).not.toHaveBeenCalled()
  setActivePinia(createPinia())
  expect(useChatStore().current('default')!.messages[0]!.queryPlan).toEqual(plan)
})

it('empty local search explains the result without pretending to generate an answer', async () => {
  vi.mocked(api.localQuery).mockResolvedValue({
    sources: [],
    kind: 'retrieval',
    content: '暂时没有找到相关资料。',
    notice: '本次仅在本机检索，不调用 DeepSeek。',
  })
  const store = useChatStore()
  await store.ask('default', '没有的资料', 'search')
  expect(store.conversations.default![1]!.content).toContain('没有找到相关资料')
  expect(api.query).not.toHaveBeenCalled()
  setActivePinia(createPinia())
  expect(useChatStore().current('default')!.messages[1]!.resultKind).toBe('retrieval')
})

it('defaults to local search and persists the explicit local execution notice', async () => {
  vi.mocked(api.localQuery).mockResolvedValue({
    sources: [],
    content: '暂时没有找到相关资料。',
    notice: '本次仅在本机检索，不调用 DeepSeek。',
  })
  const store = useChatStore()
  await store.ask('default', '帮我检索本地图片')
  expect(api.query).not.toHaveBeenCalled()
  expect(store.current('default')!.messages[1]!.mode).toBe('search')
  expect(store.current('default')!.messages[1]!.notice).toContain('不调用 DeepSeek')
})

it('uses the backend execution event to label a locally answered query accurately', async () => {
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'sources', sources: [] }
    yield { type: 'execution', location: 'local', result_kind: 'retrieval' }
    yield { type: 'notice', message: '本次仅在本机检索' }
    yield { type: 'delta', delta: '没有找到相关资料。' }
    yield { type: 'done' }
  })
  const store = useChatStore()
  await store.ask('default', '帮我检索本地图片', 'chat')
  expect(store.current('default')!.messages[1]!.mode).toBe('search')
  expect(store.current('default')!.messages[1]!.status).toBe('complete')
  expect(store.current('default')!.messages[1]!.resultKind).toBe('retrieval')
})

it('stopping a pending search cancels its transport and clears the busy state', async () => {
  vi.mocked(api.localQuery).mockImplementation(
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
  vi.mocked(api.localQuery).mockResolvedValue({
    sources: [],
    content: '暂时没有找到相关资料。',
    notice: '本次仅在本机检索，不调用 DeepSeek。',
  })
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
  vi.mocked(api.localQuery).mockResolvedValue({
    sources: [],
    content: '暂时没有找到相关资料。',
    notice: '本次仅在本机检索，不调用 DeepSeek。',
  })
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
  vi.mocked(api.localQuery).mockResolvedValue({
    sources: [],
    content: '暂时没有找到相关资料。',
    notice: '本次仅在本机检索，不调用 DeepSeek。',
  })
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
it('keeps existing conversations intact when restored chats exceed storage quota', async () => {
  const store = useChatStore()
  const original = store.create('default')
  vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
    throw new Error('quota')
  })
  await expect(
    store.importConversations([{ ...original, id: 'restored-chat', library: 'restored-library' }]),
  ).rejects.toThrow('quota')
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

it('preserves original user whitespace and streams saved answer checkpoints', async () => {
  const question = '  请整理资料\n\n保留格式  '
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'delta', delta: '第一段\n\n' }
    const saved = JSON.parse(localStorage.getItem('edge-assistant.chats.v1')!)
    expect(saved.sessions[0].messages[1].content).toBe('第一段\n\n')
    yield { type: 'delta', delta: '第二段  ' }
    yield { type: 'done' }
  })
  const store = useChatStore()
  await store.ask('default', question, 'chat')
  expect(store.current('default')!.messages[0]!.content).toBe(question)
  expect(store.current('default')!.messages[1]!.content).toBe('第一段\n\n第二段  ')
  expect(store.current('default')!.messages[1]!.error).toBeUndefined()
})

it('replaces generic legacy chat titles with a concise topic summary', async () => {
  const store = useChatStore()
  const chat = store.create('default')
  chat.title = '新对话'
  vi.mocked(api.localQuery).mockResolvedValue({
    sources: [],
    content: '暂时没有找到相关资料。',
    notice: '本次仅在本机检索，不调用 DeepSeek。',
  })
  await store.ask('default', '帮我查询出威海荣成的 fpt 地址和用户名和密码是多少', 'search')
  expect(store.current('default')!.title).toBe('威海荣成 · FTP 连接信息')
})

it('migrates legacy records once and restores the database after clearing browser cache', async () => {
  vi.mocked(api.localQuery).mockResolvedValue({
    sources: [],
    content: '暂时没有找到相关资料。',
    notice: '本次仅在本机检索，不调用 DeepSeek。',
  })
  const legacy = useChatStore()
  await legacy.ask('default', '请帮我整理项目架构', 'search')
  let remote = {
    version: 1 as const,
    initialized: false,
    revision: 0,
    sessions: [] as typeof legacy.sessions,
    active: {},
  }
  vi.mocked(api.loadChatState).mockImplementation(async () => JSON.parse(JSON.stringify(remote)))
  vi.mocked(api.saveChatState).mockImplementation(async (value, revision) => {
    expect(revision).toBe(remote.revision)
    remote = { ...JSON.parse(JSON.stringify(value)), initialized: true, revision: revision + 1 }
    return { revision: remote.revision }
  })
  await legacy.initialize()
  expect(remote.sessions[0]!.title).toBe('项目架构')
  localStorage.removeItem('edge-assistant.chats.v1')
  setActivePinia(createPinia())
  const restored = useChatStore()
  await restored.initialize()
  expect(restored.current('default')!.messages).toEqual(legacy.current('default')!.messages)
  for (const chat of [...restored.sessions]) restored.remove(chat.id)
  await restored.flush()
  setActivePinia(createPinia())
  const empty = useChatStore()
  await empty.initialize()
  expect(empty.sessions).toEqual([])
  expect(empty.create('default')).toBeDefined()
  await empty.flush()
})

it('saves full streaming content despite browser quota and retains answer versions', async () => {
  vi.mocked(api.loadChatState).mockResolvedValue({
    version: 1,
    initialized: false,
    revision: 0,
    sessions: [],
    active: {},
  })
  let revision = 0
  vi.mocked(api.saveChatState).mockImplementation(async () => ({ revision: ++revision }))
  const store = useChatStore()
  await store.initialize()
  vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
    throw new Error('quota')
  })
  const content = '段落\n'.repeat(100000)
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'delta', delta: content }
    yield { type: 'done' }
  })
  await store.ask('default', '请总结方案', 'chat')
  expect(store.savingError).toBe('')
  const answer = store.current('default')!.messages[1]!
  await store.retry('default', answer.id)
  expect(answer.versions![0]!.content).toBe(content)
  expect(vi.mocked(api.saveChatState).mock.calls.at(-1)![0].sessions[0]!.messages[1]!.content).toBe(
    content,
  )
})

it('does not overwrite corrupt legacy records with an empty state', async () => {
  localStorage.setItem('edge-assistant.chats.v1', '{corrupt')
  vi.mocked(api.loadChatState).mockResolvedValue({
    version: 1,
    initialized: false,
    revision: 0,
    sessions: [],
    active: {},
  })
  const store = useChatStore()
  await store.initialize()
  store.create('default')
  expect(localStorage.getItem('edge-assistant.chats.v1')).toBe('{corrupt')
  expect(api.saveChatState).not.toHaveBeenCalled()
  expect(store.savingError).toContain('读取失败')
})

it('keeps manual titles and interrupted stream content when reopening database records', async () => {
  const store = useChatStore()
  const session = store.create('default')
  store.rename(session.id, '手动标题')
  session.messages.push({
    id: 'partial',
    role: 'assistant',
    content: '已收到的文字\n ',
    sources: [],
    status: 'streaming',
  })
  vi.mocked(api.loadChatState).mockResolvedValue({
    version: 1,
    initialized: true,
    revision: 5,
    sessions: [JSON.parse(JSON.stringify(session))],
    active: { default: session.id },
    lastLibrary: 'default',
  })
  vi.mocked(api.saveChatState).mockResolvedValue({ revision: 6 })
  await store.initialize()
  expect(store.current('default')!.title).toBe('手动标题')
  expect(store.current('default')!.messages[0]!.content).toBe('已收到的文字\n ')
  expect(store.current('default')!.messages[0]!.status).toBe('stopped')
  expect(store.lastLibrary).toBe('default')
})

it('keeps actual processing stages and duration across saving and retry history', async () => {
  vi.mocked(api.query).mockImplementation(async function* () {
    yield { type: 'progress', stage: 'validating' }
    yield { type: 'progress', stage: 'planning' }
    yield { type: 'progress', stage: 'retrieving' }
    yield { type: 'sources', sources: [] }
    yield { type: 'execution', location: 'local', generator: 'local' }
    yield { type: 'delta', delta: '本地回答' }
    yield { type: 'done' }
  })
  const store = useChatStore()
  await store.ask('default', '总结资料', 'chat')
  const answer = store.current('default')!.messages[1]!
  expect(answer.processing?.steps.map((step) => step.stage)).toEqual([
    'waiting',
    'validating',
    'planning',
    'retrieving',
    'generating',
  ])
  expect(answer.processing!.finishedAt).toBeGreaterThanOrEqual(answer.processing!.startedAt)
  const original = structuredClone(JSON.parse(JSON.stringify(answer.processing)))
  await store.retry('default', answer.id)
  expect(answer.versions!.at(-1)!.processing).toEqual(original)
  setActivePinia(createPinia())
  expect(useChatStore().current('default')!.messages[1]!.processing).toEqual(answer.processing)
})
