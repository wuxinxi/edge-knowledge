import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../../shared/api/client'
import type { Source, HistoryMessage } from '../../shared/types/api'
import { useI18n } from '../../shared/i18n'

export interface Reference {
  id: string
  filename: string
}
export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
  references?: Reference[]
  mode?: 'search' | 'chat'
  error?: string
  notice?: string
}
export interface Conversation {
  id: string
  library: string
  title: string
  createdAt: string
  updatedAt: string
  messages: Message[]
  references: Reference[]
}
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
  const sessions = ref<Conversation[]>([])
  const activeByLibrary = ref<Record<string, string>>({})
  const busy = ref(false)
  const savingError = ref('')
  const deleted = ref<Conversation>()
  const { t, preferences } = useI18n()
  let controller: AbortController | undefined
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null')
    if (saved?.version === 1 && Array.isArray(saved.sessions)) {
      sessions.value = saved.sessions.filter(
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
      activeByLibrary.value = saved.active && typeof saved.active === 'object' ? saved.active : {}
      for (const session of sessions.value) {
        const last = session.messages.at(-1)
        if (last?.role === 'assistant' && !last.content && !last.error) last.error = t('已停止。')
      }
    }
  } catch {
    /* Storage is optional in tests; unavailable storage is surfaced when writing. */
  }
  function persist() {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({ version: 1, sessions: sessions.value, active: activeByLibrary.value }),
      )
      savingError.value = ''
    } catch {
      savingError.value = t('对话保存失败，请导出备份后检查设备存储。')
    }
  }
  function importConversations(items: Conversation[]) {
    if (busy.value) throw new Error(t('请等待当前对话完成后再恢复备份。'))
    const merged = [...items, ...sessions.value]
    const active = { ...activeByLibrary.value }
    for (const item of items) if (!active[item.library]) active[item.library] = item.id
    // Commit storage before changing in-memory state; quota failures keep existing chats.
    localStorage.setItem(storageKey, JSON.stringify({ version: 1, sessions: merged, active }))
    sessions.value = merged
    activeByLibrary.value = active
    savingError.value = ''
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
  function create(library: string) {
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
    if (!sessions.value.some((item) => item.id === id && item.library === library)) return
    stop()
    activeByLibrary.value[library] = id
    persist()
  }
  function rename(id: string, title: string) {
    const session = sessions.value.find((item) => item.id === id)
    if (session && title.trim()) {
      session.title = title.trim().slice(0, 80)
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
    mode: 'search' | 'chat' = 'chat',
    allowImageUpload = false,
  ) {
    if (busy.value || !question.trim()) return
    const session = current(library) ?? create(library)
    const messages = session.messages
    const history = boundedHistory(messages)
    const references = [...session.references]
    if (!session.title) session.title = question.trim().slice(0, 40)
    session.updatedAt = new Date().toISOString()
    messages.push({
      id: crypto.randomUUID(),
      role: 'user',
      content: question.trim(),
      sources: [],
      references,
      mode,
    })
    messages.push({ id: crypto.randomUUID(), role: 'assistant', content: '', sources: [], mode })
    const answer = messages[messages.length - 1]!
    await runAnswer(library, question, mode, references, history, answer, allowImageUpload)
  }
  async function runAnswer(
    library: string,
    question: string,
    mode: 'search' | 'chat',
    references: Reference[],
    history: HistoryMessage[],
    answer: Message,
    allowImageUpload: boolean,
  ) {
    const pending = (controller = new AbortController())
    busy.value = true
    persist()
    try {
      if (mode === 'search') {
        answer.sources = await api.search(
          library,
          question.trim(),
          pending.signal,
          references.map((item) => item.id),
        )
        answer.content = answer.sources.length
          ? preferences.values.language === 'en-US'
            ? `Found ${answer.sources.length} relevant excerpts. Open the sources below.`
            : `找到 ${answer.sources.length} 个相关片段。展开下方来源查看原文。`
          : t('暂时没有找到相关资料。请先导入文档，或换一种描述。')
        return
      }
      for await (const event of api.query(
        library,
        question.trim(),
        pending.signal,
        allowImageUpload,
        { documentIds: references.map((item) => item.id), history },
      )) {
        if (event.type === 'sources') answer.sources = event.sources
        if (event.type === 'delta') answer.content += event.delta
        if (event.type === 'notice') answer.notice = event.message
        if (event.type === 'error') {
          answer.error = event.message
          break
        }
      }
    } catch (cause) {
      answer.error =
        cause instanceof Error && cause.name === 'AbortError'
          ? t('已停止。')
          : cause instanceof Error
            ? cause.message
            : t('回答失败，请重试。')
    } finally {
      busy.value = false
      controller = undefined
      persist()
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
    answer.content = ''
    answer.sources = []
    answer.error = undefined
    answer.notice = undefined
    session.updatedAt = new Date().toISOString()
    await runAnswer(
      library,
      question.content,
      question.mode ?? 'chat',
      question.references ?? [],
      boundedHistory(session.messages.slice(0, -2)),
      answer,
      allowImageUpload,
    )
    if (answer.error && original.content) {
      const error = answer.error
      Object.assign(answer, original, { error })
      answer.notice = t('重新生成未完成，已保留上次回答。')
      persist()
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
    importConversations,
    conversations,
    activeByLibrary,
    busy,
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
