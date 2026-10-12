import { describe, it, expect, afterEach } from 'vitest'
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { LocalAccess } from './access'
const temporary: string[] = []
afterEach(async () => {
  await Promise.all(temporary.splice(0).map((path) => rm(path, { recursive: true, force: true })))
})
async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'edge-access-'))
  temporary.push(root)
  const folder = join(root, 'selected')
  await mkdir(folder)
  const access = new LocalAccess(join(root, 'private', 'grants.json'))
  await access.initialize()
  return { root, folder, access }
}
describe('scoped local access', () => {
  it('persists only explicit locations and excludes hidden files and symlink escapes', async () => {
    const { root, folder, access } = await fixture()
    await writeFile(join(folder, 'notes.md'), 'authorized')
    await writeFile(join(folder, '.hidden.md'), 'private')
    await writeFile(join(root, 'outside.md'), 'outside')
    await symlink(join(root, 'outside.md'), join(folder, 'linked.md'))
    await access.grant([folder], 'directory')
    const id = access.list()[0]!.id,
      scan = await access.scan(id)
    expect(scan.files.map((file) => file.name)).toEqual(['notes.md'])
    expect(scan.skipped).toBe(2)
    const restored = new LocalAccess(join(root, 'private', 'grants.json'))
    await restored.initialize()
    expect(restored.list()).toEqual(access.list())
    await expect(
      access.importFiles(id, ['../outside.md'], 'default', async () => false),
    ).rejects.toThrow('扫描结果已失效')
  })
  it('imports selected IDs, reports duplicates, and rejects changed files', async () => {
    const { folder, access } = await fixture()
    const file = join(folder, 'notes.md')
    await writeFile(file, 'original')
    await access.grant([folder], 'directory')
    const id = access.list()[0]!.id,
      scan = await access.scan(id)
    const contents: string[] = []
    const imported = await access.importFiles(
      id,
      [scan.files[0]!.id],
      'default',
      async (_, bytes) => {
        contents.push(new TextDecoder().decode(bytes))
        return false
      },
    )
    expect(imported.imported).toBe(1)
    expect(contents).toEqual(['original'])
    const duplicates = await access.importFiles(
      id,
      [scan.files[0]!.id],
      'default',
      async () => true,
    )
    expect(duplicates.duplicates).toBe(1)
    await writeFile(file, 'changed content')
    const changed = await access.importFiles(id, [scan.files[0]!.id], 'default', async () => {
      throw new Error('must not import')
    })
    expect(changed.failed[0]!.message).toContain('文件已改变')
  })
  it('rejects revoked grants and replaced files before reading', async () => {
    const { root, folder, access } = await fixture()
    const file = join(folder, 'notes.md')
    await writeFile(file, 'original')
    await access.grant([folder], 'directory')
    const id = access.list()[0]!.id,
      scan = await access.scan(id)
    await writeFile(join(root, 'outside.md'), 'outside')
    await rm(file)
    await symlink(join(root, 'outside.md'), file)
    const replaced = await access.importFiles(id, [scan.files[0]!.id], 'default', async () => {
      throw new Error('must not read')
    })
    expect(replaced.failed[0]!.message).toContain('授权范围以外')
    await access.revoke(id)
    await expect(access.scan(id)).rejects.toThrow('未授权或已撤销')
    await expect(
      access.importFiles(id, [scan.files[0]!.id], 'default', async () => false),
    ).rejects.toThrow('未授权或已撤销')
  })
  it('bounds recursive scans and rejects oversized batches', async () => {
    const { folder, access } = await fixture()
    await Promise.all(
      Array.from({ length: 101 }, (_, i) => writeFile(join(folder, `${i}.md`), 'ok')),
    )
    await access.grant([folder], 'directory')
    const id = access.list()[0]!.id,
      scan = await access.scan(id)
    expect(scan.files).toHaveLength(100)
    expect(scan.limited).toBe(true)
    await expect(
      access.importFiles(id, [scan.files[0]!.id, scan.files[0]!.id], 'default', async () => false),
    ).rejects.toThrow('参数无效')
    await expect(
      access.importFiles(id, [scan.files[0]!.id], '../other', async () => false),
    ).rejects.toThrow('参数无效')
  })
})
