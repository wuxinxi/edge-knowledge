export interface BackendSession {
  baseUrl: string
  token: string
}
export interface Health {
  status: string
  embedding_loaded: boolean
}
export interface Library {
  id: string
  name: string
  chunks: number
}
export interface Document {
  id: string
  filename: string
  chunks: number
  size: number
  created_at: string
  kind: MediaKind
  media_type: string
  width: number
  height: number
  ocr_status: string
  ocr_message: string
  duration?: number
  assets?: number
}
export interface Source {
  document_id: string
  filename: string
  text: string
  section: string
  index: number
  score: number
  kind?: MediaKind
  ocr_status?: string
  start?: number
  end?: number
}
export interface HistoryMessage {
  role: 'user' | 'assistant'
  content: string
}
export interface QueryOptions {
  documentIds?: string[]
  history?: HistoryMessage[]
}
export interface Settings {
  base_url: string
  model: string
  stream: boolean
  top_k: number
  min_score: number
  chunk_size: number
  chunk_overlap: number
  credential_storage?: string
  credential_message?: string
  credential_migration_pending?: boolean
  api_key_configured: boolean
  image_qa_mode: 'local_ocr' | 'cloud_vision'
}
export interface Capabilities {
  embedding: {
    ready: boolean
    images: boolean
    audio?: boolean
    video?: boolean
    joint?: boolean
    context_limit?: number
    dimensions?: number[]
  }
  generator: { model: string; images: boolean }
  ocr: { available: boolean }
  image_qa_mode: 'local_ocr' | 'cloud_vision'
  max_cloud_images: number
}
export interface OCRExtraction {
  status: 'ready' | 'empty' | 'unavailable' | 'error'
  text: string
  message: string
  width: number
  height: number
  regions: { text: string; confidence: number; bbox: [number, number, number, number] }[]
}
export type SettingsPatch = Partial<
  Omit<
    Settings,
    | 'api_key_configured'
    | 'credential_storage'
    | 'credential_message'
    | 'credential_migration_pending'
  >
> & { api_key?: string }
export type ChatEvent =
  | { type: 'sources'; sources: Source[] }
  | { type: 'delta'; delta: string }
  | { type: 'done' }
  | { type: 'notice'; message: string }
  | { type: 'error'; message: string; code?: string }

declare global {
  interface Window {
    edgeDesktop?: {
      getBackendSession(): Promise<BackendSession>
      access: import('./access').DesktopAccess
      folders: import('./access').DesktopFolders
    }
  }
}

export type MediaKind = 'document' | 'image' | 'audio' | 'video' | 'bundle'
export interface EmbeddingBudget {
  limit: number
  max_tokens: number
  segments: number
  fits?: boolean
}
export interface SemanticOptions {
  library_id: string
  text: string
  name?: string
  task?: 'search' | 'document' | 'code' | 'qa' | 'fact'
  dimension?: number
  top_k?: number
  document_ids?: string[]
  kinds?: MediaKind[]
}
export interface SemanticResult {
  sources: Source[]
  budget: EmbeddingBudget
  dimension: number
  aggregation: string
}
export interface OrganizationResult {
  task: string
  dimension: number
  documents: Document[]
  assignments?: {
    document_id: string
    label: string
    scores: { label: string; score: number }[]
  }[]
  groups?: string[][]
  pairs?: { left: string; right: string; score: number; exact?: boolean }[]
  threshold?: number
}
export interface MediaAsset {
  index: number
  filename: string
  kind: MediaKind
  media_type: string
}

export interface BackupInspection {
  model: string
  compatible: boolean
  libraries: number
  documents: number
  archived: number
  missing_originals: number
  frontend: { chats?: unknown; preferences?: unknown }
}
export interface BackupRestoration {
  libraries: Library[]
  mapping: Record<string, string>
  frontend: { chats?: unknown; preferences?: unknown }
}
