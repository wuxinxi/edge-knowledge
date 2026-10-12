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
  if (data.version !== 1 || !Array.isArray(data.sessions) || data.sessions.length > 500)
    throw new Error('对话备份格式无效或超过 500 个对话。')
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
      chat.messages.length > 2000 ||
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
        !string(message.content, 200000) ||
        !Array.isArray(message.sources) ||
        message.sources.length > 50
      )
        throw new Error('对话消息格式无效。')
      const sources = message.sources.map((source) => {
        if (
          !source ||
          !string(source.document_id, 100) ||
          !string(source.filename, 255) ||
          !string(source.text, 200000) ||
          !string(source.section, 20000) ||
          !Number.isInteger(source.index) ||
          source.index < 0 ||
          !Number.isFinite(source.score) ||
          (source.kind && !['document', 'image', 'audio', 'video', 'bundle'].includes(source.kind))
        )
          throw new Error('对话来源格式无效。')
        for (const time of [source.start, source.end])
          if (time !== undefined && (!Number.isFinite(time) || time < 0))
            throw new Error('媒体时间格式无效。')
        return {
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
      return {
        id: message.id,
        role: message.role,
        content: message.content,
        sources,
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
  if (new TextEncoder().encode(JSON.stringify(result)).length > 3 * 1024 * 1024)
    throw new Error('对话备份超过 3 MB，请先分开导出较长对话。')
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
