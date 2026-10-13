import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../../shared/api/client'
import type { Source, HistoryMessage } from '../../shared/types/api'
import type { QuerySpec } from '../../shared/types/query'
import { useI18n } from '../../shared/i18n'

import type {
  Conversation,
  Message,
  Reference,
  ChatSnapshot,
} from '../../shared/types/conversations'
export type { Conversation, Message, Reference } from '../../shared/types/conversations'
import { useTaskStore } from '../tasks/store'
import { updateConversationTitle } from './title'
import { chatStages, stageLabels, type ChatStage } from '../../shared/types/processing'

const storageKey = 'edge-assistant.chats.v1'
export function boundedHistory(messages: Message[]): HistoryMessage[] {
  const result: HistoryMessage[] = []
  let size = 0
  for (const message of [...messages].reverse()) {
    if (message.mode !== 'chat' || message.error || !message.content.trim()) continue
    const content = message.content.slice(-6000)
    if (size + content.length > 24000 || result.length === 10) break
    result.unshift({ role: message.role, content })
    size += content.length
  }
  // The history starts with a user turn and does not contain a dangling question.
  while (result[0]?.role === 'assistant') result.shift()
  if (result.at(-1)?.role === 'user') result.pop()
  return result
}
export const useChatStore = defineStore('chat', () => {
  const tasks = useTaskStore(),
    taskId = ref(''),
    activeAnswerId = ref('')
  const activeTask = computed(() => tasks.get(taskId.value))
  const sessions = ref<Conversation[]>([])
  const activeByLibrary = ref<Record<string, string>>({})
  const busy = ref(false)
  const savingError = ref('')
  const deleted = ref<Conversation>()
  const lastLibrary = ref('')
  const loading = ref(false)
  const durable = ref(false)
  let revision = 0
  let queue: Promise<void> = Promise.resolve()
  let failedRead = false
  let legacyCorrupt = false
  const { t, preferences } = useI18n()
  let controller: AbortController | undefined
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null')
    if (saved !== null && saved?.version !== 1) throw new Error('Unsupported chat snapshot')
    if (saved?.version === 1 && Array.isArray(saved.sessions)) {
      if (
        !saved.sessions.every(
          (item: Conversation) =>
            typeof item?.id === 'string' &&
            typeof item.library === 'string' &&
            typeof item.title === 'string' &&
            typeof item.updatedAt === 'string' &&
            typeof item.createdAt === 'string' &&
            Array.isArray(item.messages) &&
            Array.isArray(item.references) &&
            item.references.every(
              (ref) => typeof ref?.id === 'string' && typeof ref?.filename === 'string',
            ) &&
            item.messages.every(
              (m) =>
                typeof m.id === 'string' &&
                ['user', 'assistant'].includes(m.role) &&
                typeof m.content === 'string' &&
                Array.isArray(m.sources),
            ),
        )
      )
        throw new Error('Invalid chat storage')
      sessions.value = saved.sessions
      lastLibrary.value = saved.lastLibrary ?? ''
      activeByLibrary.value = saved.active && typeof saved.active === 'object' ? saved.active : {}
      for (const [library, id] of Object.entries(activeByLibrary.value)) {
        if (!sessions.value.some((item) => item.library === library && item.id === id))
          delete activeByLibrary.value[library]
      }
      for (const session of sessions.value) {
        const last = session.messages.at(-1)
        updateConversationTitle(session)
        if (last?.role === 'assistant' && last.status === 'streaming') {
          last.status = 'stopped'
          last.error = t('已停止。')
        }
      }
    }
  } catch {
    failedRead = true
    legacyCorrupt = true
    savingError.value = t('会话记录读取失败，原始记录已保留，请导出或检查存储。')
  }
  function snapshot(): ChatSnapshot {
    return JSON.parse(
      JSON.stringify({
        version: 1,
        sessions: sessions.value,
        active: activeByLibrary.value,
        lastLibrary: lastLibrary.value,
      }),
    )
  }
  function cache(value: ChatSnapshot) {
    localStorage.setItem(storageKey, JSON.stringify(value))
  }
  function persist(): Promise<void> {
    const value = snapshot()
    if (!durable.value) {
      if (failedRead) return Promise.resolve()
      try {
        cache(value)
        savingError.value = ''
      } catch {
        savingError.value = t('对话保存失败，请导出备份后检查设备存储。')
      }
      return Promise.resolve()
    }
    // Capture immutable snapshots and serialize writes so delayed responses cannot roll state back.
    queue = queue
      .catch(() => {})
      .then(async () => {
        try {
          const result = await api.saveChatState(value, revision)
          revision = result.revision
          savingError.value = ''
          // Cache is for migration/offline recovery; SQLite is authoritative after initialization.
          try {
            cache(value)
          } catch {
            /* Full database snapshot remains durable. */
          }
        } catch {
          savingError.value = t('对话保存失败，请导出备份后检查设备存储。')
          throw new Error(savingError.value)
        }
      })
    void queue.catch(() => {})
    return queue
  }
  async function initialize() {
    if (loading.value || durable.value) return
    loading.value = true
    try {
      const saved = await api.loadChatState()
      revision = saved.revision
      if (saved.initialized) {
        failedRead = false
        sessions.value = saved.sessions
        lastLibrary.value = saved.lastLibrary ?? ''
        activeByLibrary.value = saved.active
      } else if (legacyCorrupt) {
        throw new Error('Legacy snapshot needs recovery')
      }
      failedRead = false
      for (const session of sessions.value) {
        updateConversationTitle(session)
        const last = session.messages.at(-1)
        if (last?.status === 'streaming') {
          last.status = 'stopped'
          last.error = t('已停止。')
        }
      }
      durable.value = true
      await persist()
    } catch {
      failedRead = true
      savingError.value = t('会话记录读取失败，原始记录已保留，请导出或检查存储。')
    } finally {
      loading.value = false
    }
  }
  async function flush() {
    await queue
  }
  async function importConversations(items: Conversation[]) {
    if (busy.value) throw new Error(t('请等待当前对话完成后再恢复备份。'))
    const previous = snapshot()
    const merged = [...items, ...sessions.value]
    const active = { ...activeByLibrary.value }
    for (const item of items) if (!active[item.library]) active[item.library] = item.id
    if (!durable.value) cache({ version: 1, sessions: merged, active })
    sessions.value = merged
    activeByLibrary.value = active
    try {
      await persist()
    } catch (error) {
      sessions.value = previous.sessions
      activeByLibrary.value = previous.active
      throw error
    }
  }
  function list(library: string) {
    return sessions.value
      .filter((item) => item.library === library)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  }
  function current(library: string) {
    return sessions.value.find(
      (item) => item.library === library && item.id === activeByLibrary.value[library],
    )
  }
  const conversations = computed(() =>
    Object.fromEntries(
      Object.keys(activeByLibrary.value).map((library) => [
        library,
        current(library)?.messages ?? [],
      ]),
    ),
  )
  function rememberLibrary(library: string) {
    lastLibrary.value = library
    if (!loading.value) void persist()
  }
  function create(library: string) {
    lastLibrary.value = library
    const active = current(library)
    if (active && !active.messages.length) return active
    stop()
    // Reuse a previous draft when returning from an existing conversation.
    const draft = sessions.value.find((item) => item.library === library && !item.messages.length)
    if (draft) {
      activeByLibrary.value[library] = draft.id
      persist()
      return draft
    }
    const now = new Date().toISOString()
    const session: Conversation = {
      id: crypto.randomUUID(),
      library,
      title: '',
      titleSource: 'auto',
      createdAt: now,
      updatedAt: now,
      messages: [],
      references: [],
    }
    sessions.value.unshift(session)
    activeByLibrary.value[library] = session.id
    persist()
    return current(library)!
  }
  function select(library: string, id: string) {
    lastLibrary.value = library
    if (!sessions.value.some((item) => item.id === id && item.library === library)) return
    stop()
    activeByLibrary.value[library] = id
    persist()
  }
  function rename(id: string, title: string) {
    const session = sessions.value.find((item) => item.id === id)
    if (session && title.trim()) {
      session.title = title.trim().slice(0, 80)
      session.titleSource = 'manual'
      persist()
    }
  }
  function remove(id: string) {
    const session = sessions.value.find((item) => item.id === id)
    if (!session) return
    stop()
    deleted.value = session
    sessions.value = sessions.value.filter((item) => item.id !== id)
    if (activeByLibrary.value[session.library] === id) {
      const next = list(session.library)[0]
      if (next) activeByLibrary.value[session.library] = next.id
      else delete activeByLibrary.value[session.library]
    }
    persist()
  }
  function undoDelete() {
    if (!deleted.value) return
    const restored = deleted.value
    sessions.value.unshift(restored)
    activeByLibrary.value[restored.library] = restored.id
    deleted.value = undefined
    persist()
  }
  function setReferences(library: string, references: Reference[]) {
    const session = current(library) ?? create(library)
    session.references = references.slice(0, 10)
    persist()
  }
  async function ask(
    library: string,
    question: string,
    mode: 'search' | 'chat' = 'search',
    allowImageUpload = false,
    queryPlan?: QuerySpec,
  ) {
    if (loading.value || busy.value || !question.trim()) return
    const session = current(library) ?? create(library)
    const messages = session.messages
    const history = boundedHistory(messages)
    const references = [...session.references]
    session.updatedAt = new Date().toISOString()
    messages.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
      sources: [],
      references,
      mode,
      ...(queryPlan ? { queryPlan: JSON.parse(JSON.stringify(queryPlan)) } : {}),
    })
    updateConversationTitle(session)
    messages.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      sources: [],
      mode,
      status: 'streaming',
    })
    const answer = messages[messages.length - 1]!
    await runAnswer(
      library,
      question,
      mode,
      references,
      history,
      answer,
      allowImageUpload,
      queryPlan,
    )
  }
  async function runAnswer(
    library: string,
    question: string,
    mode: 'search' | 'chat',
    references: Reference[],
    history: HistoryMessage[],
    answer: Message,
    allowImageUpload: boolean,
    queryPlan?: QuerySpec,
  ) {
    const pending = (controller = new AbortController())
    busy.value = true
    activeAnswerId.value = answer.id
    const feedback = (taskId.value = tasks.begin(
      mode === 'search' ? '查找资料' : '资料问答',
      library,
      { stop, stopLabel: '停止回答' },
    ))
    answer.processing = { startedAt: Date.now(), steps: [] }
    function stage(value: ChatStage) {
      if (!chatStages.includes(value) || answer.processing!.steps.at(-1)?.stage === value) return
      answer.processing!.steps.push({ stage: value, startedAt: Date.now() })
      tasks.update(feedback, { phase: stageLabels[value] })
    }
    stage(mode === 'search' ? 'querying' : 'waiting')
    try {
      await persist()
      pending.signal.throwIfAborted()
      if (mode === 'search') {
        const args = [
          library,
          question.trim(),
          pending.signal,
          references.map((item) => item.id),
        ] as const
        const result = queryPlan
          ? await api.localQuery(...args, queryPlan)
          : await api.localQuery(...args)
        answer.comparisons = result.comparisons
        answer.sources = result.sources
        answer.content =
          result.kind === 'retrieval' &&
          result.sources.length &&
          preferences.values.language === 'en-US'
            ? `Found ${new Set(result.sources.map((source) => source.document_id)).size} sources. Results are shown below.`
            : t(result.content)
        answer.notice = t(result.notice)
        answer.planner = result.query?.planner
        answer.status = 'complete'
        await persist()
        return
      }
      for await (const event of api.query(
        library,
        question.trim(),
        pending.signal,
        allowImageUpload,
        {
          documentIds: references.map((item) => item.id),
          history,
          ...(queryPlan ? { queryPlan } : {}),
        },
      )) {
        if (event.type === 'progress') stage(event.stage)
        if (event.type === 'comparisons') {
          answer.comparisons = event.comparisons
        }
        if (event.type === 'sources') {
          answer.sources = event.sources
          // Sources arrive before execution metadata; they do not imply generation.
        }
        if (event.type === 'execution') {
          answer.planner = event.planner
          answer.generator = event.generator
          answer.mode = event.generator ? 'chat' : event.location === 'local' ? 'search' : 'chat'
          stage(event.generator ? 'generating' : 'presenting')
        }
        if (event.type === 'delta') answer.content += event.delta
        if (event.type === 'notice') answer.notice = event.message
        if (event.type === 'error') {
          answer.error = event.message
          answer.status = 'error'
        }
        if (event.type === 'done') answer.status = 'complete'
        await persist()
        if (event.type === 'error') break
      }
      if (answer.status === 'streaming') answer.status = 'stopped'
    } catch (cause) {
      answer.error =
        cause instanceof Error && cause.name === 'AbortError'
          ? t('已停止。')
          : cause instanceof Error
            ? cause.message
            : t('回答失败，请重试。')
      answer.status = pending.signal.aborted ? 'stopped' : 'error'
    } finally {
      answer.processing!.finishedAt = Date.now()
      tasks.finish(
        feedback,
        answer.status === 'stopped' ? 'stopped' : answer.error ? 'error' : 'success',
        answer.status === 'stopped'
          ? t('已停止接收回答，已收到的内容已保留。后台请求可能仍在结束。')
          : answer.error || '',
      )
      tasks.setActions(feedback, {})
      busy.value = false
      if (controller === pending) controller = undefined
      await persist().catch(() => {})
    }
  }
  async function retry(library: string, answerId: string, allowImageUpload = false) {
    if (busy.value) return
    const session = current(library)
    const answer = session?.messages.at(-1)
    const question = session?.messages.at(-2)
    if (
      !session ||
      !answer ||
      answer.id !== answerId ||
      answer.role !== 'assistant' ||
      question?.role !== 'user'
    )
      return
    const original: Message = JSON.parse(JSON.stringify(answer))
    answer.versions ??= []
    answer.versions.push({
      content: original.content,
      sources: original.sources,
      error: original.error,
      notice: original.notice,
      savedAt: new Date().toISOString(),
      planner: original.planner,
      generator: original.generator,
      comparisons: original.comparisons,
      processing: original.processing,
    })
    answer.status = 'streaming'
    answer.content = ''
    answer.sources = []
    answer.error = undefined
    answer.notice = undefined
    answer.planner = undefined
    answer.generator = undefined
    answer.comparisons = undefined
    session.updatedAt = new Date().toISOString()
    await runAnswer(
      library,
      question.content,
      question.mode ?? 'chat',
      question.references ?? [],
      boundedHistory(session.messages.slice(0, -2)),
      answer,
      allowImageUpload,
      question.queryPlan,
    )
    if (answer.error && original.content) {
      const error = answer.error
      if (answer.content && answer.content !== original.content) {
        answer.versions?.push({
          content: answer.content,
          sources: answer.sources,
          error,
          notice: answer.notice,
          savedAt: new Date().toISOString(),
          planner: original.planner,
          generator: original.generator,
          comparisons: answer.comparisons,
          processing: answer.processing,
        })
      }
      const versions = answer.versions
      Object.assign(answer, original, { error, versions, status: 'error' })
      answer.notice = t('重新生成未完成，已保留上次回答。')
      await persist().catch(() => {})
    }
  }
  function stop() {
    controller?.abort()
  }
  function clear(library: string) {
    create(library)
  }
  return {
    sessions,
    initialize,
    flush,
    loading,
    lastLibrary,
    rememberLibrary,
    durable,
    importConversations,
    conversations,
    activeByLibrary,
    busy,
    activeTask,
    activeAnswerId,
    savingError,
    deleted,
    list,
    current,
    create,
    select,
    rename,
    remove,
    undoDelete,
    setReferences,
    ask,
    retry,
    stop,
    clear,
  }
})
