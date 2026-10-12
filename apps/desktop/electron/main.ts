import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import { mkdir, realpath } from 'node:fs/promises'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { LocalAccess } from './access'
import { BackendProcess, type BackendSession } from './backend'
import { FolderSources } from './folders'

const here = dirname(fileURLToPath(import.meta.url))
const backend = new BackendProcess()
let window: BrowserWindow | null = null
let session: BackendSession
let quitting = false
let folders: FolderSources | undefined

function createWindow(): void {
  window = new BrowserWindow({
    width: 1280,
    height: 850,
    minWidth: 960,
    minHeight: 700,
    title: 'Edge Assistant',
    backgroundColor: '#f4f6fa',
    webPreferences: {
      preload: join(here, '../preload/index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-navigate', (event) => event.preventDefault())
  window.webContents.session.setPermissionCheckHandler(
    (contents, permission) =>
      contents === window?.webContents && permission === 'clipboard-sanitized-write',
  )
  window.webContents.session.setPermissionRequestHandler((contents, permission, callback) =>
    callback(contents === window?.webContents && permission === 'clipboard-sanitized-write'),
  )
  window.on('closed', () => {
    window = null
  })
  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void window.loadFile(join(here, '../renderer/index.html'))
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    window?.show()
    window?.focus()
  })
  app.whenReady().then(async () => {
    try {
      const dataDir = join(app.getPath('userData'), app.isPackaged ? 'knowledge' : 'knowledge-dev')
      await mkdir(dataDir, { recursive: true, mode: 0o700 })
      session = await backend.start(
        resolve(here, '../..'),
        dataDir,
        process.resourcesPath,
        app.isPackaged,
        () => {
          dialog.showErrorBox('本地服务已停止', '请重新打开应用。已导入的知识库保存在本机。')
          app.quit()
        },
      )
      ipcMain.handle('backend:session', (event) => {
        if (
          event.sender !== window?.webContents ||
          event.senderFrame !== window.webContents.mainFrame
        ) {
          throw new Error('Unauthorized sender')
        }
        return session
      })
      const access = new LocalAccess(join(dataDir, 'local-access.json'))
      await access.initialize()
      async function localRequest(path: string, init: RequestInit): Promise<Response> {
        const headers = new Headers(init.headers)
        headers.set('Authorization', 'Bearer ' + session.token)
        const response = await fetch(session.baseUrl + path, { ...init, headers })
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { error?: { message?: string } }
          throw new Error(body.error?.message || '本地同步失败，请检查模型和知识库状态。')
        }
        return response
      }
      const folderPath = (library: string, source: string, suffix: string) =>
        `/api/libraries/${encodeURIComponent(library)}/folders/${encodeURIComponent(source)}/${suffix}`
      folders = new FolderSources(join(dataDir, 'folder-sources.json'), access, {
        lease: async (library, source, signal) =>
          (await localRequest(folderPath(library, source, 'lease'), { signal })).json(),
        activate: async (library, source) =>
          (await localRequest(folderPath(library, source, 'activate'), { method: 'POST' })).json(),
        ready: async (signal) =>
          Boolean(
            (await (await localRequest('/api/capabilities', { signal })).json()).embedding.ready,
          ),
        files: async (library, source, signal) =>
          (await localRequest(folderPath(library, source, 'files'), { signal })).json(),
        upsert: async (library, source, path, bytes, signal, epoch = 0) => {
          const body = new FormData()
          body.append('path', path)
          body.append('epoch', String(epoch))
          body.append('file', new Blob([new Uint8Array(bytes)]), basename(path))
          return (
            await localRequest(folderPath(library, source, 'files'), {
              method: 'POST',
              body,
              signal,
            })
          ).json()
        },
        reconcile: async (library, source, paths, signal, epoch = 0) =>
          (
            await localRequest(folderPath(library, source, 'reconcile'), {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ paths, complete: true, epoch }),
              signal,
            })
          ).json(),
      })
      await folders.initialize()
      const authorized = (event: Electron.IpcMainInvokeEvent) => {
        if (
          event.sender !== window?.webContents ||
          event.senderFrame !== window.webContents.mainFrame
        )
          throw new Error('Unauthorized sender')
      }
      ipcMain.handle('access:list', (event) => {
        authorized(event)
        return access.list()
      })
      ipcMain.handle('access:choose', async (event, kind: unknown) => {
        authorized(event)
        if (kind !== 'file' && kind !== 'directory') throw new Error('Invalid selection')
        const selected = await dialog.showOpenDialog(window!, {
          title: kind === 'directory' ? '选择允许读取的目录' : '选择允许读取的文件',
          properties: kind === 'directory' ? ['openDirectory'] : ['openFile', 'multiSelections'],
          buttonLabel: '允许读取所选位置',
        })
        if (!selected.canceled) await access.grant(selected.filePaths, kind)
        return access.list()
      })
      ipcMain.handle('access:revoke', async (event, id: string) => {
        authorized(event)
        await access.revoke(id)
        await folders!.revoke(id)
      })
      ipcMain.handle('access:scan', (event, id: string) => {
        authorized(event)
        return access.scan(id)
      })
      ipcMain.handle(
        'access:import',
        async (event, id: string, files: string[], library: string) => {
          authorized(event)
          return access.importFiles(id, files, library, async (name, content) => {
            const body = new FormData()
            body.append('file', new Blob([new Uint8Array(content)]), name)
            const response = await fetch(
              session.baseUrl + '/api/libraries/' + encodeURIComponent(library) + '/documents',
              {
                method: 'POST',
                headers: { Authorization: 'Bearer ' + session.token },
                body,
              },
            )
            if (!response.ok) throw new Error('本地导入失败，请检查模型状态、文件格式和知识库。')
            return Boolean(((await response.json()) as { duplicate: boolean }).duplicate)
          })
        },
      )
      ipcMain.handle('folders:list', (event, library: string) => {
        authorized(event)
        return folders!.list(library)
      })
      ipcMain.handle('folders:choose', async (event, library: string) => {
        authorized(event)
        folders!.list(library)
        const selected = await dialog.showOpenDialog(window!, {
          title: '连接笔记文件夹到当前知识库',
          message:
            '只读扫描子目录；应用打开时每分钟检查更新。不会修改原文件，可随时暂停或撤销访问。',
          properties: ['openDirectory'],
          buttonLabel: '连接并同步此文件夹',
        })
        if (!selected.canceled && selected.filePaths[0]) {
          const canonical = await realpath(selected.filePaths[0])
          const grants = await access.grant(selected.filePaths, 'directory')
          const grant = grants.find((g) => g.path === canonical)!
          const id = await folders!.connect(grant.id, library)
          await folders!.sync(id)
        }
        return folders!.list(library)
      })
      for (const action of ['sync', 'pause', 'resume', 'disconnect'] as const) {
        ipcMain.handle('folders:' + action, (event, id: string) => {
          authorized(event)
          return action === 'sync' ? folders!.sync(id, true) : folders![action](id)
        })
      }
      createWindow()
      folders.start()
      app.on('activate', () => {
        if (!window) createWindow()
      })
    } catch (error) {
      dialog.showErrorBox('启动失败', error instanceof Error ? error.message : '无法启动应用。')
      app.quit()
    }
  })
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
  app.on('before-quit', (event) => {
    if (quitting) return
    event.preventDefault()
    quitting = true
    void (folders?.stop() ?? Promise.resolve())
      .finally(() => backend.stop())
      .finally(() => app.quit())
  })
}
