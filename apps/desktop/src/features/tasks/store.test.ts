import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTaskStore } from './store'
beforeEach(() => setActivePinia(createPinia()))
it('never turns a stopped request into a success when its late response arrives', () => {
  const tasks = useTaskStore(),
    id = tasks.begin('查找资料', 'notes-a')
  tasks.finish(id, 'stopped', 'Stopped waiting')
  tasks.update(id, { phase: 'Late response' })
  tasks.finish(id, 'success')
  expect(tasks.get(id)).toMatchObject({ state: 'stopped', detail: 'Stopped waiting' })
})
it('keeps active and resumable jobs when clearing or trimming history', () => {
  const tasks = useTaskStore(),
    live = tasks.begin('查找资料', 'notes-a')
  const retry = vi.fn(),
    resumable = tasks.begin('导入资料', 'notes-b')
  tasks.finish(resumable, 'stopped')
  tasks.setActions(resumable, { retry })
  for (let i = 0; i < 30; i++) {
    const id = tasks.begin('查找资料', 'notes-a')
    tasks.finish(id, 'success')
  }
  expect(tasks.get(live)?.state).toBe('running')
  expect(tasks.get(resumable)).toBeDefined()
  tasks.clearFinished()
  expect(tasks.items).toHaveLength(2)
  tasks.retry(resumable)
  expect(retry).toHaveBeenCalledTimes(1)
})
