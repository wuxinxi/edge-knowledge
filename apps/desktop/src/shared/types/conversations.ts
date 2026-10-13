import type { Source, DuplicateComparison } from './api'
export interface Reference {
  id: string
  filename: string
}
export interface AnswerVersion {
  content: string
  sources: Source[]
  error?: string
  notice?: string
  savedAt: string
  planner?: 'local' | 'local_model' | 'deepseek'
  generator?: 'local' | 'deepseek'
  comparisons?: DuplicateComparison[]
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
  status?: 'streaming' | 'complete' | 'stopped' | 'error'
  versions?: AnswerVersion[]
  queryPlan?: import('./query').QuerySpec
  planner?: 'local' | 'local_model' | 'deepseek'
  generator?: 'local' | 'deepseek'
  comparisons?: DuplicateComparison[]
}
export interface Conversation {
  id: string
  library: string
  title: string
  titleSource?: 'auto' | 'manual'
  createdAt: string
  updatedAt: string
  messages: Message[]
  references: Reference[]
}
export interface ChatSnapshot {
  lastLibrary?: string
  version: 1
  sessions: Conversation[]
  active: Record<string, string>
}
export interface SavedChatState extends ChatSnapshot {
  initialized: boolean
  revision: number
}
