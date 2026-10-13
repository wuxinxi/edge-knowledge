import type {
  BackupInspection,
  BackupRestoration,
  SemanticOptions,
  SemanticResult,
  OrganizationResult,
  MediaAsset,
  EmbeddingBudget,
  BackendSession,
  QueryOptions,
  ChatEvent,
  Capabilities,
  OCRExtraction,
  Document,
  Health,
  Library,
  Settings,
  SettingsPatch,
  Source,
  LocalQueryResult,
} from '../types/api'
import { readSSE } from './sse'
import type { ChatSnapshot, SavedChatState } from '../types/conversations'
import type { FolderIndexedFile } from '../types/access'

let connection: Promise<BackendSession> | undefined
function session(): Promise<BackendSession> {
  return (connection ??=
    window.edgeDesktop?.getBackendSession() ?? Promise.resolve({ baseUrl: '', token: '' }))
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const backend = await session()
  const headers = new Headers(init.headers)
  if (backend.token) headers.set('Authorization', `Bearer ${backend.token}`)
  const response = await fetch(backend.baseUrl + path, { ...init, headers })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.error?.message || `本地服务请求失败（${response.status}）。`)
  }
  return response
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request(path, init)).json() as Promise<T>
}
function payload(value: unknown): RequestInit {
  return { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) }
}

