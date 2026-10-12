import { afterEach, describe, expect, it, vi } from 'vitest'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, writeFile, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { LocalAccess } from './access'
import { FolderSources, type FolderBackend } from './folders'

const temporary: string[] = []
const managers: FolderSources[] = []
afterEach(async () => {
  for (const manager of managers.splice(0)) await manager.stop()
  vi.useRealTimers()
  await Promise.all(temporary.splice(0).map((path) => rm(path, { recursive: true, force: true })))
})
async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'edge-folders-'))
  temporary.push(root)
  const folder = join(root, 'notes')
  await mkdir(folder)
  const access = new LocalAccess(join(root, 'grants.json'))
  await access.initialize()
  await access.grant([folder], 'directory')
  const grant = access.list()[0]!
  const rows = new Map<string, Map<string, string>>()
  function entries(library: string, source: string) {
    const key = library + '/' + source
    if (!rows.has(key)) rows.set(key, new Map())
    return rows.get(key)!
  }
  const backend: FolderBackend = {
    ready: vi.fn(async () => true),
    files: vi.fn(async (library, source) =>
      [...entries(library, source)].map(([path, fingerprint]) => ({ path, fingerprint })),
    ),
    upsert: vi.fn(async (library, source, path, bytes) => {
      entries(library, source).set(path, createHash('sha256').update(bytes).digest('hex'))
      return { changed: true }
    }),
    reconcile: vi.fn(async (library, source, paths) => {
      let removed = 0
      for (const path of entries(library, source).keys())
        if (!paths.includes(path)) {
          entries(library, source).delete(path)
          removed++
        }
      return { removed }
    }),
  }
  const store = join(root, 'sources.json')
  const folders = new FolderSources(store, access, backend)
  managers.push(folders)
  await folders.initialize()
  const id = await folders.connect(grant.id, 'default')
  return { root, folder, access, grant, backend, folders, id, store }
}
async function sync(folders: FolderSources, id: string) {
  await folders.sync(id)
  await folders.settled()
}

