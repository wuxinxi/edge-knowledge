// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useImportStore } from './imports'
import { useTaskStore } from '../tasks/store'
import { api } from '../../shared/api/client'
import { memoryStorage } from '../../shared/preferences/test-storage'
vi.mock('../../app/store', () => ({
  useAppStore: () => ({ refreshLibraries: vi.fn().mockResolvedValue(undefined) }),
}))
vi.mock('../../shared/api/client', () => ({ api: { ingest: vi.fn() } }))
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  setActivePinia(createPinia())
  vi.clearAllMocks()
  vi.mocked(api.ingest).mockResolvedValue({ duplicate: false, document: { chunks: 1 } } as never)
})
function file(name: string) {
  return new File(['sample'], name, { type: 'text/plain' })
}
function pending<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}
it('stops after the submitted file settles and resumes only unfinished files in the original library', async () => {
  const store = useImportStore(),
    tasks = useTaskStore()
  const first = pending<never>()
  vi.mocked(api.ingest).mockReturnValueOnce(first.promise)
  const work = store.start('notes-a', [file('one.md'), file('two.md')])
  expect(store.running).toBe(true)
  expect(tasks.get(store.job!.taskId)).toMatchObject({ state: 'running', completed: 0, total: 2 })
  store.stop()
  expect(store.running).toBe(true)
  expect(tasks.get(store.job!.taskId)?.phase).toBe('等待当前文件完成')
  first.resolve({ duplicate: false, document: { chunks: 1 } } as never)
  await work
  expect(api.ingest).toHaveBeenCalledTimes(1)
  expect(store.remaining).toBe(1)
  expect(tasks.get(store.job!.taskId)).toMatchObject({ state: 'stopped', completed: 1, total: 2 })
  await store.retry()
  expect(api.ingest).toHaveBeenCalledTimes(2)
  expect(api.ingest).toHaveBeenLastCalledWith(
    'notes-a',
    expect.objectContaining({ name: 'two.md' }),
  )
  expect(tasks.get(store.job!.taskId)?.state).toBe('success')
})
it('keeps successful files intact and retries just the failed file', async () => {
  const store = useImportStore(),
    tasks = useTaskStore()
  vi.mocked(api.ingest).mockRejectedValueOnce(new Error('Readable failure'))
  await store.start('notes-a', [file('one.md'), file('two.md')])
  expect(store.failures).toBe(1)
  expect(tasks.get(store.job!.taskId)?.state).toBe('partial')
  expect(store.job!.rows[1]!.file).toBeUndefined()
  await store.retry()
  expect(api.ingest).toHaveBeenCalledTimes(3)
  expect(api.ingest).toHaveBeenLastCalledWith(
    'notes-a',
    expect.objectContaining({ name: 'one.md' }),
  )
  expect(store.job!.rows.map((row) => row.state)).toEqual(['success', 'success'])
})
it('blocks unsupported inputs locally and ignores another batch while one is running', async () => {
  const store = useImportStore()
  const first = pending<never>()
  vi.mocked(api.ingest).mockReturnValueOnce(first.promise)
  const work = store.start('notes-a', [file('one.md'), file('app.exe')])
  await store.start('notes-b', [file('wrong-library.md')])
  expect(store.job!.library).toBe('notes-a')
  first.resolve({ duplicate: false, document: { chunks: 1 } } as never)
  await work
  expect(api.ingest).toHaveBeenCalledTimes(1)
  expect(store.job!.rows[1]).toMatchObject({ state: 'error', message: '不支持此文件格式。' })
  expect(store.job!.rows[1]!.file).toBeUndefined()
  expect(useTaskStore().controls(store.job!.taskId).retry).toBeUndefined()
})
it('the task center can continue a stopped batch without retaining a mounted library view', async () => {
  const store = useImportStore(),
    tasks = useTaskStore(),
    first = pending<never>()
  vi.mocked(api.ingest).mockReturnValueOnce(first.promise)
  const work = store.start('notes-a', [file('one.md'), file('two.md')])
  tasks.stop(store.job!.taskId)
  first.resolve({ duplicate: false, document: { chunks: 1 } } as never)
  await work
  tasks.retry(store.job!.taskId)
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(api.ingest).toHaveBeenLastCalledWith(
    'notes-a',
    expect.objectContaining({ name: 'two.md' }),
  )
  expect(store.remaining).toBe(0)
})