function desktopAccess() {
  if (!window.edgeDesktop?.access)
    throw new Error('目录授权需要在桌面应用中使用。浏览器预览可以通过选择文件导入。')
  return window.edgeDesktop.access
}
function desktopFolders() {
  if (!window.edgeDesktop?.folders) throw new Error('文件夹持续同步需要在桌面应用中使用。')
  return window.edgeDesktop.folders
}
export const api = {
  loadChatState: () => json<SavedChatState>('/api/chat-state'),
  saveChatState: (state: ChatSnapshot, revision: number) =>
    json<{ revision: number }>('/api/chat-state', {
      method: 'POST',
      ...payload({ ...state, revision }),
    }),
  archiveDocuments: (library: string, ids: string[], all = false) =>
    json<{ archived: number; document_ids: string[]; folder_sync_paused: boolean }>(
      `/api/libraries/${encodeURIComponent(library)}/documents/archive-batch`,
      { method: 'POST', ...payload({ document_ids: ids, all_documents: all }) },
    ),
  restoreDocuments: (library: string, ids: string[]) =>
    json<{ restored: number }>(
      `/api/libraries/${encodeURIComponent(library)}/archive/restore-batch`,
      { method: 'POST', ...payload({ document_ids: ids }) },
    ),
  async pauseFolderSources(library: string) {
    if (!window.edgeDesktop?.folders) return
    for (const source of await desktopFolders().list(library)) {
      if (source.state !== 'revoked') await desktopFolders().pause(source.id)
    }
  },
  folderIndexedFiles: (library: string, source: string) =>
    json<FolderIndexedFile[]>(
      `/api/libraries/${encodeURIComponent(library)}/folders/${encodeURIComponent(source)}/files`,
    ),
  foldersAvailable: () => Boolean(window.edgeDesktop?.folders),
  folderSources: (library: string) => desktopFolders().list(library),
  folderChoose: (library: string) => desktopFolders().choose(library),
  folderSync: (id: string) => desktopFolders().sync(id),
  folderPause: (id: string) => desktopFolders().pause(id),
  folderResume: (id: string) => desktopFolders().resume(id),
  folderDisconnect: (id: string) => desktopFolders().disconnect(id),
  async exportBackup(frontend: unknown, signal: AbortSignal) {
    return (
      await request('/api/backup/export', { method: 'POST', ...payload(frontend), signal })
    ).blob()
  },
  async inspectBackup(file: File, signal: AbortSignal) {
    const body = new FormData()
    body.append('file', file)
    return json<BackupInspection>('/api/backup/inspect', { method: 'POST', body, signal })
  },
  async restoreBackup(file: File, signal: AbortSignal) {
    const body = new FormData()
    body.append('file', file)
    return json<BackupRestoration>('/api/backup/restore', { method: 'POST', body, signal })
  },
  desktopAvailable: () => Boolean(window.edgeDesktop?.access),
  accessList: () => desktopAccess().list(),
  accessChoose: (kind: 'file' | 'directory') => desktopAccess().choose(kind),
  accessRevoke: (id: string) => desktopAccess().revoke(id),
  accessScan: (id: string) => desktopAccess().scan(id),
  accessImport: (id: string, files: string[], library: string) =>
    desktopAccess().importFiles(id, [...files], library),
  async semanticBudget(options: SemanticOptions, files: File[], signal: AbortSignal) {
    const form = new FormData()
    form.append('options', JSON.stringify(options))
    files.forEach((file) => form.append('files', file))
    return json<EmbeddingBudget>('/api/multimodal/budget', { method: 'POST', body: form, signal })
  },
  async semanticSearch(options: SemanticOptions, files: File[], signal: AbortSignal) {
    const form = new FormData()
    form.append('options', JSON.stringify(options))
    files.forEach((file) => form.append('files', file))
    return json<SemanticResult>('/api/multimodal/search', { method: 'POST', body: form, signal })
  },
  async semanticIngest(options: SemanticOptions, files: File[], signal: AbortSignal) {
    const form = new FormData()
    form.append('options', JSON.stringify(options))
    files.forEach((file) => form.append('files', file))
    return json<{ document: Document; duplicate: boolean; budget?: EmbeddingBudget }>(
      '/api/multimodal/ingest',
      { method: 'POST', body: form, signal },
    )
  },
  organize: (
    options: {
      library_id: string
      document_ids: string[]
      task: string
      dimension: number
      labels: string[]
      clusters: number
      threshold: number
    },
    signal: AbortSignal,
  ) => json<OrganizationResult>('/api/organize', { method: 'POST', ...payload(options), signal }),
  mediaManifest: (library: string, document: string, signal: AbortSignal) =>
    json<MediaAsset[]>(
      `/api/libraries/${encodeURIComponent(library)}/documents/${encodeURIComponent(document)}/media`,
      { signal },
    ),
  async mediaAsset(library: string, document: string, index: number, signal: AbortSignal) {
    return (
      await request(
        `/api/libraries/${encodeURIComponent(library)}/documents/${encodeURIComponent(document)}/media/${index}`,
        { signal },
      )
    ).blob()
  },
  archived: (library: string) =>
    json<Document[]>(`/api/libraries/${encodeURIComponent(library)}/archive`),
  archiveDocument: (library: string, document: string, signal?: AbortSignal) =>
    json(
      `/api/libraries/${encodeURIComponent(library)}/documents/${encodeURIComponent(document)}/archive`,
      { method: 'POST', signal },
    ),
  restoreDocument: (library: string, document: string, signal?: AbortSignal) =>
    json(
      `/api/libraries/${encodeURIComponent(library)}/archive/${encodeURIComponent(document)}/restore`,
      { method: 'POST', signal },
    ),
  health: () => json<Health>('/api/health'),
  libraries: () => json<Library[]>('/api/libraries'),
  async extractImageText(file: File, signal?: AbortSignal) {
    const form = new FormData()
    form.append('file', file)
    return json<OCRExtraction>('/api/ocr', { method: 'POST', body: form, signal })
  },
  createLibrary: (name: string) =>
    json<Library>('/api/libraries', { method: 'POST', ...payload({ name }) }),
  documents: (library: string) =>
    json<Document[]>(`/api/libraries/${encodeURIComponent(library)}/documents`),
  async ingest(library: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    return json<{ document: Document; duplicate: boolean }>(
      `/api/libraries/${encodeURIComponent(library)}/documents`,
      { method: 'POST', body: form },
    )
  },
  deleteDocument: (library: string, document: string) =>
    json(
      `/api/libraries/${encodeURIComponent(library)}/documents/${encodeURIComponent(document)}`,
      { method: 'DELETE' },
    ),
  settings: () => json<Settings>('/api/settings'),
  capabilities: (model?: string) =>
    json<Capabilities>('/api/capabilities' + (model ? `?model=${encodeURIComponent(model)}` : '')),
  async imageAsset(library: string, document: string, thumbnail: boolean, signal: AbortSignal) {
    const response = await request(
      `/api/libraries/${encodeURIComponent(library)}/documents/${encodeURIComponent(document)}/${thumbnail ? 'thumbnail' : 'image'}`,
      { signal },
    )
    return response.blob()
  },
  updateSettings: (settings: SettingsPatch) =>
    json<Settings>('/api/settings', { method: 'PATCH', ...payload(settings) }),
  search: (library: string, question: string, signal: AbortSignal, documentIds: string[] = []) =>
    json<Source[]>('/api/search', {
      method: 'POST',
      ...payload({ library_id: library, question, document_ids: documentIds }),
      signal,
    }),
  localQuery: (
    library: string,
    question: string,
    signal: AbortSignal,
    documentIds: string[] = [],
    queryPlan?: import('../types/query').QuerySpec,
  ) =>
    json<LocalQueryResult>('/api/local-query', {
      method: 'POST',
      ...payload({
        library_id: library,
        question,
        document_ids: documentIds,
        query_plan: queryPlan,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
      signal,
    }),
  async *query(
    library: string,
    question: string,
    signal: AbortSignal,
    allowImageUpload = false,
    options: QueryOptions = {},
  ): AsyncGenerator<ChatEvent> {
    const response = await request('/api/query', {
      method: 'POST',
      ...payload({
        library_id: library,
        question,
        allow_image_upload: allowImageUpload,
        document_ids: options.documentIds ?? [],
        query_plan: options.queryPlan,
        allow_planning: true,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        history: options.history ?? [],
      }),
      signal,
    })
    if (!response.body) throw new Error('本地服务没有返回回答。')
    let completed = false
    for await (const event of readSSE<ChatEvent>(response.body)) {
      yield event
      if (event.type === 'done' || event.type === 'error') {
        completed = true
        break
      }
    }
    if (!completed) throw new Error('回答连接中断，请重试。')
  },
}
