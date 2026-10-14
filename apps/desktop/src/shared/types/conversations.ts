import type { Source, DuplicateComparison } from './api'
export interface Reference {
  id: string
  filename: string
}
export interface AnswerVersion {
  resultKind?: import('./query').QueryResultKind
  processing?: import('./processing').ChatProcessing
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
  resultKind?: import('./query').QueryResultKind
  processing?: import('./processing').ChatProcessing
  id: string
  role: 'user' | 'assistant'
  content: string
  sources: Source[]
  references?: Reference[]
  contextReferences?: Reference[]
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
  contextEnabled?: boolean
  draft?: { content: string; mode: 'search' | 'chat' }
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