describe('folder source synchronization', () => {
  it('respects a persisted clear-library pause and submits the new epoch only after explicit resume', async () => {
    const { folder, folders, id, backend, access } = await fixture()
    await writeFile(join(folder, 'notes.md'), 'New note')
    let enabled = false
    backend.lease = vi.fn(async () => ({ epoch: 4, enabled }))
    backend.activate = vi.fn(async () => {
      enabled = true
    })
    const scan = vi.spyOn(access, 'scan')
    await sync(folders, id)
    expect(scan).not.toHaveBeenCalled()
    expect(folders.list('default')[0]).toMatchObject({ state: 'paused', automatic: false })
    await folders.resume(id)
    await folders.settled()
    expect(backend.activate).toHaveBeenCalledTimes(1)
    expect(vi.mocked(backend.upsert).mock.calls[0]![5]).toBe(4)
  })
  it('indexes more than 100 nested notes and encodes only changed content on later scans', async () => {
    const { folder, folders, id, backend } = await fixture()
    await mkdir(join(folder, 'nested'))
    await Promise.all(
      Array.from({ length: 130 }, (_, i) =>
        writeFile(join(folder, 'nested', i + '.md'), 'note ' + i),
      ),
    )
    await sync(folders, id)
    expect(folders.list('default')[0]!.indexed).toBe(130)
    expect(backend.upsert).toHaveBeenCalledTimes(130)
    await sync(folders, id)
    expect(backend.upsert).toHaveBeenCalledTimes(130)
    await writeFile(join(folder, 'nested', '0.md'), 'updated')
    await rm(join(folder, 'nested', '1.md'))
    await sync(folders, id)
    expect(backend.upsert).toHaveBeenCalledTimes(131)
    expect(folders.list('default')[0]).toMatchObject({
      indexed: 129,
      changed: 1,
      removed: 1,
      state: 'idle',
    })
    expect(await folders.connect(folders.list('default')[0]!.grantId, 'default')).toBe(id)
    expect(folders.list('another')).toEqual([])
  })
  it('does not reconcile missing files after a partial scan or indexing failure', async () => {
    const { folder, folders, id, backend, access } = await fixture()
    await writeFile(join(folder, 'notes.md'), 'original')
    await sync(folders, id)
    vi.mocked(backend.reconcile).mockClear()
    await rm(join(folder, 'notes.md'))
    const realScan = access.scan.bind(access)
    vi.spyOn(access, 'scan').mockImplementation(async (...args) => ({
      ...(await realScan(...args)),
      complete: false,
    }))
    await sync(folders, id)
    expect(backend.reconcile).not.toHaveBeenCalled()
    expect(folders.list('default')[0]!.state).toBe('error')
    vi.restoreAllMocks()
    await writeFile(join(folder, 'new.md'), 'new')
    vi.mocked(backend.upsert).mockRejectedValueOnce(new Error('model failure'))
    await sync(folders, id)
    expect(backend.reconcile).not.toHaveBeenCalled()
    expect(folders.list('default')[0]!.failures).toHaveLength(1)
  })
  it('never reads a replaced symlink and preserves its previous index during reconciliation', async () => {
    const { root, folder, folders, id, backend } = await fixture()
    await writeFile(join(folder, 'notes.md'), 'original')
    await sync(folders, id)
    await writeFile(join(root, 'outside.md'), 'outside private content')
    await rm(join(folder, 'notes.md'))
    await symlink(join(root, 'outside.md'), join(folder, 'notes.md'))
    await sync(folders, id)
    expect(backend.upsert).toHaveBeenCalledTimes(1)
    expect(folders.list('default')[0]!.indexed).toBe(1)
    expect(vi.mocked(backend.reconcile).mock.calls.at(-1)![2]).toContain('notes.md')
  })
  it('pauses a pending file and prevents subsequent reads and reconciliation', async () => {
    const { folder, folders, id, backend } = await fixture()
    await writeFile(join(folder, 'one.md'), 'one')
    await writeFile(join(folder, 'two.md'), 'two')
    let entered!: () => void
    const pending = new Promise<void>((resolve) => {
      entered = resolve
    })
    vi.mocked(backend.upsert).mockImplementation(async (_lib, _id, _path, _bytes, signal) => {
      entered()
      await new Promise((_resolve, reject) =>
        signal.addEventListener('abort', () => reject(signal.reason), { once: true }),
      )
      return { changed: true }
    })
    await folders.sync(id)
    await pending
    await folders.pause(id)
    await folders.settled()
    expect(backend.upsert).toHaveBeenCalledTimes(1)
    expect(backend.reconcile).not.toHaveBeenCalled()
    expect(folders.list('default')[0]).toMatchObject({ state: 'paused', automatic: false })
  })
  it('persists paused sources, revokes access, and disconnects without deleting indexed data', async () => {
    const { folder, folders, id, backend, access, grant, store } = await fixture()
    await writeFile(join(folder, 'notes.md'), 'original')
    await sync(folders, id)
    await folders.pause(id)
    const reloaded = new FolderSources(store, access, backend)
    managers.push(reloaded)
    await reloaded.initialize()
    expect(reloaded.list('default')[0]).toMatchObject({
      state: 'paused',
      automatic: false,
      indexed: 1,
    })
    await access.revoke(grant.id)
    await folders.revoke(grant.id)
    await expect(folders.resume(id)).rejects.toThrow('已撤销')
    await sync(folders, id)
    expect(folders.list('default')[0]!.state).toBe('revoked')
    await folders.disconnect(id)
    expect(folders.list('default')).toEqual([])
    expect(await backend.files('default', id, new AbortController().signal)).toHaveLength(1)
    await access.grant([folder], 'directory')
    const reconnected = await folders.connect(access.list()[0]!.id, 'default')
    expect(reconnected).toBe(id)
    await sync(folders, id)
    expect(backend.upsert).toHaveBeenCalledTimes(1)
  })
  it('automatically detects new files on the next minute while the app is running', async () => {
    const { folder, folders, backend } = await fixture()
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    folders.start()
    await folders.settled()
    await writeFile(join(folder, 'new.md'), 'new note')
    await vi.advanceTimersByTimeAsync(60_000)
    await folders.settled()
    expect(backend.upsert).toHaveBeenCalledTimes(1)
  })
  it('does not read notes or start indexing when the real model is not ready', async () => {
    const { folder, folders, id, backend } = await fixture()
    await writeFile(join(folder, 'notes.md'), 'original')
    vi.mocked(backend.ready).mockResolvedValue(false)
    await sync(folders, id)
    expect(backend.files).not.toHaveBeenCalled()
    expect(backend.upsert).not.toHaveBeenCalled()
    expect(folders.list('default')[0]).toMatchObject({
      state: 'error',
      message: '本地检索模型尚未准备，请先完成模型下载。',
    })
  })
})
