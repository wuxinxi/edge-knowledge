import { createHash, randomUUID } from 'node:crypto'
import { mkdir, readFile, writeFile, rename } from 'node:fs/promises'
import { dirname } from 'node:path'
import type { FolderSource } from '../src/shared/types/access'
import { LocalAccess } from './access'

export interface FolderBackend {
  lease?(
    library: string,
    source: string,
    signal: AbortSignal,
  ): Promise<{ epoch: number; enabled: boolean }>
  activate?(library: string, source: string): Promise<unknown>
  ready(signal: AbortSignal): Promise<boolean>
  files(
    library: string,
    source: string,
    signal: AbortSignal,
  ): Promise<{ path: string; fingerprint: string }[]>
  upsert(
    library: string,
    source: string,
    path: string,
    bytes: Uint8Array,
    signal: AbortSignal,
    epoch?: number,
  ): Promise<{ changed: boolean }>
  reconcile(
    library: string,
    source: string,
    paths: string[],
    signal: AbortSignal,
    epoch?: number,
  ): Promise<{ removed: number }>
}

export class FolderSources {
  private sources = new Map<string, FolderSource & { detached?: boolean }>()
  private controllers = new Map<string, AbortController>()
  private tasks = new Map<string, Promise<void>>()
  private queue: Promise<void> = Promise.resolve()
  private writes: Promise<void> = Promise.resolve()
  private timer?: ReturnType<typeof setInterval>
  private stopped = false
  constructor(
    private store: string,
    private access: LocalAccess,
    private backend: FolderBackend,
  ) {}

