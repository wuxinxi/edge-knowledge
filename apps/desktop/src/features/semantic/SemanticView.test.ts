// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createApp, nextTick } from 'vue'
import { createPinia } from 'pinia'
import SemanticView from './SemanticView.vue'
import { api } from '../../shared/api/client'
import { memoryStorage } from '../../shared/preferences/test-storage'
import { inputIssue } from './workflows'
vi.mock('../../app/store', () => ({
  useAppStore: () => ({ activeLibrary: 'default', health: {}, refreshLibraries: vi.fn() }),
}))
vi.mock('../../shared/api/client', () => ({
  api: {
    documents: vi.fn(),
    archived: vi.fn(),
    semanticBudget: vi.fn(),
    semanticSearch: vi.fn(),
    organize: vi.fn(),
    semanticIngest: vi.fn(),
  },
}))
let root: HTMLDivElement, view: ReturnType<typeof createApp>
const wait = async () => {
  await new Promise((resolve) => setTimeout(resolve, 0))
  await nextTick()
}
function button(text: string) {
  return [...root.querySelectorAll<HTMLButtonElement>('button')].find((el) =>
    el.textContent?.includes(text),
  )!
}
async function mount() {
  root = document.createElement('div')
  document.body.append(root)
  view = createApp(SemanticView).use(createPinia())
  view.component('RouterLink', { template: '<a><slot /></a>' })
  view.mount(root)
  await wait()
}
beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  vi.clearAllMocks()
  vi.mocked(api.documents).mockResolvedValue([
    { id: 'image', filename: 'sample.png', kind: 'image' },
  ] as never)
  vi.mocked(api.archived).mockResolvedValue([])
  vi.mocked(api.semanticBudget).mockResolvedValue({
    fits: true,
    limit: 8192,
    max_tokens: 300,
    segments: 1,
    details: [],
  } as never)
  vi.mocked(api.semanticSearch).mockResolvedValue({
    sources: [],
    dimension: 768,
    budget: { limit: 8192, max_tokens: 300, segments: 1 },
  } as never)
  vi.mocked(api.organize).mockResolvedValue({ documents: [], pairs: [] } as never)
})
afterEach(() => {
  view?.unmount()
  root?.remove()
})
it('finds images with one action, automatic capacity checks and image results by default', async () => {
  await mount()
  expect(root.querySelector('details.workflow-advanced')?.hasAttribute('open')).toBe(false)
  const text = root.querySelector('textarea')!
  text.value = '蓝色产品图'
  text.dispatchEvent(new Event('input'))
  await wait()
  button('查找图片').click()
  await wait()
  expect(api.semanticBudget).toHaveBeenCalledTimes(1)
  expect(root.textContent).toContain('输入检查通过')
  expect(root.textContent).not.toContain('输入需要缩减')
  expect(api.semanticSearch).toHaveBeenCalledWith(
    expect.objectContaining({
      kinds: ['image'],
      dimension: 768,
      match_mode: 'auto',
      min_score: 0.55,
    }),
    [],
    expect.any(AbortSignal),
  )
})
it('allows explicit image text matching and explains filtered empty results', async () => {
  vi.mocked(api.semanticSearch).mockResolvedValue({
    sources: [],
    dimension: 768,
    aggregation: 'joint',
    budget: { limit: 8192, max_tokens: 300, segments: 1 },
    relevance: {
      mode: 'image_text',
      strategy: 'image_text',
      min_score: 0.55,
      candidate_count: 6,
      matched_count: 0,
      filtered_count: 6,
    },
  })
  await mount()
  const text = root.querySelector('textarea')!
  text.value = 'Massive Audio Embedding Benchmark'
  text.dispatchEvent(new Event('input'))
  const mode = root.querySelector<HTMLSelectElement>('select[aria-label="匹配方式"]')!
  mode.value = 'image_text'
  mode.dispatchEvent(new Event('change'))
  await wait()
  button('查找图片').click()
  await wait()
  expect(api.semanticSearch).toHaveBeenCalledWith(
    expect.objectContaining({ match_mode: 'image_text' }),
    [],
    expect.any(AbortSignal),
  )
  expect(root.querySelector('.semantic-results')?.textContent).toContain('按图片内文字匹配')
  expect(root.querySelector('.semantic-results')?.textContent).toContain('已过滤 6')
  expect(root.querySelector('.semantic-results')?.textContent).toContain('没有找到符合当前匹配条件')
})
it('clears image-text mode when switching to audio', async () => {
  vi.mocked(api.documents).mockResolvedValue([
    { id: 'image', filename: 'sample.png', kind: 'image' },
    { id: 'audio', filename: 'clip.wav', kind: 'audio' },
  ] as never)
  await mount()
  const mode = root.querySelector<HTMLSelectElement>('select[aria-label="匹配方式"]')!
  mode.value = 'image_text'
  mode.dispatchEvent(new Event('change'))
  await wait()
  button('找音视频片段').click()
  await wait()
  expect(mode.value).toBe('auto')
  const text = root.querySelector('textarea')!
  text.value = '海浪'
  text.dispatchEvent(new Event('input'))
  await wait()
  button('查找片段').click()
  await wait()
  expect(api.semanticSearch).toHaveBeenCalledWith(
    expect.objectContaining({ match_mode: 'auto', kinds: ['audio', 'video'] }),
    [],
    expect.any(AbortSignal),
  )
})
it('blocks an oversized input before inference and shows how to fix it', async () => {
  vi.mocked(api.semanticBudget).mockResolvedValue({
    fits: false,
    limit: 8192,
    max_tokens: 9000,
    segments: 1,
  } as never)
  await mount()
  const text = root.querySelector('textarea')!
  text.value = '场景'
  text.dispatchEvent(new Event('input'))
  await wait()
  button('查找图片').click()
  await wait()
  expect(api.semanticSearch).not.toHaveBeenCalled()
  expect(root.textContent).toContain('减少图片或缩短说明')
})
it('audio and video task selects both media types without requiring a format dropdown', async () => {
  vi.mocked(api.documents).mockResolvedValue([
    { id: 'video', filename: 'clip.mp4', kind: 'video' },
  ] as never)
  await mount()
  button('找音视频片段').click()
  await wait()
  const text = root.querySelector('textarea')!
  text.value = '海浪'
  text.dispatchEvent(new Event('input'))
  await wait()
  button('查找片段').click()
  await wait()
  expect(api.semanticSearch).toHaveBeenCalledWith(
    expect.objectContaining({ kinds: ['audio', 'video'] }),
    [],
    expect.any(AbortSignal),
  )
})
it('a large corpus requires a bounded selection before organization', async () => {
  vi.mocked(api.documents).mockResolvedValue(
    Array.from({ length: 201 }, (_, i) => ({
      id: String(i),
      filename: `notes-${i}.md`,
      kind: 'document',
    })) as never,
  )
  await mount()
  button('整理已有资料').click()
  await wait()
  expect(button('生成分类建议').disabled).toBe(true)
  expect(root.textContent).toContain('一次最多整理 200')
  const selected = root.querySelector<HTMLInputElement>('input[type="checkbox"]')!
  selected.checked = true
  selected.dispatchEvent(new Event('change'))
  await wait()
  button('生成分类建议').click()
  await wait()
  expect(api.organize).toHaveBeenCalledWith(
    expect.objectContaining({ document_ids: ['0'], task: 'classification' }),
    expect.any(AbortSignal),
  )
})
it('rejects incompatible files and multiple media inputs with specific instructions', () => {
  expect(inputIssue('images', [{ name: 'clip.mp4', size: 10 }])).toContain('组合查找')
  expect(
    inputIssue('mixed', [
      { name: 'a.mp3', size: 10 },
      { name: 'b.mp4', size: 10 },
    ]),
  ).toContain('一段音视频')
  expect(
    inputIssue('collect', [
      { name: 'notes.md', size: 10 },
      { name: 'ref.png', size: 10 },
    ]),
  ).toBe('')
})

