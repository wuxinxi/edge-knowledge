import { defineStore } from 'pinia'
import { computed, ref, shallowReactive } from 'vue'

export type TaskState = 'running' | 'success' | 'partial' | 'error' | 'stopped'
export interface TaskRecord {
  id: string
  library: string
  title: string
  state: TaskState
  phase: string
  detail: string
  completed?: number
  total?: number
  startedAt: number
  updatedAt: number
}
interface Actions {
  stop?: () => void
  stopLabel?: string
  retry?: () => void
  retryLabel?: string
}
export const useTaskStore = defineStore('tasks', () => {
  const items = ref<TaskRecord[]>([])
  // Callbacks and file handles belong to this app run, never to saved user data.
  const actions = shallowReactive(new Map<string, Actions>())
  const activeCount = computed(() => items.value.filter((task) => task.state === 'running').length)
  const attentionCount = computed(
    () =>
      items.value.filter(
        (task) =>
          ['error', 'partial'].includes(task.state) ||
          (task.state === 'stopped' && !!actions.get(task.id)?.retry),
      ).length,
  )
  function prune() {
    const finished = items.value
      .filter((task) => task.state !== 'running' && !actions.get(task.id)?.retry)
      .slice(20)
    for (const task of finished) dismiss(task.id)
  }
  function begin(title: string, library: string, controls: Actions = {}) {
    const id = crypto.randomUUID(),
      now = Date.now()
    items.value.unshift({
      id,
      library,
      title,
      state: 'running',
      phase: '准备中',
      detail: '',
      startedAt: now,
      updatedAt: now,
    })
    actions.set(id, controls)
    prune()
    return id
  }
  function get(id: string) {
    return items.value.find((task) => task.id === id)
  }
  function update(
    id: string,
    patch: Partial<Pick<TaskRecord, 'phase' | 'detail' | 'completed' | 'total'>>,
  ) {
    const task = get(id)
    if (task?.state === 'running') Object.assign(task, patch, { updatedAt: Date.now() })
  }
  function finish(id: string, state: Exclude<TaskState, 'running'>, detail = '') {
    const task = get(id)
    if (task?.state !== 'running') return
    Object.assign(task, { state, detail, updatedAt: Date.now() })
    prune()
  }
  function setActions(id: string, controls: Actions) {
    if (get(id)) actions.set(id, controls)
  }
  function controls(id: string) {
    return actions.get(id) ?? {}
  }
  function stop(id: string) {
    if (get(id)?.state === 'running') actions.get(id)?.stop?.()
  }
  function retry(id: string) {
    if (get(id)?.state !== 'running') actions.get(id)?.retry?.()
  }
  function dismiss(id: string) {
    if (get(id)?.state === 'running') return
    items.value = items.value.filter((task) => task.id !== id)
    actions.delete(id)
  }
  function clearFinished() {
    for (const task of [...items.value]) if (!actions.get(task.id)?.retry) dismiss(task.id)
  }
  return {
    items,
    activeCount,
    attentionCount,
    begin,
    get,
    update,
    finish,
    setActions,
    controls,
    stop,
    retry,
    dismiss,
    clearFinished,
  }
})