  async initialize() {
    try {
      const data: unknown = JSON.parse(await readFile(this.store, 'utf8'))
      if (!Array.isArray(data) || data.length > 100) throw new Error('Invalid sources')
      for (const item of data) {
        if (
          !item ||
          !/^[a-f0-9-]{36}$/.test(item.id) ||
          !/^[a-f0-9-]{36}$/.test(item.grantId) ||
          !/^[a-zA-Z0-9_-]{1,100}$/.test(item.library) ||
          typeof item.automatic !== 'boolean'
        )
          throw new Error('Invalid source')
        const grant = this.access
          .list()
          .find((g) => g.id === item.grantId && g.kind === 'directory')
        this.sources.set(item.id, {
          ...item,
          name: grant?.name ?? item.name,
          path: grant?.path ?? item.path,
          state: grant ? (item.automatic ? 'idle' : 'paused') : 'revoked',
          failures: [],
          message: '',
          completed: 0,
          total: 0,
        })
      }
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code !== 'ENOENT')
        throw new Error('文件夹来源记录无法读取，请检查本地数据目录。')
    }
  }
  start() {
    this.timer = setInterval(() => {
      for (const source of this.sources.values())
        if (!source.detached && source.automatic && source.state !== 'revoked')
          this.schedule(source)
    }, 60_000)
    this.timer.unref()
    for (const source of this.sources.values())
      if (!source.detached && source.automatic && source.state !== 'revoked') this.schedule(source)
  }
  private schedule(source: FolderSource) {
    void this.sync(source.id).catch(() => {
      source.state = 'error'
      source.message = '无法启动同步，请检查授权和本地存储。'
    })
  }
  list(library: string) {
    this.library(library)
    return [...this.sources.values()]
      .filter((s) => s.library === library && !s.detached)
      .map((s) => structuredClone(s))
  }
  private library(library: string) {
    if (typeof library !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(library))
      throw new Error('知识库无效。')
  }
  private get(id: string) {
    const source = this.sources.get(id)
    if (!source) throw new Error('文件夹来源不存在。')
    return source
  }
  private persist() {
    const data = JSON.stringify([...this.sources.values()])
    const pending = this.writes
      .catch(() => {})
      .then(async () => {
        await mkdir(dirname(this.store), { recursive: true, mode: 0o700 })
        await writeFile(this.store + '.tmp', data, { mode: 0o600 })
        await rename(this.store + '.tmp', this.store)
      })
    this.writes = pending
    return pending
  }
  async connect(grantId: string, library: string) {
    this.library(library)
    const grant = this.access.list().find((g) => g.id === grantId && g.kind === 'directory')
    if (!grant) throw new Error('请选择已授权的文件夹。')
    const existing = [...this.sources.values()].find(
      (s) => s.library === library && (s.grantId === grantId || s.path === grant.path),
    )
    if (existing) {
      const old = structuredClone(existing)
      Object.assign(existing, {
        grantId,
        detached: false,
        automatic: true,
        state: 'idle',
        message: '',
      })
      try {
        await this.persist()
      } catch (cause) {
        Object.assign(existing, old)
        throw cause
      }
      await this.backend.activate?.(library, existing.id)
      return existing.id
    }
    if (this.sources.size >= 100) throw new Error('最多连接 100 个文件夹来源。')
    const source: FolderSource = {
      id: randomUUID(),
      grantId,
      library,
      name: grant.name,
      path: grant.path,
      automatic: true,
      state: 'idle',
      completed: 0,
      total: 0,
      indexed: 0,
      changed: 0,
      removed: 0,
      skipped: 0,
      failures: [],
      message: '',
    }
    this.sources.set(source.id, source)
    try {
      await this.persist()
    } catch (cause) {
      this.sources.delete(source.id)
      throw cause
    }
    await this.backend.activate?.(library, source.id)
    return source.id
  }
  async sync(id: string, explicit = false) {
    const source = this.get(id)
    if (source.detached) throw new Error('文件夹来源已移除，请重新连接。')
    if (this.stopped || this.controllers.has(id)) return
    if (explicit) await this.backend.activate?.(source.library, source.id)
    if (!this.access.list().some((g) => g.id === source.grantId)) {
      source.state = 'revoked'
      source.automatic = false
      await this.persist()
      return
    }
    const controller = new AbortController()
    this.controllers.set(id, controller)
    source.state = 'queued'
    this.queue = this.queue
      .catch(() => {})
      .then(async () => {
        try {
          await this.run(source, controller.signal)
        } catch (cause) {
          if (!controller.signal.aborted) {
            source.state = 'error'
            source.message = cause instanceof Error ? cause.message : '文件夹同步失败，请重试。'
          }
        } finally {
          this.controllers.delete(id)
          try {
            await this.persist()
          } catch {
            source.state = 'error'
            source.message = '同步状态保存失败，请检查设备存储。'
          }
          this.tasks.delete(id)
        }
      })
    this.tasks.set(id, this.queue)
  }
  private async run(source: FolderSource, signal: AbortSignal) {
    signal.throwIfAborted()
    source.state = 'scanning'
    source.failures = []
    source.message = ''
    source.completed = source.total = source.changed = source.removed = 0
    if (!(await this.backend.ready(signal)))
      throw new Error('本地检索模型尚未准备，请先完成模型下载。')
    const lease = (await this.backend.lease?.(source.library, source.id, signal)) ?? {
      epoch: 0,
      enabled: true,
    }
    if (!lease.enabled) {
      source.automatic = false
      source.state = 'paused'
      source.message = '资料已清空，文件夹同步保持暂停，可手动重新开启。'
      return
    }
    const scan = await this.access.scan(source.grantId, 5000, signal)
    signal.throwIfAborted()
    const manifest = await this.backend.files(source.library, source.id, signal)
    const known = new Map(manifest.map((e) => [e.path, e.fingerprint]))
    source.indexed = manifest.length
    source.total = scan.files.length
    source.skipped = scan.skipped
    source.state = 'syncing'
    let failed = 0
    for (const file of scan.files) {
      signal.throwIfAborted()
      const result = await this.access.importFiles(
        source.grantId,
        [file.id],
        source.library,
        async (_, bytes) => {
          signal.throwIfAborted()
          const fingerprint = createHash('sha256').update(bytes).digest('hex')
          if (known.get(file.name) === fingerprint) return true
          const update = await this.backend.upsert(
            source.library,
            source.id,
            file.name,
            bytes,
            signal,
            lease.epoch,
          )
          if (update.changed) {
            source.changed++
            known.set(file.name, fingerprint)
            source.indexed = known.size
          }
          return !update.changed
        },
      )
      signal.throwIfAborted()
      failed += result.failed.length
      source.failures.push(...result.failed.slice(0, 20 - source.failures.length))
      source.completed++
    }
    signal.throwIfAborted()
    if (scan.complete && !failed) {
      const present = new Set(scan.files.map((f) => f.name))
      for (const entry of manifest)
        if (scan.protected.some((p) => entry.path === p || entry.path.startsWith(p + '/')))
          present.add(entry.path)
      source.removed = (
        await this.backend.reconcile(source.library, source.id, [...present], signal, lease.epoch)
      ).removed
      source.lastSynced = new Date().toISOString()
    } else {
      source.message = scan.limited
        ? '本次扫描达到 5000 份资料或遍历上限；已处理可见资料，未清理缺失索引。请连接更小的子目录。'
        : '部分文件无法读取或索引，本次保留旧索引；修复后可重试。'
    }
    const current = await this.backend.files(source.library, source.id, signal)
    signal.throwIfAborted()
    source.indexed = current.length
    source.state = failed || !scan.complete ? 'error' : source.automatic ? 'idle' : 'paused'
  }
  async pause(id: string) {
    const source = this.get(id)
    source.automatic = false
    this.controllers.get(id)?.abort()
    source.state = source.state === 'revoked' ? 'revoked' : 'paused'
    await this.persist()
  }
  async resume(id: string) {
    const source = this.get(id)
    if (!this.access.list().some((g) => g.id === source.grantId))
      throw new Error('目录授权已撤销，请重新添加文件夹。')
    source.automatic = true
    source.state = 'idle'
    await this.persist()
    await this.tasks.get(id)
    await this.backend.activate?.(source.library, source.id)
    await this.sync(id)
  }
  async revoke(grantId: string) {
    for (const source of this.sources.values()) {
      if (source.grantId !== grantId) continue
      this.controllers.get(source.id)?.abort()
      source.automatic = false
      source.state = 'revoked'
      source.message = '目录访问已撤销，已入库资料保留。'
    }
    await this.persist()
  }
  async disconnect(id: string) {
    await this.pause(id)
    const source = this.get(id)
    // Retain the ownership identity so reconnecting does not duplicate existing notes.
    await this.tasks.get(id)
    source.detached = true
    try {
      await this.persist()
    } catch (cause) {
      source.detached = false
      throw cause
    }
  }
  async settled() {
    await this.queue
  }
  async stop() {
    this.stopped = true
    clearInterval(this.timer)
    for (const controller of this.controllers.values()) controller.abort()
    await this.queue
  }
}