it('does not present cross-media semantic matches as default duplicate candidates', async () => {
  vi.mocked(api.organize).mockResolvedValue({
    documents: [
      { id: 'image', filename: 'sample.png', kind: 'image' },
      { id: 'video', filename: 'clip.mp4', kind: 'video' },
    ],
    pairs: [{ left: 'image', right: 'video', exact: false, score: 0.95 }],
  } as never)
  await mount()
  button('整理已有资料').click()
  await wait()
  button('找重复资料').click()
  await wait()
  button('查找重复资料').click()
  await wait()
  expect(root.querySelectorAll('.organization-pair')).toHaveLength(0)
  expect(root.textContent).toContain('当前阈值下没有相似候选')
})

it('reports stopped waiting and ignores a late capacity-check response', async () => {
  let resolve!: (value: never) => void
  vi.mocked(api.semanticBudget).mockReturnValueOnce(
    new Promise((done) => {
      resolve = done
    }),
  )
  await mount()
  const text = root.querySelector('textarea')!
  text.value = '图片'
  text.dispatchEvent(new Event('input'))
  await wait()
  button('查找图片').click()
  await wait()
  expect(root.textContent).toContain('检查输入容量')
  button('停止等待').click()
  await wait()
  expect(root.textContent).toContain('已提交的请求可能仍在处理')
  resolve({ fits: true, limit: 8192, max_tokens: 10, segments: 1 } as never)
  await wait()
  expect(api.semanticSearch).not.toHaveBeenCalled()
  expect(root.textContent).toContain('已停止')
})
it('provides a single retry action for a failed search and runs the same valid input again', async () => {
  vi.mocked(api.semanticSearch).mockRejectedValueOnce(new Error('Search temporarily unavailable'))
  await mount()
  const text = root.querySelector('textarea')!
  text.value = '图片'
  text.dispatchEvent(new Event('input'))
  await wait()
  button('查找图片').click()
  await wait()
  expect(root.querySelector('.task-feedback.error')?.textContent).toContain(
    'Search temporarily unavailable',
  )
  button('重试').click()
  await wait()
  expect(api.semanticSearch).toHaveBeenCalledTimes(2)
  expect(root.querySelector('.task-feedback.success')).not.toBeNull()
})
