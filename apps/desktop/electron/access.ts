import { constants } from 'node:fs'
import {
  mkdir,
  readFile,
  writeFile,
  rename,
  lstat,
  realpath,
  opendir,
  open,
} from 'node:fs/promises'
import { basename, dirname, join, relative, isAbsolute, extname } from 'node:path'
import { randomUUID } from 'node:crypto'
import type { AccessGrant, AccessFile, AccessScan, AccessImport } from '../src/shared/types/access'

const media = new Set([
  '.wav',
  '.mp3',
  '.m4a',
  '.aac',
  '.flac',
  '.ogg',
  '.mp4',
  '.mov',
  '.mkv',
  '.webm',
])
const formats = new Set([
  '.txt',
  '.md',
  '.pdf',
  '.docx',
  '.png',
  '.jpg',
  '.jpeg',
  '.webp',
  ...media,
])
const contains = (root: string, path: string) => {
  const part = relative(root, path)
  return !isAbsolute(part) && part !== '..' && !part.startsWith('../') && !part.startsWith('..\\')
}
type Candidate = AccessFile & { path: string; ino: number; dev: number; mtime: number }
export class LocalAccess {
  private grants = new Map<string, AccessGrant>()
  private candidates = new Map<string, Map<string, Candidate>>()
  private writes: Promise<void> = Promise.resolve()
  constructor(private store: string) {}
  async initialize() {
    try {
      const values: unknown = JSON.parse(await readFile(this.store, 'utf8'))
      if (!Array.isArray(values)) return
      for (const item of values.slice(0, 100)) {
        if (
          item &&
          typeof item.id === 'string' &&
          typeof item.path === 'string' &&
          isAbsolute(item.path) &&
          typeof item.name === 'string' &&
          ['file', 'directory'].includes(item.kind)
        )
          this.grants.set(item.id, item)
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT')
        throw new Error('授权记录无法读取，请检查本地数据目录。')
    }
  }
  list() {
    return [...this.grants.values()]
  }
  private persist() {
    const data = JSON.stringify(this.list())
    const pending = this.writes
      .catch(() => {})
      .then(async () => {
        await mkdir(dirname(this.store), { recursive: true, mode: 0o700 })
        const temporary = this.store + '.tmp'
        await writeFile(temporary, data, { mode: 0o600 })
        await rename(temporary, this.store)
      })
    this.writes = pending
    return pending
  }
  async grant(paths: string[], kind: 'file' | 'directory') {
    const added: AccessGrant[] = []
    const created: string[] = []
    if (paths.length > 20 || this.grants.size + paths.length > 100)
      throw new Error('最多授权 100 个位置，每次最多选择 20 个。')
    for (const path of paths) {
      const canonical = await realpath(path)
      const stats = await lstat(canonical)
      if (kind === 'directory' ? !stats.isDirectory() : !stats.isFile())
        throw new Error('请选择有效的文件或目录。')
      const existing = this.list().find((item) => item.path === canonical)
      if (existing) {
        added.push(existing)
        continue
      }
      const grant: AccessGrant = {
        id: randomUUID(),
        name: basename(canonical),
        path: canonical,
        kind,
        createdAt: new Date().toISOString(),
      }
      this.grants.set(grant.id, grant)
      created.push(grant.id)
      added.push(grant)
    }
    try {
      await this.persist()
    } catch (error) {
      for (const id of created) this.grants.delete(id)
      throw error
    }
    return this.list()
  }
  async revoke(id: string) {
    const grant = this.grants.get(id)
    if (!grant) return
    this.grants.delete(id)
    this.candidates.delete(id)
    try {
      await this.persist()
    } catch (error) {
      this.grants.set(id, grant)
      throw error
    }
  }
  private get(id: string) {
    const grant = this.grants.get(id)
    if (!grant) throw new Error('此位置未授权或已撤销，请重新选择。')
    return grant
  }
  async scan(id: string, maxFiles = 100, signal?: AbortSignal): Promise<AccessScan> {
    const grant = this.get(id)
    if ((await realpath(grant.path)) !== grant.path || (await lstat(grant.path)).isSymbolicLink())
      throw new Error('授权位置已改变，请重新选择。')
    const files = new Map<string, Candidate>()
    const protectedPaths: string[] = []
    let skipped = 0,
      visited = 0,
      limited = false,
      complete = true
    const visit = async (path: string, depth: number): Promise<void> => {
      signal?.throwIfAborted()
      this.get(id)
      if (++visited > maxFiles * 20 || files.size >= maxFiles || depth > 32) {
        limited = true
        return
      }
      const stats = await lstat(path)
      if (stats.isSymbolicLink()) {
        protectedPaths.push(relative(grant.path, path).replaceAll('\\', '/'))
        skipped++
        return
      }
      if (stats.isDirectory()) {
        const entries = await opendir(path)
        for await (const entry of entries) {
          if (visited + skipped >= maxFiles * 20 || files.size >= maxFiles) {
            limited = true
            break
          }
          if (entry.name.startsWith('.') || ['node_modules', '__pycache__'].includes(entry.name)) {
            skipped++
            continue
          }
          if (visited >= maxFiles * 20 || files.size >= maxFiles) {
            limited = true
            break
          }
          try {
            await visit(join(path, entry.name), depth + 1)
          } catch (error) {
            signal?.throwIfAborted()
            if (!this.grants.has(id)) throw error
            complete = false
            skipped++
          }
        }
      } else if (stats.isFile()) {
        const suffix = extname(path).toLowerCase()
        if (!formats.has(suffix) || stats.size > (media.has(suffix) ? 200 : 20) * 1024 ** 2) {
          protectedPaths.push(relative(grant.path, path).replaceAll('\\', '/'))
          skipped++
          return
        }
        const file: Candidate = {
          id: randomUUID(),
          name:
            grant.kind === 'file' ? grant.name : relative(grant.path, path).replaceAll('\\', '/'),
          size: stats.size,
          path,
          ino: stats.ino,
          dev: stats.dev,
          mtime: stats.mtimeMs,
        }
        files.set(file.id, file)
      }
    }
    await visit(grant.path, 0)
    this.get(id)
    this.candidates.set(id, files)
    return {
      files: [...files.values()].map(({ id, name, size }) => ({ id, name, size })),
      skipped,
      limited,
      complete: complete && !limited,
      protected: protectedPaths,
    }
  }
  async importFiles(
    id: string,
    ids: string[],
    library: string,
    ingest: (name: string, content: Uint8Array) => Promise<boolean>,
  ): Promise<AccessImport> {
    if (
      !Array.isArray(ids) ||
      !ids.length ||
      ids.length > 100 ||
      ids.some((value) => typeof value !== 'string') ||
      new Set(ids).size !== ids.length ||
      typeof library !== 'string' ||
      !/^[a-zA-Z0-9_-]{1,100}$/.test(library)
    )
      throw new Error('导入参数无效。')
    const grant = this.get(id)
    const candidates = this.candidates.get(id)
    const selected = ids.map((file) => {
      const item = candidates?.get(file)
      if (!item) throw new Error('扫描结果已失效，请重新扫描。')
      return item
    })
    if (selected.reduce((sum, file) => sum + file.size, 0) > 512 * 1024 ** 2)
      throw new Error('单次导入总量不能超过 512 MB，请分批选择。')
    const result: AccessImport = { imported: 0, duplicates: 0, failed: [] }
    for (const file of selected) {
      this.get(id)
      try {
        const canonical = await realpath(file.path)
        if (
          canonical !== file.path ||
          (grant.kind === 'file' ? canonical !== grant.path : !contains(grant.path, canonical))
        )
          throw new Error('文件已移动或指向授权范围以外。')
        const handle = await open(file.path, constants.O_RDONLY | constants.O_NOFOLLOW)
        let content: Uint8Array
        try {
          const stats = await handle.stat()
          if (
            !stats.isFile() ||
            stats.ino !== file.ino ||
            stats.dev !== file.dev ||
            stats.size !== file.size ||
            stats.mtimeMs !== file.mtime
          )
            throw new Error('文件已改变，请重新扫描。')
          // Bound allocation even if another process grows the file after the metadata check.
          const buffer = Buffer.alloc(file.size + 1)
          let offset = 0
          while (offset < buffer.length) {
            const read = await handle.read(buffer, offset, buffer.length - offset, offset)
            if (!read.bytesRead) break
            offset += read.bytesRead
          }
          if (offset !== file.size) throw new Error('文件正在修改，请稍后重试。')
          content = buffer.subarray(0, offset)
          const after = await handle.stat()
          if (after.size !== file.size || after.mtimeMs !== file.mtime)
            throw new Error('文件正在修改，请稍后重试。')
        } finally {
          await handle.close()
        }
        this.get(id)
        const duplicate = await ingest(basename(file.path), content)
        duplicate ? result.duplicates++ : result.imported++
      } catch (error) {
        if (!this.grants.has(id)) throw error
        result.failed.push({
          name: file.name,
          message: error instanceof Error ? error.message : '无法读取文件，请检查系统权限。',
        })
      }
    }
    return result
  }
}
