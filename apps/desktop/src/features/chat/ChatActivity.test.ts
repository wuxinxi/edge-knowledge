// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick, reactive } from 'vue'
import { createPinia } from 'pinia'
import ChatActivity from './ChatActivity.vue'
let view: ReturnType<typeof createApp>, root: HTMLDivElement

afterEach(() => {
  view?.unmount()
  root?.remove()
  vi.useRealTimers()
})
it('shows actual stages while waiting, collapses on first answer and freezes duration on finish', async () => {
  vi.useFakeTimers()
  vi.setSystemTime(1000)
  const props = reactive({
    processing: {
      startedAt: 1000,
      finishedAt: undefined as number | undefined,
      steps: [{ stage: 'planning' as const, startedAt: 1000 }],
    },
    running: true,
    hasContent: false,
    status: 'streaming',
  })
  root = document.createElement('div')
  document.body.append(root)
  view = createApp({
    components: { ChatActivity },
    setup: () => ({ props }),
    template: '<ChatActivity v-bind="props" />',
  }).use(createPinia())
  view.mount(root)
  expect(root.querySelector('details')!.open).toBe(true)
  expect(root.textContent).toContain('理解问题')
  vi.advanceTimersByTime(1500)
  await nextTick()
  expect(root.querySelector('.activity-elapsed')!.textContent).toBe('1.5s')
  props.hasContent = true
  await nextTick()
  expect(root.querySelector('details')!.open).toBe(false)
  props.running = false
  props.status = 'stopped'
  props.processing.finishedAt = 2600
  await nextTick()
  vi.advanceTimersByTime(5000)
  await nextTick()
  expect(root.querySelector('.activity-elapsed')!.textContent).toBe('1.6s')
  expect(root.textContent).toContain('已停止')
  expect(vi.getTimerCount()).toBe(0)
})
