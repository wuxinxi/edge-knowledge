export interface AccessGrant {
  id: string
  name: string
  path: string
  kind: 'file' | 'directory'
  createdAt: string
}
export interface AccessFile {
  id: string
  name: string
  size: number
}
export interface AccessScan {
  files: AccessFile[]
  skipped: number
  limited: boolean
  complete: boolean
  protected: string[]
}

export interface FolderSource {
  id: string
  grantId: string
  library: string
  name: string
  path: string
  automatic: boolean
  state: 'idle' | 'queued' | 'scanning' | 'syncing' | 'paused' | 'error' | 'revoked'
  completed: number
  total: number
  indexed: number
  changed: number
  removed: number
  skipped: number
  failures: { name: string; message: string }[]
  lastSynced?: string
  message: string
}
export interface DesktopFolders {
  list(library: string): Promise<FolderSource[]>
  choose(library: string): Promise<FolderSource[]>
  sync(id: string): Promise<void>
  pause(id: string): Promise<void>
  resume(id: string): Promise<void>
  disconnect(id: string): Promise<void>
}
export interface FolderIndexedFile {
  path: string
  fingerprint: string
  document_id: string
}
export interface AccessImport {
  imported: number
  duplicates: number
  failed: { name: string; message: string }[]
}
export interface DesktopAccess {
  list(): Promise<AccessGrant[]>
  choose(kind: 'file' | 'directory'): Promise<AccessGrant[]>
  revoke(id: string): Promise<void>
  scan(id: string): Promise<AccessScan>
  importFiles(id: string, files: string[], library: string): Promise<AccessImport>
}
