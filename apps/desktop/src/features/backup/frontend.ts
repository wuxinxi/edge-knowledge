import { chatStages } from '../../shared/types/processing'
import type { Conversation, Message } from '../chat/store'
import { validatePreferences, type Preferences } from '../../shared/preferences/store'

export interface FrontendBackup {
  chats?: { version: number; sessions: unknown[]; active?: unknown }
  preferences?: unknown
}
const string = (value: unknown, maximum: number): value is string =>
  typeof value === 'string' && value.length <= maximum
export function validateChatBackup(value: unknown): Conversation[] {
  if (value === undefined || value === null) return []
  if (typeof value !== 'object') throw new Error('对话备份格式无效。')
  const data = value as { version?: unknown; sessions?: unknown }
  if (data.version !== 1 || !Array.isArray(data.sessions)) throw new Error('对话备份格式无效。')
  const ids = new Set<string>()
  return data.sessions.map((item) => {
    if (!item || typeof item !== 'object') throw new Error('对话备份格式无效。')
    const chat = item as Conversation
    if (
      !string(chat.id, 100) ||
      ids.has(chat.id) ||
      !string(chat.library, 100) ||
      !string(chat.title, 80) ||
      !string(chat.createdAt, 100) ||
      !string(chat.updatedAt, 100) ||
      !Array.isArray(chat.messages) ||
      !Array.isArray(chat.references) ||
      chat.references.length > 10
    )
      throw new Error('对话备份包含无效记录。')
    ids.add(chat.id)
    const reference = (ref: { id: string; filename: string }) => {
      if (!ref || !string(ref.id, 100) || !string(ref.filename, 255))
        throw new Error('对话引用格式无效。')
      return { id: ref.id, filename: ref.filename }
    }
    const messages: Message[] = chat.messages.map((message) => {
      if (
        !message ||
        !string(message.id, 100) ||
        !['user', 'assistant'].includes(message.role) ||
        typeof message.content !== 'string' ||
        !Array.isArray(message.sources) ||
        message.sources.length > 50
      )
        throw new Error('对话消息格式无效。')
      const sources = message.sources.map((source) => {
        if (
          !source ||
          !string(source.document_id, 100) ||
          !string(source.filename, 255) ||
          typeof source.text !== 'string' ||
          !string(source.section, 20000) ||
          !Number.isInteger(source.index) ||
          source.index < 0 ||
          !Number.isFinite(source.score) ||
          (source.path !== undefined && !string(source.path, 4096)) ||
          (source.kind && !['document', 'image', 'audio', 'video', 'bundle'].includes(source.kind))
        )
          throw new Error('对话来源格式无效。')
        for (const time of [source.start, source.end])
          if (time !== undefined && (!Number.isFinite(time) || time < 0))
            throw new Error('媒体时间格式无效。')
        return {
          ...(source.path ? { path: source.path } : {}),
          document_id: source.document_id,
          filename: source.filename,
          text: source.text,
          section: source.section,
          index: source.index,
          score: source.score,
          ...(source.kind ? { kind: source.kind } : {}),
          ...(typeof source.ocr_status === 'string'
            ? { ocr_status: source.ocr_status.slice(0, 100) }
            : {}),
          ...(source.start === undefined ? {} : { start: source.start }),
          ...(source.end === undefined ? {} : { end: source.end }),
        }
      })
      if (
        message.comparisons &&
        (!Array.isArray(message.comparisons) || message.comparisons.length > 50)
      )
        throw new Error('查重对比格式无效。')
      const comparisons = message.comparisons?.map((pair) => {
        if (
          !pair ||
          !Number.isFinite(pair.score) ||
          pair.score < -1 ||
          pair.score > 1 ||
          typeof pair.exact !== 'boolean' ||
          (pair.body_exact !== undefined && typeof pair.body_exact !== 'boolean') ||
          (pair.content_similarity !== undefined &&
            (!Number.isFinite(pair.content_similarity) ||
              pair.content_similarity < 0 ||
              pair.content_similarity > 1))
        )
          throw new Error('查重对比格式无效。')
        const validated = validateChatBackup({
          version: 1,
          sessions: [
            {
              ...chat,
              messages: [
                {
                  ...message,
                  sources: [pair.left, pair.right],
                  comparisons: undefined,
                  versions: undefined,
                },
              ],
            },
          ],
        })[0]!.messages[0]!.sources
        return {
          left: validated[0]!,
          right: validated[1]!,
          score: pair.score,
          exact: pair.exact,
          ...(typeof pair.body_exact === 'boolean' ? { body_exact: pair.body_exact } : {}),
          ...(Number.isFinite(pair.content_similarity)
            ? { content_similarity: pair.content_similarity }
            : {}),
        }
      })
      if (message.processing) {
        const trace = message.processing
        const validTime = (value: unknown) =>
          typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
        if (
          !validTime(trace.startedAt) ||
          (trace.finishedAt !== undefined && !validTime(trace.finishedAt)) ||
          !Array.isArray(trace.steps) ||
          trace.steps.length > 32 ||
          trace.steps.some(
            (step) => !step || !chatStages.includes(step.stage) || !validTime(step.startedAt),
          )
        )
          throw new Error('处理过程格式无效。')
      }
      return {
        ...(message.processing ? { processing: structuredClone(message.processing) } : {}),
        id: message.id,
        role: message.role,
        content: message.content,
        sources,
        ...(comparisons ? { comparisons } : {}),
        ...(message.queryPlan ? { queryPlan: structuredClone(message.queryPlan) } : {}),
        ...(message.generator === 'local' || message.generator === 'deepseek'
          ? { generator: message.generator }
          : {}),
        ...(['local', 'local_model', 'deepseek'].includes(String(message.planner))
          ? { planner: message.planner as Message['planner'] }
          : {}),
        ...(message.status ? { status: message.status } : {}),
        ...(message.versions
          ? {
              versions: message.versions.map((version) => {
                if (
                  !version ||
                  typeof version.content !== 'string' ||
                  !Array.isArray(version.sources) ||
                  !string(version.savedAt, 100)
                )
                  throw new Error('历史回答格式无效。')
                const nested = validateChatBackup({
                  version: 1,
                  sessions: [
                    {
                      ...chat,
                      messages: [
                        {
                          ...message,
                          content: version.content,
                          sources: version.sources,
                          versions: undefined,
                          comparisons: version.comparisons,
                          processing: version.processing,
                        },
                      ],
                    },
                  ],
                })[0]!.messages[0]!
                return {
                  content: version.content,
                  sources: nested.sources,
                  ...(nested.comparisons ? { comparisons: nested.comparisons } : {}),
                  savedAt: version.savedAt,
                  ...(nested.processing ? { processing: nested.processing } : {}),
                  ...(version.generator === 'local' || version.generator === 'deepseek'
                    ? { generator: version.generator }
                    : {}),
                  ...(['local', 'local_model', 'deepseek'].includes(String(version.planner))
                    ? { planner: version.planner as Message['planner'] }
                    : {}),
                  ...(string(version.error, 2000) ? { error: version.error } : {}),
                  ...(string(version.notice, 4000) ? { notice: version.notice } : {}),
                }
              }),
            }
          : {}),
        ...(message.references ? { references: message.references.map(reference) } : {}),
        ...(message.mode === 'chat' || message.mode === 'search' ? { mode: message.mode } : {}),
        ...(string(message.error, 2000) ? { error: message.error } : {}),
        ...(string(message.notice, 4000) ? { notice: message.notice } : {}),
      }
    })
    return {
      id: chat.id,
      library: chat.library,
      title: chat.title,
      ...(chat.titleSource === 'auto' || chat.titleSource === 'manual'
        ? { titleSource: chat.titleSource }
        : {}),
      createdAt: chat.createdAt,
      updatedAt: chat.updatedAt,
      messages,
      references: chat.references.map(reference),
    }
  })
}
export function portableFrontend(chats: Conversation[], preferences: Preferences) {
  const result = {
    chats: {
      version: 1,
      sessions: validateChatBackup({ version: 1, sessions: chats }),
      active: {},
    },
    preferences: validatePreferences(preferences),
  }
  if (new TextEncoder().encode(JSON.stringify(result)).length > 64 * 1024 * 1024)
    throw new Error('对话备份超过 64 MB，请先分开导出较长对话。')
  return result
}
export function restoredChats(value: unknown, mapping: Record<string, string>) {
  return validateChatBackup(value)
    .filter((chat) => Object.hasOwn(mapping, chat.library))
    .map((chat) => ({
      ...chat,
      id: crypto.randomUUID(),
      library: mapping[chat.library]!,
      messages: chat.messages.map((message) => ({ ...message, id: crypto.randomUUID() })),
    }))
}
